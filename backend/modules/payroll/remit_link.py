# -*- coding: utf-8 -*-
"""IP-105 `payslip.remit`：承攬商匯款單（M04）與勞報單（M07）的連結（R12，使用者 2026-09-30 裁示 (b)）。

[規則] 承攬商派工的個人（外包人員）匯款前必須關聯一張勞報單，匯款金額＝該勞報單實付（扣繳留在勞報單）；匯款單標記已匯款時，
  連結的勞報單一併記為已付款（付款日＝匯款日、`data_json.paid_via_remit`＝匯款單號），總帳不再另產生該勞報單的 E06b；取消匯款則一併退回。
[三個動作，都不 commit（呼叫端與匯款單同一個交易）]
- `check(conn, slip_no)`：唯讀，回付款前要驗的欄位（不含個資）；不存在 ⇒ None。
- `candidates(conn, contractor_id)`：該受款人已核准／已匯出／已簽回、未付款的勞報單清單（{slipNo, net, slipDate, incomeType}）。
- `mark_paid(conn, slip_nos, remit_no, payment_date, who)`：已核准／已匯出／已簽回 → 已付款；回實際更新筆數。
- `unmark_paid(conn, remit_no)`：把 `paid_via_remit == remit_no` 的勞報單退回付款前最近的狀態（有簽回檔＝已簽回；匯出過＝已匯出；否則已核准）；回筆數。
[第46班 Q13（使用者裁示）] 與「已核准即可付款」（Q4）一致：匯款單關聯勞報單由「須已簽回」放寬為 已核准／已匯出／已簽回。
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


#: 可由匯款單付款的勞報單狀態（Q13）
PAYABLE = ("已核准", "已匯出", "已簽回")


def candidates(conn, contractor_id):
    """該受款人『已核准以上（已核准／已匯出／已簽回）、尚未付款』的勞報單（供匯款單挑選）；不含個資。"""
    return [{"slipNo": r["slip_no"], "net": float(r["net_amount"] or 0), "slipDate": r["slip_date"] or "", "incomeType": r["income_type"] or ""}
            for r in conn.execute("SELECT slip_no, net_amount, slip_date, income_type FROM payslips WHERE contractor_id=? AND status IN ('已核准','已匯出','已簽回') "
                                  "ORDER BY slip_date DESC, slip_no DESC", (contractor_id,)).fetchall()]


def mark_paid(conn, slip_nos, remit_no, payment_date, who):
    now = datetime.now().isoformat()
    n = 0
    for no in slip_nos:
        r = conn.execute("SELECT data_json FROM payslips WHERE slip_no=? AND status IN ('已核准','已匯出','已簽回')", (no,)).fetchone()
        if r is None:
            continue
        d = _data(r["data_json"])
        d["paid_via_remit"] = remit_no
        cur = conn.execute("UPDATE payslips SET status='已付款', payment_date=?, voucher_no='', paid_by=?, paid_at=?, data_json=?, updated_at=? "
                           "WHERE slip_no=? AND status IN ('已核准','已匯出','已簽回')", (payment_date, who, now, json.dumps(d, ensure_ascii=False), now, no))
        n += cur.rowcount
    return n


def unmark_paid(conn, remit_no):
    now = datetime.now().isoformat()
    n = 0
    from modules.payroll.payslip_payables import unpay_status
    for r in conn.execute("SELECT slip_no, data_json, signed_files_json, export_count FROM payslips WHERE status='已付款'").fetchall():
        d = _data(r["data_json"])
        if d.get("paid_via_remit") != remit_no:
            continue
        d.pop("paid_via_remit", None)
        conn.execute("UPDATE payslips SET status=?, payment_date='', voucher_no='', paid_by='', paid_at='', data_json=?, updated_at=? "
                     "WHERE slip_no=?", (unpay_status(r), json.dumps(d, ensure_ascii=False), now, r["slip_no"]))
        n += 1
    return n


class _Remit:
    check = staticmethod(check)
    candidates = staticmethod(candidates)
    mark_paid = staticmethod(mark_paid)
    unmark_paid = staticmethod(unmark_paid)
