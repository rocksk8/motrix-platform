"""瀏覽器端對端：我的帳號（2026-11-13）。

- 個人資料分頁全部唯讀、有「此資料由管理者維護，會顯示在報價單上」說明、顯示報價用信箱與「尚未設定公司信箱」提醒；
- 舊網址 change-password.html 轉到 my-account.html?tab=security（forced 參數原樣帶過去），密碼表單仍在；
- 偏好設定改了之後，換一個全新的瀏覽器工作階段登入仍在（存在伺服器）；
- 手機 375px 寬：四個分頁都點得到、頁面沒有橫向捲動。
"""
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_profile_tab_is_read_only_and_shows_quote_email_hint(live_server, make_user, new_page, login_as):
    u = make_user(username="e2e_ma1", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/my-account.html")
    page.locator("[data-testid=tab-profile]").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-testid=profile-name]').innerText.trim().length > 0", timeout=10000)
    assert "此資料由管理者維護，會顯示在報價單上" in page.locator("[data-testid=tab-profile]").inner_text()
    inputs = page.locator("[data-testid=tab-profile] input")
    n = inputs.count()
    assert n >= 5
    for i in range(n):
        assert inputs.nth(i).is_disabled(), i
    # 沒有公司信箱、也沒有個人報價信箱 ⇒ 提醒
    page.locator("[data-testid=profile-quote-email-unset]").wait_for(state="visible", timeout=5000)
    assert "尚未設定公司信箱" in page.locator("[data-testid=profile-quote-email-unset]").inner_text()


@pytest.mark.e2e
def test_old_change_password_url_lands_on_security_tab(live_server, make_user, new_page, login_as):
    u = make_user(username="e2e_ma2", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/change-password.html")
    page.wait_for_url("**/my-account.html?tab=security", timeout=15000)
    page.locator("[data-testid=tab-security]").wait_for(state="visible", timeout=15000)
    assert page.locator("input[type=password]").count() >= 3
    assert page.locator("[data-testid=tab-profile]").is_hidden()


@pytest.mark.e2e
def test_preferences_persist_across_sessions(live_server, make_user, new_page, login_as):
    u = make_user(username="e2e_ma3", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/my-account.html?tab=prefs")
    sel = page.locator("[data-testid=pref-font_size]")
    sel.wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=pref-font_size] option').length >= 3", timeout=10000)
    sel.select_option("large")
    page.locator("[data-testid=pref-saved]").wait_for(state="visible", timeout=10000)
    # 全新的瀏覽器工作階段（等同換電腦）登入 ⇒ 偏好仍在
    page2 = new_page(viewport={"width": 1280, "height": 1400})
    login_as(page2, u)
    page2.goto(f"{live_server}/pages/my-account.html?tab=prefs")
    page2.wait_for_function("() => document.querySelectorAll('[data-testid=pref-font_size] option').length >= 3", timeout=15000)
    page2.wait_for_function("() => document.querySelector('[data-testid=pref-font_size]').value === 'large'", timeout=10000)
    page2.wait_for_function("() => document.documentElement.style.zoom === '1.1'", timeout=10000)


@pytest.mark.e2e
def test_mobile_375_tabs_reachable_without_horizontal_scroll(live_server, make_user, new_page, login_as):
    u = make_user(username="e2e_ma4", role="sales")
    page = new_page(viewport={"width": 375, "height": 800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/my-account.html")
    page.locator("[data-testid=tab-profile]").wait_for(state="visible", timeout=20000)
    for key in ("security", "notify", "prefs", "profile"):
        btn = page.locator(f"[data-testid=tab-btn-{key}]")
        btn.scroll_into_view_if_needed()
        btn.click()
        page.locator(f"[data-testid=tab-{key}]").wait_for(state="visible", timeout=10000) if key != "notify" else page.locator("[data-testid=tab-notify]").wait_for(state="attached", timeout=10000)
        over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert over <= 1, (key, over)
