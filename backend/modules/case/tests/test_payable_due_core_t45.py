# -*- coding: utf-8 -*-
"""第 45 班 S5／S7：共用提醒庫 `helpers.payable_due_core`——逾期提醒（Q2）、站內通知、叫料來源、行事曆來源開關與叫料事件跟著現況走。
Google 用假行事曆；寄信用攔截的 `_async_send`（不連外）。"""
import json
from datetime import date, timedelta

from modules.case.tests import test_payable_planned_pay_date_2026_10_05 as P
from modules.case.tests.test_payable_planned_pay_date_2026_10_05 import mails  # noqa: F401  fixture
from tests import _fake_gcal
from tests._requires import skip_module_unless

skip_module_unless("case", "提醒庫的案件來源在 M01")

NO = "MQ-PDC-001"


# ── 案件來源：逾期信＋站內通知 ───────────────────────────────────────────────

def _notes(username):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM notifications WHERE username=? AND type LIKE ? ORDER BY id", (username, "payable_due_%"))]
    finally:
        c.close()


def test_overdue_mail_once_and_finance_in_app_notice_without_amount(client, make_user, mails):
    P._finance(make_user, "pdc_fin")
    P._finance(make_user, "pdc_muted", muted=("payable_due_overdue",))
    make_user(username="pdc_eng", role="user")
    P._seed_exp(planned=P.TODAY.isoformat(), amount=7777)
    nxt = P.TODAY + timedelta(days=1)
    assert P._run(nxt) == 1 and P._subjects_kind(mails) == ["overdue"], "預定日後第 1 個工作日寄 1 封"
    assert P._run(nxt) == 0 and P._run(nxt + timedelta(days=1)) == 0 and len(mails) == 1, "不重寄、不週提"
    n = _notes("pdc_fin")
    assert len(n) == 1 and n[0]["type"] == "payable_due_overdue" and n[0]["link"] == "cashier.html?tab=payreq"
    assert "7777" not in n[0]["message"] and "7,777" not in n[0]["message"] and "NT$" not in n[0]["message"]
    assert _notes("pdc_muted") == [], "退訂該信件類型的不寫站內通知"
    assert _notes("pdc_eng") == [], "非財務角色不收"
    html = mails[0][2]
    assert "7777" not in html and "7,777" not in html


def test_paid_before_overdue_day_sends_nothing(client, make_user, mails):
    P._finance(make_user, "pdc_fin")
    eid = P._seed_exp(planned=P.TODAY.isoformat())
    _x("UPDATE case_extra_expenses SET paid_date='2031-06-10' WHERE id=?", (eid,))
    assert P._run(P.TODAY + timedelta(days=1)) == 0 and mails == []


# ── 叫料來源 ────────────────────────────────────────────────────────────────

def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur
    finally:
        c.close()


def _seed_material(planned, status="已核准", amount=6000, paid=0.0):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "叫料客", "叫料案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
    snap = json.dumps({"itemName": "交換器", "supplierName": "秘密供應商", "bankAccountNumber": "28881234567890"}, ensure_ascii=False)
    import db
    c = db.get_db()
    try:
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM case_material_payments WHERE quote_no=? AND item_id='L1'", (NO,)).fetchone()[0]
        pid = c.execute("INSERT INTO case_material_payments (doc_code, quote_no, item_id, seq, supplier_id, amount_approved, snapshot_json, status,"
                        " approval_json, created_by, created_at, updated_at, planned_pay_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("MP-T45-%d" % seq, NO, "L1", seq, 1, amount, snap, status, "{}", "pdc_eng", "2031-06-01", "2031-06-01", planned)).lastrowid
        if paid:
            c.execute("INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, created_at) VALUES (?,?,?,?)", (pid, "2031-06-02", paid, "2031-06-02"))
        c.commit()
    finally:
        c.close()
    return pid


def test_material_source_reminded_with_independent_guard_and_no_secrets(client, make_user, mails):
    P._finance(make_user, "pdc_fin")
    _seed_material(P.TODAY.isoformat())
    P._seed_exp(planned=P.TODAY.isoformat())
    assert P._run() == 2 and len(mails) == 2, "叫料與額外支出各一封（同 id 也不互擋）"
    blob = " ".join(m[2] for m in mails)
    assert "MP-T45-1" in blob and "秘密供應商" not in blob and "28881234567890" not in blob and "6000" not in blob and "6,000" not in blob
    assert P._run() == 0


def test_material_not_reminded_when_settled_unapproved_or_no_date(client, make_user, mails):
    P._finance(make_user, "pdc_fin")
    _seed_material(P.TODAY.isoformat(), paid=6000.0)                      # 已結清
    _seed_material(P.TODAY.isoformat(), status="草稿")
    _seed_material("")
    assert P._run() == 0 and mails == []
    _seed_material(P.TODAY.isoformat(), paid=2500.0)                      # 分次付款、仍有餘額 ⇒ 要提醒
    assert P._run() == 1


# ── 叫料行事曆事件跟著現況走 ─────────────────────────────────────────────────

def test_material_calendar_follows_state(client, make_user, monkeypatch):
    from modules.case import material_payable_event as ME
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, ME)
    _fake_gcal.set_events(events={"payable_due": True})
    pid = _seed_material("2031-06-20", status="草稿")
    ME.fire(pid)
    assert cal.events == {}, "草稿不建事件"
    _x("UPDATE case_material_payments SET status='已核准' WHERE id=?", (pid,))
    ME.fire(pid)
    assert len(cal.events) == 1
    ev = list(cal.events.values())[0]
    blob = " ".join(str(v) for v in ev.values())
    assert "2031-06-20" in blob and "交換器" in blob and "MP-T45-1" in blob
    for leak in ("秘密供應商", "28881234567890", "6000", "6,000", "NT$"):
        assert leak not in blob, leak
    _x("INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, created_at) VALUES (?,?,?,?)", (pid, "2031-06-02", 2500.0, "2031-06-02"))
    ME.fire(pid)
    assert len(cal.events) == 1, "分次付款仍有餘額 ⇒ 事件保留"
    _x("INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, created_at) VALUES (?,?,?,?)", (pid, "2031-06-03", 3500.0, "2031-06-03"))
    ME.fire(pid)
    assert cal.events == {}, "結清 ⇒ 收回"
    _x("DELETE FROM case_material_payment_lines WHERE payment_id=?", (pid,))
    ME.fire(pid)
    assert len(cal.events) == 1, "差額退回（明細刪除）回待付款 ⇒ 重建"
    _x("UPDATE case_material_payments SET status='作廢' WHERE id=?", (pid,))
    ME.fire(pid)
    assert cal.events == {}
