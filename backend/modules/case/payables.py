# -*- coding: utf-8 -*-
"""IP-100 `payables.pending`：M01 的請款待付款（INTEGRATION-POINTS；2026-09-27 使用者裁示請款流程）。

[單位] case:payables    [層] L2（M01）    [穩定度] 契約（IP-100 v1）
[公開介面] _Payables.pending(conn), _Payables.mark_paid(conn, key, paid_date, user)
[不變式] 只列「已核准、付款日空白」的案件額外支出；登錄付款＝寫回同一筆的 paid_date ⇒ 從清單消失、月支出現金口徑改用這一天
[契約題] modules/case/tests/test_payreq_2026_09_27.py、modules/arap/tests/test_cashier_pending_payables_2026_09_27.py

出納（M05）不直接讀本模組的表：列清單、登錄付款都經這個提供者（出納通常看不到案件本身——案件的擁有者規則不放行出納）。
"""
import json
from datetime import datetime

from modules.case.recognition import _approved_at

SOURCE_LABEL = "案件額外支出（請款）"


def _col(r, name, default=""):
    try:
        return r[name]
    except (IndexError, KeyError):
        return default


def _files(raw):
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def _item(r):
    files = _files(r["files_json"])
    return {
        "key": str(r["id"]), "sourceLabel": SOURCE_LABEL,
        "quoteNo": r["quote_no"] or "", "customerName": _col(r, "customer_name") or "", "projectName": _col(r, "project_name") or "",
        "title": "%s｜%s" % (r["category"] or "其他", r["description"] or ""),
        "amount": float(r["total_cost"] or 0),
        "payee": r["payer_name"] or r["created_by_name"] or "", "requestedBy": r["created_by_name"] or "",
        "expenseDate": (r["expense_date"] or "")[:10], "approvedAt": _approved_at(r["approval_json"]) or "",
        "invoiceDate": (_col(r, "invoice_date") or "")[:10], "invoiceNo": _col(r, "invoice_no") or "",
        "invoiceFiles": sum(1 for f in files if isinstance(f, dict) and f.get("kind") == "invoice"),
        "files": len(files),
    }


class _Payables:
    """IP-100 提供者（多提供者，名稱 `case`）。"""

    @staticmethod
    def pending(conn) -> list:
        rows = conn.execute(
            "SELECT e.*, q.customer_name, q.project_name FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
            " WHERE e.status = '已核准' AND COALESCE(e.paid_date, '') = '' ORDER BY e.id").fetchall()
        return [_item(r) for r in rows]

    @staticmethod
    def mark_paid(conn, key, paid_date, user) -> dict:
        """寫回付款日。查無 ⇒ LookupError；不是已核准或已登錄過 ⇒ ValueError（呼叫端各自轉 404／409）。不 commit（呼叫端）。

        原子（稽核 A AB-S1）：先用帶條件的 UPDATE（已核准、付款日空白）寫，`rowcount==0` 才回頭讀原因——
        兩位出納同時按「登錄付款」，後到的那位拿到「已被登錄」，不會蓋掉前者的付款日。"""
        try:
            exp_id = int(key)
        except (TypeError, ValueError):
            raise LookupError("找不到這筆請款")
        cur = conn.execute(
            "UPDATE case_extra_expenses SET paid_date=?, updated_at=?, updated_by_name=?"
            " WHERE id=? AND status='已核准' AND COALESCE(paid_date, '')=''",
            (paid_date, datetime.now().isoformat(timespec="seconds"),
             user.get("display_name") or user.get("username") or "", exp_id))
        r = conn.execute("SELECT id, quote_no, status, paid_date, total_cost FROM case_extra_expenses WHERE id=?",
                         (exp_id,)).fetchone()
        if cur.rowcount == 0:
            if not r:
                raise LookupError("找不到這筆請款")
            if r["status"] != "已核准":
                raise ValueError("這筆請款還沒核准，不能登錄付款")
            raise ValueError("這筆請款已被登錄付款日 %s（可能是另一位出納剛登錄）" % (r["paid_date"] or ""))
        return {"quoteNo": r["quote_no"], "key": str(exp_id), "amount": float(r["total_cost"] or 0), "paidDate": paid_date}
