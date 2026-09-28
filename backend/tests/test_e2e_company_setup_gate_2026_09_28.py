# -*- coding: utf-8 -*-
"""本公司資料設定閘門（瀏覽器）：未設定 ⇒ 最高管理員導向設定頁、在那裡確認後功能開放；其他人導向說明頁；
判定失敗與暫時放行 ⇒ 所有頁面頂端橫幅（COMPANY-SETUP-GATE §3.6、§4.2）。驗 DOM／資料庫終點。
"""
import json
from datetime import datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import company_setup as cs  # noqa: E402
from tests.test_company_setup_core_2026_09_28 import make_ubn  # noqa: E402

pytestmark = [pytest.mark.company_gate]

UBN = make_ubn("3456780")


@pytest.fixture(autouse=True)
def _fresh():
    cs.reset_cache()
    yield
    cs.reset_cache()


def _profile(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.put("/api/settings/company-profile", json={
        "name": "測試丙股份有限公司", "tax_id": UBN, "contact_info": "Tel: 02-2222-3333"}, headers=h).status_code == 200


@pytest.mark.e2e
def test_superadmin_is_sent_to_settings_confirms_and_gets_in(client, live_server, make_user, new_page, login_as):
    boss = make_user(username="e2e_cs_boss", role="superadmin")
    _profile(client, boss)                                               # 欄位填好但沒按確認
    page = new_page()
    login_as(page, tuple(boss)[:2])
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/company-profile-settings.html?setup=1", timeout=20000)
    card = page.locator("[data-company-setup-card]")
    card.wait_for(state="visible", timeout=10000)
    assert "尚未確認" in page.locator("[data-company-setup-reason]").inner_text()
    btn = page.locator("[data-company-setup-confirm]")
    assert btn.is_disabled()                                             # 沒勾「以上為本公司資料」不可按
    page.locator("[data-company-setup-ack]").check()
    with page.expect_response(lambda r: "/api/settings/company-profile" in r.url and r.request.method == "PUT"):
        btn.click()
    card.wait_for(state="hidden", timeout=10000)
    import db
    conn = db.get_db()
    try:
        assert cs.status(conn)["configured"] is True
    finally:
        conn.close()
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_load_state("networkidle")
    assert page.url.endswith("/pages/customers.html")                    # 不再被導走


@pytest.mark.e2e
def test_non_admin_sees_the_explanation_page(live_server, make_user, new_page, login_as):
    clerk = make_user(username="e2e_cs_clerk", role="admin")
    page = new_page()
    login_as(page, tuple(clerk)[:2])
    page.goto(f"{live_server}/pages/customers.html")
    page.wait_for_url("**/company-setup-required.html", timeout=20000)
    box = page.locator("[data-company-setup-required]")
    box.wait_for(state="visible", timeout=10000)
    assert "請最高管理員先到「公司資料設定」確認本公司資料" in box.inner_text()
    assert "暫時放行" in box.inner_text()                                # 最高管理員不在時的處置（CG-S5）


@pytest.mark.e2e
def test_status_error_shows_the_banner_and_keeps_pages_usable(live_server, make_user, new_page, login_as, monkeypatch):
    clerk = make_user(username="e2e_cs_err", role="admin")
    monkeypatch.setattr(cs, "status", lambda conn, root=None, now=None: (_ for _ in ()).throw(RuntimeError("boom")))
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_group_emails", lambda key: [])
    page = new_page()
    login_as(page, tuple(clerk)[:2])
    page.goto(f"{live_server}/pages/customers.html")
    banner = page.locator("#motrix-company-setup-banner")
    banner.wait_for(state="visible", timeout=20000)
    assert banner.inner_text() == "本公司設定狀態無法判定，對外文件暫停輸出，請聯絡管理員"
    assert page.url.endswith("/pages/customers.html")                    # 一般功能照常（Q7＝C）


@pytest.mark.e2e
def test_grace_banner(live_server, make_user, new_page, login_as):
    clerk = make_user(username="e2e_cs_grace", role="admin")
    cs.ensure_install_id()
    now = datetime.now()
    with open(cs._files()[2], "w", encoding="utf-8") as f:
        json.dump({"created": now.isoformat(), "until": (now + timedelta(hours=1)).isoformat(),
                   "reason": "測試", "install": cs.install_hash()}, f)
    try:
        page = new_page()
        login_as(page, tuple(clerk)[:2])
        page.goto(f"{live_server}/pages/customers.html")
        banner = page.locator("#motrix-company-setup-banner")
        banner.wait_for(state="visible", timeout=20000)
        assert "暫時放行" in banner.inner_text() and banner.get_attribute("data-kind") == "grace"
    finally:
        import os
        os.remove(cs._files()[2])
