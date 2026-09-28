# -*- coding: utf-8 -*-
"""附近旅宿覆蓋層（地圖頁，瀏覽器）：手動開啟、輸入地址查詢、標記與清單、顯名、存成紀錄；
回應底圖與頁面不一致 ⇒ 不畫、請重新整理（D 稽核 LG3-S1）；沒有資料 ⇒ 說出來。驗 DOM／資料庫終點。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import geo  # noqa: E402
from modules.lodging import source as ls  # noqa: E402
from modules.lodging.tests import _fixtures as fx  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

C_LAT, C_LNG = 24.1372, 120.6867
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)

    def fake_locate(address, manual_coord=None):
        return geo.GeoResult(coord=(C_LAT, C_LNG), precision=geo.PRECISION_STREET, source=geo.SOURCE_NOMINATIM,
                             address=address)
    monkeypatch.setattr(geo, "locate_cached", fake_locate)


def _seed():
    import db
    conn = db.get_db()
    try:
        ls.replace_catalog(conn, ls.parse_dataset(fx.dataset(
            [fx.hotel(1, lat=C_LAT + 0.001, lng=C_LNG), fx.hotel(2, lat=C_LAT + 0.002, lng=C_LNG, cls=4)]))["rows"])
    finally:
        conn.close()


def _open(e2e_browser, base, user, search_override=None):
    ctx = e2e_browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    if search_override is not None:
        ctx.route("**/api/lodging/search", lambda r: r.fulfill(status=200, content_type="application/json",
                                                               body=json.dumps(search_override, ensure_ascii=False)))
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/map.html")
    btn = page.locator("[data-map-overlay=lodging]")
    btn.wait_for(state="visible", timeout=20000)
    btn.click()
    page.wait_for_selector("[data-map-overlay-panel=lodging] [data-lodging-status]", state="attached", timeout=20000)
    return page


def _search_by_address(page):
    panel = page.locator("[data-map-overlay-panel=lodging]")
    panel.locator("[data-lodging-address]").fill("測試市測試路1號")
    panel.locator("[data-lodging-search]").click()
    return panel


@pytest.mark.e2e
def test_overlay_search_draws_list_markers_attribution_and_saves(live_server, make_user, e2e_browser):
    _seed()
    user = make_user(username="e2e_lov_a", role="sales", modules=["lodging", "map"])
    page = _open(e2e_browser, live_server, user)
    panel = _search_by_address(page)
    panel.locator("[data-lodging-item]").nth(1).wait_for(state="attached", timeout=20000)
    assert panel.locator("[data-lodging-item]").count() == 2
    assert "官方資料 2 筆" in panel.locator("[data-lodging-status]").inner_text()
    assert "半徑 3 km 內 2 間" in panel.locator("[data-lodging-msg]").inner_text()
    attr = panel.locator("[data-lodging-attribution]").inner_text()
    assert "交通部觀光署 2026 旅館民宿 - 觀光資訊資料庫" in attr and "data.gov.tw/license" in attr
    page.wait_for_function("() => document.querySelectorAll('#mp-canvas .mp-ov-pin, #mp-canvas .marker-cluster').length > 0",
                           timeout=10000)
    # 清單點一筆 ⇒ 地圖開那一筆的彈窗
    panel.locator("[data-lodging-item='Hotel_TEST_000001'] button").click()
    page.wait_for_selector(".leaflet-popup-content .mp-ov-pop", state="visible", timeout=10000)
    assert "測試旅宿1" in page.inner_text(".leaflet-popup-content")
    # 存成紀錄
    panel.locator("[data-lodging-note]").fill("e2e 備註")
    panel.locator("[data-lodging-save]").click()
    page.wait_for_function("() => (document.querySelector('[data-lodging-msg]') || {}).innerText"
                           " && document.querySelector('[data-lodging-msg]').innerText.includes('已存成紀錄')", timeout=15000)
    rows = fx.rows("SELECT * FROM lodging_searches WHERE created_by='e2e_lov_a'")
    assert len(rows) == 1 and rows[0]["note"] == "e2e 備註" and rows[0]["center_source"] == geo.SOURCE_NOMINATIM


@pytest.mark.e2e
def test_basemap_mismatch_draws_nothing_and_asks_reload(live_server, make_user, e2e_browser):
    _seed()
    user = make_user(username="e2e_lov_b", role="sales", modules=["lodging", "map"])
    fake = {"available": True, "basemap": "google", "radiusM": 3000, "count": 1, "attribution": "x",
            "center": {"lat": C_LAT, "lng": C_LNG, "label": "x", "precisionNote": ""},
            "items": [{"sourceId": "S1", "kind": "hotel", "name": "不該畫", "lat": C_LAT, "lng": C_LNG,
                       "classLabel": "一般旅館", "licenseNo": "", "address": "", "distanceM": 1,
                       "priceLow": None, "priceHigh": None, "priceSuspect": False, "priceRegisteredAt": ""}]}
    page = _open(e2e_browser, live_server, user, search_override=fake)
    panel = _search_by_address(page)
    page.wait_for_function("() => (document.querySelector('[data-lodging-msg]') || {}).innerText"
                           " && document.querySelector('[data-lodging-msg]').innerText.includes('重新整理')", timeout=15000)
    assert panel.locator("[data-lodging-item]").count() == 0
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas .mp-ov-pin, #mp-canvas .marker-cluster').length") == 0


@pytest.mark.e2e
def test_no_catalog_is_said_in_overlay(live_server, make_user, e2e_browser):
    user = make_user(username="e2e_lov_c", role="sales", modules=["lodging", "map"])
    page = _open(e2e_browser, live_server, user)
    page.wait_for_function("() => (document.querySelector('[data-lodging-status]') || {}).innerText"
                           " && document.querySelector('[data-lodging-status]').innerText.includes('尚未下載旅宿資料')",
                           timeout=15000)
    panel = _search_by_address(page)
    page.wait_for_function("() => (document.querySelector('[data-lodging-msg]') || {}).innerText"
                           " && document.querySelector('[data-lodging-msg]').innerText.includes('尚未下載旅宿資料')",
                           timeout=15000)
    assert panel.locator("[data-lodging-item]").count() == 0
