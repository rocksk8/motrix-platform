# -*- coding: utf-8 -*-
"""`MP5` · 地圖全螢幕與手機版。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP5：
「高度隨視窗（配合 `--fz`）；全螢幕鈕；手機斷點」。

⚙️ 觀測點：畫面上的實際尺寸（getBoundingClientRect，視窗像素）與 Leaflet 量到的尺寸。
⚙️ 對照組：字級「標」與「特」地圖高度都是視窗高的 62%（修法前「特」會被 zoom 放大 1.3 倍）；
   Esc 與按鈕都能退出全螢幕，退出後頁面恢復可捲動。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: E402,F401
from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""
_POINTS = [{"dataset": "suppliers", "sourceKey": "suppliers", "recordId": i, "name": "供應商%d" % i,
            "address": "台中市", "lat": 24.0 + i * 0.1, "lon": 120.6, "precision": "street",
            "distanceFromOfficeKm": i, "distanceFromUserKm": None} for i in range(1, 4)]


def _open(pw_, live_server, u, p, w, h, zoom=None):
    browser = pw_.chromium.launch()
    page = browser.new_page(viewport={"width": w, "height": h})
    page.route("**/api/map/points*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"points": _POINTS, "locations": [], "sources": []})))
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
    if zoom:
        page.add_init_script("localStorage.setItem('motrix_font_zoom', '%s')" % zoom)
    _login(page, live_server, u, p)
    page.goto(live_server + "/pages/map.html")
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                           " && d.info.points.length === 3 }", timeout=15000)
    page.evaluate("() => { const d = " + _D + "; if (!d.mapOpen) d.openMap() }")
    page.wait_for_function("() => " + _D + "._map", timeout=15000)
    page.wait_for_timeout(500)
    return browser, page


_RECT = """() => { const c = document.getElementById('mp-canvas').getBoundingClientRect();
    const pn = document.querySelector('.mp-map-panel').getBoundingClientRect();
    const s = """ + _D + """._map.getSize();
    const last = document.querySelector('.mp-map-panel > .mp-panel-body').lastElementChild.getBoundingClientRect();
    return {canvasH: c.height, canvasW: c.width, canvasBottom: c.bottom, lastBottom: last.bottom, panel: [pn.left, pn.top, pn.right, pn.bottom],
            leaflet: [s.x, s.y], ih: innerHeight, iw: innerWidth,
            scrollW: document.documentElement.scrollWidth,
            overflow: document.body.style.overflow} }"""


@pytest.mark.e2e
@pytest.mark.parametrize("zoom", ["1", "1.3"], ids=["標", "特"])
def test_mp5_the_map_height_follows_the_window_at_every_font_size(live_server, make_user, _geo, zoom):
    u, p = make_user(username="mp5_h%s" % zoom.replace(".", ""), role="superadmin")
    with sync_playwright() as pw_:
        browser, page = _open(pw_, live_server, u, p, 1366, 768, zoom)
        try:
            r = page.evaluate(_RECT)
            print("MP5 字級 %s 地圖高 %.1f（視窗 %d 的 62%% ＝ %.1f）" % (zoom, r["canvasH"], r["ih"], 0.62 * r["ih"]))
            assert abs(r["canvasH"] - 0.62 * r["ih"]) < 3, r
        finally:
            browser.close()


@pytest.mark.e2e
@pytest.mark.parametrize("zoom", ["1", "1.3"], ids=["標", "特"])
def test_mp5_fullscreen_fills_the_window_and_esc_or_the_button_leaves_it(live_server, make_user, _geo, zoom):
    u, p = make_user(username="mp5_f%s" % zoom.replace(".", ""), role="superadmin")
    with sync_playwright() as pw_:
        browser, page = _open(pw_, live_server, u, p, 1366, 768, zoom)
        try:
            before = page.evaluate(_RECT)
            page.locator("button.mp-full-btn").click()
            page.wait_for_timeout(500)
            full = page.evaluate(_RECT)
            print("MP5 字級 %s 全螢幕：%r" % (zoom, full))
            l, t, rr, b = full["panel"]
            assert abs(l) < 1.5 and abs(t) < 1.5 and abs(rr - 1366) < 1.5 and abs(b - 768) < 1.5, full
            # 地圖本身要撐到底（不是只有外框變大）：地圖下方只剩 OSM 出處那一行（條款要求，保留），
            # 那一行的底邊到視窗底只剩面板內距（12px×字級）。
            assert 768 - full["lastBottom"] < 12 * float(zoom) + 4, "地圖沒有撐滿：%r" % full
            assert full["lastBottom"] - full["canvasBottom"] < 40 * float(zoom), "地圖與出處行之間不該有空白：%r" % full
            assert full["canvasH"] > before["canvasH"], (before, full)
            # Leaflet 量到的尺寸要跟著變（否則圖磚只畫原本那一塊）：與容器一致（容器含 1px 框）。
            ratio = full["canvasH"] / full["leaflet"][1]
            assert abs(ratio - float(zoom)) < 0.02, (
                "Leaflet 尺寸 %r 與容器高 %.1f 不一致（字級 %s）" % (full["leaflet"], full["canvasH"], zoom))
            assert full["overflow"] == "hidden", "全螢幕時底下的頁面不可以跟著捲"
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            out = page.evaluate(_RECT)
            assert abs(out["canvasH"] - before["canvasH"]) < 2 and out["overflow"] == "", out
            page.locator("button.mp-full-btn").click()
            page.wait_for_timeout(300)
            assert page.locator("button.mp-full-btn").inner_text() == "結束全螢幕"
            page.locator("button.mp-full-btn").click()
            page.wait_for_timeout(300)
            assert abs(page.evaluate(_RECT)["canvasH"] - before["canvasH"]) < 2
        finally:
            browser.close()


@pytest.mark.e2e
def test_mp5_on_a_phone_the_page_does_not_scroll_sideways(live_server, make_user, _geo):
    u, p = make_user(username="mp5_phone", role="superadmin")
    with sync_playwright() as pw_:
        browser, page = _open(pw_, live_server, u, p, 390, 844)
        try:
            r = page.evaluate(_RECT)
            print("MP5 手機 390×844：%r" % r)
            assert r["scrollW"] <= r["iw"] + 1, "頁面不可以橫向捲動：scrollWidth %d > %d" % (r["scrollW"], r["iw"])
            assert abs(r["canvasH"] - 0.5 * r["ih"]) < 3, r
            assert r["canvasW"] <= r["iw"], r
        finally:
            browser.close()
