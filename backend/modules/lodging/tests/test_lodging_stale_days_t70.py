# -*- coding: utf-8 -*-
"""T70-3：附近旅宿「資料過舊」提示天數是設定 `lodging_freshness.stale_days`（預設 30、7～365）。
改設定一律走真實帳號＋HTTP（設定中心路由）；資料日期用合成目錄；不 monkeypatch 權限。"""
from datetime import timedelta

import pytest

import db
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR
from modules.lodging import source as ls
from modules.lodging.tests import _fixtures as fx

URL = "/api/settings-center/groups/lodging_freshness"


def _login(client, make_user, name, role, modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(age_days):
    """目錄的資料日期 ＝ 現在往前 age_days 天。"""
    when = (ls._now() - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
    conn = db.get_db()
    try:
        ls.replace_catalog(conn, ls.parse_dataset(fx.dataset([fx.hotel(1)], when))["rows"])
        conn.commit()
    finally:
        conn.close()


def _status(client, h):
    r = client.get("/api/lodging/status", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def su(client, make_user):
    return _login(client, make_user, "lg_su", "superadmin")


def test_default_is_30_and_the_boundary_matches_the_old_constant(client, su):
    f = {x["key"]: x for x in SR.groups()["lodging_freshness"]["fields"]}["stale_days"]
    assert (f["default"], f["min"], f["max"]) == (30, 7, 365)
    assert ls.STALE_DAYS == 30 == ls.stale_days()
    _seed(29)
    s = _status(client, su)
    assert s["stale"] is False and s["staleDays"] == 30
    _seed(31)
    s = _status(client, su)
    assert s["stale"] is True and s["staleDays"] == 30


def test_changing_the_setting_moves_the_threshold_in_status_and_in_the_message(client, su):
    _seed(45)
    assert _status(client, su)["stale"] is True                       # 預設 30 ⇒ 45 天算過舊
    assert client.post(URL, json={"values": {"stale_days": 60}, "reason": "放寬提示"}, headers=su).status_code == 200
    s = _status(client, su)
    assert s["stale"] is False and s["staleDays"] == 60               # 設成 60 ⇒ 45 天不算
    assert client.post(URL, json={"values": {"stale_days": 7}, "reason": "更早提示"}, headers=su).status_code == 200
    _seed(10)
    s = _status(client, su)
    assert s["stale"] is True and s["staleDays"] == 7                 # 設成 7 ⇒ 10 天算過舊
    # 儲存的紀錄頁用同一個值
    from modules.lodging import api_records  # noqa: F401
    conn = db.get_db()
    try:
        assert ls.catalog_state(conn)["stale_days"] == 7
    finally:
        conn.close()


def test_bounds_and_permissions_with_real_users(client, make_user, su):
    keep = ls.stale_days()
    for bad in (0, 6, 366, "abc"):
        r = client.post(URL, json={"values": {"stale_days": bad}, "reason": "x"}, headers=su)
        assert r.status_code == 400, (bad, r.text)
    ad = _login(client, make_user, "lg_admin", "admin", modules=["lodging"])
    assert client.post(URL, json={"values": {"stale_days": 45}, "reason": "x"}, headers=ad).status_code in (401, 403)
    assert ls.stale_days() == keep
    assert client.post(URL, json={"values": {"stale_days": 45}, "reason": "x"}).status_code in (401, 403)


def test_unreadable_or_invalid_setting_falls_back_to_30(monkeypatch):
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ls.stale_days() == 30
    monkeypatch.setattr(SR, "get", lambda *a, **k: 3)
    assert ls.stale_days() == 30
