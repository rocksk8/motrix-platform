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
    page.locator("[data-testid=profile-quote-email-none]").wait_for(state="visible", timeout=5000)
    assert "尚未設定" in page.locator("[data-testid=profile-quote-email-none]").inner_text()
    assert "尚未設定" in page.locator("[data-testid=profile-quote-email]").input_value()


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
    page2.wait_for_function("() => parseFloat(document.documentElement.style.zoom) === 1.15", timeout=10000)   # 與頂欄「大」同一檔


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


# ── hichan-3 審查修正 M1／L3：字級偏好與頂欄是同一套、登出清快取 ───────────────────────────────
def _zoom_state(page):
    return page.evaluate("""() => ({zoom: document.documentElement.style.zoom, fz: document.documentElement.style.getPropertyValue('--fz'),
        ls: localStorage.getItem('motrix_font_zoom'), prefs: JSON.parse(localStorage.getItem('motrix_prefs') || 'null')})""")


def _put_pref(page, value):
    return page.evaluate("""async (v) => { const s = JSON.parse(localStorage.getItem('motrix_session'));
        const r = await fetch('/api/auth/preferences', {method:'PUT', headers:{'Content-Type':'application/json', Authorization:'Bearer ' + s.token}, body: JSON.stringify({font_size: v})});
        return r.status }""", value)


@pytest.mark.e2e
def test_font_pref_and_topbar_share_one_zoom_and_survive_page_changes(live_server, make_user, new_page, login_as):
    u = make_user(username="fs_user", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, u)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_load_state("networkidle")
    assert _put_pref(page, "xlarge") == 200
    page.evaluate("() => { sessionStorage.clear() }")                      # 模擬新登入期間：要向伺服器同步
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => localStorage.getItem('motrix_font_zoom') === '1.3'", timeout=10000)
    s1 = _zoom_state(page)
    assert float(s1["zoom"]) == 1.3 and s1["fz"] == "1.3"                  # ① 偏好套用到同一套（--fz 與 zoom 一致）
    page.goto(live_server + "/pages/customers.html")
    page.wait_for_load_state("networkidle")
    s2 = _zoom_state(page)
    assert float(s2["zoom"]) == 1.3 and s2["fz"] == "1.3"                  # ② 換頁後保留
    page.evaluate("() => window.motrixSetZoom(1.15)")                      # ③ 頂欄改「大」⇒ 偏好同步成 large，兩邊一致
    page.wait_for_function("""async () => { const s = JSON.parse(localStorage.getItem('motrix_session'));
        const r = await fetch('/api/auth/preferences', {headers:{Authorization:'Bearer ' + s.token}}); const d = await r.json();
        return d.prefs.font_size === 'large' }""", timeout=10000)
    page.evaluate("() => { sessionStorage.clear() }")
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    s3 = _zoom_state(page)
    assert float(s3["zoom"]) == 1.15 and s3["fz"] == "1.15" and s3["prefs"]["font_size"] == "large"   # 下個登入期間仍是頂欄選的


@pytest.mark.e2e
def test_default_pref_does_not_reset_a_topbar_choice_on_sync(live_server, make_user, new_page, login_as):
    u = make_user(username="fs_user2", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, u)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => { localStorage.setItem('motrix_font_zoom', '1.15'); localStorage.removeItem('motrix_prefs'); sessionStorage.clear() }")   # 舊使用者：只用過頂欄、伺服器是預設值
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    assert float(_zoom_state(page)["zoom"]) == 1.15


@pytest.mark.e2e
def test_logout_clears_prefs_caches(live_server, make_user, new_page, login_as):
    u = make_user(username="fs_user3", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, u)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_load_state("networkidle")
    assert _put_pref(page, "large") == 200
    page.evaluate("() => { sessionStorage.clear() }")
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => localStorage.getItem('motrix_prefs') !== null", timeout=10000)
    # 在同一個同步區塊內讀（導向發生之前）：測試夾具會在每個新頁面重放登入，登入頁會被帶回首頁、重新同步，事後讀會讀到新一輪的快取
    left = page.evaluate("() => { window.motrixLogout(); return [localStorage.getItem('motrix_prefs'), localStorage.getItem('motrix_font_zoom'), sessionStorage.getItem('motrix_prefs_synced'), sessionStorage.getItem('motrix_home_done')] }")
    assert left == [None, None, None, None]
