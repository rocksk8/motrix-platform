"""瀏覽器端對端：`static/ui.js`（MotrixUI）共用提示／對話框（CM12 P4 預備，2026-09-24）。

測試頁：`set_content` 組一頁只載 `css/style.css` 與 `static/ui.js` 的最小頁（不動任何產品頁；
案件頁在 CM12 凍結中）。觀測點：API 回傳值、焦點位置、DOM 結構與計算後樣式。
helper（`tests/_ui_dialogs.py`）也在這裡被用一次——它本身就是交付物。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_material_orders_2026_09_11 import live_server  # noqa: F401
from tests._ui_dialogs import answer_confirm, answer_prompt, expect_toast, forbid_native_dialogs, wait_dialog


def _page(p, base, theme=None):
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_content(
        '<html%s><head><link rel="stylesheet" href="%s/css/style.css"></head>'
        '<body><main><button id="opener">開啟</button><input id="other"></main></body></html>'
        % (' data-theme="%s"' % theme if theme else "", base))
    page.add_script_tag(url=base + "/static/ui.js")
    page.wait_for_function("() => !!window.MotrixUI")
    return browser, page


def _start(page, js):
    """在頁面裡開一個對話框，回傳結果存在 window.__r（不 await：對話框開著時 evaluate 會卡住）。"""
    page.evaluate("() => { window.__r = 'pending'; (%s).then(v => { window.__r = v }) }" % js)


def _result(page):
    page.wait_for_function("() => window.__r !== 'pending'", timeout=5000)
    return page.evaluate("() => window.__r")


@pytest.mark.e2e
def test_confirm_keyboard_and_clicks(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            for how, want in (("Enter", True), ("Escape", False)):
                _start(page, "MotrixUI.confirm('要繼續嗎？')")
                wait_dialog(page, "confirm")
                page.keyboard.press(how)
                assert _result(page) is want, how
            _start(page, "MotrixUI.confirm('要繼續嗎？')")
            wait_dialog(page, "confirm").locator('[data-testid="ui-dialog-cancel"]').click()
            assert _result(page) is False
            _start(page, "MotrixUI.confirm('要繼續嗎？')")
            wait_dialog(page, "confirm")
            page.mouse.click(5, 5)                       # 點背景
            assert _result(page) is False
            assert page.locator('[data-testid="ui-dialog"]').count() == 0
        finally:
            browser.close()


@pytest.mark.e2e
def test_danger_confirm_starts_on_cancel_so_a_stray_enter_does_not_do_it(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            _start(page, "MotrixUI.confirm('確定要刪除？', {danger: true, okText: '刪除'})")
            dlg = wait_dialog(page, "confirm")
            assert dlg.get_attribute("role") == "alertdialog"
            page.wait_for_function("() => document.activeElement && document.activeElement.dataset.testid === 'ui-dialog-cancel'")
            page.keyboard.press("Enter")
            assert _result(page) is False
        finally:
            browser.close()


@pytest.mark.e2e
def test_prompt_values_cancel_and_required(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            _start(page, "MotrixUI.prompt('退回原因', {value: '預設'})")
            inp = wait_dialog(page, "prompt").locator('[data-testid="ui-dialog-input"]')
            assert inp.input_value() == "預設"
            page.wait_for_function("() => document.activeElement && document.activeElement.dataset.testid === 'ui-dialog-input'")
            page.keyboard.type("比例要調")               # 預設值已全選 ⇒ 直接取代
            page.keyboard.press("Enter")
            assert _result(page) == "比例要調"

            _start(page, "MotrixUI.prompt('備註')")
            wait_dialog(page, "prompt")
            page.keyboard.press("Enter")
            assert _result(page) == "", "空字串是合法答案（不是取消）"

            _start(page, "MotrixUI.prompt('備註')")
            wait_dialog(page, "prompt")
            page.keyboard.press("Escape")
            assert _result(page) is None, "取消＝null，與空字串分得開"

            _start(page, "MotrixUI.prompt('駁回原因', {required: '請填寫駁回原因'})")
            dlg = wait_dialog(page, "prompt")
            page.keyboard.press("Enter")
            assert page.evaluate("() => window.__r") == "pending", "必填的空白不可以送出"
            assert "請填寫駁回原因" in dlg.locator(".mui-err").inner_text()
            dlg.locator('[data-testid="ui-dialog-input"]').fill("  ")
            page.keyboard.press("Enter")
            assert page.evaluate("() => window.__r") == "pending", "只有空白也算沒填"
            dlg.locator('[data-testid="ui-dialog-input"]').fill("金額不對")
            page.keyboard.press("Enter")
            assert _result(page) == "金額不對"
        finally:
            browser.close()


@pytest.mark.e2e
def test_focus_is_trapped_and_returns_to_the_opener(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            page.focus("#opener")
            _start(page, "MotrixUI.prompt('名稱')")
            wait_dialog(page, "prompt")
            page.wait_for_function("() => document.activeElement && document.activeElement.dataset.testid === 'ui-dialog-input'")
            seen = []
            for _ in range(6):
                page.keyboard.press("Tab")
                seen.append(page.evaluate("() => document.activeElement.dataset.testid || document.activeElement.id"))
            assert set(seen) <= {"ui-dialog-input", "ui-dialog-cancel", "ui-dialog-ok"}, seen
            assert "other" not in seen and "opener" not in seen
            page.keyboard.press("Shift+Tab")
            assert page.evaluate("() => document.activeElement.closest('[data-testid=ui-dialog]') !== null")
            page.keyboard.press("Escape")
            assert _result(page) is None
            assert page.evaluate("() => document.activeElement.id") == "opener", "關閉後焦點回到開啟前的元素"
        finally:
            browser.close()


@pytest.mark.e2e
def test_dialogs_queue_one_at_a_time_and_helper_answers_them(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            natives = forbid_native_dialogs(page)
            page.evaluate("""() => { window.__a = 'pending'; window.__b = 'pending'
              MotrixUI.confirm('第一個').then(v => { window.__a = v })
              MotrixUI.prompt('第二個').then(v => { window.__b = v }) }""")
            wait_dialog(page)
            assert page.locator('[data-testid="ui-dialog"]').count() == 1, "一次只開一個"
            assert answer_confirm(page, ok=True, expect="第一個") == "第一個"
            answer_prompt(page, "好", expect="第二個")
            page.wait_for_function("() => window.__a === true && window.__b === '好'")
            assert natives == []
        finally:
            browser.close()


@pytest.mark.e2e
def test_toast_and_banner(live_server):
    with sync_playwright() as p:
        browser, page = _page(p, live_server)
        try:
            page.evaluate("() => MotrixUI.toast('已儲存', {kind: 'ok', ms: 400})")
            t = expect_toast(page, "已儲存", kind="ok")
            assert t.get_attribute("role") == "status"
            t.wait_for(state="detached", timeout=3000)
            page.evaluate("() => MotrixUI.toast('失敗了', {kind: 'error', ms: 0})")
            assert expect_toast(page, "失敗了", kind="error").get_attribute("role") == "alert"

            evil = "<img src=x onerror=\"window.__pwned=1\">"
            page.evaluate("(m) => { window.__h = MotrixUI.banner(m, {id: 'conflict', kind: 'error'}) }", evil)
            b = page.locator('[data-testid="ui-banner"]')
            b.wait_for(state="visible")
            assert b.locator(".mui-banner__msg").inner_text() == evil, "訊息一律當文字，不當 HTML"
            assert page.evaluate("() => window.__pwned") is None
            page.evaluate("() => MotrixUI.banner('第二版', {id: 'conflict'})")
            assert b.count() == 1 and "第二版" in b.inner_text(), "同 id 取代，不疊加"
            page.wait_for_timeout(400)
            assert b.count() == 1, "banner 常駐，不會自己消失"
            page.locator('[data-testid="ui-banner-close"]').click()
            assert b.count() == 0
        finally:
            browser.close()


@pytest.mark.e2e
def test_dark_mode_reads_the_dark_tokens_and_is_not_inverted_twice(live_server):
    """深色：讀 P3 的深色 token（--surface 等），而根元素要**退出**全站 invert——
    否則深色值被再反轉一次變回淺色。淺色：淺色 token、本來就沒有 filter。"""
    js = """() => { const b = document.querySelector('.mui-backdrop'), d = b.querySelector('.mui-dialog');
      return {direct: b.parentElement === document.body, filter: getComputedStyle(b).filter,
              bg: getComputedStyle(d).backgroundColor, ink: getComputedStyle(d).color} }"""
    with sync_playwright() as p:
        browser, page = _page(p, live_server, theme="dark")
        try:
            _start(page, "MotrixUI.confirm('深色')")
            wait_dialog(page)
            info = page.evaluate(js)
            assert info["direct"] is True
            assert info["filter"] == "none", "深色 token 已經是深色，不可以再被反轉：%r" % info
            assert info["bg"] == "rgb(28, 28, 30)", "要吃深色 --surface（#1C1C1E）：%r" % info
            assert info["ink"] == "rgb(242, 242, 240)", info
            # 正對照：同一頁的一般 body 直下元素仍被反轉（證明這一頁的深色模式規則確實生效）
            assert "invert" in page.evaluate("() => getComputedStyle(document.querySelector('main')).filter")
            page.keyboard.press("Escape")
        finally:
            browser.close()
        browser, page = _page(p, live_server)
        try:
            _start(page, "MotrixUI.confirm('淺色')")
            wait_dialog(page)
            info = page.evaluate(js)
            assert info["filter"] == "none" and info["bg"] == "rgb(255, 255, 255)", info
        finally:
            browser.close()
