"""出納模組（2026-08-31 新增）：跨案件彙整「待付款」（已核准未匯款的承攬商
匯款申請）與「待收款」（未收款的案件款項期別），供財務/出納分工的出納
角色使用，取代原本要一個案件一個案件點進去才看得到待辦事項的做法。

權限：admin+ 或具備 cashier 模組（見 helpers.user_has_module()），跟既有
paid-toggle／mark_payment／bank-reconcile 的門檻一致（見那幾支端點同一輪
一併補上的 cashier 模組判斷）。
"""
import json
from datetime import date

from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, user_has_module, payment_item_amounts
from routers.contractor_vouchers import _voucher_public

router = APIRouter()


def _require_admin_or_cashier(user: dict) -> None:
    if user["role"] not in ("superadmin", "admin") and not user_has_module(user, "cashier"):
        raise HTTPException(403, "僅管理員或出納可存取")


def _payable_queue(conn) -> list:
    rows = conn.execute("""
        SELECT * FROM contractor_payment_vouchers
        WHERE status='已核准' AND is_paid=0
    """).fetchall()
    items = [_voucher_public(r, include_snapshot=False) for r in rows]
    # payableDate 空值排最後；非空依日期升冪（快到期的排前面）
    items.sort(key=lambda v: (not v["payableDate"], v["payableDate"]))
    return items


def _receivable_queue(conn) -> list:
    today = date.today()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person,
               total, pretax, quote_date,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
        ORDER BY quote_date ASC
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
            if pi.get("received"):
                continue
            expected = pi.get("expectedReceiptDate") or ""
            items.append({
                "quoteNo":             row["quote_no"],
                "idx":                 idx,
                "customer":            row["customer_name"] or "",
                "project":             row["project_name"] or "",
                "salesPerson":         row["sales_person"] or "",
                "dealTag":             row["deal_tag"] or "",
                "type":                pi.get("type", f"第{idx+1}期"),
                "amount":              amounts[idx],
                "quoteDate":           row["quote_date"] or "",
                "expectedReceiptDate": expected,
                "overdue":             bool(expected) and expected < today.isoformat(),
            })

    # expectedReceiptDate 空值排最後；非空依日期升冪
    items.sort(key=lambda i: (not i["expectedReceiptDate"], i["expectedReceiptDate"]))
    return items


@router.get("/api/cashier/payable-queue")
def get_payable_queue(authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin_or_cashier(user)
    conn = get_db()
    try:
        return _payable_queue(conn)
    finally:
        conn.close()


@router.get("/api/cashier/receivable-queue")
def get_receivable_queue(authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin_or_cashier(user)
    conn = get_db()
    try:
        return _receivable_queue(conn)
    finally:
        conn.close()


@router.get("/api/cashier/summary")
def get_cashier_summary(authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin_or_cashier(user)
    conn = get_db()
    try:
        payable = _payable_queue(conn)
        receivable = _receivable_queue(conn)
    finally:
        conn.close()
    return {"payableCount": len(payable), "receivableCount": len(receivable)}
