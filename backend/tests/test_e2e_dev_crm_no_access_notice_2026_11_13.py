# -*- coding: utf-8 -*-
"""業務角色沒有「業務開發 CRM」模組時打開 dev-crm.html：以前靜默導回儀表板（UX 巡檢 hichan-7，2026-11-13），現在留在原頁並說明。
查證：sales 角色預設模組不含 dev_crm（helpers/module_registry.py），是逐人開啟的模組、選單入口也要 dev_crm 才出現 ⇒ 沒權限是設計，所以補說明而不是改權限。"""
import pytest

pytest.importorskip("playwright.sync_api")


def _open(live_server, make_user, new_page, login_as, name, **kw):
    user = make_user(username=name, **kw)
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.wait_for_timeout(2000)
    return page


@pytest.mark.e2e
def test_sales_without_the_module_gets_an_explanation_not_a_silent_redirect(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "e2e_dcrm_sales", role="sales")
    assert page.url.endswith("/pages/dev-crm.html"), "不可以悄悄導走：" + page.url
    box = page.locator('[data-testid="dev-crm-no-access"]')
    box.wait_for(state="visible", timeout=10000)
    text = box.inner_text()
    assert "沒有" in text and "使用者管理" in text and "回首頁" in text, text


@pytest.mark.e2e
@pytest.mark.parametrize("kw", [dict(role="sales", modules=["dev_crm"]), dict(role="admin")], ids=["sales+module", "admin"])
def test_people_with_access_see_the_page_not_the_notice(live_server, make_user, new_page, login_as, kw):
    page = _open(live_server, make_user, new_page, login_as, "e2e_dcrm_ok_" + kw["role"] + str(len(kw)), **kw)
    assert page.url.endswith("/pages/dev-crm.html"), page.url
    assert page.locator('[data-testid="dev-crm-no-access"]').count() == 0
