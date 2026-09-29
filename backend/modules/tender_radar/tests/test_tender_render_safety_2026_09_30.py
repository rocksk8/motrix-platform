# -*- coding: utf-8 -*-
"""T22-4 稽核（W3 交叉稽核 M1／M2）：整格 x-html 的跳脫守門要「每個來自外部的欄位都放惡意值」，以及重畫後焦點還原。

1. 惡意值放在**每一個**會進 x-html 的欄位：http 連結列的 name／org（走 _link 的文字）、watch 名稱、標註人 display_name、
   caseNo 含引號（data-case-no／data-mark 屬性、在地圖上看的連結）；斷言：沒有腳本執行（window.__pwned）、
   沒有注入的 img／onerror／onmouseover 元素或屬性，而惡意字串以「文字」原樣顯示。
   反向控制（稽核時實測、寫在 CHANGELOG）：拿掉 matchedWatches 的 `_esc(w.name)`，或 `_link` 的 `_esc(text)` ⇒ 本檔紅。
2. 標註鈕（鍵盤）：聚焦鈕、按 Enter 標註後，整個 tbody 重畫，焦點要回到同一筆的標註鈕（不是 BODY）；
   使用者已經移到別處時不搶焦點。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402
from tests._mapiso import no_tile_probe  # noqa: E402,F401

PW = "T-Pass-1234"
EVIL_IMG = '<img src=x onerror="window.__pwned=1">'
QUOTED_NO = 'Q"onmouseover="window.__pwned=2'


def _seed(display_name):
    import db
    conn = db.get_db()
    try:
        # http 連結列：name／org 都帶惡意值（走 _link 的文字，不是純文字 span）
        conn.execute("INSERT INTO tenders (case_no, name, org, location, url, fetched_at) VALUES (?,?,?,?,?,?)",
                     ("L-1", "名稱" + EVIL_IMG, "機關" + EVIL_IMG, "台中市", "https://web.pcc.gov.tw/ok", "2026-09-30"))
        # caseNo 含引號、url 含引號
        conn.execute("INSERT INTO tenders (case_no, name, org, location, url, fetched_at) VALUES (?,?,?,?,?,?)",
                     (QUOTED_NO, "含引號案號", "機關B", "台中市", 'https://web.pcc.gov.tw/a"b', "2026-09-30"))
        conn.execute("INSERT INTO tenders (case_no, name, org, location, url, fetched_at) VALUES (?,?,?,?,?,?)",
                     ("K-1", "含監視器", "機關C", "台中市", None, "2026-09-30"))
        conn.execute("INSERT INTO tender_watches (name, keywords, excludes, org, budget_min, budget_max, enabled, created_at, updated_at) "
                     "VALUES (?, ?, '[]', '', NULL, NULL, 1, '2026-09-30T00:00:00', '2026-09-30T00:00:00')",
                     ("監看" + EVIL_IMG, json.dumps(["含"], ensure_ascii=False)))
        conn.execute("UPDATE users SET display_name=? WHERE username='safeuser'", (display_name,))
        conn.commit()
    finally:
        conn.close()


def _page(live_server, e2e_browser):
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    block_tiles(page)
    inject_login(page, live_server, "safeuser", PW)
    page.goto(live_server + "/pages/tender-radar.html")
    page.wait_for_function("() => document.querySelectorAll('table[data-layout-list=tenders] tbody tr').length >= 3", timeout=20000)
    # 等載入終點：清單第一次畫出來之後，個人版面偏好（user prefs／layout-cols）還會再抵達並重畫整個 tbody 一次（實測第二次重畫在
    # 第一次之後約 300～550 ms）；此時 focus() 的鈕被換掉、焦點掉到 BODY、Enter 沒有作用 ⇒ 偶發紅（40 次裡 2～4 次）。等網路靜止再開始。
    page.wait_for_load_state("networkidle", timeout=20000)
    return page


@pytest.mark.e2e
def test_every_external_field_is_escaped_in_the_tbody(live_server, make_user, no_tile_probe, e2e_browser):
    make_user("safeuser", PW, role="superadmin")
    _seed("標註人" + EVIL_IMG)
    page = _page(live_server, e2e_browser)
    # 先標註一筆，讓「標註人」欄有值（display_name 是惡意值）
    page.locator('tr[data-case-no="K-1"] button[data-mark]').click()
    page.wait_for_function("() => document.querySelector('tr[data-case-no=\"K-1\"] .tr-mark-who')", timeout=10000)
    assert page.evaluate("() => window.__pwned") is None, "有腳本被執行了"
    body = page.locator("table[data-layout-list=tenders] tbody")
    assert body.locator("img").count() == 0, "tbody 裡出現注入的 <img>"
    assert page.evaluate("() => document.querySelectorAll('tbody [onerror], tbody [onmouseover]').length") == 0
    # 惡意字串以文字原樣顯示（沒被吃掉、也沒被解析）
    assert EVIL_IMG in page.locator('tr[data-case-no="L-1"]').inner_text()
    assert EVIL_IMG in body.locator(".chip").first.inner_text()
    assert EVIL_IMG in page.locator('tr[data-case-no="K-1"] .tr-mark-who').inner_text()
    # 含引號的 caseNo：屬性沒被截斷（沒有多出 onmouseover 屬性），而且仍可標註
    quoted = page.locator("tbody tr").filter(has_text="含引號案號")
    assert quoted.count() == 1
    assert quoted.evaluate("e => e.hasAttribute('onmouseover')") is False
    assert quoted.locator("button[data-mark]").evaluate("e => e.hasAttribute('onmouseover')") is False
    assert quoted.locator("a.mp1-onmap").evaluate("e => e.hasAttribute('onmouseover')") is False
    quoted.locator("button[data-mark]").click()
    page.wait_for_function("() => document.querySelectorAll('tbody button[data-mark].on').length === 2", timeout=10000)
    assert page.evaluate("() => window.__pwned") is None


@pytest.mark.e2e
def test_keyboard_toggle_keeps_focus_on_the_same_mark_button(live_server, make_user, no_tile_probe, e2e_browser):
    make_user("safeuser", PW, role="superadmin")
    _seed("一般人")
    page = _page(live_server, e2e_browser)
    page.locator('tr[data-case-no="K-1"] button[data-mark]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('tr[data-case-no=\"K-1\"] button[data-mark].on')", timeout=10000)
    page.wait_for_function("""() => { const a = document.activeElement;
        return !!a && a.tagName === 'BUTTON' && a.dataset && a.dataset.mark === 'K-1' }""", timeout=5000)
    # 再按一次（取消標註）：焦點仍在同一筆的鈕上（該筆移位後仍找得到）
    page.keyboard.press("Enter")
    page.wait_for_function("() => !document.querySelector('tr[data-case-no=\"K-1\"] button[data-mark].on')", timeout=10000)
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.mark === 'K-1'",
                           timeout=5000)


@pytest.mark.e2e
def test_focus_is_not_stolen_when_user_moved_elsewhere(live_server, make_user, no_tile_probe, e2e_browser):
    """使用者按了標註後立刻點到別處（例如搜尋框）⇒ 重畫完不可把焦點搶回標註鈕。"""
    make_user("safeuser", PW, role="superadmin")
    _seed("一般人")
    page = _page(live_server, e2e_browser)
    page.evaluate("""() => { window.__origFetch = window.fetch;
        window.fetch = (u, o) => (String(u).includes('/mark') ? new Promise(r => setTimeout(r, 400)).then(() => window.__origFetch(u, o)) : window.__origFetch(u, o)) }""")
    page.locator('tr[data-case-no="K-1"] button[data-mark]').focus()
    page.keyboard.press("Enter")
    inp = page.locator("input[type=search], input[type=text]").first
    inp.focus()
    page.wait_for_function("() => document.querySelector('tr[data-case-no=\"K-1\"] button[data-mark].on')", timeout=10000)
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.activeElement && document.activeElement.tagName") == "INPUT", "焦點被搶回標註鈕"
