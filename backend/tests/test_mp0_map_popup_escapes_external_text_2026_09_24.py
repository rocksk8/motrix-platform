# -*- coding: utf-8 -*-
"""`MP0` · 地圖點位彈窗要跳脫外部文字（XSS）。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP0 ＋ A 讀碼：
`map.html` 點位彈窗把 `p.name`／`p.org`／`p.address` 直接拼進 HTML（據點彈窗早就有 `_esc`）。
標案資料來自外部政府網站 ⇒ **外部輸入**：一個叫 `<img src=x onerror=…>` 的標案名稱會在
每一個開地圖的人的瀏覽器裡執行。

⚙️ 觀測點：彈窗裡**沒有** `<img>` 元素、文字原樣看得到、`onerror` **沒有執行**（`window.__mp0`）。
⚙️ 資料用 `page.route` 換掉 `/api/map/points` 的回應——量的是前端怎麼畫，後端只是照存照吐。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)

#: ⚠️ 用 `[x-data="mapPage()"]`：頁上最前面的 `[x-data]` 是頂欄的，不是地圖頁的。
_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""
EVIL = '<img src=x onerror="window.__mp0=1">'


def _points_body():
    return json.dumps({
        "points": [{"dataset": "tenders", "lat": 24.15, "lon": 120.67,
                    "name": "標案" + EVIL, "org": "機關" + EVIL, "address": "台中市" + EVIL,
                    "precision": "district", "distanceFromUserKm": None,
                    "distanceFromOfficeKm": None}],
        "locations": [], "sources": {},
    })


@pytest.mark.e2e
def test_mp0_a_point_popup_shows_external_text_as_text(live_server, make_user):
    u, p = make_user(username="mp0_xss", role="superadmin")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.route("**/api/map/points*", lambda route: route.fulfill(
                status=200, content_type="application/json", body=_points_body()))
            _login(page, live_server, u, p)
            page.goto(live_server + "/pages/map.html")
            page.wait_for_function(
                "() => { const d = " + _D + ";"
                " return d.info && d.info.points && d.info.points.length === 1 }", timeout=15000)
            page.evaluate("() => " + _D + ".openMap()")
            pin = page.locator(".leaflet-marker-icon .mp-pin").first
            pin.wait_for(state="visible", timeout=15000)
            pin.click()
            pop = page.locator(".leaflet-popup-content").first
            pop.wait_for(state="visible", timeout=5000)
            page.wait_for_timeout(300)
            imgs = pop.locator("img").count()
            text = pop.inner_text()
            fired = page.evaluate("() => window.__mp0 === 1")
            print("MP0 頁面實測：彈窗 img 數 %d／onerror 執行 %s／文字 %r" % (imgs, fired, text[:80]))
            assert imgs == 0 and not fired, "外部文字被當成 HTML：img %d 個、onerror 執行 %s" % (imgs, fired)
            assert EVIL in text, "文字要原樣顯示（跳脫後看得到），不是被吃掉：%r" % text
        finally:
            browser.close()
