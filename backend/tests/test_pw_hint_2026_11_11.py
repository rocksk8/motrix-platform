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


# 提示程式碼不該碰的東西：密碼內容的來源（.value／.defaultValue／組字結果 e.data／按鍵 e.key／e.code）、
# 任何能把資料送出去或動態執行的出口。⚠️ 這是字串黑名單，只擋「寫出來」的那幾種；它不是證明，
# 所以另有 test_value_guard_flags_a_deliberately_bad_snippet 當正對照，並且人工審過（K審）。
_FORBIDDEN = (".value", ".defaultValue", "['value']", '["value"]', ".data", ".key", ".code",
              "FormData", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "Image(",
              "postMessage", "eval", "new Function", "setTimeout(\"", "localStorage", "sessionStorage",
              "document.cookie", "navigator.", "location", "innerHTML", "outerHTML", "insertAdjacentHTML",
              "console.")
_TOKEN = re.compile(r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|/\*.*?\*/|//[^\n]*""", re.S)


def _code_without_comments(js):
    """剔除註解但保留字串（字串裡的 // 如 'http://…' 不會把同一行後面的程式碼一起吃掉）。"""
    return _TOKEN.sub(lambda m: m.group(1) or "", js)


def _violations(js):
    code = _code_without_comments(js)
    assert code.strip(), "剔除註解後沒有程式碼＝檢查器壞了（會讓每個檢查都假綠）"
    return [bad for bad in _FORBIDDEN if bad in code]


def test_hint_code_never_touches_the_password_value_or_network():
    assert _violations(_snippet(LOGIN)) == []


def test_value_guard_flags_a_deliberately_bad_snippet():
    """正對照：同一支檢查器對「故意寫壞」的程式碼要真的報出來，否則上面那題綠燈沒有意義。"""
    bad = ("document.addEventListener('keydown', function (e) {\n"
           "  var u = 'http://x.example'; fetch(u, {body: e.target.value + e.key})   // 字串裡的 // 不能遮住後面\n"
           "  el.innerHTML = e.data\n})")
    hits = _violations(bad)
    for must in (".value", ".key", ".data", "fetch(", "innerHTML"):
        assert must in hits, (must, hits)
    # 註解裡提到這些字不算違規
    assert _violations("var a = 1  // 不讀 .value 也不 fetch(\n/* e.data */ var b = 2") == []


def test_every_hinted_input_sits_in_a_form_group_inside_its_template_root():
    """提示元素是輸入欄的下一個兄弟（afterend）。若欄位本身就是 x-if <template> 的根，
    提示會長在 template 外面、欄位被移除後它還留著（外洩）。所以欄位必須在 .form-group 之內，
    而且那個 .form-group 要在「最近的 <template>」之後開始。"""
    for page in (LOGIN, CHANGE_PW):
        src = page.read_text(encoding="utf-8")
        found = 0
        for m in re.finditer(r"<input[^>]*data-pw-hint[^>]*>", src, re.S):
            found += 1
            before = src[:m.start()]
            fg, tpl = before.rfind('class="form-group'), before.rfind("<template")
            assert fg != -1 and fg > tpl, f"{page.name}: data-pw-hint 欄位不在 template 內的 .form-group 裡 —— {m.group(0)[:80]}"
        assert found >= 1, page.name


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


@pytest.mark.e2e
def test_real_mouse_click_on_submit_works_while_the_hint_is_showing(live_server, make_user, e2e_browser):
    """K審 hichan-11：提示在 focusout 被移除 ⇒ 下面的按鈕往上跳 ⇒ mousedown 把焦點移走、版面一動，
    mouseup 落在別的元素上 ⇒ 不產生 click。鍵盤 Enter 不受影響，所以只有「真滑鼠點」測得到。"""
    u, pw = make_user(username="pwhint_click", role="admin")
    p = e2e_browser.new_context().new_page()
    _goto_login(p, live_server)
    p.fill("input[x-model='username']", u)
    p.click(PW)
    p.keyboard.type(pw)
    _key(p, PW, "keydown", True)                     # 大寫鎖定提示出現（版面被撐開）
    assert CAPS_MSG in _hint_text(p, PW)
    with p.expect_request(lambda r: "/api/auth/login" in r.url and r.method == "POST", timeout=5000):
        box = p.locator(".btn-login:visible").bounding_box()
        p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.9)   # 下緣：K審實測，版面上跳時最先落空的位置
        p.mouse.down()
        p.mouse.up()
    # 按完之後（滑鼠已放開）提示要收乾淨，不留空白
    p.wait_for_function("() => !document.querySelector('.pw-hint') || location.pathname.endsWith('index.html')")


@pytest.mark.e2e
def test_hint_hidden_but_not_removed_while_mouse_is_down_then_removed_after(login_page):
    p = login_page
    _key(p, PW, "keydown", True)
    box = p.locator(".btn-login:visible").bounding_box()
    p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.9)   # 下緣：K審實測，版面上跳時最先落空的位置
    p.mouse.down()                                   # 焦點離開密碼欄，但滑鼠還沒放開
    st = p.evaluate("() => { const h = document.querySelector('.pw-hint'); return h ? getComputedStyle(h).visibility : 'gone' }")
    assert st == "hidden", "滑鼠按著時不能動版面：元素留著但看不見（%s）" % st
    p.mouse.up()
    p.wait_for_function("() => !document.querySelector('.pw-hint')")


@pytest.mark.e2e
def test_change_password_submit_by_mouse_works_while_the_hint_is_showing(live_server, make_user, e2e_browser):
    from tests._e2e_login import inject_login
    u, pw = make_user(username="pwhint_chg2", role="admin")
    p = e2e_browser.new_context().new_page()
    inject_login(p, live_server, u, pw)
    p.goto(f"{live_server}/pages/change-password.html")
    p.wait_for_function("() => document.querySelectorAll('input[data-pw-hint]').length >= 3")
    f = p.locator("input[data-pw-hint]")
    f.nth(0).fill(pw); f.nth(1).fill("NewPassw0rd!x1"); f.nth(2).fill("NewPassw0rd!x1")
    f.nth(2).focus()
    f.nth(2).evaluate("el => el.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', bubbles: true, modifierCapsLock: true}))")
    assert p.locator(HINT).count() == 1
    with p.expect_request(lambda r: "/api/auth/change-password" in r.url, timeout=5000):
        box = p.locator("button.btn-primary[type=submit]").bounding_box()
        p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.9)   # 下緣：K審實測，版面上跳時最先落空的位置
        p.mouse.down()
        p.mouse.up()


@pytest.mark.e2e
def test_repeated_identical_state_does_not_rewrite_the_live_region(login_page):
    """role=status：每次 keydown／keyup 都重寫 textContent，螢幕閱讀器會一直重念。文字沒變就不動 DOM。"""
    p = login_page
    _key(p, PW, "keydown", True)
    p.evaluate("""() => { window.__muts = 0
        new MutationObserver(rs => { window.__muts += rs.length })
          .observe(document.querySelector('.pw-hint').parentElement, {childList: true, characterData: true, subtree: true}) }""")
    for t in ("keydown", "keyup", "keydown", "keyup", "keydown"):
        _key(p, PW, t, True)
    assert p.evaluate("() => window.__muts") == 0


@pytest.mark.e2e
def test_lost_mouseup_does_not_leave_an_invisible_hint_reserving_space(login_page):
    """K審 hichan-11 nit：mouseup 遺失（例如 mousedown 就開右鍵選單）時 mouseDown 旗標會卡住，
    之後用 Tab 離開欄位 ⇒ 提示只被隱藏、永遠不移除（看不見但佔位）。任何鍵盤事件都要重置旗標。"""
    p = login_page
    _key(p, PW, "keydown", True)
    assert p.locator(HINT).count() == 1
    # 空白處 mousedown、沒有 mouseup（合成：只送 mousedown 事件，不觸發焦點變化）
    p.evaluate("() => document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    p.keyboard.press("Tab")                          # 真的鍵盤換焦點離開密碼欄
    p.wait_for_function("() => !document.querySelector('.pw-hint')")
