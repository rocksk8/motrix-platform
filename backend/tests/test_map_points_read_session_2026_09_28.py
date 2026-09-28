# -*- coding: utf-8 -*-
"""/api/map/points 的定位快取讀取：整次取點共用一條連線（正式機 2026-09-28「進標案雷達都會延遲」）。

正式機規模約 400 個地址：原本每個地址各開一次連線讀 geocode_cache（開連線本身每筆數毫秒）⇒ 一次取點 2～7 秒。
開發機量測（400 地址、快取冷）：修正前兩種底圖都是 get_db 404 次、約 2.5 秒；修正後 5 次、約 0.1 秒。
⚠ osm 與 google 兩種模式的成本**相同**（差距不在模式）；正式機 google 模式那兩次慢請求是切換設定後快取鍵改變的冷請求。

判準用「連線次數」而不是秒數（秒數受機器負載影響、不可重現）；兩種模式各量一次，並附反向控制。
"""
import contextlib
import json
from datetime import datetime

import pytest

from helpers import geo

N = 400
MAX_CONN = 20          # 與地址數無關的常數（使用者、設定、資料表各讀幾次）；修正前是 N＋4


@pytest.fixture()
def big(client, make_user, monkeypatch):
    import db
    from tests._map_cache_warm import clear_map_response_cache
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_CACHE", {})
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        for i in range(N):
            a = "台中市西屯區量測路%d號" % i
            conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at) VALUES (?,?,?,?,?,?)",
                         (a, 24.1 + i * 1e-4, 120.6, geo.SOURCE_NOMINATIM, geo.PRECISION_STREET, now))
            conn.execute("INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
                         ("量%d" % i, json.dumps({"deliveryAddress": a}, ensure_ascii=False), now))
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(username="mprs_admin", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    calls = {"n": 0}
    real = db.get_db

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(db, "get_db", counting)

    def run(mode):
        from helpers.settings import _get_setting, _set_setting
        cur = _get_setting("company_profile", {}) or {}
        keys = ({"google_maps_api_key": "k", "google_maps_browser_key": "b", "google_maps_map_id": "m"} if mode == "google"
                else {"google_maps_browser_key": "", "google_maps_map_id": ""})
        _set_setting("company_profile", {**cur, **keys})
        geo._CACHE.clear()                       # 快取冷（正式機慢的那兩次）
        clear_map_response_cache()
        calls["n"] = 0
        r = client.get("/api/map/points?sources=customers&basemap=" + mode, headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()["points"]) == N
        return calls["n"]
    return run


@pytest.mark.parametrize("mode", ["osm", "google"])
def test_cold_map_points_opens_a_bounded_number_of_connections(big, mode):
    n = big(mode)
    assert n <= MAX_CONN, "%s 模式 %d 個地址開了 %d 次連線（每個地址一次 ⇒ 正式機一次取點數秒）" % (mode, N, n)


def test_reverse_control_without_the_shared_session_it_is_one_connection_per_address(big, monkeypatch):
    monkeypatch.setattr(geo, "cache_read_session", contextlib.nullcontext)
    assert big("osm") >= N, "反向控制：拿掉共用連線時應該回到每個地址一次（量測本身有效）"
