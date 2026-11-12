"""瀏覽器端對端：LINE 收件人粒度（角色＋個人）與額度用量條（2026-11-12）。

- 通知設定頁 LINE 卡：用量條常駐顯示（不必按「驗證 token」）、顏色隨門檻變、門檻欄位儲存（含錯誤輸入被擋）、
  每個類型的「可收角色」勾選會真的寫入（全勾＝缺省）；
- 帳號安全頁：已綁定的同仁看到「我要收的 LINE 通知」，只列公司已開啟且自己角色被允許的類型，取消勾選重新整理後仍然取消；
  角色被拿掉的類型從清單消失；未綁定只顯示提示。
對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import pytest

pytest.importorskip("playwright.sync_api")

EV = "approval_review_edit"
EV2 = "warranty_expiry"
UID = "U" + "c" * 32


@pytest.fixture()
def fake(monkeypatch):
    from helpers import line_notify, line_quota
    st = {"used": 40, "limit": 200}

    def _http(method, path, token, payload=None):
        if path.endswith("/quota/consumption"):
            return 200, {"totalUsage": st["used"]}
        if path.endswith("/quota"):
            return 200, {"type": "limited", "value": st["limit"]}
        return 200, {}

    monkeypatch.setattr(line_notify, "_http", _http)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    line_quota._mem["checked_at"] = None
    line_quota._pending = False
    return st


def _configure(events=True):
    from helpers.settings import _set_setting
    from helpers import line_quota
    # 額度快取在行程記憶體裡、活過這一題：前一題（含別的檔，例如心跳卡片 e2e 開了通知設定頁）留下的讀取失敗不能帶進來
    line_quota._mem.update(checked_at=None, failed_at=None, error="", fp=None)
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-quota-0123456789", "events": {EV: events, EV2: events},
                                 "public_base_url": "https://line.example.com", "login_channel_id": "1234567890",
                                 "login_channel_secret": "0123456789abcdef0123456789abcdef"})


def _open_settings(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('#line-panel input[id^=chk-line-ev-]').length >= 2", timeout=20000)
    return page


@pytest.mark.e2e
def test_quota_bar_is_always_shown_and_changes_color_with_thresholds(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_lq1")
    txt = page.locator("[data-testid=line-quota-text]")
    txt.wait_for(state="visible", timeout=10000)          # 沒按「驗證 token」就已經顯示
    assert "40 / 200" in txt.inner_text() and "20%" in txt.inner_text()
    ok_style = page.locator("[data-testid=line-quota-fill]").get_attribute("style")
    assert "width:20%" in ok_style.replace(" ", "")
    fake["used"] = 170
    page.locator("[data-testid=line-quota]").get_by_role("button", name="重新整理").click()
    page.wait_for_function("() => document.querySelector('[data-testid=line-quota-text]').innerText.includes('170 / 200')", timeout=10000)
    warn_style = page.locator("[data-testid=line-quota-fill]").get_attribute("style")
    assert warn_style != ok_style and "#B45309" in warn_style, "超過第一個門檻（80%）要變琥珀色"
    fake["used"] = 200
    page.locator("[data-testid=line-quota]").get_by_role("button", name="重新整理").click()
    page.wait_for_function("() => document.querySelector('[data-testid=line-quota-text]').innerText.includes('200 / 200')", timeout=10000)
    assert "var(--danger)" in page.locator("[data-testid=line-quota-fill]").get_attribute("style")


@pytest.mark.e2e
def test_quota_shows_reason_when_line_is_not_configured(live_server, make_user, new_page, login_as, fake):
    from helpers.settings import _set_setting
    _set_setting("line_notify", {})
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_lq2")
    err = page.locator("[data-testid=line-quota-error]")
    err.wait_for(state="visible", timeout=10000)
    page.wait_for_function("() => (document.querySelector('[data-testid=line-quota-error]').innerText || '').includes('token')", timeout=10000)   # 先出現「讀取中…」，等回應後才換成原因
    assert "token" in err.inner_text()


@pytest.mark.e2e
def test_threshold_field_saves_and_rejects_garbage(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_lq3")
    field = page.locator("#line-quota-th")
    assert field.input_value() == "80,100"
    field.fill("90, 50")
    page.locator("#line-panel").get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="LINE 設定已儲存").wait_for(state="visible", timeout=10000)
    page.reload()
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelector('#line-quota-th').value === '50,90'", timeout=10000)
    page.locator("#line-quota-th").fill("abc")
    page.locator("#line-panel").get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="整數百分比").wait_for(state="visible", timeout=10000)
    page.locator("#line-quota-th").fill("0,150")
    page.locator("#line-panel").get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="1～100").wait_for(state="visible", timeout=10000)
    from helpers import line_quota
    assert line_quota.thresholds() == [50, 90], "被擋的輸入不會寫入"


@pytest.mark.e2e
def test_role_checkboxes_write_through_and_all_checked_means_default(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_lq4")
    from helpers import line_recipients as lr
    box = lambda role: page.locator("[data-testid=line-role-%s-%s]" % (EV, role))          # noqa: E731
    page.locator("[data-testid=line-roles-%s]" % EV).wait_for(state="visible", timeout=10000)
    assert box("sales").is_checked() and box("viewer").is_checked(), "缺省＝所有角色都勾"
    box("viewer").uncheck()
    page.locator("[data-testid=line-msg]").filter(has_text="可收的角色").wait_for(state="visible", timeout=10000)
    assert "viewer" not in (lr.allowed_roles(EV) or []) and lr.allowed_roles(EV) is not None
    page.reload()
    page.locator("[data-testid=line-roles-%s]" % EV).wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => !document.querySelector('[data-testid=line-role-%s-viewer]').checked" % EV, timeout=10000)
    assert box("sales").is_checked() and not box("viewer").is_checked()
    assert page.locator("[data-testid=line-role-%s-viewer]" % EV2).is_checked(), "別的類型不受影響"
    box("viewer").check()
    from helpers.settings import _get_setting
    page.wait_for_function("() => document.querySelector('[data-testid=line-msg]') && document.querySelector('[data-testid=line-role-%s-viewer]').checked" % EV, timeout=10000)
    deadline = __import__("time").time() + 10
    while lr.allowed_roles(EV) is not None and __import__("time").time() < deadline:
        page.wait_for_timeout(200)
    assert lr.allowed_roles(EV) is None, "全部勾回來＝回到缺省（不留一份等同全選的清單）"
    assert EV not in (_get_setting("line_notify", {}).get("event_roles") or {})


@pytest.mark.e2e
def test_personal_prefs_on_account_security_page(live_server, make_user, new_page, login_as, fake):
    from helpers import line_notify, line_recipients as lr
    _configure()
    u = make_user(username="e2e_lq5", role="sales")
    line_notify.link_user("e2e_lq5", UID)
    page = new_page(viewport={"width": 1280, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/change-password.html")
    page.locator("[data-testid=line-prefs]").wait_for(state="visible", timeout=20000)
    cb = lambda k: page.locator("[data-testid=line-pref-%s]" % k)          # noqa: E731
    assert cb(EV).is_checked() and cb(EV2).is_checked(), "預設全收"
    cb(EV).uncheck()
    page.wait_for_function("() => document.querySelector('#line-bind-card').innerText.includes('已取消')", timeout=10000)
    assert lr.muted_events("e2e_lq5") == {EV}
    page.reload()
    page.locator("[data-testid=line-prefs]").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => !document.querySelector('[data-testid=line-pref-%s]').checked" % EV, timeout=10000)
    assert cb(EV2).is_checked()
    # 管理員把這個類型的角色拿掉 ⇒ 從個人清單消失
    line_notify.set_event_roles(EV2, ["admin"])
    page.reload()
    page.locator("[data-testid=line-prefs]").wait_for(state="visible", timeout=20000)
    assert page.locator("[data-testid=line-pref-%s]" % EV2).count() == 0 and cb(EV).count() == 1


@pytest.mark.e2e
def test_unlinked_user_sees_hint_not_checkboxes(live_server, make_user, new_page, login_as, fake):
    _configure()
    u = make_user(username="e2e_lq6", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/change-password.html")
    page.locator("[data-testid=line-prefs-need-link]").wait_for(state="visible", timeout=20000)
    assert page.locator("[data-testid=line-prefs]").is_visible() is False


@pytest.mark.e2e
def test_rapid_role_clicks_do_not_overwrite_each_other(live_server, make_user, new_page, login_as, fake):
    """K 審 F7：快速連點兩個角色，第二次不能拿舊清單蓋掉第一次（請求期間該列勾選會被鎖住）。"""
    _configure()
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_lq7")
    from helpers import line_recipients as lr
    page.locator("[data-testid=line-roles-%s]" % EV).wait_for(state="visible", timeout=10000)
    page.locator("[data-testid=line-role-%s-viewer]" % EV).click()
    page.locator("[data-testid=line-role-%s-finance]" % EV).click()          # 不等第一個回應
    deadline = __import__("time").time() + 10
    while (lr.allowed_roles(EV) is None or {"viewer", "finance"} & set(lr.allowed_roles(EV))) and __import__("time").time() < deadline:
        page.wait_for_timeout(200)
    got = lr.allowed_roles(EV)
    assert got is not None and "viewer" not in got and "finance" not in got, got
