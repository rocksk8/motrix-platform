# -*- coding: utf-8 -*-
"""行事曆「包商撥款」（2026-09-30 使用者裁示，預設關）：承攬商匯款申請 paid-toggle 標記已匯款 ⇒ 以匯款日期建立事件；
取消匯款不刪、也不另建。Google 用假行事曆（tests/_fake_gcal.py）。"""
from tests import _fake_gcal
from modules.subcontract.tests.test_contractor_voucher_paid_date_2026_08_31 import (
    _auth, _login, _make_approved_voucher)


def _setup(client, make_user, monkeypatch, events, no):
    from modules.subcontract.api import contractor_vouchers as cv
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, cv)
    _fake_gcal.set_events(events=events)
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    return cal, t, _make_approved_voucher(client, t, no)


def _toggle(client, t, vno, action):
    r = client.post(f"/api/contractor-vouchers/{vno}/paid-toggle", headers=_auth(t),
                    json={"action": action, **({"paid_at": "2031-06-07"} if action == "pay" else {})})
    assert r.status_code == 200, r.text


def test_off_by_default(client, make_user, monkeypatch):
    cal, t, vno = _setup(client, make_user, monkeypatch, None, "MQ-CALPAY-001")
    _toggle(client, t, vno, "pay")
    assert cal.calls == []


def test_on_creates_event_on_remit_date_and_unpay_keeps_it(client, make_user, monkeypatch):
    cal, t, vno = _setup(client, make_user, monkeypatch, {"contractor_payout": True}, "MQ-CALPAY-002")
    _toggle(client, t, vno, "pay")
    assert cal.methods() == ["POST"]
    ev = list(cal.events.values())[0]
    assert ev["summary"].startswith("包商匯款 — %s" % vno)
    assert ev["start"] == {"date": "2031-06-07"}
    assert "應付：NT$" in ev["description"] and "匯款日期：2031-06-07" in ev["description"]
    _toggle(client, t, vno, "unpay")
    assert cal.methods() == ["POST"] and len(cal.events) == 1      # 取消匯款：不刪、不另建
