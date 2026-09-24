"""登入頁：輸入完帳號密碼按 Enter 就登入，不必再點「登入」（使用者 2026-09-25 回報）。

表單本身是 <form @submit.prevent="login()"> ＋ type=submit，一般打字後按 Enter 會送出；
這一題逐一走「按 Enter 沒反應」可能的情境。觀測點：是否真的換到 index.html（登入成功後才會跳）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_mark_all_read_2026_09_24 import live_server  # noqa: F401  (live_server 是 fixture)

U = "input[x-model='username']"
P = "input[x-model='password']"


def _typed_then_enter_in_password(page, u, pw):
    page.click(U); page.keyboard.type(u)
    page.keyboard.press("Tab"); page.keyboard.type(pw)
    page.keyboard.press("Enter")


def _enter_in_username(page, u, pw):
    page.fill(P, pw)
    page.click(U); page.keyboard.type(u)
    page.keyboard.press("Enter")


def _password_first(page, u, pw):
    page.click(P); page.keyboard.type(pw)
    page.click(U); page.keyboard.type(u)
    page.click(P); page.keyboard.press("Enter")


def _autofilled_then_enter(page, u, pw):
    # 瀏覽器自動填入：欄位有值，但不一定觸發 input 事件（x-model 還是空的）
    page.evaluate("([u, p]) => { document.querySelector(\"input[x-model='username']\").value = u;"
                  " document.querySelector(\"input[x-model='password']\").value = p }", [u, pw])
    page.focus(P)
    page.keyboard.press("Enter")


def _eye_toggled_then_enter(page, u, pw):
    page.fill(U, u)
    page.click(P); page.keyboard.type(pw)
    page.click(".eye-btn")                      # 看一下密碼有沒有打對
    assert page.get_attribute(P, "type") == "text", "眼睛鈕要真的切成顯示密碼（前提）"
    page.keyboard.press("Enter")


def _after_a_failed_attempt(page, u, pw):
    page.fill(U, u)
    page.click(P); page.keyboard.type("wrong-pass")
    page.keyboard.press("Enter")
    page.locator(".error-msg:visible").wait_for(timeout=5000)
    page.fill(P, "")
    page.click(P); page.keyboard.type(pw)
    page.keyboard.press("Enter")


SCENARIOS = {
    "typed_enter_in_password": _typed_then_enter_in_password,
    "enter_in_username": _enter_in_username,
    "password_first": _password_first,
    "autofilled": _autofilled_then_enter,
    "eye_toggled": _eye_toggled_then_enter,
    "after_failed_attempt": _after_a_failed_attempt,
}


@pytest.mark.e2e
@pytest.mark.parametrize("webauthn", [False, True], ids=["plain", "webauthn"])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_enter_logs_in(live_server, make_user, scenario, webauthn):
    u, pw = make_user(username=("le_" + scenario)[:20] + ("_w" if webauthn else ""), role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            if webauthn:   # 已設定 Passkey：頁面多一顆「或使用 Passkey 登入」
                page.route("**/api/system/webauthn-config-status", lambda r: r.fulfill(
                    status=200, content_type="application/json", body='{"configured": true}'))
            page.goto(f"{live_server}/pages/login.html")
            page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')._x_dataStack")
            page.wait_for_timeout(300)
            if webauthn:
                assert page.locator("button:has-text('Passkey')").is_visible(), "前提：Passkey 鈕要出現"
            SCENARIOS[scenario](page, u, pw)
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=8000)
        finally:
            browser.close()


# ── 顯式 Enter 處理（使用者 2026-09-25：自己打字後按 Enter「完全沒反應」，正式機與開發機都一樣）──
# 推測：瀏覽器記住的帳號建議下拉開著時，Enter 被瀏覽器拿去選建議；Playwright 的 chromium 沒有密碼管理員，
# 重現不到那個下拉 ⇒ 以合成事件驗「頁面自己處理 Enter」：不再只依賴表單的隱式送出。
KEY = """([sel, type, composing]) => document.querySelector(sel).dispatchEvent(
  new KeyboardEvent(type, { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true, isComposing: composing }))"""


def _open_login(browser, live_server):
    page = browser.new_context().new_page()
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/api/auth/login") else None)
    page.goto(f"{live_server}/pages/login.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')._x_dataStack")
    page.wait_for_timeout(300)
    return page, posts


@pytest.mark.e2e
@pytest.mark.parametrize("field", [U, P], ids=["username", "password"])
def test_a_page_level_enter_keydown_submits(live_server, make_user, field):
    u, pw = make_user(username="lk_" + ("u" if field == U else "p"), role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, posts = _open_login(browser, live_server)
            page.fill(U, u); page.fill(P, pw)
            page.evaluate(KEY, [field, "keydown", False])
            page.evaluate(KEY, [field, "keyup", False])
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=8000)
            assert len(posts) == 1, posts
        finally:
            browser.close()


@pytest.mark.e2e
def test_enter_that_only_reaches_the_page_as_keyup_still_submits(live_server, make_user):
    """帳號建議下拉吃掉 keydown 時，頁面只收到 keyup。"""
    u, pw = make_user(username="lk_up", role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, posts = _open_login(browser, live_server)
            page.fill(U, u); page.fill(P, pw)
            page.evaluate(KEY, [U, "keyup", False])
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=8000)
            assert len(posts) == 1, posts
        finally:
            browser.close()


@pytest.mark.e2e
def test_pressing_enter_repeatedly_sends_one_login(live_server, make_user):
    u, pw = make_user(username="lk_rep", role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, posts = _open_login(browser, live_server)
            page.route("**/api/auth/login", lambda r: (page.wait_for_timeout(800), r.continue_()))   # 回應慢一點
            page.fill(U, u); page.click(P); page.keyboard.type(pw)
            for _ in range(3):
                page.keyboard.press("Enter")
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=8000)
            assert len(posts) == 1, posts
        finally:
            browser.close()


@pytest.mark.e2e
def test_enter_while_composing_does_not_submit(live_server, make_user):
    """輸入法選字的 Enter（isComposing）不送出，它的 keyup 也不送。"""
    u, pw = make_user(username="lk_ime", role="admin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page, posts = _open_login(browser, live_server)
            page.fill(U, u); page.fill(P, pw)
            page.evaluate(KEY, [U, "keydown", True])
            page.evaluate(KEY, [U, "keyup", False])
            page.wait_for_timeout(1500)
            assert posts == [] and page.url.endswith("/login.html"), (posts, page.url)
        finally:
            browser.close()
