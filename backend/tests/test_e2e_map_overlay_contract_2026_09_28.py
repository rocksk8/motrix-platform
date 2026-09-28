# -*- coding: utf-8 -*-
"""IP-101 `map.overlay`（L1）瀏覽器端：合成覆蓋層在兩種底圖都畫得出來，而且只經契約（LODGING-NEARBY §3.6.1 守門 ①②⑥⑦）。

覆蓋層清單與腳本以攔截回應提供（合成，不綁任何真的 L2 模組）。Google 用既有的假 google.maps（身分檢查：
收到 Proxy 就丟 InvalidValueError），只證明呼叫方式對，不證明真 Google 行為（GOOGLE-BASEMAP §7.2 人工驗收）。
① 兩種底圖：addMarkers（500 點走群聚）／addCircle／fitTo／focus／panel／onMarkerClick 生效；面板在地圖外。
② 反向控制：把地圖頁的 `_layer`／`_cluster` 等內部欄位拿掉後，覆蓋層照常（證明它沒碰內部）。
⑥ handle 存進 Alpine reactive 再交回 ⇒ 照常（LG2-S1）。
⑦ 彈窗：標題裡的 `<img onerror>` 顯示成文字、`javascript:`／`//evil` 不成連結（LG2-S2）；mount 丟例外 ⇒ 面板說「載入失敗」、地圖照常。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_map_google_basemap_2026_09_28 import (  # noqa: E402
    BROWSER_KEY, FAKE_CLUSTER, FAKE_GMAPS, PNG, _keys)

MD = "Alpine.$data(document.querySelector('.mp-wrap'))"
SCRIPT_URL = "/map-overlays/zz_synth/zz-overlay.js"

SYNTH = r"""
window.MotrixMapOverlay.register('zz', {
  mount: function (api) {
    var body = api.panel('合成覆蓋層')
    var out = document.createElement('div'); out.id = 'zz-out'; body.appendChild(out)
    window.__zz = { api: api }
    api.onBasemapReady(function () {
      var list = []
      for (var i = 0; i < 500; i++) list.push({ id: 'p' + i, lat: 24.10 + i * 0.0001, lng: 120.60, title: '點' + i,
        popup: { title: '<img src=x onerror="window.__xss=1">點' + i, lines: ['第' + i + '筆'],
                 links: [{ label: '好連結', href: '/pages/map.html' }, { label: '壞一', href: 'javascript:window.__xss=2' },
                         { label: '壞二', href: '//evil.example/x' }] } })
      var h = api.addMarkers(list, { icon: 'hotel', color: 'accent' })
      var c = api.addCircle({ lat: 24.12, lng: 120.60 }, 3000, { color: 'accent' })
      var box = window.Alpine.reactive({ h: h, c: c })          // ⑥：handle 存進 Alpine 狀態再交回
      api.onMarkerClick(box.h, function (id) { out.setAttribute('data-clicked', id) })
      api.fitTo(box.h)
      api.focus(box.h, 'p3')
      window.__zz.box = box
      out.setAttribute('data-handle-type', typeof h)
      out.setAttribute('data-ready', api.basemap())
    })
  },
  unmount: function () { window.__zzUnmounted = 1 }
})
window.MotrixMapOverlay.register('zzboom', { mount: function () { throw new Error('boom') }, unmount: function () {} })
"""
OVERLAYS = {"overlays": [{"key": "zz", "label": "合成覆蓋層", "scriptUrl": SCRIPT_URL},
                         {"key": "zzboom", "label": "壞覆蓋層", "scriptUrl": SCRIPT_URL}]}


@pytest.fixture(autouse=True)
def _no_tile_probe(monkeypatch):
    """伺服器端的圖磚探測（geo.tiles_blocked）會真的連 OSM ⇒ 換掉（同 GB 題）。"""
    from helpers import geo
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)


def _open(e2e_browser, base, user, overlays=OVERLAYS):
    ctx = e2e_browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    ctx.route(re.compile(r"https://maps\.googleapis\.com/maps/api/js.*"),
              lambda r: r.fulfill(status=200, content_type="application/javascript", body=FAKE_GMAPS))
    ctx.route("**/markerclusterer-2.6.2/markerclusterer.min.js",
              lambda r: r.fulfill(status=200, content_type="application/javascript", body=FAKE_CLUSTER))
    ctx.route("**/api/map/overlays", lambda r: r.fulfill(status=200, content_type="application/json",
                                                         body=json.dumps(overlays, ensure_ascii=False)))
    ctx.route("**" + SCRIPT_URL, lambda r: r.fulfill(status=200, content_type="application/javascript", body=SYNTH))
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/map.html")
    page.wait_for_function(f"() => {{ try {{ const d = {MD}; return d._map && !d.mapLoading }} catch (e) {{ return false }} }}",
                           timeout=30000)
    return page


def _mount(page, basemap):
    page.locator("[data-map-overlay=zz]").click()
    page.wait_for_selector("#zz-out[data-ready=%s]" % basemap, state="attached", timeout=20000)
    # 面板在地圖外（不蓋 Google 標誌與歸屬）
    assert page.evaluate("() => !!document.querySelector('#mp-overlay-panels [data-map-overlay-panel=zz]')"
                         " && !document.querySelector('#mp-canvas [data-map-overlay-panel]')")
    assert page.get_attribute("#zz-out", "data-handle-type") == "string"          # ⑥ handle 是字串
    assert page.evaluate("() => window.__xss") is None


def _strip_internals(page):
    """② 反向控制：拿掉覆蓋層不應該用到的地圖頁內部欄位。"""
    page.evaluate(f"() => {{ const d = {MD}; d._layer = undefined; d._cluster = undefined; d._gmMarkers = undefined;"
                  " d._markerByKey = undefined }")


@pytest.mark.e2e
def test_overlay_contract_on_leaflet(live_server, make_user, e2e_browser):
    _keys("")
    page = _open(e2e_browser, live_server, make_user(username="ov_osm", role="superadmin"))
    _strip_internals(page)
    _mount(page, "osm")
    # ① 500 點走群聚：可見的單點遠少於 500，且有群聚圖示
    page.wait_for_function("() => document.querySelectorAll('#mp-canvas .marker-cluster').length > 0", timeout=10000)
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas .mp-ov-pin').length") < 500
    # ⑦ focus 開的彈窗：標題是文字、壞連結不成連結
    pop = page.locator(".leaflet-popup-content .mp-ov-pop")
    pop.wait_for(state="visible", timeout=10000)
    assert '<img src=x onerror="window.__xss=1">點3' in pop.inner_text()
    hrefs = page.evaluate("() => [...document.querySelectorAll('.leaflet-popup-content a')].map(a => a.getAttribute('href'))")
    assert hrefs == ["/pages/map.html"]
    assert page.evaluate("() => window.__xss") is None
    # 圓
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas path.leaflet-interactive').length") >= 1
    # ⑥ 用存在 reactive 裡的 handle 清掉
    page.evaluate("() => window.__zz.api.clear(window.__zz.box.h)")
    page.wait_for_function("() => document.querySelectorAll('#mp-canvas .marker-cluster, #mp-canvas .mp-ov-pin').length === 0",
                           timeout=10000)
    # 關掉 ⇒ unmount、面板移除、清掉其餘（圓）
    page.locator("[data-map-overlay=zz]").click()
    page.wait_for_function("() => window.__zzUnmounted === 1 && !document.querySelector('[data-map-overlay-panel=zz]')",
                           timeout=10000)


@pytest.mark.e2e
def test_overlay_contract_on_google(live_server, make_user, e2e_browser):
    _keys(BROWSER_KEY)
    page = _open(e2e_browser, live_server, make_user(username="ov_gm", role="superadmin"))
    _strip_internals(page)
    before = page.evaluate("() => window.__gm.markers.length")
    _mount(page, "google")
    # ① 500 點交給群聚（假群聚對每個 marker 做身分檢查：Proxy 會丟例外）
    assert page.evaluate("() => window.__gm.markers.length") - before == 500
    assert page.evaluate("() => window.__gm.cluster") == 500
    assert page.evaluate("() => window.__gm.circles").count(3000) == 1
    # ⑦ focus 開的彈窗內容是 L1 組的 DOM：標題是文字、壞連結不成連結
    txt = page.evaluate("() => window.__gm.iw.html.textContent")
    assert '<img src=x onerror="window.__xss=1">點3' in txt
    hrefs = page.evaluate("() => [...window.__gm.iw.html.querySelectorAll('a')].map(a => a.getAttribute('href'))")
    assert hrefs == ["/pages/map.html"]
    assert page.evaluate("() => window.__gm.maps[0].zoom") == 16
    # ⑥ reactive 裡的 handle 交回（假 Google 對 Proxy 會丟例外）
    page.evaluate("() => window.__zz.api.clear(window.__zz.box.h)")
    assert page.evaluate("() => window.__gm.markers.filter(m => m.map).length") < 500


@pytest.mark.e2e
def test_mount_failure_is_said_and_map_keeps_working(live_server, make_user, e2e_browser):
    _keys("")
    page = _open(e2e_browser, live_server, make_user(username="ov_boom", role="superadmin"))
    page.locator("[data-map-overlay=zzboom]").click()
    err = page.locator("[data-map-overlay-error=zzboom]")
    err.wait_for(state="visible", timeout=10000)
    assert err.inner_text() == "壞覆蓋層載入失敗"
    _mount(page, "osm")                                                          # 其他覆蓋層照常


@pytest.mark.e2e
def test_no_overlays_no_buttons(live_server, make_user, e2e_browser):
    _keys("")
    page = _open(e2e_browser, live_server, make_user(username="ov_none", role="superadmin"), overlays={"overlays": []})
    page.wait_for_function("() => { try { return Array.isArray(Alpine.$data(document.querySelector('.mp-wrap')).overlays) }"
                           " catch (e) { return false } }", timeout=10000)
    assert page.locator("[data-map-overlay]").count() == 0


PINS = "() => document.querySelectorAll('#mp-canvas .mp-ov-pin, #mp-canvas .marker-cluster').length"


@pytest.mark.e2e
def test_quick_unmount_remount_while_map_loads_leaves_nothing_uncleared(live_server, make_user, e2e_browser):
    """E3-S3：地圖載入中「掛上→卸下→再掛上」⇒ 只有最後一次畫；清掉之後地圖上一個覆蓋層標點都不剩。"""
    _keys("")
    page = _open(e2e_browser, live_server, make_user(username="ov_race", role="superadmin"))
    _mount(page, "osm")                                            # 先載好腳本
    page.locator("[data-map-overlay=zz]").click()                  # 卸下
    page.wait_for_function(PINS + " === 0", timeout=10000)
    # 關圖 ⇒ 同一個同步區塊內：掛上、卸下、再掛上、開圖（就緒回呼排隊中）
    page.evaluate(f"() => {{ const d = {MD}; d.closeMap(); const M = window.MotrixMapOverlay;"
                  " window.__zzUnmounted = 0; M._mount('zz', '合成覆蓋層'); M._unmount('zz'); M._mount('zz', '合成覆蓋層');"
                  " d.openMap() }")
    page.wait_for_selector("#zz-out[data-ready=osm]", state="attached", timeout=20000)
    page.wait_for_function(PINS + " > 0", timeout=10000)
    assert page.evaluate("() => document.querySelectorAll('[data-map-overlay-panel=zz]').length") == 1
    page.evaluate("() => window.__zz.api.clear()")                 # 用現在這一次的 api 清
    page.wait_for_function(PINS + " === 0", timeout=10000)         # 修正前：第一次 mount 的標點留在圖上清不掉
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas path.leaflet-interactive').length") == 0
    # 反向控制：被取代的舊 api 畫圖 ⇒ 回 null、不畫
    assert page.evaluate("() => window.MotrixMapOverlay.isActive('zz')")


@pytest.mark.e2e
def test_close_map_unmounts_and_resets_the_button(live_server, make_user, e2e_browser):
    """E3-S3：closeMap ⇒ 覆蓋層卸下、按鈕回到未開（反向控制：關之前是開著的樣子）。"""
    _keys("")
    page = _open(e2e_browser, live_server, make_user(username="ov_close", role="superadmin"))
    _mount(page, "osm")
    btn = page.locator("[data-map-overlay=zz]")
    assert "btn-primary" in btn.get_attribute("class")             # 反向控制
    page.evaluate(f"() => {MD}.closeMap()")
    page.wait_for_function("() => window.__zzUnmounted === 1", timeout=10000)
    page.wait_for_function("() => !document.querySelector('[data-map-overlay=zz]').classList.contains('btn-primary')",
                           timeout=10000)
    assert page.evaluate(f"() => {MD}.overlayOn.zz") in (None, False)
    assert page.locator("[data-map-overlay-panel=zz]").count() == 0
