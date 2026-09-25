# -*- coding: utf-8 -*-
"""STATES-PLATFORM（docs/platform/states/STATES-PLATFORM.md §9）：模組沒有載入時，入口、直接打網址、地圖、連結。

- P-DT-01：地圖（L1）直接讀 `tenders`；標案雷達沒有載入 ⇒ 不列標案，`sources` 標 `module_not_loaded` 並說明
- P-FE-02：模組不在安裝包（狀態表裡沒有這個 key）⇒ 側欄入口也要藏（原本只藏「列為未載入」的）
- P-FE-03：直接打網址進入未載入模組的頁面 ⇒ 提示頁（停用／未授權／載入失敗／未安裝），不是半空白頁
- P-FE-06：連結依模組狀態決定產不產生（`MotrixRecordLink.recordUrl`）

每一題都有正對照（模組已載入時照舊），觀測點不綁在畫面文字上的靜態字串。
"""
from pathlib import Path

import pytest

from core import registry

# 這一檔驗的是「標案雷達這個模組不在時，L1 的地圖與它的頁面入口」——對象本身就是 tender_radar。
# 安裝包沒有這個模組（例：core-only）⇒ 明說 skip，不是紅（AUDIT-X-9c A-2）。
if not (Path(__file__).resolve().parents[1] / "modules" / "tender_radar" / "module.json").is_file():
    pytest.skip("安裝包沒有 modules/tender_radar ⇒ 本檔無對象", allow_module_level=True)


@pytest.fixture(autouse=True)
def _no_tile_probe(monkeypatch):
    """頁面（地圖、標案雷達）會讓伺服器探測圖磚（`geo.tiles_blocked`）⇒ 測試不對外連線。"""
    from helpers import geo
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)


def _seed_tender(case_no="SP-T1"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location, deadline, fetched_at)"
                     " VALUES (?,?,?,?,?,?)",
                     (case_no, "標案" + case_no, "台中市西屯區", "台中市西屯區", "2099-01-01", "2026-09-25"))
        conn.commit()
    finally:
        conn.close()


def _unload_tender_radar(monkeypatch, state="disabled"):
    """模擬「重啟後沒有載入」：登錄表移出、狀態表改寫（monkeypatch 自動還原）。"""
    monkeypatch.delitem(registry._LOADED, "tender_radar")
    st = dict(registry._STATES["tender_radar"])
    if state is None:
        monkeypatch.delitem(registry._STATES, "tender_radar")
    else:
        monkeypatch.setitem(registry._STATES, "tender_radar", {**st, "state": state, "reason": "測試"})


# ── P-DT-01：地圖 API ──────────────────────────────────────────────────────────

from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo, _auth  # noqa: E402,F401


def test_map_lists_tenders_only_while_the_module_is_loaded(client, make_user, _geo, monkeypatch):
    _seed_tender()
    h = _auth(client, make_user)
    r = client.get("/api/map/points?sources=tenders", headers=h).json()
    assert [p["caseNo"] for p in r["points"]] == ["SP-T1"], "正對照：模組已載入時列出標案"
    assert r["sources"][0]["skipped"] is None

    _unload_tender_radar(monkeypatch)
    r = client.get("/api/map/points?sources=tenders", headers=h).json()
    assert r["points"] == []
    assert r["sources"] == [{"source": "tenders", "skipped": "module_not_loaded", "count": 0,
                             "note": "標案雷達模組目前未啟用，地圖上不會顯示標案"}]


# ── 前端（e2e）─────────────────────────────────────────────────────────────────

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

_LINK = "a[href$='tender-radar.html']"
_HIDDEN = ("() => { const a = document.querySelector(\"%s\"); return a ? a.style.display === 'none' : null }"
           % _LINK)
_NOTICE = "[data-testid='module-unavailable']"


def _page(e2e_browser, live_server, make_user, name, path, role="superadmin"):
    u = make_user(username=name, role=role)
    page = e2e_browser.new_context().new_page()
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/{path}")
    return page


def _availability_loaded(page):
    page.wait_for_function("() => window.MOTRIX_MODULE_AVAILABILITY", timeout=15000)


@pytest.mark.e2e
def test_sidebar_hides_entry_of_module_not_in_package(live_server, make_user, e2e_browser, monkeypatch):
    """P-FE-02：狀態表沒有這個 key（不在安裝包）⇒ 入口藏起來。正對照：已載入時看得到。"""
    page = _page(e2e_browser, live_server, make_user, "sp_fe02a", "module-settings.html")
    page.wait_for_function(f"() => document.querySelector(\"{_LINK}\")", timeout=15000)
    _availability_loaded(page)
    assert page.evaluate(_HIDDEN) is False, "正對照：模組已載入時入口不可被藏"

    _unload_tender_radar(monkeypatch, state=None)
    page.reload()
    page.wait_for_function(f"() => document.querySelector(\"{_LINK}\")", timeout=15000)
    _availability_loaded(page)
    assert "tender_radar" not in page.evaluate("() => window.MOTRIX_MODULE_AVAILABILITY")
    page.wait_for_function(_HIDDEN, timeout=10000)
    assert page.evaluate(_HIDDEN) is True


@pytest.mark.e2e
@pytest.mark.parametrize("state,kind,title", [
    ("disabled", "disabled", "此模組目前已停用"),
    ("unlicensed", "unlicensed", "此模組未授權"),
    ("failed", "failed", "此模組載入失敗"),
    (None, "missing", "此模組未安裝"),
])
def test_direct_url_to_unloaded_module_shows_notice(live_server, make_user, e2e_browser, monkeypatch,
                                                     state, kind, title):
    """P-FE-03：提示頁取代頁面本體（`<main>` 藏起來），寫明原因與處理方式。"""
    _unload_tender_radar(monkeypatch, state=state)
    page = _page(e2e_browser, live_server, make_user, "sp_fe03_" + kind, "tender-radar.html")
    page.locator(_NOTICE).wait_for(state="visible", timeout=15000)
    assert page.locator(_NOTICE).get_attribute("data-state") == kind
    assert page.locator(_NOTICE + " h2").inner_text().strip() == title
    assert page.evaluate("() => getComputedStyle(document.querySelector('main.main')).display") == "none"


@pytest.mark.e2e
def test_direct_url_to_loaded_module_has_no_notice(live_server, make_user, e2e_browser):
    """正對照：模組已載入 ⇒ 沒有提示頁、頁面本體照常顯示。"""
    page = _page(e2e_browser, live_server, make_user, "sp_fe03_ok", "tender-radar.html")
    _availability_loaded(page)
    assert page.evaluate("() => window.MOTRIX_MODULE_AVAILABILITY.tender_radar.state") == "loaded"
    assert page.locator(_NOTICE).count() == 0
    assert page.evaluate("() => getComputedStyle(document.querySelector('main.main')).display") != "none"


_RECORD_URL = ("() => window.MotrixRecordLink.recordUrl({sourceKey: 'tenders', caseNo: 'SP-T1'},"
               " {role: 'superadmin', modules: []})")
_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


@pytest.mark.e2e
def test_map_page_does_not_list_tenders_or_link_to_unloaded_module(live_server, make_user, e2e_browser, _geo,
                                                                   monkeypatch):
    """P-DT-01＋P-FE-06（頁面）：未載入 ⇒ 地圖不列標案、顯示原因、連結不產生。正對照在前。"""
    _seed_tender()
    page = _page(e2e_browser, live_server, make_user, "sp_map_ok", "map.html")
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points }", timeout=20000)
    _availability_loaded(page)
    assert "SP-T1" in page.evaluate("() => " + _D + ".info.points.map(p => p.caseNo)"), "正對照：載入時列出"
    assert page.evaluate(_RECORD_URL) == "tender-radar.html?case=SP-T1", "正對照：載入時產生連結"

    _unload_tender_radar(monkeypatch)
    page.reload()
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points }", timeout=20000)
    _availability_loaded(page)
    assert "SP-T1" not in page.evaluate("() => " + _D + ".info.points.map(p => p.caseNo || '')")
    skipped = page.evaluate("() => " + _D + ".info.sources.filter(s => s.source === 'tenders')"
                            ".map(s => s.skipped)")
    assert skipped == ["module_not_loaded"]
    assert page.locator(".mp-note.info", has_text="標案雷達模組目前未啟用").first.is_visible()
    assert page.evaluate(_RECORD_URL) is None
