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
