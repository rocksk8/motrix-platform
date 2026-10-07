# -*- coding: utf-8 -*-
"""勞報單 ⇄ 出納（第 46 班；設計 PAYSLIP-APPROVAL-T45.md §4）：IP-100 `payables.pending`（名稱 `payroll_payslip`）。

[單位] payroll:payslip_payables    [層] L2（M07）    [穩定度] 實作
[公開介面] mark_payslip_paid(conn, slip_no, payment_date, voucher_no, who)（付款唯一實作，勞報單端點與出納 IP-100 共用）、
          unpay_status(row)、_Payables（IP-100 提供者）
[規則（使用者 2026-10-07 裁示）]
  Q1 出納端權限＝財務角色＋superadmin（`has_finance_access`／`has_cashier_access`），不再認 `cashier` 模組勾選；金額可見＝能付款的人。
  Q4 **付款不需已簽回**：已核准／已匯出／已簽回且未付款即可付款；匯出與簽回檔都變選填（舊的已簽回列行為不變）。
  Q7 **不進行事曆**（`NO_CALENDAR`：出納端不為勞報單建「支出付款」事件；`payable_due` 以 L1 來源開關排除）。只有 `planned_pay_date` 欄位＋出納清單。
  付款日只在出納這步填；傳票單號必填並經 `voucher.by_no`（IP-4）驗證。出納清單**不回**身分證、地址、電話、銀行帳號（F2）。
"""
import json
import logging
from datetime import datetime

from core import registry

logger = logging.getLogger(__name__)

SOURCE_LABEL = "勞報單"
#: 可付款的狀態（Q4：已核准即可；已匯出、已簽回照舊）
PAYABLE_STATUSES = ("已核准", "已匯出", "已簽回")


class PayError(Exception):
    """付款被拒：`status`＝HTTP 狀態碼（呼叫端轉 HTTPException）。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _data(raw):
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def unpay_status(row) -> str:
    """付款填錯退回時回到哪個狀態（由資料推得，不新增欄位）：有簽回檔 ⇒ 已簽回；否則匯出過 ⇒ 已匯出；否則 已核准。
    舊列（已簽回後付款）有簽回檔 ⇒ 仍退回已簽回，與今天一致。"""
    try:
        files = json.loads(row["signed_files_json"] or "[]")
    except (TypeError, ValueError, KeyError, IndexError):
        files = []
    if files:
        return "已簽回"
    return "已匯出" if int(row["export_count"] or 0) > 0 else "已核准"


def mark_payslip_paid(conn, slip_no, payment_date, voucher_no, who) -> dict:
    """已核准／已匯出／已簽回 → 已付款（不 commit）。付款日期已由呼叫端驗過格式；傳票單號必填並驗證。⇒ {status, payment_date, voucher_no, paid_by}。
    失敗 ⇒ `PayError`（400／404／409）；兩位出納同時按，後到的拿到 409（帶條件的 UPDATE）。"""
    vno = (voucher_no or "").strip()
    if not vno:
        raise PayError(400, "請填寫傳票單號")
    row = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    if not row:
        raise PayError(404, "找不到此勞報單")
    if row["status"] == "已付款":
        raise PayError(409, "這張勞報單已付款")
    if row["status"] not in PAYABLE_STATUSES:
        raise PayError(409, "只有已核准、已匯出或已簽回的勞報單可以標記付款（目前「%s」）" % row["status"])
    # 傳票單號必須是系統裡真實存在且未作廢的傳票：經 M06 的 `voucher.by_no`（IP-4 追加），不直接讀會計的傳票表。
    # 會計模組不在 ⇒ 無法驗證 ⇒ 拒絕並說明（不猜、不放行）。
    lookup = registry.single_provider("voucher.by_no")
    if lookup is None:
        raise PayError(409, "會計模組未安裝，無法驗證傳票單號，暫不能標記付款")
    v = lookup(conn, vno)
    if v is None:
        raise PayError(400, "查無傳票單號 %s，請確認後再填" % vno)
    if v["voided"]:
        raise PayError(400, "傳票 %s 已作廢，請改填有效傳票" % vno)
    now = datetime.now().isoformat()
    cur = conn.execute("UPDATE payslips SET status='已付款', payment_date=?, voucher_no=?, paid_by=?, paid_at=?, updated_at=? "
                       "WHERE slip_no=? AND status IN ('已核准','已匯出','已簽回')", (payment_date, vno, who, now, now, slip_no))
    if cur.rowcount == 0:
        raise PayError(409, "這張勞報單已被付款或狀態已改變，請重新整理")
    return {"status": "已付款", "payment_date": payment_date, "voucher_no": vno, "paid_by": who}


def _signed_count(raw) -> int:
    try:
        return len(json.loads(raw or "[]"))
    except (TypeError, ValueError):
        return 0


def _item(r) -> dict:
    d = _data(r["data_json"])
    appr = _data(r["approval_json"]) if "approval_json" in r.keys() else {}
    return {
        "key": r["slip_no"], "sourceLabel": SOURCE_LABEL, "quoteNo": "", "customerName": "", "projectName": "",
        "title": ("%s %s" % (r["slip_no"], r["contractor_name"] or "")).strip(),            # 出納清單內部顯示（含受領人姓名；提醒信／通知文字不得帶）
        "amount": float(r["net_amount"] or 0),                                              # 現金出的是實發（扣繳另繳）；gross／tax 放 extra
        "payee": r["contractor_name"] or "", "requestedBy": appr.get("requestedBy") or r["created_by"] or "",
        "kind": "payslip", "docCode": r["slip_no"], "payeeType": "vendor", "payeeUsername": "", "payeeBank": "",
        "payTerms": "", "remitDate": "", "expenseDate": (r["slip_date"] or "")[:10],
        "approvedAt": (r["approved_at"] or "")[:10] or (r["signed_at"] or "")[:10] or (r["updated_at"] or "")[:10],
        "invoiceDate": "", "invoiceNo": "", "invoiceFiles": 0, "files": _signed_count(r["signed_files_json"]),
        "plannedPayDate": (r["planned_pay_date"] or "")[:10],
        "needsVoucherNo": True,                                                             # 出納頁要多一個「傳票單號」欄（必填）
        "signedBack": r["status"] == "已簽回",                                              # 小標「已簽回／未簽回」供參考，不影響付款（Q4）
        "payslipStatus": r["status"],
        "extra": {"gross": int(r["gross_amount"] or 0), "tax": int(r["tax_withheld"] or 0), "nhi": int(r["nhi_supplement"] or 0),
                  "incomeType": r["income_type"] or ""},
    }


class _Payables:
    """IP-100 提供者（名稱 `payroll_payslip`）。"""

    #: 勞報單不進行事曆（Q7）：出納端據此不為它建「支出付款」事件
    NO_CALENDAR = True
    #: 出納端 `payee-bank`：完整帳號只給財務角色與最高管理者（與叫料匯款同規則）
    FULL_ACCOUNT_STRICT = True

    @staticmethod
    def pending(conn) -> list:
        return [_item(r) for r in conn.execute(
            "SELECT * FROM payslips WHERE status IN ('已核准','已匯出','已簽回') ORDER BY COALESCE(NULLIF(approved_at,''), signed_at, updated_at), id").fetchall()]

    @staticmethod
    def paid(conn, start, end) -> list:
        """付款日在 [start, end] 的勞報單（出納執行紀錄用；經匯款單付款的不列，它們的付款在匯款單那邊）。"""
        out = []
        for r in conn.execute("SELECT * FROM payslips WHERE status='已付款' AND substr(payment_date,1,10) BETWEEN ? AND ? ORDER BY payment_date, id",
                              (start, end)).fetchall():
            if _data(r["data_json"]).get("paid_via_remit"):
                continue
            out.append({"key": r["slip_no"], "sourceLabel": SOURCE_LABEL, "quoteNo": "", "title": (r["slip_no"] + " " + (r["contractor_name"] or "")).strip(),
                        "payable": float(r["net_amount"] or 0), "actual": float(r["net_amount"] or 0), "fee": 0.0,
                        "paidAt": (r["payment_date"] or "")[:10], "review": ""})
        return out

    @staticmethod
    def mark_paid(conn, key, paid_date, user, remit=None) -> dict:
        """出納登錄付款（IP-100 `mark_paid`）：委派 `mark_payslip_paid`（與勞報單端點同一份實作）。`remit.voucherNo`＝傳票單號（必填）。不 commit。
        查無 ⇒ LookupError；其餘拒絕 ⇒ ValueError（帶 `status`，呼叫端轉 HTTP）。"""
        vno = (remit or {}).get("voucherNo") or (remit or {}).get("voucher_no") or ""
        who = user.get("display_name") or user.get("username") or ""
        row = conn.execute("SELECT net_amount, contractor_name FROM payslips WHERE slip_no=?", (key,)).fetchone()
        if row is None:
            raise LookupError("找不到這張勞報單")
        try:
            res = mark_payslip_paid(conn, key, paid_date, vno, who)
        except PayError as e:
            if e.status == 404:
                raise LookupError(str(e))
            err = ValueError(str(e))
            err.status = e.status
            raise err
        net = float(row["net_amount"] or 0)
        return {"quoteNo": "", "key": key, "amount": net, "paidDate": paid_date, "actual": net, "fee": 0.0, "diff": 0.0, "remitReview": "",
                "title": key, "payee": "", "voucherNo": res["voucher_no"]}

    @staticmethod
    def set_planned_pay_date(conn, key, value, user) -> dict:
        """出納端點改預定付款日（`value` 已正規化；''＝清除）。只認還在出納清單上的（已核准／已匯出／已簽回）；已付款 ⇒ ValueError（409）。不 commit。"""
        r = conn.execute("SELECT status, planned_pay_date, created_by, approval_json, slip_no FROM payslips WHERE slip_no=?", (key,)).fetchone()
        if r is None or r["status"] not in PAYABLE_STATUSES + ("已付款",):
            raise LookupError("找不到這張勞報單")
        if r["status"] == "已付款":
            raise ValueError("這張勞報單已付款，預定付款日保留為歷史紀錄，不能再修改")
        old = (r["planned_pay_date"] or "")[:10]
        conn.execute("UPDATE payslips SET planned_pay_date=?, updated_at=? WHERE slip_no=? AND status IN ('已核准','已匯出','已簽回')",
                     (value, datetime.now().isoformat(), key))
        return {"plannedPayDate": value, "old": old, "quoteNo": "", "applicant": _data(r["approval_json"]).get("requestedBy") or r["created_by"] or "",
                "docCode": r["slip_no"], "link": "payslips.html?q=%s" % r["slip_no"]}

    @staticmethod
    def planned_changed(key) -> None:
        """commit 之後呼叫（出納改預定日）：勞報單不進行事曆（Q7）⇒ 什麼都不做。"""
        return None

    @staticmethod
    def after_paid(key) -> None:
        """出納登錄付款 commit 之後呼叫：通知送審人「已付款」（不含金額）。**不碰行事曆**（Q7）。"""
        try:
            from db import get_db
            from modules.payroll import payslip_notify as _pn
            conn = get_db()
            try:
                r = conn.execute("SELECT status, slip_date, paid_by, approval_json, created_by FROM payslips WHERE slip_no=?", (key,)).fetchone()
            finally:
                conn.close()
            if r is not None and r["status"] == "已付款":
                _pn.fire_paid(key, r["slip_date"], _data(r["approval_json"]).get("requestedBy") or r["created_by"] or "", payer=r["paid_by"] or "")
        except Exception:                                            # noqa: BLE001 — 附帶動作
            logger.exception("勞報單已付款通知失敗（%s）", key)

    @staticmethod
    def payee_info(conn, key) -> dict:
        """出納付款前看收款人資料（完整，只給出納端點、每次看都留稽核）：取單據上的收款資料（F2）。查無／不在清單 ⇒ LookupError。"""
        r = conn.execute("SELECT status, contractor_name, data_json FROM payslips WHERE slip_no=?", (key,)).fetchone()
        if r is None or r["status"] not in PAYABLE_STATUSES:
            raise LookupError("找不到這張勞報單")
        d = _data(r["data_json"])
        return {"payeeType": "vendor", "payeeName": d.get("bankAccountName") or r["contractor_name"] or "", "payeeUsername": "",
                "bank": ("%s %s" % (d.get("bankCode") or "", d.get("bankName") or "")).strip(), "account": d.get("bankAccountNumber") or ""}
