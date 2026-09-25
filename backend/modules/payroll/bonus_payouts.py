# -*- coding: utf-8 -*-
"""獎金分潤對外：出納頁（IP-8）、營運報表與月支出（IP-9）、通知對象（CORE-SPEC「使用者裁示」獎金分潤三項）。

- IP-8 `bonus.payouts`（M07 → M05 出納）：待發放清單、期間內已發放紀錄。
  出納頁的「標記已發放」打的是**同一支** `POST /api/bonus/cases/{單號}/mark-paid`（同一個動作，不另寫一份）。
- IP-9 `expense.entries`（M07 → M08 報表）：以**發放日**列為支出（案件合計，不列個人）。
- 通知對象：送審／換人簽 ⇒ 當層下一位簽核人＋他今天有效的代理人；進入待發放 ⇒ 出納。
  **名單上的成員不會因為「在名單上」而收到通知**（金額屬敏感資訊）；信裡不放金額。
  ⚠️ 名單成員同時是簽核人或出納時，仍以簽核人／出納的身分收到（否則沒人知道要簽、要發）。

本檔在 M07 載入時登記提供者；M07 不在 ⇒ 沒有提供者，使用方照 INTEGRATION-POINTS 退化。
"""
import json
from datetime import date


#: 出納頁與報表的顯示文字
EXPENSE_CATEGORY = "獎金分潤"


def _parse(s):
    try:
        v = json.loads(s or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _case_rows(conn, where, args):
    return [dict(r) for r in conn.execute(
        "SELECT a.id, a.quote_no, a.status, a.paid_at, a.paid_by, a.updated_at,"
        " COALESCE(q.customer_name, '') AS customer_name, COALESCE(q.project_name, '') AS project_name,"
        " (SELECT COALESCE(SUM(l.amount), 0) FROM bonus_case_award_lines l WHERE l.award_id = a.id) AS total,"
        " (SELECT COUNT(DISTINCT l.username) FROM bonus_case_award_lines l WHERE l.award_id = a.id) AS people"
        " FROM bonus_case_awards a LEFT JOIN quotations q ON q.quote_no = a.quote_no"
        " WHERE " + where, args)]


def paid_snapshot(conn, award_id):
    """標記已發放那一筆編寫紀錄裡的扣繳快照（U4）。沒有 ⇒ None。"""
    row = conn.execute(
        "SELECT changes_json FROM bonus_case_award_edit_log WHERE award_id = ? AND action = 'mark_paid'"
        " ORDER BY id DESC LIMIT 1", (award_id,)).fetchone()
    if row is None:
        return None
    return _parse(row["changes_json"]).get("deductions")


# ── IP-8 bonus.payouts（契約版本 1）───────────────────────────────────────────

class _Payouts:
    """出納頁用。兩支都在呼叫端的連線上讀，不寫。"""

    @staticmethod
    def pending(conn):
        """待發放：[{quoteNo, customer, project, total, people, approvedAt}]，舊的在前。"""
        rows = _case_rows(conn, "a.status = '待發放' ORDER BY a.updated_at", ())
        return [{"quoteNo": r["quote_no"], "customer": r["customer_name"], "project": r["project_name"],
                 "total": int(r["total"] or 0), "people": int(r["people"] or 0),
                 "approvedAt": (r["updated_at"] or "")[:10]} for r in rows]

    @staticmethod
    def paid(conn, start, end):
        """發放日在 [start, end]（YYYY-MM-DD，含首尾）：
        [{quoteNo, customer, project, total, people, paidAt, paidBy, withholding, nhiPremium, net}]。
        扣繳快照不存在（R1 接上前發放的）⇒ withholding／nhiPremium／net 為 None（不是 0）。"""
        rows = _case_rows(conn, "a.status = '已發放' AND substr(a.paid_at, 1, 10) BETWEEN ? AND ?"
                                " ORDER BY a.paid_at DESC", (start, end))
        out = []
        for r in rows:
            snap = paid_snapshot(conn, r["id"]) or {}
            tot = snap.get("totals") or {}
            out.append({"quoteNo": r["quote_no"], "customer": r["customer_name"], "project": r["project_name"],
                        "total": int(r["total"] or 0), "people": int(r["people"] or 0),
                        "paidAt": (r["paid_at"] or "")[:10], "paidBy": r["paid_by"] or "",
                        "withholding": tot.get("withholding"), "nhiPremium": tot.get("nhiPremium"),
                        "net": tot.get("net")})
        return out


# IP-8 由 modules/payroll/__init__.py 的 ModuleSpec.providers 登記（模組沒載入就沒有登記）


# ── IP-9 expense.entries（契約版本 1；多提供者，以名稱區分）─────────────────────

def _expense_entries(conn, start, end):
    """發放日在 [start, end] 的獎金分潤：[{date, quoteNo, desc, amount, category}]，一案一筆（不列個人）。"""
    rows = _case_rows(conn, "a.status = '已發放' AND substr(a.paid_at, 1, 10) BETWEEN ? AND ?"
                            " ORDER BY a.paid_at", (start, end))
    return [{"date": (r["paid_at"] or "")[:10], "quoteNo": r["quote_no"],
             "desc": "%s（%d 人）" % (EXPENSE_CATEGORY, int(r["people"] or 0)),
             "amount": int(r["total"] or 0), "category": EXPENSE_CATEGORY} for r in rows]


# IP-9 由 modules/payroll/__init__.py 的 ModuleSpec.providers 登記


# ── 通知對象 ─────────────────────────────────────────────────────────────────

def _active(conn, usernames):
    if not usernames:
        return []
    ph = ",".join("?" * len(usernames))
    ok = {r["username"] for r in conn.execute(
        "SELECT username FROM users WHERE active = 1 AND username IN (%s)" % ph, list(usernames))}
    return [u for u in usernames if u in ok]


def delegates_of(conn, username, today=None):
    """username 今天有效的簽核代理人。"""
    today = today or date.today().isoformat()
    return [r["delegate_username"] for r in conn.execute(
        "SELECT delegate_username FROM approval_delegates WHERE delegator_username = ? AND active = 1"
        " AND start_date <= ? AND end_date >= ? ORDER BY id", (username, today, today))]


def approver_recipients(conn, award, appr, requester):
    """現在輪到誰簽：當層第一位未簽的人＋他的代理人。沒有簽核鏈 ⇒ 最高管理者（申請人自己除外）。"""
    tiers = appr.get("tiers") or []
    ct = int(appr.get("currentTier") or 0)
    if tiers:
        if ct >= len(tiers):
            return []
        nxt = next((a for a in (tiers[ct].get("approvers") or []) if a.get("status") != "approved"), None)
        if nxt is None:
            return []
        who = [nxt.get("username") or ""] + delegates_of(conn, nxt.get("username") or "")
    else:
        who = [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE active = 1 AND role = 'superadmin' ORDER BY id")
            if r["username"] != requester]
    return _active(conn, list(dict.fromkeys(w for w in who if w)))


def cashier_recipients(conn, award):
    """持有出納模組（cashier）的在職帳號。"""
    out = []
    for r in conn.execute("SELECT username, modules FROM users WHERE active = 1 ORDER BY id"):
        try:
            mods = json.loads(r["modules"] or "[]")
        except (TypeError, ValueError):
            mods = []
        if "cashier" in (mods or []):
            out.append(r["username"])
    return out
