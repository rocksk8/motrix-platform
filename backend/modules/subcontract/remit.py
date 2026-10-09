# -*- coding: utf-8 -*-
"""承攬商匯款單的匯款實付／手續費／差額審核（W1，2026-09-30 使用者裁示）。

[單位] subcontract:remit    [層] L2（M04）
[規則]
- 應付＝匯款單快照 grandTotal；實付（remit_actual）不帶＝等於應付；手續費（remit_fee）是**公司自付的額外支出**，不從受款方扣，
  不參與比對；匯款日期（paid_at）由呼叫端驗。
- 實付 ≠ 應付（四捨五入到分）⇒ remit_review='pending'（差額待審核）：照常標已匯款、通知 admin，
  admin／superadmin 核可（approved）或退回（＝回未匯款，實付／手續費／審核欄位清空，紀錄留在 paid_log 與稽核）。
- IP-102 `remit.reviews`（名稱 `contractor_voucher`）：M05 出納頁的審核清單與核可／退回都經 `_RemitReviews`。
- IP-9 `expense.entries`（名稱 `remit_fee_contractor`）：手續費以匯款日列為營運報表支出（權責／現金兩口徑相同）。
"""
from helpers.validation import body_flag  # noqa: E402
import json
import math
from datetime import datetime

class RemitForbidden(ValueError):
    """自己標記的匯款不能自己核可／退回（呼叫端轉 403）。"""
    status = 403


REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
FEE_CATEGORY = "匯款手續費"
SOURCE_LABEL = "承攬商匯款"


def _num(v, label):
    """數字欄位 ⇒ 四捨五入到分的 float；非數字、非有限、布林 ⇒ ValueError（呼叫端轉 400）。"""
    if isinstance(v, bool) or v is None or (isinstance(v, str) and not v.strip()):
        raise ValueError("%s格式不正確" % label)
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s格式不正確" % label)
    if not math.isfinite(f):
        raise ValueError("%s格式不正確" % label)
    return round(f + 0.0, 2)


def parse_remit(body, payable):
    """從請求 body 取實付／手續費 ⇒ `{actual, fee, review, diff}`；格式不對 ⇒ ValueError。

    接受 `actualAmount`／`actual_amount`、`hasFee`／`has_fee`（勾選有手續費；沒勾＝0，不管有沒有帶金額）、`fee`／`remit_fee`。
    實付不帶＝應付；手續費勾選了就要有金額且 ≥ 0。"""
    body = body or {}
    payable = round(float(payable or 0), 2)
    raw_actual = body.get("actualAmount", body.get("actual_amount"))
    actual = payable if raw_actual in (None, "") else _num(raw_actual, "實付金額")
    if actual <= 0:
        raise ValueError("實付金額必須大於 0")
    has_fee = body_flag(body, "hasFee", body_flag(body, "has_fee"))      # 第50班 W1c-P2b：字串 "false" 以前會被當成有手續費
    fee = 0.0
    if has_fee:
        fee = _num(body.get("fee", body.get("remit_fee")), "手續費")
        if fee < 0:
            raise ValueError("手續費不可為負數")
    diff = round(actual - payable, 2)
    return {"actual": actual, "fee": fee, "diff": diff,
            "review": REVIEW_PENDING if diff != 0 else ""}


def actual_of(row, payable):
    """實付金額：有記錄用記錄，舊資料（NULL）回退應付。row 可為 sqlite Row 或 dict。"""
    try:
        v = row["remit_actual"]
    except (KeyError, IndexError):
        v = None
    return float(payable or 0) if v is None else float(v)


def _payable(snapshot_json):
    try:
        return float((json.loads(snapshot_json or "{}") or {}).get("grandTotal") or 0)
    except (TypeError, ValueError):
        return 0.0


def remit_fields(d):
    """`_voucher_public` 併入的欄位（d＝資料列 dict）。"""
    payable = _payable(d.get("snapshot_json"))
    has = d.get("remit_actual") is not None
    actual = float(d["remit_actual"]) if has else payable
    return {
        "payableAmount": payable,
        "remitActual": actual if d.get("is_paid") else None,
        "remitFee": float(d.get("remit_fee") or 0),
        "remitDiff": round(actual - payable, 2) if (d.get("is_paid") and has) else 0,
        "remitReview": d.get("remit_review") or "",
        "remitReviewBy": d.get("remit_review_by") or "",
        "remitReviewAt": d.get("remit_review_at") or "",
        "remitReviewNote": d.get("remit_review_note") or "",
    }


CLEAR_SQL = ("remit_actual=NULL, remit_fee=0, remit_review='', remit_review_by='', "
             "remit_review_at='', remit_review_note=''")


class _RemitReviews:
    """IP-102 `remit.reviews` 提供者（名稱 `contractor_voucher`）：列出差額待審核、核可／退回。"""

    @staticmethod
    def pending(conn):
        out = []
        for r in conn.execute(
                "SELECT v.*, q.customer_name FROM contractor_payment_vouchers v"
                " LEFT JOIN quotations q ON q.quote_no = v.quote_no"
                " WHERE v.is_paid=1 AND v.remit_review=? ORDER BY v.paid_at", (REVIEW_PENDING,)).fetchall():
            d = dict(r)
            payable = _payable(d.get("snapshot_json"))
            actual = actual_of(d, payable)
            try:
                vendor = (json.loads(d.get("snapshot_json") or "{}") or {}).get("vendorName") or ""
            except ValueError:
                vendor = ""
            out.append({"key": d["voucher_no"], "sourceLabel": SOURCE_LABEL, "quoteNo": d["quote_no"] or "",
                        "customerName": d.get("customer_name") or "", "payee": vendor or "（外包人員點工）",
                        "payable": payable, "actual": actual, "diff": round(actual - payable, 2),
                        "fee": float(d.get("remit_fee") or 0), "paidAt": (d.get("paid_at") or "")[:10],
                        "paidBy": d.get("paid_by") or ""})
        return out

    @staticmethod
    def decide(conn, key, decision, user, note=""):
        """approve ⇒ 核可；reject ⇒ 退回（回未匯款）。查無 ⇒ LookupError；不是待審核 ⇒ ValueError。不 commit（呼叫端）。
        帶條件的 UPDATE（is_paid=1 且 remit_review='pending'）＋rowcount：兩位主管同時按，後到的得到「已被處理」。"""
        if decision not in ("approve", "reject"):
            raise ValueError("decision 必須為 approve 或 reject")
        row = conn.execute("SELECT voucher_no, quote_no, paid_log, remit_review, is_paid, paid_by FROM contractor_payment_vouchers"
                           " WHERE voucher_no=?", (key,)).fetchone()
        if not row:
            raise LookupError("找不到這張匯款申請")
        # W1 稽核 M4：標記匯款的人不能自己核可／退回自己的差額（paid_by 存的是顯示名稱，帳號與顯示名稱都比）
        if row["remit_review"] == REVIEW_PENDING and (row["paid_by"] or "") in (
                user.get("username") or "\0", user.get("display_name") or "\0"):
            raise RemitForbidden("這筆匯款是您自己標記的，差額需由其他財務角色成員或最高管理者審核")
        now = datetime.now().isoformat()
        who = user.get("display_name") or user.get("username") or ""
        log = json.loads(row["paid_log"] or "[]")
        log.append({"at": now, "username": user.get("username") or "", "userDisplay": who,
                    "action": "remit_review_" + ("approved" if decision == "approve" else "rejected"), "note": note})
        if decision == "approve":
            cur = conn.execute(
                "UPDATE contractor_payment_vouchers SET remit_review=?, remit_review_by=?, remit_review_at=?,"
                " remit_review_note=?, paid_log=?, updated_at=? WHERE voucher_no=? AND is_paid=1 AND remit_review=?",
                (REVIEW_APPROVED, who, now, note, json.dumps(log, ensure_ascii=False), now, key, REVIEW_PENDING))
        else:
            cur = conn.execute(
                "UPDATE contractor_payment_vouchers SET is_paid=0, paid_by='', paid_at='', paid_bank_account_name='',"
                " paid_bank_account_code='', " + CLEAR_SQL + ", paid_log=?, updated_at=? WHERE voucher_no=? AND is_paid=1"
                " AND remit_review=?", (json.dumps(log, ensure_ascii=False), now, key, REVIEW_PENDING))
        if cur.rowcount == 0:
            raise ValueError("這張匯款申請不是待審核狀態（可能已被處理）")
        out = {"quoteNo": row["quote_no"], "key": key, "decision": decision}
        if decision == "reject":                                    # 差額退回＝回未匯款 ⇒ 重建「付款待辦」（出納端 commit 後 upsert；事件不含金額）
            from modules.subcontract import payable_due as _pd
            ev = _pd.event_tuple(conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (key,)).fetchone())
            if ev:
                out["payableEvent"] = ev
        return out


def _expense_entries(conn, start, end):
    """IP-9：匯款日在 [start, end] 的手續費 ⇒ `[{date, quoteNo, desc, amount, category}]`（一單一筆）。"""
    out = []
    for r in conn.execute(
            "SELECT voucher_no, quote_no, snapshot_json, paid_at, remit_fee, remit_review FROM contractor_payment_vouchers"
            " WHERE is_paid=1 AND remit_fee > 0 AND substr(paid_at, 1, 10) BETWEEN ? AND ? ORDER BY paid_at",
            (start, end)).fetchall():
        try:
            vendor = (json.loads(r["snapshot_json"] or "{}") or {}).get("vendorName") or ""
        except ValueError:
            vendor = ""
        out.append({"date": (r["paid_at"] or "")[:10], "quoteNo": r["quote_no"] or "",
                    "desc": "%s｜%s（匯款申請 %s）" % (FEE_CATEGORY, vendor or "（外包人員點工）", r["voucher_no"]),
                    "amount": float(r["remit_fee"]), "category": FEE_CATEGORY, "pending": r["remit_review"] == REVIEW_PENDING})
    return out


def fee_total_for_case(conn, quote_no):
    """某案件已匯款的手續費合計（案件成本用）。"""
    r = conn.execute("SELECT COALESCE(SUM(remit_fee), 0) AS t FROM contractor_payment_vouchers"
                     " WHERE quote_no=? AND is_paid=1", (quote_no,)).fetchone()
    return float(r["t"] or 0)
