# -*- coding: utf-8 -*-
"""密碼欄位輸入提示：大寫鎖定＋非英文輸入法組字（login.html、change-password.html，2026-11-11）。

兩層：
1. 靜態守門（不開瀏覽器）：兩頁的提示程式碼逐字相同；每個密碼欄位都有 data-pw-hint；
   提示程式碼不碰欄位的值、不連網、不用 innerHTML。
2. e2e（真瀏覽器）：大寫鎖定開／關即時反應、組字出現／結束、純英數不誤報、失焦收掉、兩種同時成立、
   眼睛切換（password↔text）不影響、change-password 的每個密碼欄位同樣有效。

⚠️ 精確度上限（也寫在頁面註解裡）：
- 輸入法只能抓「正在組字」，抓不到「輸入法圖示的模式」；開著中文輸入法但打純英數 ⇒ 不組字 ⇒ 不會提示。
- Playwright 的 keyboard.press('CapsLock') 不會讓 getModifierState('CapsLock') 變 true，
  所以這裡用 KeyboardEventInit.modifierCapsLock 合成事件；瀏覽器端判斷的 API 與真實按鍵相同。
- 輸入法用 CDP Input.imeSetComposition 觸發「真的」組字事件；若這個環境不支援才退回合成 CompositionEvent。
"""
import re
import pytest

from core import source_tree

LOGIN = source_tree.page_file("login.html")
CHANGE_PW = source_tree.page_file("change-password.html")

CAPS_MSG = "大寫鎖定已開啟"
IME_MSG = "輸入法可能不是英文"


def _snippet(path):
    src = path.read_text(encoding="utf-8")
    m = re.search(r"/\* pw-hint:begin.*?/\* pw-hint:end \*/", src, re.S)
    assert m, f"{path.name} 找不到 pw-hint 區塊（/* pw-hint:begin … /* pw-hint:end */）"
    return m.group(0)


# ── 1. 靜態守門 ────────────────────────────────────────────────────────────

def test_hint_code_identical_on_both_pages():
    assert _snippet(LOGIN) == _snippet(CHANGE_PW), "兩頁的 pw-hint 區塊要逐字相同（改一邊要同步另一邊）"


def test_hint_code_never_touches_the_password_value_or_network():
    code = _snippet(LOGIN)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)         # 註解可以提到這些字（區塊註解、行註解都剔除）
    code = re.sub(r"//[^\n]*", "", code)
    for bad in (".value", "fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage",
                "innerHTML", "outerHTML", "insertAdjacentHTML", "console."):
        assert bad not in code, f"提示程式碼不該出現 {bad!r}（它不需要、也不該碰密碼內容）"


def test_login_password_input_is_marked():
    src = LOGIN.read_text(encoding="utf-8")
    m = re.search(r"<input[^>]*x-ref=\"password\"[^>]*>", src, re.S)
    assert m and "data-pw-hint" in m.group(0)


def test_every_password_input_on_change_password_is_marked():
    src = CHANGE_PW.read_text(encoding="utf-8")
    inputs = re.findall(r"<input[^>]*type=\"password\"[^>]*>", src, re.S)
    assert len(inputs) == 5, "預期 5 個密碼欄位（目前／新／確認＋兩個 TOTP 確認）；新增欄位請一併加 data-pw-hint 並更新這裡"
    assert all("data-pw-hint" in i for i in inputs), [i for i in inputs if "data-pw-hint" not in i]


# ── 2. e2e ─────────────────────────────────────────────────────────────────

pytest.importorskip("playwright.sync_api")

PW = "input[x-model='password']"
HINT = ".pw-hint"


def _goto_login(page, live_server):
    with page.expect_response(lambda r: "/api/system/webauthn-config-status" in r.url, timeout=15000):
        page.goto(f"{live_server}/pages/login.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')._x_dataStack")
    page.evaluate("() => new Promise(r => Alpine.nextTick(r))")


def _key(page, sel, type_, caps, key="a"):
    """在欄位上送一個帶 CapsLock 狀態的鍵盤事件（見模組 docstring）。"""
    page.evaluate("""([sel, type, caps, key]) => document.querySelector(sel).dispatchEvent(
        new KeyboardEvent(type, {key, bubbles: true, cancelable: true, modifierCapsLock: caps}))""",
                  [sel, type_, caps, key])


def _hint_text(page, sel_input):
    """輸入欄位後面（同一個 form-group 內）的提示文字；沒有提示回 ''。"""
    return page.evaluate("""(sel) => {
        const g = document.querySelector(sel).closest('.form-group');
        const h = g && g.querySelector('.pw-hint');
        return h ? h.textContent : '';
    }""", sel_input)


def _compose(page, text="ㄋ", cdp_ok=[True]):
    """組字開始。優先走 CDP（瀏覽器會真的發 compositionstart）；不支援就合成事件。"""
    if cdp_ok[0]:
        try:
            cdp = page.context.new_cdp_session(page)
            cdp.send("Input.imeSetComposition", {"text": text, "selectionStart": len(text), "selectionEnd": len(text)})
            return cdp
        except Exception:
            cdp_ok[0] = False
    page.evaluate("""() => document.activeElement.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}))""")
    return None


def _compose_end(page, cdp, committed="你"):
    if cdp is not None:
        cdp.send("Input.insertText", {"text": committed})
    else:
        page.evaluate("""() => document.activeElement.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true}))""")


@pytest.fixture
def login_page(live_server, e2e_browser):
    page = e2e_browser.new_context().new_page()
    _goto_login(page, live_server)
    page.focus(PW)
    return page


@pytest.mark.e2e
def test_caps_lock_on_shows_hint_and_off_removes_it(login_page):
    p = login_page
    assert _hint_text(p, PW) == ""
    _key(p, PW, "keydown", True)
    assert CAPS_MSG in _hint_text(p, PW)
    _key(p, PW, "keyup", True)
    assert CAPS_MSG in _hint_text(p, PW)
    _key(p, PW, "keydown", False)                   # 關掉大寫鎖定後的下一個鍵
    assert _hint_text(p, PW) == ""
    assert p.locator(HINT).count() == 0, "收掉要真的移除元素，不是只藏起來"


@pytest.mark.e2e
def test_caps_state_is_read_on_mouse_focus_before_any_key(login_page):
    p = login_page
    p.evaluate("() => document.activeElement.blur()")
    p.evaluate("""(sel) => document.querySelector(sel).dispatchEvent(
        new MouseEvent('mousedown', {bubbles: true, modifierCapsLock: true}))""", PW)
    assert CAPS_MSG in _hint_text(p, PW)


@pytest.mark.e2e
def test_plain_ascii_typing_shows_nothing_no_false_alarm(login_page):
    p = login_page
    p.keyboard.type("Passw0rd!xyz")                  # 真的鍵盤事件，CapsLock 狀態為關
    assert _hint_text(p, PW) == "" and p.locator(HINT).count() == 0
    assert p.input_value(PW) == "Passw0rd!xyz", "提示程式不能吃掉或改動輸入"


@pytest.mark.e2e
def test_ime_composition_shows_hint_and_commit_removes_it(login_page):
    p = login_page
    cdp = _compose(p)
    assert IME_MSG in _hint_text(p, PW)
    assert CAPS_MSG not in _hint_text(p, PW), "兩種提示各自獨立"
    _compose_end(p, cdp)
    assert _hint_text(p, PW) == ""


@pytest.mark.e2e
def test_both_hints_at_once_show_two_lines_and_clear_independently(login_page):
    p = login_page
    _key(p, PW, "keydown", True)
    cdp = _compose(p)
    txt = _hint_text(p, PW)
    assert CAPS_MSG in txt and IME_MSG in txt and txt.count("\n") == 1
    assert p.locator(HINT).count() == 1, "共用同一個提示區塊"
    _compose_end(p, cdp)
    assert CAPS_MSG in _hint_text(p, PW) and IME_MSG not in _hint_text(p, PW)
    _key(p, PW, "keyup", False)
    assert _hint_text(p, PW) == ""


@pytest.mark.e2e
def test_blur_clears_all_hints_and_refocus_does_not_resurrect_them(login_page):
    p = login_page
    _key(p, PW, "keydown", True)
    cdp = _compose(p)
    assert p.locator(HINT).count() == 1
    p.focus("input[x-model='username']")             # 失焦
    assert p.locator(HINT).count() == 0
    p.focus(PW)
    assert p.locator(HINT).count() == 0, "重新聚焦在沒有新事件前不會自己跳出舊提示"
    del cdp


@pytest.mark.e2e
def test_hint_survives_eye_toggle_and_stays_off_the_username_field(login_page):
    p = login_page
    _key(p, PW, "keydown", True)
    p.click(".eye-btn")                              # mousedown.prevent：焦點留在密碼欄
    assert p.get_attribute(PW, "type") == "text"
    assert CAPS_MSG in _hint_text(p, PW), "切成顯示密碼後提示還在（欄位仍有 data-pw-hint）"
    # 帳號欄沒有 data-pw-hint ⇒ 同樣的事件不會跳提示
    p.focus("input[x-model='username']")
    _key(p, "input[x-model='username']", "keydown", True)
    assert p.locator(HINT).count() == 0


@pytest.mark.e2e
def test_hint_is_sibling_not_inside_the_pw_wrap_and_login_still_works(live_server, make_user, e2e_browser):
    from tests._e2e_login import wait_logged_in
    u, pw = make_user(username="pwhint_login", role="admin")
    p = e2e_browser.new_context().new_page()
    _goto_login(p, live_server)
    p.fill("input[x-model='username']", u)
    p.click(PW)
    _key(p, PW, "keydown", True)
    assert p.evaluate("() => document.querySelector('.pw-hint').previousElementSibling.classList.contains('pw-wrap')")
    p.keyboard.type(pw)
    p.keyboard.press("Enter")
    wait_logged_in(p)


@pytest.mark.e2e
def test_change_password_every_field_gets_the_hint(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u, pw = make_user(username="pwhint_chg", role="admin")
    p = e2e_browser.new_context().new_page()
    inject_login(p, live_server, u, pw)
    p.goto(f"{live_server}/pages/change-password.html")
    fields = p.locator("input[data-pw-hint]")
    p.wait_for_function("() => document.querySelectorAll('input[data-pw-hint]').length >= 3")
    assert fields.count() >= 3
    for i in range(3):                               # 目前／新／確認
        f = fields.nth(i)
        f.focus()
        f.evaluate("""el => el.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', bubbles: true, modifierCapsLock: true}))""")
        grp = f.locator("xpath=ancestor::div[contains(@class,'form-group')][1]")
        assert CAPS_MSG in grp.locator(".pw-hint").inner_text(), i
        f.evaluate("""el => el.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}))""")
        assert IME_MSG in grp.locator(".pw-hint").inner_text(), i
        f.evaluate("""el => el.blur()""")
        assert grp.locator(".pw-hint").count() == 0, i
