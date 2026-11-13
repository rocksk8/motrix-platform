# -*- coding: utf-8 -*-
"""頭像選單的「我的帳號」（T82 整合，2026-11-13）：選單有「我的帳號」、點下去打開 my-account.html 不是 404；
「修改密碼」舊網址轉到「我的帳號 → 帳號安全」（hichan-1 的轉址頁）。MY_ACCOUNT_READY 由 false 改 true 的驗收。"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402


@pytest.mark.e2e
def test_avatar_menu_has_my_account_and_it_opens_without_404(live_server, make_user, e2e_browser):
    u, p = make_user(username="acct_menu_u", role="superadmin")[:2]
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    bad = []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.url.endswith("my-account.html") and r.status >= 400 else None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")
    page.locator("#tb-avatar").click()
    link = page.locator("#tb-acct-menu a.acct__item", has_text="我的帳號")
    link.wait_for(state="visible", timeout=15000)
    with page.expect_navigation():
        link.click()
    assert page.url.split("?")[0].endswith("/pages/my-account.html"), page.url
    page.wait_for_load_state("load")
    assert not bad, bad
    assert "404" not in page.title() and "Not Found" not in page.content()[:2000]


@pytest.mark.e2e
def test_old_change_password_url_lands_on_account_security_tab(live_server, make_user, e2e_browser):
    u, p = make_user(username="acct_menu_cp", role="superadmin")[:2]
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/change-password.html")
    page.wait_for_url("**/my-account.html*", timeout=15000)
    assert "tab=security" in page.url
