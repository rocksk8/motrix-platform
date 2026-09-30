# -*- coding: utf-8 -*-
"""行事曆「案件更新」（2026-09-30 使用者裁示，預設關）：案件留言板新增留言（重要留言除外，重要的走「案件重要留言」）
⇒ 標題「○○案件更新」；同一案件同一天合併成一個事件，說明累加。Google 用假行事曆（tests/_fake_gcal.py）。"""
import json

from tests import _fake_gcal

NO = "MQ-CALUPD-001"


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, customer_name, project_name, status, deal_tag, total, data_json,"
                     " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (NO, "甲客戶", "甲案", "已送出", "已成案", 1000, json.dumps({"dealTag": "已成案"}),
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user):
    u, p = make_user(username="calupd_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _post(client, h, content, important=""):
    r = client.post(f"/api/quotations/{NO}/updates", headers=h, data={"content": content, "important": important})
    assert r.status_code == 201, r.text


def _setup(client, make_user, monkeypatch, events):
    from modules.case.api import quotations as q
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, q)
    _fake_gcal.set_events(events=events)
    _seed()
    return cal, _hdr(client, make_user)


def test_off_by_default_no_event(client, make_user, monkeypatch):
    cal, h = _setup(client, make_user, monkeypatch, None)
    _post(client, h, "今天進場")
    assert cal.calls == []


def test_same_case_same_day_merges_into_one_event(client, make_user, monkeypatch):
    cal, h = _setup(client, make_user, monkeypatch, {"case_update": True})
    _post(client, h, "第一則：進場")
    _post(client, h, "第二則：完成配管")
    assert len(cal.events) == 1, cal.calls
    ev = list(cal.events.values())[0]
    assert ev["summary"] == "甲案案件更新"
    assert "第一則：進場" in ev["description"] and "第二則：完成配管" in ev["description"]
    assert ev["description"].index("第一則") < ev["description"].index("第二則")
    assert cal.methods() == ["GET", "POST", "GET", "PATCH"]      # 第二則找回同一天那一筆 ⇒ 更新，不新建


def test_important_comment_is_not_a_case_update(client, make_user, monkeypatch):
    """重要留言走「案件重要留言」（它自己的開關）；兩個都開也不會重複成「案件更新」。"""
    cal, h = _setup(client, make_user, monkeypatch, {"case_update": True, "important_comment": False})
    _post(client, h, "重要：客戶改期", important="true")
    assert cal.calls == []
