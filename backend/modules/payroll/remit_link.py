# -*- coding: utf-8 -*-
"""IP-104 `payslip.remit`：承攬商匯款單（M04）與勞報單（M07）的連結（R12，使用者 2026-09-30 裁示 (b)）。

[規則] 承攬商派工的個人（外包人員）匯款前必須關聯一張勞報單，匯款金額＝該勞報單實付（扣繳留在勞報單）；匯款單標記已匯款時，
  連結的勞報單一併記為已付款（付款日＝匯款日、`data_json.paid_via_remit`＝匯款單號），總帳不再另產生該勞報單的 E06b；取消匯款則一併退回。
[三個動作，都不 commit（呼叫端與匯款單同一個交易）]
- `check(conn, slip_no)`：唯讀，回付款前要驗的欄位（不含個資）；不存在 ⇒ None。
- `mark_paid(conn, slip_nos, remit_no, payment_date, who)`：已簽回 → 已付款；回實際更新筆數。
- `unmark_paid(conn, remit_no)`：把 `paid_via_remit == remit_no` 的勞報單退回已簽回；回筆數。
"""
import json
from datetime import datetime


def _data(raw):
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def check(conn, slip_no):
    r = conn.execute("SELECT slip_no, status, contractor_id, contractor_name, net_amount, data_json FROM payslips WHERE slip_no=?",
                     (str(slip_no or "").strip(),)).fetchone()
    if r is None:
        return None
    return {"slipNo": r["slip_no"], "status": r["status"], "contractorId": r["contractor_id"], "contractorName": r["contractor_name"] or "",
            "net": float(r["net_amount"] or 0), "paidViaRemit": _data(r["data_json"]).get("paid_via_remit") or ""}


def mark_paid(conn, slip_nos, remit_no, payment_date, who):
    now = datetime.now().isoformat()
    n = 0
    for no in slip_nos:
        r = conn.execute("SELECT data_json FROM payslips WHERE slip_no=? AND status='已簽回'", (no,)).fetchone()
        if r is None:
            continue
        d = _data(r["data_json"])
        d["paid_via_remit"] = remit_no
        cur = conn.execute("UPDATE payslips SET status='已付款', payment_date=?, voucher_no='', paid_by=?, paid_at=?, data_json=?, updated_at=? "
                           "WHERE slip_no=? AND status='已簽回'", (payment_date, who, now, json.dumps(d, ensure_ascii=False), now, no))
        n += cur.rowcount
    return n


def unmark_paid(conn, remit_no):
    now = datetime.now().isoformat()
    n = 0
    for r in conn.execute("SELECT slip_no, data_json FROM payslips WHERE status='已付款'").fetchall():
        d = _data(r["data_json"])
        if d.get("paid_via_remit") != remit_no:
            continue
        d.pop("paid_via_remit", None)
        conn.execute("UPDATE payslips SET status='已簽回', payment_date='', voucher_no='', paid_by='', paid_at='', data_json=?, updated_at=? "
                     "WHERE slip_no=?", (json.dumps(d, ensure_ascii=False), now, r["slip_no"]))
        n += 1
    return n


class _Remit:
    check = staticmethod(check)
    mark_paid = staticmethod(mark_paid)
    unmark_paid = staticmethod(unmark_paid)
