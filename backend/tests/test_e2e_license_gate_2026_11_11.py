# -*- coding: utf-8 -*-
"""授權閘門（瀏覽器）：被擋 ⇒ 導向「授權無法使用」說明頁（講原因與找誰、不是系統壞了）；靠緊急放行通行證撐著或裝的是
開發金鑰 ⇒ 所有頁面頂端橫幅。驗 DOM 終點（T80，使用者 2026-11-11 裁示）。後端行為見 test_licensing_emergency_2026_11_11.py。
"""
import datetime as _dt

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import license_alerts as la  # noqa: E402
from helpers import licensing as lic  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_alert_state():
    la._ALERTED.clear()
    yield
    la._ALERTED.clear()


def _login(make_user, new_page, login_as, name, role="admin"):
    user = make_user(username=name, role=role)
    page = new_page()
    login_as(page, tuple(user)[:2])
    return page


@pytest.mark.e2e
def test_blocked_license_lands_on_the_explanation_page_and_recovers(
        live_server, make_user, new_page, login_as, monkeypatch, tmp_path, license_test_key):
    page = _login(make_user, new_page, login_as, "e2e_lic_block", role="superadmin")   # 狀態／機器代碼只給最高管理者看（T83 L5）
    monkeypatch.setattr(lic, "LICENSE_PATH", str(tmp_path / "none" / "license.key"))          # 沒有授權金鑰
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/license-required.html", timeout=20000)
    box = page.locator("[data-license-required]")
    box.wait_for(state="visible", timeout=10000)
    page.locator("#lr-kv dd", has_text="missing").wait_for(state="visible", timeout=10000)
    text = box.inner_text()
    assert "尚未安裝授權金鑰" in page.locator("#lr-title").inner_text()
    assert "不是系統故障" in text and "系統供應商" in text                                       # 不是系統壞了＋找誰
    assert "狀態代碼" in text and "機器代碼" in text and license_test_key["machine"] in text    # 簽發方要的資料

    # 授權補上後按「重新檢查」⇒ 離開說明頁（不用重新登入）
    monkeypatch.setattr(lic, "LICENSE_PATH", license_test_key["path"])
    page.locator("#lr-retry").click()
    page.wait_for_url("**/index.html", timeout=20000)


@pytest.mark.e2e
def test_machine_mismatch_page_explains_the_hardware_change(
        live_server, make_user, new_page, login_as, monkeypatch):
    page = _login(make_user, new_page, login_as, "e2e_lic_mm", role="superadmin")
    monkeypatch.setattr(lic, "machine_fingerprint", lambda: "deadbeefdeadbeef")               # 硬體換了
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)                                      # 快取鍵不含指紋（正式機指紋是行程常數）；測試換指紋要清它
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/license-required.html", timeout=20000)
    page.locator("#lr-kv dd", has_text="machine_mismatch").wait_for(state="visible", timeout=10000)
    assert "不是發給這台機器的" in page.locator("#lr-title").inner_text()
    assert "主機板或網卡" in page.locator("[data-license-required]").inner_text()
    assert "deadbeefdeadbeef" in page.locator("#lr-kv").inner_text()


@pytest.mark.e2e
def test_emergency_pass_shows_a_banner_and_keeps_pages_usable(
        live_server, make_user, new_page, login_as, monkeypatch, tmp_path, license_test_key):
    d = tmp_path / "inst"
    d.mkdir()
    monkeypatch.setattr(lic, "LICENSE_PATH", str(d / "license.key"))
    today = _dt.date.today()
    (d / "license.key").write_text(lic.sign_license({
        "customer": "測試用公司", "tax_id": "00000000", "machine": license_test_key["machine"], "modules": ["*"],
        "issued": "2026-01-01", "expires": (today + _dt.timedelta(days=365)).isoformat()},
        license_test_key["priv_pem"]), encoding="utf-8")
    page = _login(make_user, new_page, login_as, "e2e_lic_pass")
    monkeypatch.setattr(lic, "machine_fingerprint", lambda: "deadbeefdeadbeef")               # 指紋漂移
    monkeypatch.setattr(lic, "_LICENSE_FILE_CACHE", None)                                      # 快取鍵不含指紋（正式機指紋是行程常數）；測試換指紋要清它
    (d / lic.EMERGENCY_FILE_NAME).write_text(lic.sign_license({
        "purpose": lic.EMERGENCY_PURPOSE, "tax_id": "00000000", "machine": license_test_key["machine"], "issued": today.isoformat(),
        "expires": (today + _dt.timedelta(days=5)).isoformat(), "reason": "e2e 換主機板"},
        license_test_key["priv_pem"]), encoding="utf-8")
    page.goto(f"{live_server}/pages/customers.html")
    banner = page.locator("#motrix-license-banner")
    banner.wait_for(state="visible", timeout=20000)
    assert banner.get_attribute("data-kind") == "emergency"
    assert "緊急放行通行證" in banner.inner_text()
    assert (today + _dt.timedelta(days=5)).isoformat() in banner.inner_text()
    assert page.url.endswith("/pages/customers.html")                                          # 沒被導走：功能照常

    # 通行證拿掉 ⇒ 下一個 /api 回應變 402 ⇒ 導向說明頁（證明橫幅與放行都來自通行證）
    (d / lic.EMERGENCY_FILE_NAME).unlink()
    page.reload()
    page.wait_for_url("**/license-required.html", timeout=20000)


@pytest.mark.e2e
def test_dev_signed_key_shows_a_banner_and_a_prod_key_does_not(
        live_server, make_user, new_page, login_as, monkeypatch, license_test_key):
    page = _login(make_user, new_page, login_as, "e2e_lic_dev")
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_load_state("networkidle")
    assert page.locator("#motrix-license-banner").count() == 0                                 # 正式金鑰：沒有橫幅

    monkeypatch.setattr(lic, "_PUBKEY_DEV", license_test_key["pub_pem"])                       # 同一把金鑰，改當成開發金鑰
    monkeypatch.setattr(lic, "_PUBKEY_PROD", b"")
    page.goto(f"{live_server}/pages/customers.html")
    banner = page.locator("#motrix-license-banner")
    banner.wait_for(state="visible", timeout=20000)
    assert banner.get_attribute("data-kind") == "dev_key" and "開發用授權金鑰" in banner.inner_text()
    assert page.url.endswith("/pages/customers.html")                                          # 只警告，不擋

    monkeypatch.setattr(lic, "_PUBKEY_DEV", b"-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAu7m0fiwC0aqhTBzZ5FkiYHqWK76JwmHgPdQbewYv50M=\n-----END PUBLIC KEY-----\n")
    monkeypatch.setattr(lic, "_PUBKEY_PROD", license_test_key["pub_pem"])                      # 換回正式金鑰 ⇒ 橫幅消失
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_load_state("networkidle")
    assert page.locator("#motrix-license-banner").count() == 0
