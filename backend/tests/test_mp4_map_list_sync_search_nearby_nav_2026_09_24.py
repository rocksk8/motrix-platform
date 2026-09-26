# -*- coding: utf-8 -*-
"""`MP4` · 清單與地圖連動＋搜尋＋附近 N 筆＋導航。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP4：
「點表格列 ⇒ 地圖平移並開彈窗；關鍵字搜尋；『附近 N 筆』；Google 導航**只給 URL 連結**（不存 Google 資料）」。

⚙️ 觀測點：畫面上的表格列、地圖彈窗內容與地圖中心；導航只驗連結網址（不點、不對外連線）。
⚙️ 對照組：地圖還沒開（上次圖磚失敗 ⇒ 不自動開）時點列 ⇒ 先開圖再定位；
   「附近 N 筆」算不出距離的點不列入；清空搜尋全部回來。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: E402,F401
from tests._e2e_login import inject_login as _login  # noqa: E402,F401

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。"""
    page.evaluate("() => new Promise(r => Alpine.nextTick(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _pt(i, name, lat, lon, km, org=None, address="台中市"):
    return {"dataset": "suppliers", "sourceKey": "suppliers", "recordId": i, "name": name,
            "org": org, "address": address, "lat": lat, "lon": lon, "precision": "street",
            "distanceFromOfficeKm": km, "distanceFromUserKm": None}


_POINTS = [_pt(1, "甲供應商", 24.10, 120.60, 3.0), _pt(2, "乙供應商", 23.00, 120.20, 40.0),
           _pt(3, "丙供應商", 22.60, 120.30, 12.0, address="高雄市前鎮區"),
           _pt(4, "丁供應商", 25.00, 121.50, None, org="乙機關")]


def _page(pw_, live_server, u, p, tile_failed=False):
    browser = pw_   # PERF #5：共用瀏覽器（e2e_browser 外殼）
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.route("**/api/map/points*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"points": _POINTS, "locations": [], "sources": []})))
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
    if tile_failed:
        page.add_init_script("localStorage.setItem('motrix_map_tile_failed', '1')")
    _login(page, live_server, u, p)
    page.goto(live_server + "/pages/map.html")
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                           " && d.info.points.length === 4 }", timeout=15000)
    _rendered(page)   # PERF #6：原本固定等 300ms
    return browser, page


def _rows(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('tr.mp-row'))
        .map(tr => tr.querySelectorAll('td')[2].innerText.trim().split(/\\s/)[0])""")


def _click_row(page, name):
    page.locator("tr.mp-row", has_text=name).locator("td").nth(3).click()


def _popup(page):
    pop = page.locator(".leaflet-popup-content").first
    pop.wait_for(state="visible", timeout=8000)
    return pop


@pytest.mark.e2e
def test_mp4_clicking_a_row_moves_the_map_to_that_point_and_opens_it(live_server, make_user, _geo, e2e_browser):
    u, p = make_user(username="mp4_row", role="superadmin")
    pw_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _page(pw_, live_server, u, p)
    try:
        page.evaluate("() => { const d = " + _D + "; if (!d.mapOpen) d.openMap() }")
        page.wait_for_function("() => " + _D + "._markerOf", timeout=15000)
        _rendered(page)   # PERF #6：原本固定等 300ms
        _click_row(page, "丙供應商")
        text = _popup(page).inner_text()
        c = page.evaluate("() => { const c = " + _D + "._map.getCenter(); return [c.lat, c.lng] }")
        print("MP4 點列實測：彈窗 %r／中心 %r" % (text[:30], c))
        assert "丙供應商" in text, text
        assert abs(c[0] - 22.60) < 0.01 and abs(c[1] - 120.30) < 0.01, c
        # 導航：只給網址。
        nav = _popup(page).locator("a.mp-nav").get_attribute("href")
        assert nav == "https://www.google.com/maps/dir/?api=1&destination=22.6,120.3", nav
        _click_row(page, "甲供應商")
        page.wait_for_function("() => document.querySelector('.leaflet-popup-content')"
                               " && document.querySelector('.leaflet-popup-content').innerText.includes('甲供應商')",
                               timeout=8000)
    finally:
        browser.close()


@pytest.mark.e2e
def test_mp4_clicking_a_row_before_the_map_is_open_opens_it_first(live_server, make_user, _geo, e2e_browser):
    """對照組：上次圖磚失敗 ⇒ 不自動開圖；點列要先開圖再定位，不可以什麼都不發生。"""
    u, p = make_user(username="mp4_closed", role="superadmin")
    pw_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _page(pw_, live_server, u, p, tile_failed=True)
    try:
        assert page.evaluate("() => " + _D + ".mapOpen") is False, "量尺：地圖應該還沒開"
        _click_row(page, "乙供應商")
        assert "乙供應商" in _popup(page).inner_text()
    finally:
        browser.close()


@pytest.mark.e2e
def test_mp4_search_and_nearest_n_filter_the_list(live_server, make_user, _geo, e2e_browser):
    u, p = make_user(username="mp4_filter", role="superadmin")
    pw_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _page(pw_, live_server, u, p)
    try:
        assert len(_rows(page)) == 4
        page.locator("input.mp-search").fill("乙")
        _rendered(page)   # PERF #6：原本固定等 400ms
        got = _rows(page)
        print("MP4 搜尋「乙」：%r" % got)
        assert sorted(got) == ["丁供應商", "乙供應商"], "名稱與機關都要搜得到：%r" % got
        page.locator("input.mp-search").fill("前鎮")
        _rendered(page)   # PERF #6：原本固定等 400ms
        assert _rows(page) == ["丙供應商"], "地址也要搜得到"
        page.locator("input.mp-search").fill("")
        _rendered(page)   # PERF #6：原本固定等 400ms
        assert len(_rows(page)) == 4, "清空搜尋全部回來"

        page.locator("select.mp-near").select_option("10")
        _rendered(page)   # PERF #6：原本固定等 300ms
        got = _rows(page)
        print("MP4 最近 10 筆（依據點）：%r" % got)
        assert got == ["甲供應商", "丙供應商", "乙供應商"], "依距離由近到遠；算不出距離的丁不列入：%r" % got
        page.evaluate("() => { " + _D + ".nearN = '20' }")
        _POINTS_N = page.evaluate("() => " + _D + ".view.points.length")
        assert _POINTS_N == 3
        # 只取 N 筆
        page.evaluate("() => { const d = " + _D + "; d.nearN = '1' }")
        _rendered(page)   # PERF #6：原本固定等 200ms
        assert _rows(page) == ["甲供應商"]
    finally:
        browser.close()
