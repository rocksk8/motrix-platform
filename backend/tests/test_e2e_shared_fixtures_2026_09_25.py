"""e2e 共用瀏覽器與伺服器（PLAN-TEST-PERF #5，conftest.py「e2e 共用瀏覽器與伺服器」段）本身的守門。

① 共用伺服器看到的是**這一題的庫**（每題 `client` 換 db.DB_PATH）——參數化兩題各建各的帳號，互相看不到
② `login_as` 注入的 session 與走登入頁得到的**同一個形狀**（格式跟著 login.html 走，改了會在這裡紅）
③ 並存：共用的 Playwright 開著時，停掉它之後「還沒轉」的寫法（題內自開 sync_playwright）可以用，
   之後共用的會自動重啟
④ 每題的 context 互相隔離：前一題寫進 localStorage 的東西，下一題看不到
⚠️ 這一檔**不可以**在模組層 import sync_playwright（否則整檔會被當成「還沒轉」）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

SESSION_JS = "() => JSON.parse(localStorage.getItem('motrix_session') || 'null')"


@pytest.mark.e2e
@pytest.mark.parametrize("i", [1, 2])
def test_the_shared_server_sees_this_tests_own_db(live_server, make_user, new_page, login_as, client, i):
    u = make_user(username=f"shf_db{i}", role="admin")
    other = f"shf_db{3 - i}"
    r = client.post("/api/auth/login", json={"username": other, "password": u[1]})
    assert r.status_code != 200, "另一題的帳號不應出現在這一題的庫"
    page = new_page()
    login_as(page, u)
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')")
    assert page.evaluate(SESSION_JS)["username"] == u[0]
    assert page.url.endswith("/pages/case-management.html"), ("token 注入後不應被導回登入頁", page.url)


@pytest.mark.e2e
def test_login_as_writes_the_same_session_shape_as_the_login_page(live_server, make_user, new_page, login_as):
    u = make_user(username="shf_shape", role="admin")
    ui = new_page()
    # keep-ui-login：這一段是「走登入頁」的對照組，換掉這題就失效
    ui.goto(f"{live_server}/pages/login.html")
    ui.fill('input[x-model="username"]', u[0])
    ui.fill('input[x-model="password"]', u[1])
    ui.click('button:has-text("登入")')
    ui.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    real = ui.evaluate(SESSION_JS)
    inj = new_page()
    login_as(inj, u)
    inj.goto(f"{live_server}/pages/login.html")
    injected = inj.evaluate(SESSION_JS)
    assert sorted(real) == sorted(injected), (sorted(real), sorted(injected))
    assert {k: injected[k] for k in ("username", "role", "userId")} == {k: real[k] for k in ("username", "role", "userId")}


@pytest.mark.e2e
def test_old_style_playwright_works_after_the_shared_one_is_stopped(new_page):
    import tests.conftest as cf
    new_page().goto("data:text/html,<p>shared</p>")        # 共用的已啟動
    assert cf._PW["browser"] is not None
    cf._stop_shared_browser()                              # _pw_coexist 在「還沒轉」的模組前做的事
    from playwright.sync_api import sync_playwright         # 題內自開（舊寫法）
    with sync_playwright() as p:
        b = p.chromium.launch()
        b.new_page().goto("data:text/html,<p>old</p>")
        b.close()
    new_page().goto("data:text/html,<p>again</p>")          # 共用的自動重啟
    assert cf._PW["browser"] is not None


def test_the_coexist_switch_only_fires_for_modules_that_still_import_sync_playwright():
    import types

    import tests.conftest as cf
    assert cf._module_opens_its_own_playwright(types.SimpleNamespace(sync_playwright=object())) is True
    assert cf._module_opens_its_own_playwright(types.SimpleNamespace()) is False
    assert cf._module_opens_its_own_playwright(None) is False
    import sys
    assert cf._module_opens_its_own_playwright(sys.modules[__name__]) is False, "這一檔自己不可以被當成還沒轉"


@pytest.mark.e2e
@pytest.mark.parametrize("step", ["write", "read"])
def test_each_test_gets_an_isolated_context(live_server, new_page, step):
    page = new_page()
    page.goto(f"{live_server}/pages/login.html")
    if step == "write":
        page.evaluate("() => localStorage.setItem('shf_leak', 'x')")
    else:
        assert page.evaluate("() => localStorage.getItem('shf_leak')") is None, "上一題的 localStorage 漏到這一題"


def test_context_hooks_run_for_every_new_context(new_context, request):
    import tests.conftest as cf
    seen = []
    cf.E2E_CONTEXT_HOOKS.append(lambda ctx, req: seen.append(req.node.name))
    try:
        new_context()
        new_context()
    finally:
        cf.E2E_CONTEXT_HOOKS.pop()
    assert seen == [request.node.name] * 2
    json.dumps(seen)


# ── A／B 對照開關 MOTRIX_E2E_FRESH_BROWSER=1：每題自開瀏覽器與伺服器 ─────────────────────
@pytest.fixture()
def fresh_mode(monkeypatch):
    # 要排在 live_server／new_page 前面（同 scope 依參數順序建立）⇒ 它們建立時已看得到開關
    monkeypatch.setenv("MOTRIX_E2E_FRESH_BROWSER", "1")


@pytest.mark.e2e
def test_the_fresh_switch_gives_this_test_its_own_browser_and_server(fresh_mode, live_server, new_page, request):
    import tests.conftest as cf
    page = new_page()
    page.goto(f"{live_server}/pages/login.html")
    assert cf._PW["browser"] is None, "開關打開時不應啟動共用瀏覽器"
    assert page.context.browser is not None
    assert live_server != request.getfixturevalue("_shared_server"), "開關打開時伺服器應是這一題自己的"


@pytest.fixture()
def shared_mode(monkeypatch):
    monkeypatch.delenv("MOTRIX_E2E_FRESH_BROWSER", raising=False)


@pytest.mark.e2e
def test_without_the_switch_the_browser_and_server_are_shared(shared_mode, live_server, new_page, request):
    import tests.conftest as cf
    page = new_page()
    page.goto(f"{live_server}/pages/login.html")
    assert page.context.browser is cf._PW["browser"] is not None
    assert live_server == request.getfixturevalue("_shared_server")


def test_drain_waits_for_in_flight_requests_and_fails_if_they_never_finish():
    """共用伺服器收尾要排空：處理中的請求跑完才往下（否則漏到下一題的庫與 monkeypatch）。
    正對照（實測）：拿掉排空，boolean_status_select 連 3 次都被 NETGUARD 抓到前一題漏過來的圖磚探測；恢復後 3/3 綠。"""
    import threading
    import time

    import tests.conftest as cf

    class _Fake:
        n = 1
    fake = _Fake()
    cf._SERVER_APPS.append(fake)
    try:
        threading.Timer(0.3, lambda: setattr(fake, "n", 0)).start()
        t0 = time.monotonic()
        cf._drain_servers(timeout=5)
        assert time.monotonic() - t0 >= 0.25, "應等到處理中的請求結束才返回"
        fake.n = 1
        with pytest.raises(pytest.fail.Exception, match="仍有 1 個請求在處理"):
            cf._drain_servers(timeout=0.2)
    finally:
        cf._SERVER_APPS.remove(fake)


@pytest.mark.e2e
def test_inject_login_writes_the_same_session_shape_as_the_login_page(live_server, make_user, new_page):
    from tests._e2e_login import inject_login
    u = make_user(username="shf_inj", role="admin")
    ui = new_page()
    # keep-ui-login：這一段是「走登入頁」的對照組，換掉這題就失效
    ui.goto(f"{live_server}/pages/login.html")
    ui.fill('input[x-model="username"]', u[0])
    ui.fill('input[x-model="password"]', u[1])
    ui.click('button:has-text("登入")')
    ui.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    real = ui.evaluate(SESSION_JS)
    inj = new_page()
    inject_login(inj, live_server, u[0], u[1])
    inj.goto(f"{live_server}/pages/case-management.html")
    inj.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')")
    got = inj.evaluate(SESSION_JS)
    assert sorted(real) == sorted(got), (sorted(real), sorted(got))
    assert {k: got[k] for k in ("username", "role", "userId")} == {k: real[k] for k in ("username", "role", "userId")}
    assert inj.url.endswith("/pages/case-management.html"), ("注入後不應被導回登入頁", inj.url)
