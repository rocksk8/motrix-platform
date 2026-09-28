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
    # 〔合回第十五班 B（主持裁示：只有 Google 實際回了查無才記 all）：「日後會用 Google 查它」只在 Google 問得到時才有意義——
    #   這一題的 env 沒有金鑰，沒金鑰時查無本來就該算（不重打 Nominatim）。⇒ 斷言前讓 Google 問得到〕
    monkeypatch.setattr(geo, "_google_key_configured", lambda: True)
    assert geo._MISS_CACHE_ALL == {}, "範圍內 Google 沒被問 ⇒ 不可以記成「Google 實際回了查無」"
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


# ── D 稽核 SST-M1：公司資料存檔時的自動定位與 profile 裡的座標 ────────────────

A_OFFICE = "台中市大里區中興路二段1號"
PROFILE = "/api/settings/company-profile"


@pytest.fixture()
def admin_h(client, make_user):
    u, p = make_user(username="sst_m1_admin", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def stages(monkeypatch):
    calls = {"google": [], "nominatim": []}
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "_locate_google",
                        lambda a, errors=None: calls["google"].append(a) or (GOOGLE_XY, geo.PRECISION_ROOFTOP))
    monkeypatch.setattr(geo, "_locate_tgos", lambda a, errors=None: None)
    monkeypatch.setattr(geo, "_locate_nominatim",
                        lambda a, errors=None: calls["nominatim"].append(a) or (FREE_XY, geo.PRECISION_STREET))
    geo.reset_geocode_misses()
    return calls


def _saved_locations():
    from helpers.settings import _get_setting
    return (_get_setting("company_profile", {}) or {}).get("locations") or []


def test_save_on_osm_basemap_never_asks_google_and_records_the_free_source(client, admin_h, stages):
    r = client.put(PROFILE, json={"locations": [{"name": "總公司", "address": A_OFFICE}]}, headers=admin_h)
    assert r.status_code == 200, r.text
    assert stages["google"] == [], "非 Google 底圖存檔時問了 Google（SST-M1）"
    loc = _saved_locations()[0]
    assert (loc["lat"], loc["lon"]) == FREE_XY and loc["coord_source"] == geo.SOURCE_NOMINATIM


def test_google_sourced_coords_are_never_written_into_the_profile(client, admin_h, stages, monkeypatch):
    monkeypatch.setattr(geo, "google_basemap", lambda: True)
    r = client.put(PROFILE, json={"locations": [{"name": "總公司", "address": A_OFFICE}]}, headers=admin_h)
    assert r.status_code == 200, r.text
    assert stages["google"] == [A_OFFICE], "前提：Google 底圖時照舊先問 Google"
    loc = _saved_locations()[0]
    assert loc["lat"] is None and loc["lon"] is None and "coord_source" not in loc, \
        "Google 座標進了 profile（永久保存、進備份，超過 SST §6.3.1 的 30 天）"


def test_manual_coords_stay_manual_across_resaves_and_are_drawn_on_osm(client, admin_h, stages, env):
    body = {"locations": [{"name": "總公司", "address": A_OFFICE, "lat": 24.11, "lon": 120.66}]}
    assert client.put(PROFILE, json=body, headers=admin_h).status_code == 200
    assert _saved_locations()[0]["coord_source"] == "manual"
    # 設定頁原樣送回（同一組值）⇒ 仍是 manual
    assert client.put(PROFILE, json=body, headers=admin_h).status_code == 200
    assert _saved_locations()[0]["coord_source"] == "manual"
    got, _ = env()
    loc = [l for l in got["locations"] if l["address"] == A_OFFICE][0]
    assert loc["source"] == geo.SOURCE_MANUAL and (loc["lat"], loc["lon"]) == (24.11, 120.66), \
        "反向控制：使用者手填的座標照用"


def test_auto_filled_coords_resent_unchanged_keep_their_source(client, admin_h, stages, env):
    assert client.put(PROFILE, json={"locations": [{"name": "總公司", "address": A_OFFICE}]},
                      headers=admin_h).status_code == 200
    loc = _saved_locations()[0]
    # 設定頁把自動填的座標載進輸入框、存檔原樣送回 ⇒ 不可以因此變成 manual
    resend = {"locations": [{"id": loc["id"], "name": "總公司", "address": A_OFFICE,
                             "lat": loc["lat"], "lon": loc["lon"]}]}
    assert client.put(PROFILE, json=resend, headers=admin_h).status_code == 200
    assert _saved_locations()[0]["coord_source"] == geo.SOURCE_NOMINATIM
    got, _ = env()
    drawn = [l for l in got["locations"] if l["address"] == A_OFFICE][0]
    assert drawn["source"] == geo.SOURCE_NOMINATIM, "自動填的座標被當成人工座標"


def test_legacy_coords_without_source_are_treated_as_manual(env):
    """既有資料（沒有 coord_source）⇒ 視為手填（使用者裁示 2026-09-28，CORE-SPEC dee64c54）。

    判斷依據：正式機診斷二 geocode_usage 從來 0 筆，而計數點在「收到 Google 回應之後」⇒ 正式機從未收過
    Google 座標 ⇒ 既有據點座標不是 Google 來源，不必背景重算。第十五班起存檔一律記 coord_source
    （見上面三題），新資料不會再是「來源未知」。
    ⚙️ 對照：coord_source=google 的（只可能是手改設定）在 OSM 上不當座標。"""
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"name": "舊公司", "locations": [
        {"id": "loc_1", "name": "總公司", "address": A_OFFICE, "lat": 24.11, "lon": 120.66},
        {"id": "loc_2", "name": "分公司", "address": A_FREE, "lat": 24.4, "lon": 120.9, "coord_source": "google"}]})
    got, _ = env()
    by = {l["address"]: l for l in got["locations"]}
    assert by[A_OFFICE]["source"] == geo.SOURCE_MANUAL and (by[A_OFFICE]["lat"], by[A_OFFICE]["lon"]) == (24.11, 120.66)
    assert (by[A_FREE]["lat"], by[A_FREE]["lon"]) == FREE_XY and by[A_FREE]["source"] == geo.SOURCE_TGOS,         "coord_source=google 的座標在 OSM 上被畫出；應改用同地址的免費來源"
