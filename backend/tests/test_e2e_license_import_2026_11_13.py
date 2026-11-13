# -*- coding: utf-8 -*-
"""授權匯入（瀏覽器；T83）：驗 DOM 終點——授權失效時最高管理者從說明頁走到授權頁、選檔、預覽、確認、系統恢復；
一般管理者看不到入口；快到期的橫幅。後端行為與邊界見 test_license_import_2026_11_13.py。
"""
import datetime as _dt
import os

import pytest

pytest.importorskip("playwright.sync_api")

from conftest import TEST_LICENSE_MACHINE  # noqa: E402
from helpers import licensing as lic  # noqa: E402


def _in(days):
    return (_dt.date.today() + _dt.timedelta(days=days)).isoformat()


@pytest.fixture()
def lic_dir(monkeypatch, tmp_path):
    d = tmp_path / "inst"
    d.mkdir()
    monkeypatch.setattr(lic, "LICENSE_PATH", str(d / "license.key"))
    lic._LICENSE_FILE_CACHE = None
    yield d
    lic._LICENSE_FILE_CACHE = None


@pytest.fixture()
def sign(license_test_key):
    def _sign(**o):
        p = {"customer": "測試用公司", "tax_id": "00000000", "machine": TEST_LICENSE_MACHINE, "modules": ["*"],
             "issued": "2026-01-01", "expires": _in(365), "kind": lic.LICENSE_KIND_SUBSCRIPTION}
        p.update(o)
        return lic.sign_license(p, license_test_key["priv_pem"])
    return _sign


def _put(lic_dir, blob):
    (lic_dir / "license.key").write_text(blob, encoding="utf-8")
    lic._LICENSE_FILE_CACHE = None


@pytest.mark.e2e
def test_superadmin_rescues_a_blocked_system_from_the_explanation_page(
        live_server, make_user, new_page, login_as, lic_dir, sign):
    _put(lic_dir, sign())
    su = make_user(username="e2e_import_su", role="superadmin")
    page = new_page()
    login_as(page, tuple(su)[:2])
    os.remove(lic_dir / "license.key")                                  # 授權消失
    lic._LICENSE_FILE_CACHE = None
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/license-required.html", timeout=20000)
    link = page.locator("#lr-import")
    link.wait_for(state="visible", timeout=10000)                       # 最高管理者看得到
    assert "前往授權頁匯入" in link.inner_text()
    link.click()
    page.wait_for_url("**/license-settings.html", timeout=20000)        # 授權頁沒有被 402 導走

    page.locator("#ls-headline").filter(has_text="尚未安裝授權").wait_for(state="visible", timeout=10000)
    assert page.locator("#ls-machine-code").text_content() == TEST_LICENSE_MACHINE      # 申請授權要提供的機器代碼

    # 選一個「給別台電腦」的檔 ⇒ 白話原因、沒有確認按鈕
    bad = lic_dir.parent / "wrong_machine.key"
    bad.write_text(sign(machine="0123456789abcdef"), encoding="utf-8")
    page.set_input_files("#ls-file", str(bad))
    page.locator("#ls-result").filter(has_text="給另一台電腦").wait_for(state="visible", timeout=10000)
    assert page.locator("#ls-confirm-row").is_hidden()

    # 選正確的檔 ⇒ 預覽 → 確認更換 → 成功
    good = lic_dir.parent / "good.key"
    good.write_text(sign(customer="匯入成功股份有限公司", expires=_in(500)), encoding="utf-8")
    page.set_input_files("#ls-file", str(good))
    page.locator("#ls-result").filter(has_text="這份授權可以使用").wait_for(state="visible", timeout=10000)
    assert "匯入成功股份有限公司" in page.locator("#ls-result").inner_text()
    assert not (lic_dir / "license.key").exists()                       # 預覽不寫任何東西
    page.locator("#ls-apply").click()
    page.locator("#ls-result").filter(has_text="已更換成新的授權").wait_for(state="visible", timeout=10000)
    page.locator("#ls-kv dd", has_text="匯入成功股份有限公司").wait_for(state="visible", timeout=10000)
    assert page.locator("#ls-status").get_attribute("data-level") == "ok"
    assert (lic_dir / "license.key").exists()

    # 系統恢復：同一個 session、不用重新登入
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_load_state("networkidle")
    assert "license-required" not in page.url


@pytest.mark.e2e
def test_admin_does_not_see_the_import_link_and_is_refused_by_the_page(
        live_server, make_user, new_page, login_as, lic_dir, sign):
    _put(lic_dir, sign())
    ad = make_user(username="e2e_import_admin", role="admin")
    page = new_page()
    login_as(page, tuple(ad)[:2])
    os.remove(lic_dir / "license.key")
    lic._LICENSE_FILE_CACHE = None
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/license-required.html", timeout=20000)
    page.locator("#lr-title").filter(has_text="系統暫時無法使用").wait_for(state="visible", timeout=10000)
    text = page.locator("[data-license-required]").inner_text()
    assert "請聯絡您的系統管理員" in text                                  # 其他角色：只有這一句
    for leaked in ("狀態代碼", "機器代碼", "missing", "授權到期日", "供應商"):
        assert leaked not in text, leaked
    assert page.locator("#lr-kv dd").count() == 0
    assert page.locator("#lr-import").is_hidden()
    page.goto(f"{live_server}/pages/license-settings.html")             # 手打網址進授權頁
    page.locator("#ls-denied").wait_for(state="visible", timeout=10000)
    assert "最高管理者" in page.locator("#ls-denied").inner_text()
    assert page.locator("#ls-main").is_hidden()


@pytest.mark.e2e
def test_expiring_license_shows_a_banner_with_a_link_for_superadmin_only(
        live_server, make_user, new_page, login_as, lic_dir, sign):
    _put(lic_dir, sign(expires=_in(5)))
    su = make_user(username="e2e_exp_su", role="superadmin")
    ad = make_user(username="e2e_exp_admin", role="admin")
    p1 = new_page()
    login_as(p1, tuple(su)[:2])
    p1.goto(f"{live_server}/pages/customers.html")
    b1 = p1.locator("#motrix-license-expiry-banner")
    b1.wait_for(state="visible", timeout=20000)
    assert "5 天後到期" in b1.inner_text() and b1.get_attribute("data-level") == "critical"
    assert b1.locator("a", has_text="前往授權頁").count() == 1
    p2 = new_page()
    login_as(p2, tuple(ad)[:2])
    p2.goto(f"{live_server}/pages/customers.html")
    p2.wait_for_load_state("networkidle")
    assert p2.locator("#motrix-license-expiry-banner").count() == 0        # 一般管理者：看不到剩幾天（T83 L5）
    assert "天後到期" not in p2.locator("body").inner_text()

    _put(lic_dir, sign(expires=_in(200)))                                 # 續約之後下一個請求就沒有橫幅
    p1.goto(f"{live_server}/pages/customers.html")
    p1.wait_for_load_state("networkidle")
    assert p1.locator("#motrix-license-expiry-banner").count() == 0
