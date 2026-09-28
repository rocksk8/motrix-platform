# -*- coding: utf-8 -*-
"""Google Maps Platform SST §6.2：Geocoding 的結果不可以配非 Google 的底圖（第十五班 ②(a)）。

逐字：「Customer must not use Google Maps Content from the Geocoding API in conjunction with a
non-Google map」（CORE-SPEC「地圖底圖與 Google 條款」「地圖修正包（第十五班）」②）。

底圖是 OSM（`geo.google_basemap()` 為 False，②(b) 之前一律如此）時，`/api/map/points`：
- Google 來源的座標**不外流**（點、據點都不帶；距離也不由它算）；
- 同一地址有免費來源（TGOS／Nominatim／行政區）的快取 ⇒ 改用它畫；
- 只有 Google 座標的 ⇒ 不畫，`googleOnlyHidden` 計數說明（不算進「來不及」「查不到」）；
- 反向控制：底圖是 Google ⇒ Google 座標照畫；免費來源照畫不受影響。
geo 層：`without_google_content()` 範圍內不讀 Google 快取、不查 Google 階、也不記負快取（Google 沒被問）。

資料：客戶（L1 `customers`，data_json 的送貨地址）＋公司據點；快取直接寫 `geocode_cache`，
走真的 `cached_only`（不用替身），開地圖期間不對外連線。
"""
import json
from datetime import datetime

import pytest

from helpers import geo
from tests._map_cache_warm import clear_map_response_cache

A_GOOGLE_ONLY = "台中市西屯區台灣大道三段99號"
A_BOTH = "台中市南屯區公益路二段51號"
A_FREE = "台中市梧棲區中和街1號"
GOOGLE_XY = (24.1600, 120.6400)
FREE_XY = (24.1500, 120.6300)


@pytest.fixture()
def env(client, make_user, monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})
    clear_map_response_cache()
    import db
    now = datetime.now().isoformat()
    rows = [(A_GOOGLE_ONLY, geo.SOURCE_GOOGLE, GOOGLE_XY),
            (A_BOTH, geo.SOURCE_GOOGLE, GOOGLE_XY),
            (A_BOTH, geo.SOURCE_NOMINATIM, FREE_XY),
            (A_FREE, geo.SOURCE_TGOS, FREE_XY)]
    conn = db.get_db()
    try:
        for addr, src, (lat, lon) in rows:
            conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at)"
                         " VALUES (?,?,?,?,?,?)", (addr, lat, lon, src, geo.PRECISION_EXACT, now))
        for name, addr in (("甲客戶", A_GOOGLE_ONLY), ("乙客戶", A_BOTH), ("丙客戶", A_FREE)):
            conn.execute("INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
                         (name, json.dumps({"deliveryAddress": addr}, ensure_ascii=False), now))
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}

    def get():
        clear_map_response_cache()
        r = client.get("/api/map/points?sources=customers", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        return body, {p["address"]: p for p in body["points"]}
    return get


def test_osm_basemap_never_draws_google_coordinates(env):
    body, by_addr = env()
    assert body["basemap"] == "osm"
    assert A_GOOGLE_ONLY not in by_addr, "只有 Google 座標的點畫上了 OSM 底圖（SST §6.2）"
    assert all(p["source"] != geo.SOURCE_GOOGLE for p in body["points"]), body["points"]
    assert body["googleOnlyHidden"] == 1
    # 不是「查不到」也不是「來不及」——兩個既有計數器都不可以吃到它
    assert body["withoutLocation"] == 0 and body["pendingGeocode"] == 0 and body["unresolvableGeocode"] == 0


def test_osm_basemap_uses_the_free_source_for_the_same_address(env):
    body, by_addr = env()
    p = by_addr[A_BOTH]
    assert p["source"] == geo.SOURCE_NOMINATIM and (p["lat"], p["lon"]) == FREE_XY


def test_free_source_points_are_drawn_unchanged(env):
    body, by_addr = env()
    p = by_addr[A_FREE]
    assert p["source"] == geo.SOURCE_TGOS and (p["lat"], p["lon"]) == FREE_XY


def test_reverse_control_google_basemap_draws_google_coordinates(env, monkeypatch):
    monkeypatch.setattr(geo, "google_basemap", lambda: True)
    body, by_addr = env()
    assert body["basemap"] == "google" and body["googleOnlyHidden"] == 0
    assert by_addr[A_GOOGLE_ONLY]["source"] == geo.SOURCE_GOOGLE
    assert by_addr[A_BOTH]["source"] == geo.SOURCE_GOOGLE, "Google 底圖時 Google 階仍然優先（既有排序不變）"
    assert by_addr[A_FREE]["source"] == geo.SOURCE_TGOS


def test_company_location_with_only_google_coords_is_not_drawn_and_says_why(env, client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"address": A_GOOGLE_ONLY, "company_name": "測試公司"})
    body, by_addr = env()
    assert all(loc["source"] != geo.SOURCE_GOOGLE for loc in body["locations"]), body["locations"]
    assert body["office"] is None or body["office"]["source"] != geo.SOURCE_GOOGLE
    un = [u for u in body["locationsUnlocated"] if u["address"] == A_GOOGLE_ONLY]
    assert un and un[0]["googleOnly"] is True
    # 距離不可以由 Google 座標的據點算出來
    assert body["points"], "前提：有點可以驗距離"
    assert all(p["distanceFromOfficeKm"] is None for p in body["points"]), body["points"]


# ── geo 層 ────────────────────────────────────────────────────────────────

def test_scope_skips_google_cache_and_stage_and_leaves_no_negative_cache(env, monkeypatch):
    called = []
    monkeypatch.setattr(geo, "_locate_google", lambda a, errors=None: called.append(a) or (GOOGLE_XY, "exact"))
    monkeypatch.setattr(geo, "_locate_tgos", lambda a, errors=None: None)
    monkeypatch.setattr(geo, "_locate_nominatim", lambda a, errors=None: None)
    monkeypatch.setattr(geo, "_locate_district", lambda a, errors=None: geo.GeoResult(error="查無此地址", address=a))
    with geo.without_google_content():
        assert geo.cached_only(A_GOOGLE_ONLY) is None
        assert geo._stage_allowed(geo.SOURCE_GOOGLE) is False
        r = geo.locate_cached(A_GOOGLE_ONLY)
        assert not r.coord
        r2 = geo.locate_cached("台中市沒有快取的新地址1號")
        assert not r2.coord
    assert called == [], "範圍內問了 Google"
    assert not geo.geocode_missed_recently("台中市沒有快取的新地址1號"), \
        "Google 階沒被問卻記了負快取 ⇒ 背景預熱七天內不會再用 Google 查它"
    # 範圍外恢復：Google 快取照讀
    hit = geo.cached_only(A_GOOGLE_ONLY)
    assert hit is not None and hit.source == geo.SOURCE_GOOGLE


# ── 背景預熱（主持裁示：非 Google 底圖 ⇒ 整輪只用免費來源）──────────────────

@pytest.fixture()
def warm(env, monkeypatch):
    """預熱只看一個假來源（A_GOOGLE_ONLY 與一個全新地址）；三階換成記錄器，節流不睡。"""
    fresh = "台中市北屯區崇德路一段1號"
    calls = {"google": [], "nominatim": []}
    monkeypatch.setattr(geo, "_WARM_SOURCES", [lambda: [A_GOOGLE_ONLY, fresh]])
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "_locate_google",
                        lambda a, errors=None: calls["google"].append(a) or ((24.30, 120.70), geo.PRECISION_EXACT))
    monkeypatch.setattr(geo, "_locate_tgos", lambda a, errors=None: None)
    monkeypatch.setattr(geo, "_locate_nominatim",
                        lambda a, errors=None: calls["nominatim"].append(a) or (FREE_XY, geo.PRECISION_STREET))
    geo.reset_geocode_misses()
    return calls, fresh


def _cached_sources(address):
    import db
    conn = db.get_db()
    try:
        return {r[0] for r in conn.execute("SELECT source FROM geocode_cache WHERE address=?", (address,))}
    finally:
        conn.close()


def test_warm_on_osm_basemap_never_calls_google_and_fills_free_coords(env, warm):
    calls, fresh = warm
    geo.warm_geocode_cache()
    assert calls["google"] == [], "非 Google 底圖的預熱問了 Google（SST §6.2）"
    assert set(calls["nominatim"]) == {A_GOOGLE_ONLY, fresh}, "只有 Google 座標的地址要重新成為待辦、由免費階補上"
    assert geo.SOURCE_NOMINATIM in _cached_sources(A_GOOGLE_ONLY)
    assert _cached_sources(fresh) == {geo.SOURCE_NOMINATIM}
    body, by_addr = env()
    assert by_addr[A_GOOGLE_ONLY]["source"] == geo.SOURCE_NOMINATIM and body["googleOnlyHidden"] == 0, \
        "預熱補了免費座標之後，地圖要畫得出來"


def test_reverse_control_warm_on_google_basemap_asks_google_first(env, warm, monkeypatch):
    calls, fresh = warm
    monkeypatch.setattr(geo, "google_basemap", lambda: True)
    geo.warm_geocode_cache()
    assert calls["google"] == [fresh], "Google 底圖時照舊先問 Google（已有 Google 座標的不是待辦）"
    assert calls["nominatim"] == []
    assert _cached_sources(fresh) == {geo.SOURCE_GOOGLE}
