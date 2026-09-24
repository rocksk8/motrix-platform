"""瀏覽器端的連外守門（conftest.py::_browser_netguard）的正對照與反向控制（2026-09-25）。

現況證據：守門上線前 mp0／mp1／mp8 開 map.html 沒攔圖磚，守門一裝上就紅
（一題 18 次、一題 51 次 tile.openstreetmap.org）。這一檔驗的是守門本身：
① 外部請求會被攔下並記帳（故意請求外部網址 ⇒ 記到、請求失敗）
② 有記帳 ⇒ 收尾的斷言會紅
③ 本機／data: 不記；題目自己 fulfill 的外部網址（例如圖磚）也不記
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests._map_tiles import block_tiles
from tests.conftest import _assert_no_browser_outbound
from tests.test_e2e_case_mark_all_read_2026_09_24 import live_server  # noqa: F401  (live_server 是 fixture)

FETCH = """(u) => fetch(u).then(r => 'ok:' + r.status, () => 'blocked')"""


@pytest.mark.allow_outbound   # 故意連外：收尾不判，改在題內驗記帳（見 docstring ①）
def test_an_external_request_is_blocked_and_recorded(request):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto("data:text/html,<p>x</p>")
            assert page.evaluate(FETCH, "https://example.com/probe.png") == "blocked", "外部請求應被攔下"
        finally:
            browser.close()
    assert request.node._browser_outbound == ["https://example.com/probe.png"], request.node._browser_outbound


def test_a_recorded_request_makes_the_teardown_assertion_fail():
    with pytest.raises(AssertionError, match="對外發出了 1 次請求"):
        _assert_no_browser_outbound(["https://tile.openstreetmap.org/1/1/1.png"])
    _assert_no_browser_outbound([])          # 沒有記帳 ⇒ 不紅


def test_local_and_test_fulfilled_requests_are_not_recorded(request):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context()
            block_tiles(ctx)                   # 題目自己攔下的外部網址：後註冊先處理，不會走到守門
            page = ctx.new_page()
            page.goto("data:text/html,<p>x</p>")
            assert page.evaluate(FETCH, "https://tile.openstreetmap.org/1/1/1.png") == "ok:200"
        finally:
            browser.close()
    assert request.node._browser_outbound == [], request.node._browser_outbound


@pytest.mark.e2e
def test_the_guard_does_not_serialize_local_requests(live_server):
    """守門不可以改變被測對象的時序：題目自己的 route 在 sleep 時，其他**本機**請求不能被一起卡住。

    第一版守門用 `**/*` ⇒ 每個請求都要等 Python 回話；題目 route handler 一 sleep，
    其他請求全被延後 ⇒ W-4／UR1 那一族「延後某個請求製造競態」的題永遠綠（突變抓不到）。
    """
    import time as _t
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.route("**/api/reads", lambda r: (_t.sleep(1.2), r.continue_()))
            page.goto(f"{live_server}/pages/login.html")
            ms = page.evaluate("""async () => {
              fetch('/api/reads', { method: 'POST', body: '{}' }).catch(() => 0)      // 被題目的 route 延後 1.2s
              await new Promise(r => setTimeout(r, 50))
              const t0 = performance.now()
              await fetch('/api/system/version')                                       // 不相干的本機請求
              return performance.now() - t0 }""")
            assert ms < 700, ("不相干的本機請求被延後了 %.0f ms（守門把請求序列化了）" % ms)
        finally:
            browser.close()
