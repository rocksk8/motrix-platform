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
import re
from datetime import date

import csv
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, UploadFile, File
from fastapi.responses import Response, StreamingResponse
import io
from urllib.parse import quote as _url_quote

from core import registry
from db import get_db, spawn_bg_thread
from helpers import _require_user, user_has_module, payment_item_amounts, notify_module_activity, push_event_for_module
from modules.arap.receivables import collect_income_items as _collect_income_items  # 本模組（ROADMAP A8b 已收回）
from helpers.legal_params import round_half_up          # bank-reconcile（金額四捨五入唯一來源）
from helpers import _audit, _tok                         # bank-reconcile 的稽核
from helpers.xlsx_out import add_pdf_sibling, check_export_rate, export_logged, set_row, xl_style

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


# ── 請款待付款（IP-100 payables.pending，多提供者；2026-09-27 使用者裁示請款流程）────────────
#: 沒有任何提供者（M01 不在）時對使用者說的話——不回空清單裝沒事
PAYABLES_MISSING = "案件管理模組未安裝：出納頁不顯示請款（案件額外支出）待付款"
_PAID_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _can_pay(user: dict) -> bool:
    """登錄付款：admin+ 或出納（與 paid-toggle 同一條；finance 只能看）。"""
    return user.get("role") in ("superadmin", "admin") or user_has_module(user, "cashier")


@router.get("/api/cashier/pending-payables")
def get_pending_payables(authorization: str = Header(None)):
    """已核准、未登錄付款日的請款（各提供者合併，依核准日）。既有 payable-queue（IP-14）與 bonus-queue（IP-8）不動。"""
    user = _require_user(authorization)
    _require_view_access(user)
    provs = registry.providers("payables.pending")
    if not provs:
        return {"available": False, "notice": PAYABLES_MISSING, "items": [], "canPay": False}
    conn = get_db()
    try:
        items = []
        for name, p in sorted(provs.items()):
            for it in p.pending(conn):
                items.append(dict(it, source=name))
    finally:
        conn.close()
    items.sort(key=lambda v: (v.get("approvedAt") or "", v["source"], v["key"]))
    return {"available": True, "notice": "", "items": items, "canPay": _can_pay(user)}


@router.get("/api/cashier/pending-payables/{source}/{key}/payee-bank")
def get_payee_bank(source: str, key: str, authorization: str = Header(None)):
    """出納付款前看收款人銀行資料（A2-3）。**只有能付款的人**（管理員／出納）；每次查看都留稽核（不記帳號內容）。
    來源優先序：銀行資料表提供者 `payee.bank_profile`（有登錄、員工）→ 單據上手填的快照 → 沒有（明說，不猜）。"""
    user = _require_user(authorization)
    if not _can_pay(user):
        raise HTTPException(403, "只有管理員或出納可以查看收款人銀行資料")
    p = registry.providers("payables.pending").get(source)
    if p is None or not hasattr(p, "payee_info"):
        raise HTTPException(404, "找不到請款來源「%s」（或該來源不提供收款人資料）" % source)
    conn = get_db()
    try:
        try:
            info = p.payee_info(conn, key)
        except LookupError as e:
            raise HTTPException(404, str(e))
        out = {"payeeType": info["payeeType"], "payeeName": info["payeeName"], "source": "none", "bank": "", "account": "", "accountName": "",
               "notice": ""}
        prof_fn = registry.single_provider("payee.bank_profile") if info.get("payeeUsername") else None
        prof = prof_fn(conn, info["payeeUsername"], user) if prof_fn else None
        if prof and prof.get("account"):
            out.update(source="profile", bank=prof.get("bank") or "", account=prof.get("account") or "", accountName=prof.get("accountName") or "")
        elif info["bank"] or info["account"]:
            out.update(source="form", bank=info["bank"], account=info["account"])
        else:
            out["notice"] = "尚未登錄收款人銀行資料" + ("（員工請先到個人設定登錄）" if info.get("payeeUsername") else "")
    finally:
        conn.close()
    _audit(_tok(authorization), "cashier.payee_bank_view", source, key, "出納查看收款人銀行資料（來源：%s）" % out["source"])
    return out


@router.post("/api/cashier/pending-payables/{source}/{key}/pay")
def pay_pending_payable(source: str, key: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """登錄付款：寫回來源單據的付款日（經提供者，出納不直接碰別的模組的表）⇒ 從待付款消失。"""
    user = _require_user(authorization)
    if not _can_pay(user):
        raise HTTPException(403, "只有管理員或出納可以登錄付款")
    p = registry.providers("payables.pending").get(source)
    if p is None:
        raise HTTPException(404, "找不到請款來源「%s」（對應的模組未安裝）" % source)
    paid = str((body or {}).get("paidDate") or "").strip()
    if not paid:
        raise HTTPException(400, "請填寫付款日（paidDate，YYYY-MM-DD）")             # W1：必填，不再默認今天
    if not _PAID_DATE_RE.match(paid):
        raise HTTPException(400, "付款日格式必須是 YYYY-MM-DD")
    try:
        date.fromisoformat(paid)
    except ValueError:
        raise HTTPException(400, "付款日不是有效的日期")
    conn = get_db()
    try:
        acct = str((body or {}).get("payAccountCode") or "").strip()      # A2-3：付款科目（選填）——有給就用會計連接器驗存在與啟用
        if acct:
            chk = registry.single_provider("voucher.account_check")
            if chk is not None:
                ok, err = chk(conn, acct)
                if not ok:
                    raise HTTPException(400, "付款科目：%s" % err)
        try:
            res = p.mark_paid(conn, key, paid, user, remit=body)          # W1：實付／手續費／差額審核
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(getattr(e, "status", 409), str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "cashier.payable_paid", source, key,
           "出納登錄請款付款：%s #%s（%s）付款日 %s 實付 %s 手續費 %s 付款方式 %s%s" % (
               source, key, res.get("quoteNo") or "", paid, res.get("actual"), res.get("fee"), (body or {}).get("payMethod") or "預設",
               "（差額 %+g，待審核）" % res["diff"] if res.get("remitReview") else ""))
    if res.get("remitReview"):
        notify_module_activity("請款付款", "匯款差額待審核", user.get("display_name") or user["username"],
                               "%s #%s（%s）" % (source, key, res.get("quoteNo") or ""), "cashier.html",
                               detail="實付與應付不符（差額 %+g），請管理員到出納頁核可或退回。" % res["diff"])
    # 行事曆「支出付款」（2026-09-30，預設關；開關在 L1 判斷）：以付款日建立。勞報單付款走自己的端點，不在此列
    spawn_bg_thread(push_event_for_module, args=_expense_calendar_args(source, key, paid, res, user))
    return {"ok": True, **res}


def _expense_calendar_args(source, key, paid, res, user):
    """行事曆「支出付款」事件的內容（push_event_for_module 的參數）；名目／金額取提供者回傳（出納不讀別的模組的表）。"""
    title = res.get("title") or "%s #%s" % (source, key)
    desc = ("出納已登錄付款。\n名目：%s\n關聯案件：%s\n受款人：%s\n金額：NT$ %s\n實付：NT$ %s\n手續費：NT$ %s\n付款日：%s\n登錄人：%s"
            % (title, res.get("quoteNo") or "", res.get("payee") or "", "{:,.0f}".format(float(res.get("amount") or 0)),
               "{:,.0f}".format(float(res.get("actual") or 0)), "{:,.0f}".format(float(res.get("fee") or 0)), paid,
               user.get("display_name") or user.get("username") or ""))
    return ("expense_payout", "支出付款 — %s" % title, desc, paid)


# ── 匯款差額審核（W1；IP-102 `remit.reviews`，多提供者：承攬商匯款、案件額外支出）────────────────

REMIT_REVIEWS_MISSING = "沒有任何提供匯款差額審核的模組：出納頁不顯示差額待審核"


def _is_admin(user: dict) -> bool:
    return user.get("role") in ("superadmin", "admin")


@router.get("/api/cashier/remit-reviews")
def get_remit_reviews(authorization: str = Header(None)):
    """實付≠應付、已標記已匯款、待管理員核可或退回的清單（各提供者合併，依匯款日）。出納／財務／管理員可看，只有 admin+ 能決定。"""
    user = _require_user(authorization)
    _require_view_access(user)
    provs = registry.providers("remit.reviews")
    conn = get_db()
    try:
        items = []
        for name, p in sorted(provs.items()):
            for it in p.pending(conn):
                items.append(dict(it, source=name))
    finally:
        conn.close()
    items.sort(key=lambda v: (v.get("paidAt") or "", v["source"], v["key"]))
    return {"available": bool(provs), "notice": "" if provs else REMIT_REVIEWS_MISSING,
            "items": items, "canDecide": _is_admin(user)}


@router.post("/api/cashier/remit-reviews/{source}/{key}/decision")
def decide_remit_review(source: str, key: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """核可（approve）或退回（reject＝回未匯款，實付／手續費清空）。只限 admin／superadmin。"""
    user = _require_user(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "只有管理員可以核可或退回匯款差額")
    p = registry.providers("remit.reviews").get(source)
    if p is None:
        raise HTTPException(404, "找不到審核來源「%s」（對應的模組未安裝）" % source)
    decision = str((body or {}).get("decision") or "").strip()
    note = str((body or {}).get("note") or "").strip()
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "decision 必須為 approve 或 reject")
    if decision == "reject" and not note:
        raise HTTPException(400, "退回請填寫原因")
    conn = get_db()
    try:
        try:
            res = p.decide(conn, key, decision, user, note)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(getattr(e, "status", 409), str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "cashier.remit_review_" + decision, source, key,
           "%s匯款差額：%s #%s（%s）%s" % ("核可" if decision == "approve" else "退回（回未匯款）", source, key,
                                       res.get("quoteNo") or "", note))
    return {"ok": True, **res}


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


#: 薪資獎金模組（M07）不在時，勞報單待付款子頁籤對使用者說的話（IP-103）
PAYSLIP_MISSING = "薪資獎金模組未安裝：出納頁不顯示勞報單待付款"


def _payslip_visible(user: dict) -> bool:
    """勞報單金額只給最高管理者與出納（同獎金分潤的可見範圍）；本頁的財務（finance）看不到。"""
    return user.get("role") == "superadmin" or user_has_module(user, "cashier")


@router.get("/api/cashier/payslip-queue")
def get_payslip_queue(authorization: str = Header(None)):
    """勞報單待付款（IP-103 payslip.payables）：對方已簽回、等出納填付款日期與傳票單號。
    「標記已付款」打的是勞報單那一支 `POST /api/payslips/{單號}/mark-paid`——同一個動作，不在這裡另寫一份。"""
    user = _require_user(authorization)
    _require_view_access(user)
    visible = _payslip_visible(user)
    if not visible:
        return {"available": True, "visible": False, "notice": "", "items": []}
    p = registry.single_provider("payslip.payables")
    if p is None:
        return {"available": False, "visible": True, "notice": PAYSLIP_MISSING, "items": []}
    conn = get_db()
    try:
        items = p.pending(conn)
    finally:
        conn.close()
    return {"available": True, "visible": True, "notice": "", "items": items, "canMarkPaid": True}


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
    # W1：請款付款（案件額外支出等，IP-100）的付款紀錄；提供者沒有 paid ⇒ 略過
    payreq = []
    for name, p in sorted(registry.providers("payables.pending").items()):
        if hasattr(p, "paid"):
            payreq.extend(dict(it, source=name) for it in p.paid(conn, start, end))
    out = {
        "start": start, "end": end,
        "outgoing": outgoing, "outgoingTotal": sum(v["grandTotal"] for v in outgoing),
        "outgoingActualTotal": sum((v["remitActual"] if v.get("remitActual") is not None else v["grandTotal"]) for v in outgoing),
        "outgoingFeeTotal": sum(v.get("remitFee") or 0 for v in outgoing),
        "payreqPaid": payreq, "payreqFeeTotal": sum(i.get("fee") or 0 for i in payreq),
        "incoming": incoming, "incomingTotal": sum(i["netAmount"] or 0 for i in incoming),      # 銀行實際入帳（2026-09-30；收入＝入帳＋客戶內扣手續費）
        "incomingFeeTotal": sum(i["feeAmount"] or 0 for i in incoming),
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
@export_logged("xlsx", "arap", "cashier-history")
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
    hdrs1 = ["申請單號", "關聯案件", "廠商", "應付金額", "應付款日期", "匯款日期", "實付金額", "手續費", "差額", "差額審核"]
    review_label = {"pending": "待審核", "approved": "已核可", "": ""}
    for i, w in enumerate([14, 14, 18, 12, 12, 12, 12, 10, 10, 10], 1):
        ws1.column_dimensions[chr(64 + i)].width = w
    ws1.merge_cells("A1:J1")
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
        set_row(ws1, r, [data["contractorNotice"]] + [""] * 9, font=mk(size=9), border=BD,
                aligns=[al("left")], height=18)
        r += 1
    for v in data["outgoing"]:
        set_row(ws1, r, [v["voucherNo"], v["quoteNo"], v["vendorName"] or "（外包人員點工）",
                           v["grandTotal"], v["payableDate"] or "", v["paidAt"][:10] if v["paidAt"] else "",
                           v["remitActual"] if v.get("remitActual") is not None else v["grandTotal"],
                           v.get("remitFee") or 0, v.get("remitDiff") or 0, review_label.get(v.get("remitReview") or "", "")],
                 font=mk(size=9), border=BD, aligns=[al("left")], height=18)
        for col in (4, 7, 8, 9):
            ws1.cell(row=r, column=col).number_format = '#,##0.##'
        r += 1
    set_row(ws1, r, ["合計", "", "", data["outgoingTotal"], "", "", data["outgoingActualTotal"], data["outgoingFeeTotal"], "", ""],
             font=mk(bold=True, size=9, color=C_WHITE), fill=fill(C_DARK), border=BD,
             aligns=[al("left")], height=20)
    for col in (4, 7, 8):
        ws1.cell(row=r, column=col).number_format = '#,##0.##'

    if data["payreqPaid"]:                                          # W1：請款付款（案件額外支出）明細
        wsp = wb.create_sheet("請款付款明細")
        wsp.sheet_view.showGridLines = False
        for i, w in enumerate([10, 14, 24, 12, 12, 10, 12, 10], 1):
            wsp.column_dimensions[chr(64 + i)].width = w
        set_row(wsp, 1, ["來源", "關聯案件", "事由", "應付金額", "實付金額", "手續費", "付款日", "差額審核"],
                font=mk(bold=True, size=9, color=C_WHITE), fill=fill("374151"), border=BD, aligns=[al("center")], height=20)
        for i, it in enumerate(data["payreqPaid"], 2):
            set_row(wsp, i, [it.get("sourceLabel") or it["source"], it.get("quoteNo") or "", it.get("title") or "",
                             it.get("payable") or 0, it.get("actual") or 0, it.get("fee") or 0, it.get("paidAt") or "",
                             review_label.get(it.get("review") or "", "")],
                    font=mk(size=9), border=BD, aligns=[al("left")], height=18)
            for col in (4, 5, 6):
                wsp.cell(row=i, column=col).number_format = '#,##0.##'

    ws2 = wb.create_sheet("已收款明細")
    ws2.sheet_view.showGridLines = False
    hdrs2 = ["案件號", "客戶", "業務員", "款項類型", "實收金額（銀行入帳）", "收款日", "客戶內扣手續費"]
    for i, w in enumerate([14, 18, 10, 10, 18, 12, 14], 1):
        ws2.column_dimensions[chr(64 + i)].width = w
    ws2.merge_cells("A1:G1")
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
        set_row(ws2, r, [it["quoteNo"], it["customer"], it["salesPerson"], it["type"],
                           it["netAmount"], it["receivedAt"], it["feeAmount"] or None],
                 font=mk(size=9), border=BD, aligns=[al("left")], height=18)
        ws2.cell(row=r, column=5).number_format = '#,##0'
        ws2.cell(row=r, column=7).number_format = '#,##0'
        r += 1
    set_row(ws2, r, ["合計", "", "", "", data["incomingTotal"], "", data["incomingFeeTotal"]],
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
    return Response(
        content=buf.getvalue(),
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


# ── 匯出：PDF 姊妹（使用者規則 2026-09-30：每個 Excel 匯出都要同時提供 PDF、每次匯出都要留紀錄）──
# 匯出稽核／PDF 姊妹的「歸屬區」＝稽核 detail.module 的字串，**不是權限 key**；用常數傳而不是字面量：
# tests/test_module_keys_consistency 的後端掃描器把任何 module 等號字串字面量當權限 key。
_EXPORT_AREA = "arap"
add_pdf_sibling(router, "/api/cashier/export/pdf", export_execution_history, module=_EXPORT_AREA, name="cashier-history", title="出納執行紀錄")
