# -*- coding: utf-8 -*-
"""寄信設定卡：設定讀回來之前不可編輯、不可儲存（fix/email-setup-load-lock-t84）。

漏洞：`_loadInit()` 在 `GET /api/settings/email-notify` 回來時 `this.cfg = {...this.cfg, ...data}`——頁面載入後 1 秒內輸入的系統網址
（ns-base-url）會被晚到的回應蓋回去；讀取失敗時卡片仍可編輯、按儲存會把空的 base_url 存回伺服器（信件裡的連結會壞）。
現在：`cfgState`（loading／ready／error／denied）；非 ready 時整張卡 `<fieldset disabled>`，`save()`／`testEmail()`／精靈的送出函式直接 return。
觀測點打在輸入框的 disabled 狀態、元件狀態與「有沒有送出寫入類請求」，不打頁面文字。
"""
import pytest

pytest.importorskip("playwright.sync_api")

URL_TAIL = "/api/settings/email-notify"
SEL = "[data-testid=ns-base-url]"
DATA = "Alpine.$data(document.querySelector('[data-testid=ns-base-url]'))"


def _is_cfg_get(route):
    r = route.request
    return r.method == "GET" and r.url.split("?")[0].endswith(URL_TAIL)


def _open(live_server, make_user, new_page, login_as, name, handler):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1600})
    login_as(page, u)
    writes = []
    page.on("request", lambda req: writes.append((req.method, req.url)) if req.method in ("PUT", "POST") and "/api/settings/email-notify" in req.url else None)
    page.route("**/api/settings/email-notify*", handler)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.wait_for_function(f"() => !!document.querySelector('[data-es-fieldset]') && !!document.querySelector('{SEL}')", timeout=20000)
    return page, writes


@pytest.mark.e2e
def test_card_is_locked_until_the_settings_arrive_and_the_server_value_is_not_lost(live_server, make_user, new_page, login_as):
    from helpers.settings import _set_setting
    _set_setting("email_notify", {"base_url": "https://erp.server.example"})
    held = []

    def handler(route):
        if _is_cfg_get(route):
            held.append(route)                    # 壓住：先不放行，模擬回應很慢
        else:
            route.continue_()
    page, writes = _open(live_server, make_user, new_page, login_as, "es_lock1", handler)
    assert page.evaluate(f"() => {DATA}.cfgState") == "loading"
    assert page.locator("[data-es-fieldset]").evaluate("el => el.disabled") is True
    assert page.locator(SEL).is_disabled(), "讀回來之前輸入框不可編輯"
    with pytest.raises(Exception):
        page.fill(SEL, "https://typed-too-early.example", timeout=1500)         # 打不進去（不是「打進去再被蓋掉」）
    page.evaluate(f"() => {{ {DATA}.save(); {DATA}.testEmail(); {DATA}.wzSendTest(); {DATA}.wzActivate() }}")   # 直接叫函式也不送
    assert page.evaluate(f"() => [{DATA}.saving, {DATA}.testing, {DATA}.wz.sending, {DATA}.wz.activating]") == [False, False, False, False]
    assert writes == [], "還沒讀回來就送出寫入類請求"

    assert held, "GET 被壓住"
    held[0].continue_()
    page.wait_for_function(f"() => {DATA}.cfgState === 'ready'", timeout=20000)
    page.wait_for_function(f"() => !document.querySelector(\"{SEL}\").disabled", timeout=10000)
    assert page.locator("[data-es-fieldset]").evaluate("el => el.disabled") is False
    assert page.locator(SEL).input_value() == "https://erp.server.example", "伺服器上的系統網址不見了"
    assert writes == []


@pytest.mark.e2e
def test_a_failed_read_keeps_the_card_locked_and_never_puts_an_empty_form(live_server, make_user, new_page, login_as):
    from helpers.settings import _set_setting
    _set_setting("email_notify", {"base_url": "https://erp.server.example"})

    def handler(route):
        if _is_cfg_get(route):
            route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')
        else:
            route.continue_()
    page, writes = _open(live_server, make_user, new_page, login_as, "es_lock2", handler)
    page.wait_for_function(f"() => {DATA}.loaded === true", timeout=20000)
    assert page.evaluate(f"() => {DATA}.cfgState") == "error"
    assert page.locator("[data-es-fieldset]").evaluate("el => el.disabled") is True
    assert page.locator(SEL).is_disabled()
    assert page.locator("[data-es-load-error]").is_visible()
    page.evaluate(f"() => {{ {DATA}.save(); {DATA}.testEmail(); {DATA}.wzSendTest(); {DATA}.wzActivate() }}")
    assert page.evaluate(f"() => [{DATA}.saving, {DATA}.testing, {DATA}.wz.sending, {DATA}.wz.activating]") == [False, False, False, False]
    assert writes == [], "讀取失敗後不可送出任何寫入類請求"
    from helpers.settings import _get_setting
    assert (_get_setting("email_notify", {}) or {}).get("base_url") == "https://erp.server.example", "伺服器上的設定被改掉了"


@pytest.mark.e2e
def test_an_unparseable_response_is_an_error_not_a_blank_editable_form(live_server, make_user, new_page, login_as):
    def handler(route):
        if _is_cfg_get(route):
            route.fulfill(status=200, content_type="application/json", body="not json")
        else:
            route.continue_()
    page, writes = _open(live_server, make_user, new_page, login_as, "es_lock3", handler)
    page.wait_for_function(f"() => {DATA}.loaded === true", timeout=20000)
    assert page.evaluate(f"() => {DATA}.cfgState") == "error"
    assert page.locator(SEL).is_disabled()
    assert writes == []
