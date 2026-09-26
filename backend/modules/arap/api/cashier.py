"""出納模組（2026-08-31 新增，同日 v2 加強）：跨案件彙整「待付款」（已核准
未匯款的承攬商匯款申請）與「待收款」（案件款項期別，含全部歷史）、「執行
歷史」（已匯款/已收款的彙整彙報）＋ Excel 匯出，取代原本要一個案件一個案件
點進去才看得到待辦事項的做法。

v2（2026-08-31 同日）：receivables.html（應收帳款）獨有的發票登錄/搜尋篩選/
取消收款/手續費統計等功能併入這裡的待收款查詢（`status=all` 帶出完整品項
欄位），dashboard.py::list_receivables()（原 GET /api/receivables）retired。

權限：
- 查詢類端點（payable-queue／receivable-queue／summary／execution-history／
  export）：admin+ 或具備 cashier 模組，**或具備 finance 模組**（沿用
  receivables.html 原本 finance 模組使用者的既有可視範圍，併頁面不代表
  砍掉他們的查詢權）。
- 實際標記已匯款/已收款的動作維持走既有 paid-toggle／mark_payment 端點，
  那兩支只認 admin+/cashier，不含 finance——查看跟執行的權限分開，維持
  這輪一開始定案的財務/出納分工原則。
"""
import json
from datetime import date

import csv
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
import io
from urllib.parse import quote as _url_quote

from core import registry
from db import get_db
from helpers import _require_user, user_has_module, payment_item_amounts
from modules.arap.receivables import collect_income_items as _collect_income_items  # 本模組（ROADMAP A8b 已收回）
from helpers.legal_params import round_half_up          # bank-reconcile（金額四捨五入唯一來源）
from helpers import _audit, _tok                         # bank-reconcile 的稽核
from helpers.xlsx_out import check_export_rate, set_row, xl_style

router = APIRouter()


def _require_view_access(user: dict) -> None:
    if (user["role"] not in ("superadmin", "admin")
            and not user_has_module(user, "cashier")
            and not user_has_module(user, "finance")):
        raise HTTPException(403, "僅管理員、出納或財務可查閱")


# ── 獎金分潤（IP-8 bonus.payouts，INTEGRATION-POINTS.md）───────────────────────
#: 薪資獎金模組（M07）不在時對使用者說的話（不可以默默略過）
BONUS_MISSING = "薪資獎金模組未安裝：出納頁不顯示獎金分潤"
#: IP-14 對方不在時（M04 外包工班）：待付款回 404＋這一句；執行歷史帶 contractorNotice
CONTRACTOR_MISSING = "外包工班模組未安裝：出納頁不顯示承攬商匯款"


def _bonus_visible(user: dict) -> bool:
    """獎金金額只給最高管理者與出納（SPEC-BONUS C1）；本頁的財務（finance）可以看其他頁籤，但看不到獎金。"""
    return user.get("role") == "superadmin" or user_has_module(user, "cashier")


def _bonus_payouts(user: dict):
    """回 `(provider | None, notice)`。M07 不在 ⇒ `(None, BONUS_MISSING)`；沒有權限 ⇒ `(None, "")`（不顯示該區）。"""
    if not _bonus_visible(user):
        return None, ""
    p = registry.single_provider("bonus.payouts")
    if p is None:
        return None, BONUS_MISSING
    return p, ""


def _payable_queue(conn) -> list:
    pub = registry.single_provider("contractor_voucher.public")        # IP-14（M04）
    if pub is None:
        raise HTTPException(404, CONTRACTOR_MISSING)                  # 待付款整頁都是承攬商匯款 ⇒ 明說，不回空清單
    rows = conn.execute("""
        SELECT * FROM contractor_payment_vouchers
        WHERE status='已核准' AND is_paid=0
    """).fetchall()
    items = [pub(r, include_snapshot=False) for r in rows]
    # payableDate 空值排最後；非空依日期升冪（快到期的排前面）
    items.sort(key=lambda v: (not v["payableDate"], v["payableDate"]))
    return items


def _receivable_queue(conn, status: str = "unreceived") -> list:
    """status: unreceived（預設，出納待辦用）／received／all（比照
    dashboard.py 原 list_receivables() 的完整歷史，供併入的應收帳款查詢用）。"""
    today = date.today()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person,
               total, pretax, quote_date,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date DESC
    """).fetchall()

    items = []
    for row in rows:
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        total = row["total"] or 0
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(total, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            received = bool(pi.get("received"))
            if status == "unreceived" and received:
                continue
            if status == "received" and not received:
                continue
            expected = pi.get("expectedReceiptDate") or ""
            items.append({
                "quoteNo":             row["quote_no"],
                "idx":                 idx,
                "itemId":              pi.get("id"),
                "customer":            row["customer_name"] or "",
                "project":             row["project_name"] or "",
                "salesPerson":         row["sales_person"] or "",
                "dealTag":             row["deal_tag"] or "",
                "type":                pi.get("type", f"第{idx+1}期"),
                "amount":              amounts[idx],
                "quoteDate":           row["quote_date"] or "",
                "expectedReceiptDate": expected,
                "overdue":             bool(expected) and not received and expected < today.isoformat(),
                "received":            received,
                "receivedAt":          pi.get("receivedAt") or "",
                "receivedBy":          pi.get("receivedBy") or "",
                "invoiceNo":           pi.get("invoiceNo") or "",
                "invoiceDate":         pi.get("invoiceDate") or "",
                "actualAmount":        pi.get("actualAmount"),
                "feeAmount":           pi.get("feeAmount") or 0,
                "feeNote":             pi.get("feeNote") or "",
                "note":                pi.get("note") or "",
            })

    if status == "unreceived":
        # 待辦性質：expectedReceiptDate 空值排最後，非空依日期升冪（快到期排前面）
        items.sort(key=lambda i: (not i["expectedReceiptDate"], i["expectedReceiptDate"]))
    # status in ('all','received') 沿用 SQL 已經給的 quote_date DESC 排序
    # （比照 receivables.html 原本「最新案件優先」的閱讀習慣）
    return items


@router.get("/api/cashier/payable-queue")
def get_payable_queue(authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_view_access(user)
    conn = get_db()
    try:
        return _payable_queue(conn)
    finally:
        conn.close()


@router.get("/api/cashier/receivable-queue")
def get_receivable_queue(status: str = Query("unreceived"), authorization: str = Header(None)):
    if status not in ("unreceived", "received", "all"):
        raise HTTPException(400, "status 必須為 unreceived／received／all")
    user = _require_user(authorization)
    _require_view_access(user)
    conn = get_db()
    try:
        return _receivable_queue(conn, status)
    finally:
        conn.close()


@router.get("/api/cashier/bonus-queue")
def get_bonus_queue(authorization: str = Header(None)):
    """獎金分潤待發放（CORE-SPEC 獎金分潤：送交出納）。「標記已發放」打的是獎金那一支
    `POST /api/bonus/cases/{單號}/mark-paid`——同一個動作，不在這裡另寫一份。"""
    user = _require_user(authorization)
    _require_view_access(user)
    p, notice = _bonus_payouts(user)
    if p is None:
        return {"available": False, "visible": _bonus_visible(user), "notice": notice, "items": []}
    conn = get_db()
    try:
        items = p.pending(conn)
    finally:
        conn.close()
    return {"available": True, "visible": True, "notice": "", "items": items,
            "canMarkPaid": user.get("role") == "superadmin" or user_has_module(user, "cashier")}


# ── 執行歷史（已匯款／已收款彙整）＋ Excel 匯出 ─────────────────────────────

def _default_month_range():
    today = date.today()
    d0 = today.replace(day=1).isoformat()
    d1 = today.isoformat()
    return d0, d1


def _execution_history(conn, start: str, end: str, user: dict = None) -> dict:
    pub = registry.single_provider("contractor_voucher.public")        # IP-14（M04）；不在 ⇒ 沒有承攬付款
    outgoing_rows = conn.execute("""
        SELECT * FROM contractor_payment_vouchers
        WHERE is_paid=1 AND paid_at BETWEEN ? AND ?
        ORDER BY paid_at DESC
    """, (start, end)).fetchall() if pub else []
    outgoing = [pub(r, include_snapshot=False) for r in outgoing_rows]
    incoming = _collect_income_items(start, end)
    out = {
        "start": start, "end": end,
        "outgoing": outgoing, "outgoingTotal": sum(v["grandTotal"] for v in outgoing),
        "incoming": incoming, "incomingTotal": sum(i["amount"] for i in incoming),
        "contractorNotice": "" if pub else CONTRACTOR_MISSING,
    }
    # 獎金分潤發放紀錄（IP-8）：只給看得到獎金的人；M07 不在 ⇒ 空清單＋明說
    p, notice = _bonus_payouts(user or {})
    bonus = p.paid(conn, start, end) if p is not None else []
    out.update({"bonusVisible": _bonus_visible(user or {}), "bonusNotice": notice,
                "bonusPaid": bonus, "bonusPaidTotal": sum(b["total"] for b in bonus)})
    return out


@router.get("/api/cashier/execution-history")
def get_execution_history(start: str = Query(None), end: str = Query(None), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_view_access(user)
    d0, d1 = _default_month_range()
    start = start or d0
    end = end or d1
    conn = get_db()
    try:
        return _execution_history(conn, start, end, user)
    finally:
        conn.close()


@router.get("/api/cashier/export")
def export_execution_history(start: str = Query(None), end: str = Query(None), authorization: str = Header(None)):
    """出納執行紀錄 Excel 匯出（已匯款／已收款明細，預設本月），沿用
    reports.py 既有的 Excel 樣式 helper，不重新發明一套。"""
    user = _require_user(authorization)
    _require_view_access(user)
    check_export_rate(user["id"], "excel")
    d0, d1 = _default_month_range()
    start = start or d0
    end = end or d1
    conn = get_db()
    try:
        data = _execution_history(conn, start, end, user)
    finally:
        conn.close()

    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    mk, fill, mk_border, al = xl_style(wb)
    BD = mk_border()
    C_DARK, C_WHITE = "111827", "FFFFFF"

    ws1 = wb.create_sheet("已匯款明細")
    ws1.sheet_view.showGridLines = False
    hdrs1 = ["申請單號", "關聯案件", "廠商", "應付金額", "應付款日期", "匯款日期"]
    for i, w in enumerate([14, 14, 18, 12, 12, 12], 1):
        ws1.column_dimensions[chr(64 + i)].width = w
    ws1.merge_cells(f"A1:F1")
    c = ws1["A1"]
    c.value = f"出納執行紀錄 — 已匯款（{start} ~ {end}）"
    c.font = mk(bold=True, size=12, color=C_WHITE)
    c.fill = fill(C_DARK)
    c.alignment = al("center")
    ws1.row_dimensions[1].height = 24
    set_row(ws1, 2, hdrs1, font=mk(bold=True, size=9, color=C_WHITE), fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)
    r = 3
    if data["contractorNotice"]:                                    # IP-14 不在 ⇒ 表內明說，不是空白表
        set_row(ws1, r, [data["contractorNotice"]] + [""] * 5, font=mk(size=9), border=BD,
                aligns=[al("left")], height=18)
        r += 1
    for v in data["outgoing"]:
        set_row(ws1, r, [v["voucherNo"], v["quoteNo"], v["vendorName"] or "（外包人員點工）",
                           v["grandTotal"], v["payableDate"] or "", v["paidAt"][:10] if v["paidAt"] else ""],
                 font=mk(size=9), border=BD, aligns=[al("left")], height=18)
        ws1.cell(row=r, column=4).number_format = '#,##0'
        r += 1
    set_row(ws1, r, ["合計", "", "", data["outgoingTotal"], "", ""],
             font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
             aligns=[al("left")], height=20)
    ws1.cell(row=r, column=4).number_format = '#,##0'

    ws2 = wb.create_sheet("已收款明細")
    ws2.sheet_view.showGridLines = False
    hdrs2 = ["案件號", "客戶", "業務員", "款項類型", "實收金額", "收款日"]
    for i, w in enumerate([14, 18, 10, 10, 12, 12], 1):
        ws2.column_dimensions[chr(64 + i)].width = w
    ws2.merge_cells(f"A1:F1")
    c = ws2["A1"]
    c.value = f"出納執行紀錄 — 已收款（{start} ~ {end}）"
    c.font = mk(bold=True, size=12, color=C_WHITE)
    c.fill = fill(C_DARK)
    c.alignment = al("center")
    ws2.row_dimensions[1].height = 24
    set_row(ws2, 2, hdrs2, font=mk(bold=True, size=9, color=C_WHITE), fill=fill("374151"), border=BD,
             aligns=[al("center")], height=20)
    r = 3
    for it in data["incoming"]:
        aa = it["actualAmount"]
        set_row(ws2, r, [it["quoteNo"], it["customer"], it["salesPerson"], it["type"],
                           aa if aa is not None else it["amount"], it["receivedAt"]],
                 font=mk(size=9), border=BD, aligns=[al("left")], height=18)
        ws2.cell(row=r, column=5).number_format = '#,##0'
        r += 1
    set_row(ws2, r, ["合計", "", "", "", data["incomingTotal"], ""],
             font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
             aligns=[al("left")], height=20)
    ws2.cell(row=r, column=5).number_format = '#,##0'

    if data["bonusVisible"]:
        ws3 = wb.create_sheet("獎金發放明細")
        ws3.sheet_view.showGridLines = False
        hdrs3 = ["案件號", "客戶", "人數", "發放總額", "代扣稅款", "補充保費", "實發", "發放日", "經辦"]
        for i, w in enumerate([14, 18, 6, 12, 12, 12, 12, 12, 10], 1):
            ws3.column_dimensions[chr(64 + i)].width = w
        ws3.merge_cells("A1:I1")
        c = ws3["A1"]
        c.value = f"出納執行紀錄 — 獎金分潤發放（{start} ~ {end}）"
        c.font = mk(bold=True, size=12, color=C_WHITE)
        c.fill = fill(C_DARK)
        c.alignment = al("center")
        ws3.row_dimensions[1].height = 24
        set_row(ws3, 2, hdrs3, font=mk(bold=True, size=9, color=C_WHITE), fill=fill("374151"), border=BD,
                aligns=[al("center")], height=20)
        r = 3
        if data["bonusNotice"]:
            set_row(ws3, r, [data["bonusNotice"]] + [""] * 8, font=mk(size=9), border=BD,
                    aligns=[al("left")], height=18)
            r += 1
        for b in data["bonusPaid"]:
            # 扣繳快照不存在（法規參數接上前發放的）⇒ 留空，不寫 0
            set_row(ws3, r, [b["quoteNo"], b["customer"], b["people"], b["total"],
                             "" if b["withholding"] is None else b["withholding"],
                             "" if b["nhiPremium"] is None else b["nhiPremium"],
                             "" if b["net"] is None else b["net"], b["paidAt"], b["paidBy"]],
                    font=mk(size=9), border=BD, aligns=[al("left")], height=18)
            for col in (4, 5, 6, 7):
                ws3.cell(row=r, column=col).number_format = '#,##0'
            r += 1
        set_row(ws3, r, ["合計", "", "", data["bonusPaidTotal"], "", "", "", "", ""],
                font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
                aligns=[al("left")], height=20)
        ws3.cell(row=r, column=4).number_format = '#,##0'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"MOTRIX_出納執行紀錄_{start}_{end}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )


# ── 銀行對帳單比對（承攬商匯款申請）───────────────────────────────────────────

_BANK_DATE_ALIASES   = ["交易日期", "日期", "過帳日", "轉帳日期", "交易日", "date", "Date"]
_BANK_AMOUNT_ALIASES = ["金額", "提出金額", "支出金額", "轉出金額", "付款金額", "提款金額",
                         "amount", "Amount", "Debit", "withdrawal"]
_BANK_DESC_ALIASES   = ["摘要", "備註", "說明", "對方戶名", "附言", "memo", "Description", "Memo"]


def _pick_csv_header(fieldnames: list, aliases: list) -> Optional[str]:
    """依常見銀行匯出欄位別名找出對應欄位——各家銀行 CSV 標頭不統一，這裡先精準比對，
    找不到再退而求其次找含該關鍵字的欄位，仍找不到就回傳 None（呼叫端自行決定要不要擋）。"""
    clean = [fn for fn in fieldnames if fn]
    for a in aliases:
        for fn in clean:
            if fn.strip() == a:
                return fn
    for a in aliases:
        for fn in clean:
            if a in fn:
                return fn
    return None


def _parse_bank_csv(raw: bytes) -> list:
    """解析銀行對帳單 CSV。不同銀行匯出的編碼／欄位命名差異很大，這裡採寬鬆偵測：
    依序嘗試常見編碼、依別名清單找日期/金額/摘要欄位，只有金額欄位是必要的。"""
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise HTTPException(400, "CSV 編碼無法辨識，請確認匯出檔案格式（支援 UTF-8 / Big5）")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    date_col = _pick_csv_header(fieldnames, _BANK_DATE_ALIASES)
    amt_col  = _pick_csv_header(fieldnames, _BANK_AMOUNT_ALIASES)
    desc_col = _pick_csv_header(fieldnames, _BANK_DESC_ALIASES)
    if not amt_col:
        raise HTTPException(400, f"CSV 找不到可辨識的金額欄位，偵測到的欄位為：{'、'.join(fieldnames) or '（無）'}")

    rows = []
    for r in reader:
        raw_amt = (r.get(amt_col) or "").replace(",", "").replace("NT$", "").strip()
        if not raw_amt:
            continue
        try:
            amt = abs(float(raw_amt))
        except ValueError:
            continue
        if amt <= 0:
            continue
        rows.append({
            "date":   (r.get(date_col) or "").strip() if date_col else "",
            "amount": amt,
            "desc":   (r.get(desc_col) or "").strip() if desc_col else "",
        })
    return rows


@router.post("/api/reports/bank-reconcile")
async def bank_reconcile(file: UploadFile = File(...), authorization: str = Header(None)):
    """銀行對帳單比對：上傳 CSV，依金額比對目前「已核准未匯款」的承攬商匯款申請。

    只做金額比對（同金額只配對一次，避免一筆申請被重複配對到多筆銀行紀錄），純供人工
    複核用途——回傳配對建議，不會自動標記已匯款，實際標記仍走既有 paid-toggle 端點，
    避免比對誤判（例如剛好同金額但其實是不同筆款項）被誤當正式入帳紀錄。"""
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin") and not user_has_module(u, "cashier"):
        raise HTTPException(403, "僅管理員或出納可查閱")
    if registry.single_provider("contractor_voucher.public") is None:     # IP-14（M04）：比對對象全是承攬商匯款申請
        raise HTTPException(404, CONTRACTOR_MISSING)

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "檔案過大（上限 5MB）")
    bank_rows = _parse_bank_csv(raw)

    conn = get_db()
    voucher_rows = conn.execute("""
        SELECT v.voucher_no, v.quote_no, v.snapshot_json, v.updated_at, q.customer_name
        FROM contractor_payment_vouchers v
        LEFT JOIN quotations q ON q.quote_no = v.quote_no
        WHERE v.status='已核准' AND v.is_paid=0
    """).fetchall()
    conn.close()

    vouchers = []
    for r in voucher_rows:
        snap = {}
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            pass
        vouchers.append({
            "voucherNo":  r["voucher_no"],
            "quoteNo":    r["quote_no"] or "",
            "customer":   r["customer_name"] or "",
            "vendorName": snap.get("vendorName") or "",
            "amount":     round_half_up(float(snap.get("grandTotal") or 0)),
        })

    matched_voucher_nos = set()
    bank_results = []
    for br in bank_rows:
        amt_r = round_half_up(br["amount"])
        candidate = next(
            (v for v in vouchers if round_half_up(v["amount"]) == amt_r and v["voucherNo"] not in matched_voucher_nos),
            None,
        )
        if candidate:
            matched_voucher_nos.add(candidate["voucherNo"])
        bank_results.append({**br, "match": candidate})

    unmatched_vouchers = [v for v in vouchers if v["voucherNo"] not in matched_voucher_nos]

    _audit(_tok(authorization), "reports.bank_reconcile", "reports", "bank-reconcile",
           f"銀行對帳單比對（上傳 {len(bank_rows)} 筆，配對成功 {len(matched_voucher_nos)} 筆）",
           {"bankRowCount": len(bank_rows), "matchedCount": len(matched_voucher_nos)})
    return {
        "bankRows":           bank_results,
        "matchedCount":       len(matched_voucher_nos),
        "unmatchedBankCount": sum(1 for r in bank_results if not r["match"]),
        "unmatchedVouchers":  unmatched_vouchers,
        "note": "僅依金額比對，且同金額只配對一次，屬建議配對供人工複核；請核對案件號/"
                "承攬商名稱後再手動標記已匯款，系統不會自動標記。",
    }
