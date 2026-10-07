# -*- coding: utf-8 -*-
"""第 45 班 S5：承攬商匯款的提醒信／站內通知／行事曆「付款待辦」薄接線（`subcontract.payable_due`＋L1 `payable_due_core`）。
事件跟著現況走（核准、改預定日、標記已匯款、取消已匯款、作廢）；來源開關；內容不含金額與廠商名。"""
import json
from datetime import date, timedelta

import pytest

from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = [requires_module("case", "用案件編號建派發／匯款單"), requires_module("arap", "出納端點在 M05")]

Q = "MQ-VPD-001"
TODAY = date(2031, 6, 10)                                                    # 週二
_N = __import__("itertools").count(1)


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


@pytest.fixture
def world(client, make_user):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (Q, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
    sa, sp = make_user(username="vpd_sa", role="superadmin")
    fin, fp = make_user(username="vpd_fin", role="finance")
    _x("UPDATE users SET email=?, active=1 WHERE username=?", ("vpd_fin@example.com", fin))
    return {"sa": _login(client, sa, sp), "fin": _login(client, fin, fp)}


def _voucher(client, h, planned, approve=True):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "秘密廠商%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": Q, "vendor_id": r.json()["id"], "status": "completed", "payable_date": "2031-08-01",
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 98765, "amount": 98765}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": r.json()["id"], "planned_pay_date": planned})
    assert r.status_code == 201, r.text
    no = r.json()["voucher_no"]
    if approve:
        _x("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
    return no


@pytest.fixture
def mails(monkeypatch):
    from helpers import email_notify as en
    sent = []

    class _Sent:
        outcome = en.SEND_SENT

        def wait(self, timeout=None):
            return self.outcome

    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: sent.append((sorted(to), subject, html)) or _Sent())
    return sent


def test_reminders_soon_today_overdue_once_each_and_no_money_or_vendor(client, world, mails):
    from modules.subcontract import payable_due as PD
    no = _voucher(client, world["sa"], TODAY.isoformat())
    base = len(mails)                                                          # 建立匯款單本身也會寄信（既有行為）；只數提醒信
    assert PD.run_reminders(date(2031, 6, 9)) == 0, "3 天前＝週六 ⇒ 前一個工作日（週五 6/6）寄，週一不補"
    assert PD.run_reminders(date(2031, 6, 6)) == 1, "週五寄 3 天前那封"
    assert PD.run_reminders(TODAY) == 1, "當天"
    assert PD.run_reminders(TODAY) == 0, "同一天重跑不重寄"
    assert PD.run_reminders(TODAY + timedelta(days=1)) == 1, "預定日後第 1 個工作日：逾期"
    assert PD.run_reminders(TODAY + timedelta(days=2)) == 0, "逾期只一封"
    assert len(mails) - base == 3
    blob = " ".join(m[2] for m in mails[base:])
    assert no in blob and "承攬商匯款" in blob
    for leak in ("秘密廠商", "98765", "98,765", "10,3", "NT$"):
        assert leak not in blob, leak


def test_no_reminder_when_paid_voided_unapproved_or_no_date(client, world, mails):
    from modules.subcontract import payable_due as PD
    a = _voucher(client, world["sa"], TODAY.isoformat())
    b = _voucher(client, world["sa"], TODAY.isoformat())
    c = _voucher(client, world["sa"], TODAY.isoformat(), approve=False)
    d = _voucher(client, world["sa"], "")
    _x("UPDATE contractor_payment_vouchers SET is_paid=1 WHERE voucher_no=?", (a,))
    _x("UPDATE contractor_payment_vouchers SET voided_at='2031-06-01' WHERE voucher_no=?", (b,))
    base = len(mails)
    assert PD.run_reminders(TODAY) == 0 and len(mails) == base, (a, b, c, d)


def test_guard_is_per_source_and_in_app_notice_written(client, world, mails):
    from modules.subcontract import payable_due as PD
    import db
    _voucher(client, world["sa"], TODAY.isoformat())
    assert PD.run_reminders(TODAY) == 1
    c = db.get_db()
    try:
        keys = [r["key"] for r in c.execute("SELECT key FROM system_settings WHERE key LIKE 'payable_due_notif.%'")]
        notes = [dict(r) for r in c.execute("SELECT * FROM notifications WHERE username='vpd_fin' AND type='payable_due_today'")]
    finally:
        c.close()
    assert keys and all(k.startswith("payable_due_notif.subcontract_voucher.") for k in keys), keys
    assert len(notes) == 1 and "NT$" not in notes[0]["message"]


def test_calendar_event_follows_state(client, world, monkeypatch):
    from modules.subcontract import payable_due as PD
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, PD)
    _fake_gcal.set_events(events={"payable_due": True})
    no = _voucher(client, world["sa"], "2031-07-15", approve=False)
    PD.fire(no)
    assert cal.events == {}, "未核准不建事件"
    _x("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert len(cal.events) == 1
    blob = " ".join(str(v) for v in list(cal.events.values())[0].values())
    assert "2031-07-15" in blob and no in blob
    for leak in ("秘密廠商", "98765", "98,765", "NT$"):
        assert leak not in blob, leak
    _x("UPDATE contractor_payment_vouchers SET planned_pay_date='2031-07-20' WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert len(cal.events) == 1 and "2031-07-20" in " ".join(str(v) for v in list(cal.events.values())[0].values()), "改期＝移動同一筆"
    _x("UPDATE contractor_payment_vouchers SET is_paid=1 WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert cal.events == {}, "已匯款 ⇒ 收回"
    _x("UPDATE contractor_payment_vouchers SET is_paid=0 WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert len(cal.events) == 1, "取消已匯款 ⇒ 重建"
    _x("UPDATE contractor_payment_vouchers SET planned_pay_date='' WHERE voucher_no=?", (no,))
    PD.fire(no)
    assert cal.events == {}, "清除預定日 ⇒ 收回"


def test_cashier_endpoint_and_paid_toggle_keep_calendar_in_sync(client, world, monkeypatch):
    from modules.subcontract import payable_due as PD
    from modules.arap.api import cashier
    cal = _fake_gcal.install(monkeypatch)
    for m in (PD, cashier):
        _fake_gcal.sync_spawn(monkeypatch, m)
    from modules.subcontract.api import contractor_vouchers as cv
    _fake_gcal.sync_spawn(monkeypatch, cv)
    _fake_gcal.set_events(events={"payable_due": True})
    no = _voucher(client, world["sa"], "")
    r = client.patch("/api/cashier/payable-queue/%s/planned-pay-date" % no, headers=world["fin"], json={"plannedPayDate": "2031-07-15"})
    assert r.status_code == 200 and len(cal.events) == 1, r.text
    r = client.patch("/api/cashier/payable-queue/%s/planned-pay-date" % no, headers=world["fin"], json={"plannedPayDate": ""})
    assert r.status_code == 200 and cal.events == {}
    client.patch("/api/cashier/payable-queue/%s/planned-pay-date" % no, headers=world["fin"], json={"plannedPayDate": "2031-07-15"})
    assert len(cal.events) == 1
    r = client.post("/api/contractor-vouchers/%s/paid-toggle" % no, headers=world["sa"], json={"action": "pay", "paid_at": "2031-07-01"})
    assert r.status_code == 200, r.text
    assert not any("付款待辦" in str(e) for e in cal.events.values()), "已匯款 ⇒ 付款待辦收回"
