# -*- coding: utf-8 -*-
"""`MP3` · 地圖標案依截止日上色＋篩選（預設「未截止」）。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP3：
「未截止／7 天內截止／已截止三色；篩選預設『未截止』」。

# 判準（後端 `_deadline_status`，「今天」由伺服器決定）
- `closed`：截止日 < 今天（**截止日當天仍可投**）
- `closing`：今天 ≤ 截止日 ≤ 今天＋7
- `open`：截止日 > 今天＋7
- `unknown`：沒有或讀不懂 ⇒ **不算已截止**（否則預設篩選會把可能還能投的藏起來）

⚙️ 對照組：非標案的點不受標案篩選影響；「全部」看得到已截止。
"""
import datetime
import json

import pytest

from routers import map_points
from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo, _auth  # noqa: F401

TODAY = datetime.date(2026, 9, 24)



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。"""
    page.evaluate("() => new Promise(r => Alpine.nextTick(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

@pytest.mark.parametrize("deadline,want", [
    ("2026-09-23", "closed"),
    ("2026-09-24", "closing"),      # 當天仍可投
    ("2026-10-01", "closing"),      # 今天＋7
    ("2026-10-02", "open"),         # 今天＋8
    (None, "unknown"),
    ("", "unknown"),
    ("115/10/01", "unknown"),       # 民國格式沒被轉換 ⇒ 讀不懂，不可以猜
])
def test_mp3_deadline_status_boundaries(deadline, want):
    assert map_points._deadline_status(deadline, TODAY) == want


def test_mp3_tender_points_carry_their_deadline_status(client, make_user, _geo, monkeypatch):
    monkeypatch.setattr(map_points, "_today", lambda: TODAY)
    import db
    conn = db.get_db()
    try:
        for case_no, deadline in (("MP3-A", "2026-09-20"), ("MP3-B", "2026-09-27"),
                                  ("MP3-C", "2026-11-30"), ("MP3-D", None)):
            conn.execute("INSERT INTO tenders (case_no, name, org, location, deadline, fetched_at)"
                         " VALUES (?,?,?,?,?,?)",
                         (case_no, "標案" + case_no, "台中市西屯區", "台中市西屯區", deadline, "2026-09-24"))
        conn.commit()
    finally:
        conn.close()
    hdr = _auth(client, make_user)
    r = client.get("/api/map/points?sources=tenders", headers=hdr)
    assert r.status_code == 200, r.text
    got = {p["caseNo"]: p.get("deadlineStatus") for p in r.json()["points"]}
    print("MP3 實測：%r" % got)
    assert got == {"MP3-A": "closed", "MP3-B": "closing", "MP3-C": "open", "MP3-D": "unknown"}, got


# ══════════════════════════════════════════════════════════════════════
# 頁面（e2e）
# ══════════════════════════════════════════════════════════════════════

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


def _tender(case_no, status, lat):
    return {"dataset": "tenders", "sourceKey": "tenders", "caseNo": case_no, "name": case_no,
            "org": "機關", "address": "台中市", "lat": lat, "lon": 120.6, "precision": "street",
            "deadline": "2026-10-01", "deadlineStatus": status,
            "distanceFromUserKm": None, "distanceFromOfficeKm": None}


_POINTS = [_tender("T-OPEN", "open", 24.0), _tender("T-SOON", "closing", 23.5),
           _tender("T-DONE", "closed", 23.0), _tender("T-UNK", "unknown", 22.5),
           {"dataset": "customers_delivery", "sourceKey": "customers", "recordId": 1, "name": "客戶甲",
            "address": "高雄", "lat": 22.6, "lon": 120.3, "precision": "street",
            "distanceFromUserKm": None, "distanceFromOfficeKm": None}]


def _names(page):
    return page.evaluate("() => " + _D + ".view.points.map(p => p.name)")


def _table(page):
    """表格實際畫出來的列：名稱 → 截止狀態字樣。"""
    return page.evaluate("""() => Array.from(document.querySelectorAll('tbody tr')).map(tr => {
        const tds = tr.querySelectorAll('td');
        if (tds.length < 6) return null;
        const d = tr.querySelector('.mp-deadline');
        return [tds[2].innerText.trim().split(/\\s/)[0], d ? d.innerText : null,
                d ? getComputedStyle(d).color : null];
    }).filter(Boolean)""")


@pytest.mark.e2e
def test_mp3_tenders_are_coloured_by_deadline_and_closed_ones_hidden_by_default(live_server, make_user, _geo):
    u, p = make_user(username="mp3_page", role="superadmin")
    with sync_playwright() as pw_:
        browser = pw_.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.route("**/api/map/points*", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"points": _POINTS, "locations": [], "sources": []})))
            page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
            _login(page, live_server, u, p)
            page.goto(live_server + "/pages/map.html")
            page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                                   " && d.info.points.length === 5 }", timeout=15000)
            _rendered(page)   # PERF #6：原本固定等 300ms
            default = page.locator("select.mp-tender-filter").input_value()
            rows = _table(page)
            print("MP3 預設（%s）表格：%r" % (default, rows))
            assert default == "notClosed"
            shown = [r[0] for r in rows]
            assert "T-DONE" not in shown, "預設不顯示已截止：%r" % rows
            assert {"T-OPEN", "T-SOON", "T-UNK", "客戶甲"} <= set(shown), "未截止／不明／非標案都要在：%r" % rows
            label = {r[0]: r[1] for r in rows}
            assert label["T-SOON"] == "7 天內截止" and label["T-UNK"] == "截止日不明", rows
            colours = {r[0]: r[2] for r in rows if r[2]}
            assert colours["T-SOON"] != colours["T-OPEN"], "即將截止要跟未截止不同色：%r" % colours

            page.locator("select.mp-tender-filter").select_option("all")
            _rendered(page)   # PERF #6：原本固定等 200ms
            assert "T-DONE" in _names(page), "「全部」要看得到已截止"
            page.locator("select.mp-tender-filter").select_option("closed")
            _rendered(page)   # PERF #6：原本固定等 200ms
            names = _names(page)
            print("MP3 只看已截止：%r" % names)
            assert set(names) == {"T-DONE", "客戶甲"}, "只篩標案，其他資料不受影響：%r" % names

            # 地圖上的圖釘：已截止那一顆是灰色。
            page.evaluate("() => { const d = " + _D + "; if (!d.mapOpen) d.openMap() }")
            page.wait_for_function("() => document.querySelectorAll('.leaflet-marker-icon .mp-pin').length === 2",
                                   timeout=15000)
            bg = page.evaluate("""() => Array.from(document.querySelectorAll('.leaflet-marker-icon .mp-pin'))
                                    .map(e => [e.textContent, getComputedStyle(e).backgroundColor])""")
            print("MP3 地圖圖釘：%r" % bg)
            assert ["標", "rgb(156, 163, 175)"] in bg, bg
        finally:
            browser.close()
