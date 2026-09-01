"""T100（鼎新）傳票批次匯出（2026-09-01 新增）。

背景：使用者要求把系統既有的財務資料對接鼎新 T100，且明確選擇「先做批次匯出成
T100 標準傳票匯入格式，不做即時 API 對接」——T100 API 需要貴公司自行向鼎新申請
存取權限，這裡沒有真實憑證可以測試，貿然做 API 串接無法驗證正確性；批次匯出成
Excel、財務人員在 T100 用既有匯入功能手動核對匯入，風險小很多，且可以立刻測試。

設計採**現金基礎**（cash basis）：只匯出「錢真的有進出」的事件，不匯出應計項目：
  - 收款事件：案件款項明細已填發票號碼且已收款（沿用 reports.py::_collect_tax_invoices()
    同一份資料源，跟稅務匯出數字保證一致）→ 借 銀行存款(含稅) / 貸 銷貨收入(未稅)
    ＋ 貸 銷項稅額(稅額，若有)
  - 付款事件：承攬商匯款申請已標記已匯款（沿用 cashier.py 出納模組同一份資料源）
    → 借 承攬商費用(含稅) / 貸 銀行存款(含稅)

刻意排除 payment_requests（請款單）——那是對客戶要款的文件，沒有「已收款」狀態，
不是真的金流事件，比照 reports.py::_compute_cash_position() 既有的排除理由（同一
份資料在系統裡任何金流类彙總都不該把它算進去，避免各處各自決定要不要排除造成
不一致）。

每筆事件產生的傳票天生借貸平衡（同一 voucherNo 底下借方合計＝貸方合計），三個
面向（銷項發票／應付／銀行對帳）用同一份匯出涵蓋，避免三份報表各自各的資料源、
數字對不上。

科目代號（借貸方會計科目）由 superadmin 在 GET/PUT /api/settings/t100-export-config
設定，預設全部留白——這是刻意的，貴公司財務團隊需要先確認實際使用的科目代號
才具備直接匯入 T100 的意義；金額/日期/摘要/來源單號/交易對象等其餘欄位在科目
代號填入前就已經正確可用，財務可以先核對數字正確性。
"""
import io
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote as _url_quote

import openpyxl
from openpyxl.utils import get_column_letter
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _tok, _audit, _get_setting, _set_setting
from routers.reports import _collect_tax_invoices, _check_export_rate, _xl_style, _set_row, _COMPANY
from routers.contractor_vouchers import _voucher_public

router = APIRouter()

_DEFAULT_T100_CONFIG = {
    "bankAccount":              "",   # 銀行存款科目代號
    "salesRevenueAccount":      "",   # 銷貨收入科目代號
    "outputTaxAccount":         "",   # 銷項稅額科目代號
    "contractorExpenseAccount": "",   # 承攬商費用科目代號
    "departmentCode":           "",   # 部門別代號（選填，留空則傳票不分部門）
    "voucherCategory":          "轉", # 傳票別（T100 常見：現／轉／記，預設「轉」）
}


# ── 科目代號設定（superadmin 維護，admin+ 可查閱） ─────────────────────────────

class T100ExportConfigBody(BaseModel):
    bankAccount: str = ""
    salesRevenueAccount: str = ""
    outputTaxAccount: str = ""
    contractorExpenseAccount: str = ""
    departmentCode: str = ""
    voucherCategory: str = "轉"


def _t100_config() -> dict:
    cfg = _get_setting("t100_export_config", {}) or {}
    return {**_DEFAULT_T100_CONFIG, **cfg}


@router.get("/api/settings/t100-export-config")
def get_t100_export_config(authorization: str = Header(None)):
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可查閱")
    return _t100_config()


@router.put("/api/settings/t100-export-config")
def set_t100_export_config(body: T100ExportConfigBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _set_setting("t100_export_config", body.model_dump())
    _audit(_tok(authorization), "settings.t100_export_config.update", "settings",
           "t100_export_config", "T100 傳票匯出科目代號設定")
    return {"ok": True}


# ── 傳票資料組裝 ────────────────────────────────────────────────────────────────

def _collect_paid_contractor_vouchers(start: str, end: str) -> list:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM contractor_payment_vouchers
            WHERE is_paid=1 AND paid_at BETWEEN ? AND ?
            ORDER BY paid_at
        """, (start + "T00:00:00", end + "T23:59:59")).fetchall()
        return [_voucher_public(r, include_snapshot=False) for r in rows]
    finally:
        conn.close()


def _voucher_line(voucher_no, d, category, summary, acct_code, acct_name, debit, credit,
                   dept, source_no, counterparty):
    return {
        "voucherNo": voucher_no, "date": d, "category": category, "summary": summary,
        "acctCode": acct_code, "acctName": acct_name,
        "debit": round(debit) if debit else 0, "credit": round(credit) if credit else 0,
        "dept": dept, "sourceNo": source_no, "counterparty": counterparty,
    }


def _build_t100_vouchers(start: str, end: str, cfg: dict) -> list:
    """回傳一組傳票分錄列（每列是一筆借方或貸方分錄），供 Excel 逐列輸出。
    每張傳票（同一 voucherNo）借方合計＝貸方合計，天生借貸平衡。"""
    rows = []
    seq = 0

    # 收款事件（銷項）：借 銀行存款(含稅) / 貸 銷貨收入(未稅) ＋ 貸 銷項稅額(稅額)
    for inv in _collect_tax_invoices():
        d = (inv.get("date") or "")[:10]
        if not d or not (start <= d <= end):
            continue
        seq += 1
        vno = f"AR{seq:04d}"
        summary = f"{inv['customer']} {inv['quoteNo']} 發票{inv['invoiceNo']} 收款"[:60]
        rows.append(_voucher_line(vno, d, cfg["voucherCategory"], summary,
                                   cfg["bankAccount"], "銀行存款", inv["amountTotal"], 0,
                                   cfg["departmentCode"], inv["quoteNo"], inv["customer"]))
        rows.append(_voucher_line(vno, d, cfg["voucherCategory"], summary,
                                   cfg["salesRevenueAccount"], "銷貨收入", 0, inv["amountPretax"],
                                   cfg["departmentCode"], inv["quoteNo"], inv["customer"]))
        if inv["taxAmount"]:
            rows.append(_voucher_line(vno, d, cfg["voucherCategory"], summary,
                                       cfg["outputTaxAccount"], "銷項稅額", 0, inv["taxAmount"],
                                       cfg["departmentCode"], inv["quoteNo"], inv["customer"]))

    # 付款事件（承攬商費用）：借 承攬商費用(含稅) / 貸 銀行存款(含稅)
    for v in _collect_paid_contractor_vouchers(start, end):
        seq += 1
        vno = f"AP{seq:04d}"
        vendor = v["vendorName"] or "外包人員點工"
        summary = f"{vendor} {v['quoteNo']} 匯款申請{v['voucherNo']}"[:60]
        paid_d = (v["paidAt"] or "")[:10]
        rows.append(_voucher_line(vno, paid_d, cfg["voucherCategory"], summary,
                                   cfg["contractorExpenseAccount"], "承攬商費用", v["grandTotal"], 0,
                                   cfg["departmentCode"], v["voucherNo"], vendor))
        rows.append(_voucher_line(vno, paid_d, cfg["voucherCategory"], summary,
                                   cfg["bankAccount"], "銀行存款", 0, v["grandTotal"],
                                   cfg["departmentCode"], v["voucherNo"], vendor))

    rows.sort(key=lambda r: (r["date"], r["voucherNo"]))
    return rows


def _build_t100_voucher_excel(rows: list, start: str, end: str, cfg: dict, gen_at: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T100傳票匯出"
    ws.sheet_view.showGridLines = False
    mk, fill, mk_border, al = _xl_style(wb)
    BD = mk_border()

    missing_codes = [k for k in ("bankAccount", "salesRevenueAccount",
                                  "outputTaxAccount", "contractorExpenseAccount")
                      if not cfg.get(k)]

    widths = [10, 12, 8, 30, 10, 12, 12, 12, 8, 14, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.merge_cells("A1:K1")
    c = ws["A1"]
    c.value = f"{_COMPANY} — T100 傳票批次匯出（{start} ~ {end}）"
    c.font = mk(bold=True, size=13, color="FFFFFF")
    c.fill = fill("111827")
    c.alignment = al("center")
    ws.row_dimensions[1].height = 28

    note = f"產製時間：{gen_at}　現金基礎（僅含實際已收款/已匯款事件）　傳票別預設「{cfg['voucherCategory']}」"
    if missing_codes:
        note += "　⚠️ 尚未設定科目代號：" + "、".join(missing_codes) + "（請至系統設定填入後再匯入 T100）"
    ws.merge_cells("A2:K2")
    c = ws["A2"]
    c.value = note
    c.font = mk(size=9, color="DC2626" if missing_codes else "6B7280")
    c.alignment = al("center", wrap=True)
    ws.row_dimensions[2].height = 18

    headers = ["傳票號", "傳票日期", "傳票別", "摘要", "科目代號", "科目名稱",
               "借方金額", "貸方金額", "部門別", "來源單號", "交易對象"]
    _set_row(ws, 3, headers, font=mk(bold=True, color="FFFFFF"), fill=fill("2563EB"), border=BD, aligns=[al("center")])
    ws.row_dimensions[3].height = 22

    r = 4
    total_debit = total_credit = 0
    body_aligns = [al("center"), al("center"), al("center"), al("left"), al("center"),
                   al("center"), al("right"), al("right"), al("center"), al("center"), al("left")]
    for row in rows:
        _set_row(ws, r, [
            row["voucherNo"], row["date"], row["category"], row["summary"],
            row["acctCode"], row["acctName"], row["debit"] or "", row["credit"] or "",
            row["dept"], row["sourceNo"], row["counterparty"],
        ], font=mk(), border=BD, aligns=body_aligns)
        total_debit += row["debit"]
        total_credit += row["credit"]
        r += 1

    _set_row(ws, r, ["合計", "", "", "", "", "", total_debit, total_credit, "", "", ""],
             font=mk(bold=True), fill=fill("F9FAFB"), border=BD, aligns=body_aligns)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/api/reports/t100-export/vouchers")
def t100_export_vouchers(
    start: str = Query(...),
    end: str = Query(...),
    authorization: str = Header(None),
):
    """T100 傳票批次匯出（Excel），現金基礎，涵蓋已收款發票與已匯款承攬商費用。"""
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "財務報告僅管理員以上可查閱")
    if not start or not end or start > end:
        raise HTTPException(400, "start/end 日期區間無效")
    _check_export_rate(u["id"], "excel")
    cfg = _t100_config()
    rows = _build_t100_vouchers(start, end, cfg)
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    xlsx = _build_t100_voucher_excel(rows, start, end, cfg, gen_at)
    fname = f"MOTRIX_T100傳票匯出_{start}_{end}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_url_quote(fname)}"},
    )
