"""公司資料設定頁：資料讀回來之前不可編輯、不可儲存（fix/company-profile-form-load-race-t84）。

漏洞：`init()` 在 `GET /api/settings/company-profile` 回來時 `this.cfg = {...this.cfg, ...data}`——使用者在回應之前已經輸入的欄位
（地圖 ID、銀行帳號…）會被伺服器舊值靜默蓋回；讀取失敗時整頁還是可編輯、按儲存會把一張空表單存回去。
現在：`cfgState`（loading／ready／error／denied）；非 ready 時整張表單 `<fieldset disabled>`、`save()` 直接 return。
觀測點打在輸入框的 disabled 狀態、元件狀態與「有沒有送出 PUT」，不打頁面文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
URL_PART = "/api/settings/company-profile"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _is_profile_get(route):
    req = route.request
    return req.method == "GET" and req.url.split("?")[0].endswith(URL_PART)


@pytest.mark.e2e
def test_form_is_locked_until_the_profile_arrives_and_nothing_typed_is_lost(live_server, make_user, e2e_browser):
    sa = make_user(username="cp_sa", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    held = []

    def handler(route):
        if _is_profile_get(route):
            held.append(route)                    # 壓住：先不放行，模擬回應很慢
        else:
            route.continue_()
    page.route("**/api/settings/company-profile*", handler)
    page.goto(f"{live_server}/pages/company-profile-settings.html")
    page.wait_for_function(f"() => {DATA}.session && {DATA}.session.token", timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-cfg-fieldset]') !== null", timeout=20000)
    assert page.evaluate(f"() => {DATA}.cfgState") == "loading"
    assert page.locator("[data-cfg-fieldset]").evaluate("el => el.disabled") is True
    assert page.locator("#google_maps_map_id").is_disabled(), "讀回來之前輸入框不可編輯"
    with pytest.raises(Exception):
        page.fill("#google_maps_map_id", "MAP-TYPED-EARLY", timeout=1500)       # 打不進去（不是「打進去再被蓋掉」）
    assert page.evaluate(f"() => {DATA}.cfg.google_maps_map_id || ''") == ""
    page.evaluate(f"() => {DATA}.save()")                                       # 直接叫 save() 也不送
    assert page.evaluate(f"() => {DATA}.saving") is False

    from helpers.settings import _set_setting
    _set_setting("company_profile", {"name": "伺服器公司", "google_maps_map_id": "MAP-SERVER"})
    assert held, "GET 被壓住"
    held[0].continue_()
    page.wait_for_function(f"() => {DATA}.cfgState === 'ready'", timeout=20000)
    assert page.locator("#google_maps_map_id").is_enabled()
    assert page.evaluate(f"() => {DATA}.cfg.google_maps_map_id") == "MAP-SERVER"    # 讀回來的是伺服器值
    page.fill("#google_maps_map_id", "MAP-TYPED-AFTER")                         # 讀回來之後才能編輯；之後不會再被任何晚到的回應蓋掉
    assert page.evaluate(f"() => {DATA}.cfg.google_maps_map_id") == "MAP-TYPED-AFTER"


@pytest.mark.e2e
def test_failed_load_keeps_the_form_locked_and_sends_no_put(live_server, make_user, e2e_browser):
    sa = make_user(username="cp_sa2", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    puts = []

    def handler(route):
        req = route.request
        if req.method == "PUT" and req.url.split("?")[0].endswith(URL_PART):
            puts.append(req.url)
            route.continue_()
        elif _is_profile_get(route):
            route.abort()
        else:
            route.continue_()
    page.route("**/api/settings/company-profile*", handler)
    page.goto(f"{live_server}/pages/company-profile-settings.html")
    page.wait_for_function(f"() => {DATA}.cfgState === 'error'", timeout=20000)
    assert page.locator("[data-cfg-fieldset]").evaluate("el => el.disabled") is True
    assert page.locator("#google_maps_map_id").is_disabled()
    page.evaluate(f"() => {DATA}.save()")
    page.evaluate(f"() => {DATA}.save(true)")
    assert puts == [], "讀取失敗時不可把空表單存回去"
    assert page.evaluate(f"() => /讀取公司資料失敗/.test({DATA}.msg)")
    assert _q("SELECT COUNT(*) AS n FROM system_settings WHERE key='company_profile'")[0]["n"] in (0, 1)


@pytest.mark.e2e
def test_normal_load_is_editable_and_saves(live_server, make_user, e2e_browser):
    sa = make_user(username="cp_sa3", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/company-profile-settings.html")
    page.wait_for_function(f"() => {DATA}.cfgState === 'ready'", timeout=20000)
    assert page.locator("[data-cfg-fieldset]").evaluate("el => el.disabled") is False
    page.fill("#google_maps_map_id", "MAP-OK-1")
    assert page.evaluate(f"() => {DATA}.cfg.google_maps_map_id") == "MAP-OK-1"
