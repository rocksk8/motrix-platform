# -*- coding: utf-8 -*-
"""T86 U12：首頁「常用捷徑」——依角色排序、依模組權限過濾；沒權限的不出現。"""
import os

import pytest

pytest.importorskip("playwright.sync_api")


def _labels(page):
    sec = page.locator("[data-testid=home-shortcuts]")
    sec.wait_for(state="visible", timeout=20000)
    return [t.strip() for t in sec.locator(".h-short__t > span:first-child").all_inner_texts()]


def _shot(page, name):
    d = os.environ.get("U12_SHOTS_DIR")
    if d:
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name))


@pytest.mark.e2e
def test_sales_sees_own_order_and_only_permitted_shortcuts(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_u12_sales", role="sales", modules=["quotation", "case_manage", "dev_crm"])
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/index.html")
    assert _labels(page) == ["新增報價單", "業務開發", "案件管理", "報價單清單", "待我簽核"]
    assert page.locator("[data-testid=home-shortcut-reports]").count() == 0
    assert page.locator("[data-testid=home-shortcut-case] ").get_attribute("href") == "pages/case-management.html"
    _shot(page, "u12_home_sales_desktop.png")


@pytest.mark.e2e
def test_no_permission_means_no_shortcut(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_u12_fin", role="finance", modules=["finance", "reports"])
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/index.html")
    page.wait_for_selector("h1.h-hero__t", timeout=20000)
    assert _labels(page) == ["報表"]                       # 沒有 quotation／case_manage 模組 ⇒ 簽核、案件、報價都不出現
    for k in ("case", "approval", "quote-new", "quote-list", "dev-crm"):
        assert page.locator(f"[data-testid=home-shortcut-{k}]").count() == 0


@pytest.mark.e2e
def test_superadmin_sees_everything_and_mobile_has_no_hscroll(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_u12_boss", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/index.html")
    labels = _labels(page)
    assert labels[:4] == ["待我簽核", "案件管理", "報價單清單", "新增報價單"] and len(labels) == 6
    _shot(page, "u12_home_boss_desktop.png")
    page.set_viewport_size({"width": 390, "height": 900})
    page.wait_for_timeout(400)
    assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
    _shot(page, "u12_home_boss_mobile.png")
