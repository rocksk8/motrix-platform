"""notif.js 在預覽模式讓位（BUILDER-UX §3.3 第一道「共用腳本看到旗標就不執行」；B，2026-09-28，D 23:52 稽核建議）。

為什麼另開一頁量：真正的預覽頁（custom-records.html?preview=1）先把 `window.fetch` 定成不可寫的拒絕函式（第三道），
notif.js 就算沒讓位，`window.fetch = …` 也只是靜默失敗 ⇒ 在預覽頁上量不出第一道有沒有作用（D 的突變因此存活）。
這裡用同源的空白頁、**不裝第三道**，只設旗標再載入 notif.js：
- 觀測點：`window.fetch` 是否仍是載入前那一個（notif.js 沒讓位時會換成自己的包裝，must_change_password 攔截）。
- 正對照：同一頁、不設旗標 ⇒ fetch 被換掉（證明這個觀測點量得到 notif.js 的動作，不是永遠相等）。
突變：把 notif.js 第一段的 `if (window.MOTRIX_PREVIEW) return` 刪掉或註解掉 ⇒ 旗標題紅（正對照不受影響）。
"""
import pytest

pytest.importorskip("playwright.sync_api")


def _load_notif(browser, base, preview):
    """同源空白頁（先開 login.html 取得同源，再換內容）＋可選的旗標，記下原本的 fetch 後載入 notif.js。"""
    page = browser.new_page()
    page.goto(base + "/pages/login.html")
    page.set_content('<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>')
    page.evaluate("p => { if (p) window.MOTRIX_PREVIEW = true; window.__fetchBefore = window.fetch }", preview)
    page.add_script_tag(url=base + "/static/notif.js")
    page.wait_for_function("() => !!window.MotrixReads")   # notif.js 已執行完（同檔後段的全域）
    return page


def _fetch_replaced(page):
    return page.evaluate("() => window.fetch !== window.__fetchBefore")


@pytest.mark.e2e
def test_notif_stands_down_when_the_preview_flag_is_set(live_server, e2e_browser):
    page = _load_notif(e2e_browser, live_server, preview=True)
    try:
        assert _fetch_replaced(page) is False, "預覽旗標在時 notif.js 不可以包裝 fetch（第一道沒有讓位）"
    finally:
        page.close()


@pytest.mark.e2e
def test_positive_control_notif_wraps_fetch_without_the_flag(live_server, e2e_browser):
    """正對照：沒有旗標 ⇒ notif.js 換掉 fetch。這題綠，上一題的「沒換掉」才有意義。"""
    page = _load_notif(e2e_browser, live_server, preview=False)
    try:
        assert _fetch_replaced(page) is True, "觀測點失效：沒有旗標時 notif.js 也沒換掉 fetch"
    finally:
        page.close()
