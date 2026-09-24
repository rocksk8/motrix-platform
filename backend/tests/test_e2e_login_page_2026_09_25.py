"""登入頁本身：帳密錯誤、兩步驟驗證（TOTP）、驗證碼步驟按 Enter（2026-09-25 補覆蓋缺口）。

登入頁是每個人每天的入口；先前 TOTP 只有 API 層的題、錯誤訊息只在 login_enter 的失敗重試題裡順帶走過。
這一檔**一律走真實登入頁**（每段都標 keep-ui-login，登入轉換腳本不可換掉）。
觀測點：畫面上的錯誤訊息、驗證碼步驟是否出現、是否真的換到 index.html（登入成功後才會跳）。
"""
import pyotp
import pytest

pytest.importorskip("playwright.sync_api")

U = "input[x-model='username']"
P = "input[x-model='password']"
CODE = "input[x-model='totpCode']"
ERR = ".error-msg:visible"
KEY = """([sel, type]) => document.querySelector(sel).dispatchEvent(
  new KeyboardEvent(type, { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }))"""


def _open_login(new_page, live_server):
    page = new_page()
    # keep-ui-login：這一檔驗的就是登入頁本身
    page.goto(f"{live_server}/pages/login.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')._x_dataStack")
    return page


def _enable_totp(client, user):
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    secret = client.post("/api/auth/totp/setup", headers=h).json()["secret"]
    r = client.post("/api/auth/totp/enable", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret, r.json()["recoveryCodes"]


def _to_totp_step(page, user):
    page.fill(U, user[0])
    page.fill(P, user[1])
    page.click('button:has-text("登入")')
    page.locator(CODE).wait_for(state="visible", timeout=10000)


def _logged_in(page):
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


@pytest.mark.e2e
def test_wrong_password_shows_the_error_and_stays_on_the_login_page(live_server, make_user, new_page):
    u = make_user(username="lp_wrong", role="admin")
    page = _open_login(new_page, live_server)
    page.fill(U, u[0])
    page.fill(P, "definitely-wrong")
    page.click('button:has-text("登入")')
    err = page.locator(ERR).first
    err.wait_for(state="visible", timeout=10000)
    assert err.inner_text().strip(), "錯誤訊息是空的"
    page.wait_for_timeout(500)
    assert page.url.endswith("/pages/login.html"), page.url
    assert page.input_value(U) == u[0], "帳號欄應保留剛才輸入的帳號"


@pytest.mark.e2e
def test_totp_account_goes_through_the_code_step(live_server, client, make_user, new_page):
    u = make_user(username="lp_totp", role="admin")
    secret, _ = _enable_totp(client, u)
    page = _open_login(new_page, live_server)
    _to_totp_step(page, u)
    assert page.url.endswith("/pages/login.html"), "還沒輸入驗證碼就不應該登入"
    # 錯碼 ⇒ 錯誤訊息、仍在驗證碼步驟
    page.fill(CODE, "000000")
    page.click('button:has-text("驗證")')
    page.locator(ERR).first.wait_for(state="visible", timeout=10000)
    assert page.locator(CODE).is_visible() and page.url.endswith("/pages/login.html")
    # 正確碼 ⇒ 登入成功
    page.fill(CODE, pyotp.TOTP(secret).now())
    page.click('button:has-text("驗證")')
    _logged_in(page)


@pytest.mark.e2e
def test_a_recovery_code_also_logs_in(live_server, client, make_user, new_page):
    u = make_user(username="lp_recov", role="admin")
    _, codes = _enable_totp(client, u)
    page = _open_login(new_page, live_server)
    _to_totp_step(page, u)
    page.fill(CODE, codes[0])
    page.click('button:has-text("驗證")')
    _logged_in(page)


@pytest.mark.e2e
def test_pressing_enter_in_the_code_step_submits(live_server, client, make_user, new_page):
    u = make_user(username="lp_enter", role="admin")
    secret, _ = _enable_totp(client, u)
    page = _open_login(new_page, live_server)
    _to_totp_step(page, u)
    page.click(CODE)
    page.keyboard.type(pyotp.TOTP(secret).now())
    page.keyboard.press("Enter")
    _logged_in(page)


@pytest.mark.e2e
def test_a_page_level_enter_in_the_code_step_submits(live_server, client, make_user, new_page):
    """比照 7f03a41：頁面自己處理 Enter，不只依賴表單的隱式送出（瀏覽器建議下拉吃掉 keydown 時也送得出去）。"""
    u = make_user(username="lp_enter2", role="admin")
    secret, _ = _enable_totp(client, u)
    page = _open_login(new_page, live_server)
    _to_totp_step(page, u)
    page.fill(CODE, pyotp.TOTP(secret).now())
    page.evaluate(KEY, [CODE, "keyup"])          # 只收到 keyup（keydown 被吃掉）
    _logged_in(page)
