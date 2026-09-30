# -*- coding: utf-8 -*-
"""行事曆「業務開發案件更新」（2026-09-30 使用者裁示，預設關）：新增開發紀錄 ⇒ 標題「○○案件更新」、說明＝紀錄內容；
同一案件同一天合併。Google 用假行事曆（tests/_fake_gcal.py）。"""
from tests import _fake_gcal


def _setup(client, make_user, monkeypatch, events):
    from modules.crm import api as crm
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, crm)
    _fake_gcal.set_events(events=events)
    u, p = make_user(username="devupd_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/api/dev-cases", headers=h, json={"case_name": "乙開發案", "customer_name": "乙客戶"})
    assert r.status_code in (200, 201), r.text
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    conn.close()
    return cal, h, r.json()["id"], uid


def _log(client, h, cid, uid, content):
    r = client.post(f"/api/dev-cases/{cid}/logs", headers=h,
                    data={"log_date": "2026-09-30", "log_by": uid, "channel": "電話", "content": content})
    assert r.status_code == 201, r.text


def test_off_by_default(client, make_user, monkeypatch):
    cal, h, cid, uid = _setup(client, make_user, monkeypatch, None)
    _log(client, h, cid, uid, "初次拜訪")
    assert cal.calls == []


def test_on_merges_same_day(client, make_user, monkeypatch):
    cal, h, cid, uid = _setup(client, make_user, monkeypatch, {"dev_case_update": True})
    _log(client, h, cid, uid, "初次拜訪")
    _log(client, h, cid, uid, "報價需求確認")
    assert len(cal.events) == 1, cal.calls
    ev = list(cal.events.values())[0]
    assert ev["summary"].startswith("乙開發案案件更新")
    assert "初次拜訪" in ev["description"] and "報價需求確認" in ev["description"]
