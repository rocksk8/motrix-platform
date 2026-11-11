# -*- coding: utf-8 -*-
"""公司設定頁不再用 404 當 Passkey 開關（2026-11-11，正式機綜合評估：webauthn-config 404 共 32 次）。

根因：company-profile-settings.html 每次載入都打 `GET /api/settings/webauthn-config`，
並把「回 404」當成「Passkey 功能已停用」的訊號——停用是常態（PASSKEY_ENABLED=False），
所以每開一次頁面就多一筆 404。開關訊號本來就有專用的公開端點
`/api/system/webauthn-config-status`（login／change-password 都用它，永遠 200）。

守門：
① 停用態：開頁面後不得出現任何對 `/api/settings/webauthn-config` 的請求（也就不會有 404），
   Passkey 卡片不顯示，頁面其他區塊照常。（舊程式碼這題會紅：它一定會打那支。）
② 啟用態（反向驗證）：開關打開後卡片要出現、設定端點要被讀、回 200。
   沒有這題，①只證明「頁面不再打了」，分不出「卡片整個壞掉再也讀不到設定」。
"""
import pytest

pytest.importorskip("playwright.sync_api")

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
CFG = "/api/settings/webauthn-config"
STATUS = "/api/system/webauthn-config-status"


def _open(page, live_server):
    seen = []   # (method, path, status)
    page.on("response", lambda r: seen.append((r.request.method, r.url.split("?")[0], r.status)))
    page.goto(live_server + "/pages/company-profile-settings.html")
    # 終點：載入流程（含 loadWebauthnConfig）跑完＝status 端點已回來
    page.wait_for_function("() => performance.getEntriesByType('resource')"
                           ".some(e => e.name.includes('/api/system/webauthn-config-status'))", timeout=20000)
    page.wait_for_function(f"() => {ROOT}.isSuperadmin === true", timeout=20000)
    page.wait_for_load_state("networkidle")
    return seen


@pytest.mark.e2e
def test_disabled_passkey_page_does_not_call_webauthn_config(live_server, make_user, new_page, login_as):
    u = make_user(username="wa404_off", role="superadmin")
    page = new_page()
    login_as(page, u)
    seen = _open(page, live_server)
    cfg_calls = [s for s in seen if s[1].endswith(CFG)]
    assert not cfg_calls, f"停用態不該呼叫 webauthn-config，卻有：{cfg_calls}"
    assert any(s[1].endswith(STATUS) and s[2] == 200 for s in seen), "沒有向 status 端點確認開關"
    assert page.evaluate(f"() => {ROOT}.passkeyFeatureEnabled") is False
    assert page.locator("text=Passkey / WebAuthn 網域設定").is_hidden()
    # 頁面其他區塊沒被連帶弄壞：頁面載入中沒有任何 4xx／5xx（Passkey 以外也一併守住）
    bad = [s for s in seen if s[2] >= 400 and "/api/" in s[1]]
    assert not bad, f"載入公司設定頁時有 API 回錯誤：{bad}"


@pytest.mark.e2e
def test_enabled_passkey_page_shows_card_and_reads_config(live_server, make_user, new_page, login_as, monkeypatch):
    import helpers.auth
    monkeypatch.setattr(helpers.auth, "PASSKEY_ENABLED", True)
    u = make_user(username="wa404_on", role="superadmin")
    page = new_page()
    login_as(page, u)
    seen = _open(page, live_server)
    page.wait_for_function(f"() => {ROOT}.passkeyFeatureEnabled === true", timeout=20000)
    assert any(s[1].endswith(CFG) and s[2] == 200 for s in seen), f"啟用態沒有讀到設定：{seen}"
    page.locator("text=Passkey / WebAuthn 網域設定").wait_for(state="visible", timeout=10000)
