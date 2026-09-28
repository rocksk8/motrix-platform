# -*- coding: utf-8 -*-
"""地圖頁 Google 底圖（第十五班 ②(b)）——畫面終點。

測試環境不能連 Google（NETGUARD）⇒ 攔截 `maps.googleapis.com/maps/api/js` 回一支**假的 google.maps**
（Map／AdvancedMarkerElement／InfoWindow／Circle／LatLngBounds，標記內容掛進 #mp-canvas 讓畫面看得到、點得到），
群聚外掛也換成假的。⚠️ 這只證明「我們呼叫轉接層與畫面邏輯正確」，**不證明真 Google 的行為**——
真 Google 由人工驗收清單負責（docs/platform/GOOGLE-BASEMAP.md §7）。

驗：
① 有地圖金鑰 ⇒ 載 Maps JS（網址帶**瀏覽器金鑰**、不帶伺服器金鑰）＋mapId；點與據點畫出來；**沒有任何 OSM 圖磚請求**；OSM 出處不顯示；
   點標記開彈窗（內容已跳脫）；
② `?focus=` 對等：開到那一筆的彈窗；
③ 反向控制：沒有地圖金鑰 ⇒ 照舊 Leaflet＋OSM，完全不碰 maps.googleapis.com；
④ 地圖設定取不到 ⇒ 說出來、不畫（不退回 OSM：後端可能正在給 Google 座標）。
"""
import base64
import json
import re
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

MD = "Alpine.$data(document.querySelector('.mp-wrap'))"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
SERVER_KEY = "AIzaSyServerKeyNeverLeaves0123456789ab"
BROWSER_KEY = "AIzaSyBrowserKeyForMapsJs0123456789cd"
MAP_ID = "motrix-test-map-id"
ADDR = {"台中市北區三民路三段1號": (24.1570, 120.6840), "台中市西區公益路2號": (24.1500, 120.6600)}

FAKE_GMAPS = r"""
(function () {
  var rec = window.__gm = { maps: [], markers: [], circles: [], iw: null };
  function host() { return document.getElementById('mp-canvas') }
  function LatLngBounds() { this.pts = [] }
  LatLngBounds.prototype.extend = function (p) { this.pts.push(p) };
  function Map(el, opts) { this.el = el; this.opts = opts; this.center = opts.center; this.zoom = opts.zoom;
    rec.maps.push(this); el.setAttribute('data-fake-gmap', '1') }
  Map.prototype.fitBounds = function (b) { rec.fit = b.pts.length };
  Map.prototype.setCenter = function (c) { this.center = c };
  Map.prototype.setZoom = function (z) { this.zoom = z };
  Map.prototype.getZoom = function () { return this.zoom };
  function AdvancedMarkerElement(o) { this.position = o.position; this.content = o.content; this.zIndex = o.zIndex;
    this._map = null; rec.markers.push(this); if (o.map) this.map = o.map }
  Object.defineProperty(AdvancedMarkerElement.prototype, 'map', {
    get: function () { return this._map },
    set: function (m) { this._map = m; if (m) { host().appendChild(this.content) } else if (this.content.remove) { this.content.remove() } } });
  AdvancedMarkerElement.prototype.addListener = function (ev, fn) { this.content.addEventListener(ev, fn) };
  function InfoWindow() { rec.iw = this; this.el = null }
  InfoWindow.prototype.setContent = function (h) { this.html = h };
  InfoWindow.prototype.setPosition = function (p) { this.position = p };
  InfoWindow.prototype.open = function () { if (!this.el) { this.el = document.createElement('div'); this.el.id = 'fake-iw'; host().appendChild(this.el) }
    this.el.innerHTML = this.html; this.el.style.display = 'block' };
  InfoWindow.prototype.close = function () { if (this.el) this.el.style.display = 'none' };
  function Circle(o) { this.o = o; rec.circles.push(o.radius) }
  Circle.prototype.setMap = function () {};
  window.google = { maps: { Map: Map, LatLngBounds: LatLngBounds, InfoWindow: InfoWindow, Circle: Circle,
    marker: { AdvancedMarkerElement: AdvancedMarkerElement },
    event: { addListenerOnce: function (o, e, fn) { setTimeout(fn, 0) } } } };
  var cb = new URL(document.currentScript.src).searchParams.get('callback');
  setTimeout(function () { window[cb]() }, 0);
})();
"""

FAKE_CLUSTER = r"""
window.markerClusterer = { MarkerClusterer: function (o) { window.__gm.cluster = o.markers.length;
  o.markers.forEach(function (m) { m.map = o.map }); this.clearMarkers = function () {}; this.setMap = function () {} } };
"""


@pytest.fixture()
def seeded(monkeypatch, client):
    from helpers import geo
    from tests._map_cache_warm import clear_map_response_cache
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_CACHE", {})
    clear_map_response_cache()
    import db
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        for i, (a, (lat, lon)) in enumerate(ADDR.items()):
            conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at)"
                         " VALUES (?,?,?,?,?,?)", (a, lat, lon, geo.SOURCE_GOOGLE, geo.PRECISION_ROOFTOP, now))
            conn.execute("INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
                         ("<b>客戶%d</b>" % i, json.dumps({"deliveryAddress": a}, ensure_ascii=False), now))
        conn.commit()
    finally:
        conn.close()


def _keys(browser_key):
    from helpers.settings import _get_setting, _set_setting
    cur = _get_setting("company_profile", {}) or {}
    _set_setting("company_profile", {**cur, "google_maps_api_key": SERVER_KEY,
                                     "google_maps_browser_key": browser_key, "google_maps_map_id": MAP_ID})


def _open(e2e_browser, base, user, path="/pages/map.html", config_fail=False):
    ctx = e2e_browser.new_context(viewport={"width": 1280, "height": 900})
    seen = {"osm": 0, "gmaps": [], "cluster": 0}

    def osm(route):
        seen["osm"] += 1
        route.fulfill(status=200, content_type="image/png", body=PNG)

    def gmaps(route):
        seen["gmaps"].append(route.request.url)
        route.fulfill(status=200, content_type="application/javascript", body=FAKE_GMAPS)

    def cluster(route):
        seen["cluster"] += 1
        route.fulfill(status=200, content_type="application/javascript", body=FAKE_CLUSTER)
    ctx.route("**/tile.openstreetmap.org/**", osm)
    ctx.route(re.compile(r"https://maps\.googleapis\.com/maps/api/js.*"), gmaps)
    ctx.route("**/markerclusterer-2.6.2/markerclusterer.min.js", cluster)
    if config_fail:
        ctx.route("**/api/map/config", lambda r: r.fulfill(status=500, body="{}"))
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + path)
    return page, seen


def _wait_drawn(page):
    page.wait_for_function(f"() => {{ try {{ const d = {MD}; return d._map && !d.loading && !d.mapLoading }} catch (e) {{ return false }} }}",
                           timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('#mp-canvas .mp-pin').length >= 2", timeout=20000)


@pytest.mark.e2e
def test_google_basemap_draws_with_the_browser_key_and_no_osm(live_server, make_user, seeded, e2e_browser):
    _keys(BROWSER_KEY)
    u = make_user(username="gbm_e1", role="superadmin")
    page, seen = _open(e2e_browser, live_server, u)
    _wait_drawn(page)
    assert len(seen["gmaps"]) == 1
    url = seen["gmaps"][0]
    assert "key=" + BROWSER_KEY in url and SERVER_KEY not in url, url
    assert "libraries=marker" in url
    assert page.evaluate("() => window.__gm.maps[0].opts.mapId") == MAP_ID
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas .mp-pin').length") == 2
    assert page.evaluate("() => window.__gm.cluster") == 2, "資料點要進群聚"
    assert seen["osm"] == 0, "Google 底圖畫面載了 OSM 圖磚（ToS §3.2.3(e)）"
    assert page.evaluate(f"() => {MD}.basemap") == "google"
    # 底圖出處（「底圖 © OpenStreetMap 貢獻者」那一行）不顯示；GB-S1 的「地點資料」那一行另題驗
    assert not page.get_by_text("OpenStreetMap", exact=True).is_visible()
    # 點標記開彈窗；使用者資料要跳脫（名稱是 <b>客戶0</b> 字面）
    page.locator("#mp-canvas .mp-pin").first.click()
    page.wait_for_selector("#fake-iw", state="visible")
    html = page.inner_html("#fake-iw")
    assert "&lt;b&gt;客戶" in html and "<b>客戶" not in html, html


@pytest.mark.e2e
def test_focus_parameter_opens_that_record_on_google(live_server, make_user, seeded, e2e_browser):
    _keys(BROWSER_KEY)
    import db
    conn = db.get_db()
    try:
        rid = conn.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    u = make_user(username="gbm_e2", role="superadmin")
    page, _seen = _open(e2e_browser, live_server, u, path="/pages/map.html?focus=customers:%d" % rid)
    _wait_drawn(page)
    page.wait_for_selector("#fake-iw", state="visible", timeout=20000)
    assert "客戶0" in page.inner_text("#fake-iw")
    assert page.evaluate("() => window.__gm.maps[0].zoom") == 17


@pytest.mark.e2e
def test_reverse_control_no_browser_key_stays_on_leaflet_and_never_loads_google(live_server, make_user, seeded, e2e_browser, monkeypatch):
    _keys("")
    from helpers import geo
    # 沒有地圖金鑰 ⇒ OSM；Google 座標依 §6.2 不畫 ⇒ 給一份免費來源座標讓點畫得出來
    import db
    conn = db.get_db()
    try:
        for a, (lat, lon) in ADDR.items():
            conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at)"
                         " VALUES (?,?,?,?,?,?)", (a, lat, lon, geo.SOURCE_NOMINATIM, geo.PRECISION_STREET,
                                                  datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    u = make_user(username="gbm_e3", role="superadmin")
    page, seen = _open(e2e_browser, live_server, u)
    page.wait_for_function(f"() => {{ try {{ return {MD}._map && !{MD}.loading }} catch (e) {{ return false }} }}", timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('.leaflet-marker-icon .mp-pin').length >= 2", timeout=20000)
    assert seen["gmaps"] == [] and page.evaluate("() => typeof window.google") == "undefined"
    assert seen["osm"] > 0
    assert page.evaluate(f"() => {MD}.basemap") == "osm"


@pytest.mark.e2e
def test_config_failure_is_said_and_nothing_is_drawn(live_server, make_user, seeded, e2e_browser):
    _keys(BROWSER_KEY)
    u = make_user(username="gbm_e4", role="superadmin")
    page, seen = _open(e2e_browser, live_server, u, config_fail=True)
    page.wait_for_function(f"() => {{ try {{ const d = {MD}; return !d.mapLoading && d.loadError }} catch (e) {{ return false }} }}",
                           timeout=20000)
    assert "地圖設定載入失敗" in page.evaluate(f"() => {MD}.loadError")
    assert page.evaluate(f"() => !{MD}._map")
    assert seen["osm"] == 0 and seen["gmaps"] == [], "設定取不到時不可以退回任何底圖"


@pytest.mark.e2e
def test_settings_page_saves_browser_key_and_map_id_without_touching_the_server_key(live_server, make_user, e2e_browser):
    """設定頁：填地圖金鑰與地圖 ID ⇒ 存進去、畫面只顯示末四碼；伺服器金鑰不變（遮蔽字不回寫）。"""
    from helpers.settings import _get_setting, _set_setting
    _set_setting("company_profile", {"name": "測試公司", "google_maps_api_key": SERVER_KEY})
    u = make_user(username="gbm_e5", role="superadmin")
    ctx = e2e_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/company-profile-settings.html")
    page.wait_for_selector("#google_maps_browser_key")
    page.fill("#google_maps_browser_key", BROWSER_KEY)
    page.fill("#google_maps_map_id", MAP_ID)
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/settings/company-profile")) as resp:
        page.get_by_role("button", name="儲存設定（公司基本資料與收款帳戶）", exact=True).first.click()
    assert resp.value.status == 200
    prof = _get_setting("company_profile", {})
    assert prof["google_maps_browser_key"] == BROWSER_KEY and prof["google_maps_map_id"] == MAP_ID
    assert prof["google_maps_api_key"] == SERVER_KEY, "伺服器金鑰被改動了"
    page.wait_for_function("k => document.body.innerText.includes('目前：' + '\u2022'.repeat(8) + k)", arg=BROWSER_KEY[-4:])
    assert BROWSER_KEY not in page.content()


@pytest.mark.e2e
def test_gbm2_settings_changed_while_page_open_is_said_and_not_drawn(live_server, make_user, seeded, e2e_browser):
    _keys(BROWSER_KEY)
    u = make_user(username="gbm_e6", role="superadmin")
    page, _seen = _open(e2e_browser, live_server, u)
    _wait_drawn(page)
    _keys("")                                             # 管理員把地圖金鑰清掉（頁面還開著）
    from tests._map_cache_warm import clear_map_response_cache
    clear_map_response_cache()
    page.evaluate(f"() => {MD}.refresh()")
    page.wait_for_function(f"() => {MD}.loadError.includes('地圖設定已變更')", timeout=20000)


@pytest.mark.e2e
def test_gbs1_nominatim_points_show_osm_data_attribution_on_google(live_server, make_user, seeded, e2e_browser):
    """GB-S1：Google 底圖上有 Nominatim 來源的點 ⇒ 顯示「地點資料 © OpenStreetMap contributors」；
    反向控制：全是 Google 座標時不顯示。"""
    _keys(BROWSER_KEY)
    u = make_user(username="gbm_e7", role="superadmin")
    page, _seen = _open(e2e_browser, live_server, u)
    _wait_drawn(page)
    assert not page.locator(".mp-osm-data").is_visible()
    import db
    from helpers import geo
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache WHERE address=?", (list(ADDR)[0],))
        conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at) VALUES (?,?,?,?,?,?)",
                     (list(ADDR)[0], 24.157, 120.684, geo.SOURCE_NOMINATIM, geo.PRECISION_STREET, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    from tests._map_cache_warm import clear_map_response_cache
    geo._CACHE.clear()
    clear_map_response_cache()
    page.evaluate(f"() => {MD}.refresh()")
    page.wait_for_selector(".mp-osm-data", state="visible", timeout=20000)
    assert "OpenStreetMap contributors" in page.inner_text(".mp-osm-data")


@pytest.mark.e2e
def test_gbm2_open_osm_page_keeps_free_coords_after_settings_switch_to_google(live_server, make_user, seeded, e2e_browser):
    """OSM 頁開著、管理員填好金鑰＋地圖 ID ⇒ 下一次取點（頁面帶 basemap=osm）仍不可以拿到 Google 座標。"""
    _keys("")
    u = make_user(username="gbm_e8", role="superadmin")
    page, seen = _open(e2e_browser, live_server, u)
    page.wait_for_function(f"() => {{ try {{ return {MD}._map && !{MD}.loading }} catch (e) {{ return false }} }}", timeout=20000)
    assert page.evaluate(f"() => {MD}.basemap") == "osm"
    _keys(BROWSER_KEY)
    from tests._map_cache_warm import clear_map_response_cache
    clear_map_response_cache()
    with page.expect_response(lambda r: "/api/map/points" in r.url) as resp:
        page.evaluate(f"() => {MD}.refresh()")
    assert "basemap=osm" in resp.value.url
    body = resp.value.json()
    assert body["basemap"] == "osm" and not [p for p in body["points"] if p["source"] == "google"], body["points"]
    assert seen["gmaps"] == []
