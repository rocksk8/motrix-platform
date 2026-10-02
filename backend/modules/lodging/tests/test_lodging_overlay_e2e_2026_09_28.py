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
    # 診斷（第十八班偶發紅）：記下每一次 /api/lodging/search 的狀態與筆數、以及 console 錯誤；失敗時一併印出
    page._lodging_log = []

    def _on_response(r):
        if "/api/lodging/search" in r.url:
            try:
                d = r.json()
                page._lodging_log.append("search %s available=%s count=%s reason=%s" % (
                    r.status, d.get("available"), d.get("count"), d.get("reason")))
            except Exception as e:  # noqa: BLE001
                page._lodging_log.append("search %s (body unreadable: %s)" % (r.status, e))
    page.on("response", _on_response)
    page.on("console", lambda m: m.type == "error" and page._lodging_log.append("console: " + m.text))
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/map.html")
    btn = page.locator("[data-map-overlay=lodging]")
    btn.wait_for(state="visible", timeout=20000)
    btn.click()
    page.wait_for_selector("[data-map-overlay-panel=lodging] [data-lodging-status]", state="attached", timeout=20000)
    return page


def _wait_items(page, panel, n, tmp_path):
    """等清單第 n 筆；逾時 ⇒ 存截圖＋印出搜尋回應紀錄與面板訊息再失敗（不靠重跑猜原因）。"""
    try:
        panel.locator("[data-lodging-item]").nth(n - 1).wait_for(state="attached", timeout=20000)
    except Exception:
        shot = tmp_path / "lodging_overlay_timeout.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:  # noqa: BLE001
            pass
        msg = panel.locator("[data-lodging-msg]").inner_text() if panel.locator("[data-lodging-msg]").count() else ""
        raise AssertionError("清單第 %d 筆沒出現；面板訊息=%r；紀錄=%r；截圖=%s" % (n, msg, page._lodging_log, shot))


_MP = "Alpine.$data(document.querySelector('.mp-wrap'))"


def _close_map_for_good(page, rounds=8, quiet_ms=1500):
    """把地圖收起來並確認**不會再被建回來**（第三十二班偶發紅：closeMap 之後 `_map` 又出現 ⇒ 等它清空逾時）。
    成因：自動開圖排在 `refresh()` 之後，負載下可能晚於覆蓋層按鈕觸發的開圖 ⇒ 測試 closeMap 後被自動開圖建回來。
    作法：收 ⇒ 靜默一段時間（用 page.wait_for_timeout，不阻塞頁面事件）⇒ 還有地圖或載入中就再收；連續一段靜默都沒被建回才算數。
    不放寬任何產品斷言；收不乾淨（一直被建回）⇒ 失敗並說出次數。"""
    for i in range(rounds):
        page.wait_for_function("() => !%s.mapLoading" % _MP, timeout=30000)
        page.evaluate("() => %s.closeMap()" % _MP)
        page.wait_for_timeout(quiet_ms)
        if page.evaluate("() => !%s._map && !%s.mapOpen && !%s.mapLoading" % (_MP, _MP, _MP)):
            return i
    raise AssertionError("地圖收起來 %d 次都被建回來（自動開圖沒停）" % rounds)


def _search_by_address(page):
    panel = page.locator("[data-map-overlay-panel=lodging]")
    panel.locator("[data-lodging-address]").fill("測試市測試路1號")
    panel.locator("[data-lodging-search]").click()
    return panel


@pytest.mark.e2e
def test_overlay_search_draws_list_markers_attribution_and_saves(live_server, make_user, e2e_browser, tmp_path):
    _seed()
    user = make_user(username="e2e_lov_a", role="sales", modules=["lodging", "map"])
    page = _open(e2e_browser, live_server, user)
    panel = _search_by_address(page)
    _wait_items(page, panel, 2, tmp_path)
    assert panel.locator("[data-lodging-item]").count() == 2
    # 資料狀態是另一支請求（/api/lodging/status），與搜尋結果誰先到不一定 ⇒ 等它的終點，不假設順序
    page.wait_for_function("() => (document.querySelector('[data-lodging-status]') || {}).innerText"
                           " && document.querySelector('[data-lodging-status]').innerText.includes('官方資料 2 筆')", timeout=15000)
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


@pytest.mark.e2e
def test_results_arriving_before_the_map_is_ready_still_list_and_draw_later(live_server, make_user, e2e_browser, tmp_path):
    """列車第十八班偶發紅的成因（產品競態）：搜尋回應先到、地圖還沒建好 ⇒ 原本畫標記丟例外、被當成「連線不到」、清單不出現。
    決定性重現：先把地圖收起來再搜尋 ⇒ 清單與訊息照常出現；地圖開好之後標記補畫上去。"""
    _seed()
    user = make_user(username="e2e_lov_d", role="sales", modules=["lodging", "map"])
    page = _open(e2e_browser, live_server, user)
    # 先等開頁自動開圖完成，再收起來（否則自動開圖晚一步完成會把地圖建回來）
    page.wait_for_function("() => { const d = Alpine.$data(document.querySelector('.mp-wrap')); return d._map && !d.mapLoading }",
                           timeout=30000)
    _close_map_for_good(page)
    # 收圖會卸下覆蓋層 ⇒ 重新掛上（地圖此時沒有開）
    page.evaluate("() => window.MotrixMapOverlay._mount('lodging', '附近旅宿')")
    panel = _search_by_address(page)
    _wait_items(page, panel, 2, tmp_path)
    assert "半徑 3 km 內 2 間" in panel.locator("[data-lodging-msg]").inner_text()
    assert "交通部觀光署" in panel.locator("[data-lodging-attribution]").inner_text()
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas .mp-ov-pin, #mp-canvas .marker-cluster').length") == 0
    page.evaluate("() => Alpine.$data(document.querySelector('.mp-wrap')).openMap()")
    page.wait_for_function("() => document.querySelectorAll('#mp-canvas .mp-ov-pin, #mp-canvas .marker-cluster').length > 0",
                           timeout=20000)


@pytest.mark.e2e
def test_close_map_for_good_recloses_a_late_rebuild_and_gives_up_on_endless_rebuilds(live_server, make_user, e2e_browser):
    """反向控制（上面那題的收圖輔助）：①收圖後 400ms 地圖被晚到的開圖建回來 ⇒ 輔助再收一次、最後確實是收著的；
    ②地圖每 300ms 就被建回來 ⇒ 輔助必須失敗（不是靜默放行）。"""
    user = make_user(username="e2e_lov_e", role="sales", modules=["lodging", "map"])
    page = _open(e2e_browser, live_server, user)
    page.wait_for_function("() => { const d = %s; return d._map && !d.mapLoading }" % _MP, timeout=30000)
    page.evaluate("() => { const d = %s; window.__late = 0; setTimeout(() => { window.__late++; d.openMap() }, 400) }" % _MP)
    rounds = _close_map_for_good(page)
    assert rounds >= 1, "晚到的開圖要讓輔助多收一輪（沒有 ⇒ 這個反向控制沒打到）"
    assert page.evaluate("() => window.__late") == 1
    assert page.evaluate("() => { const d = %s; return !d._map && !d.mapOpen }" % _MP)
    page.evaluate("() => { const d = %s; window.__t = setInterval(() => d.openMap(), 300) }" % _MP)
    with pytest.raises(AssertionError, match="都被建回來"):
        _close_map_for_good(page, rounds=3, quiet_ms=1000)
    page.evaluate("() => clearInterval(window.__t)")
