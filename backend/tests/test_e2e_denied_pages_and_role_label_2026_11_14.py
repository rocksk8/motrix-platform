# -*- coding: utf-8 -*-
"""T86 h3 最終複測 F2／F4。

F2：業務、財務直接開管理員網址（設定中心、職責角色）被 403 擋下後，頁面丟未捕捉的錯誤
    （settings-center 的 `Cannot set properties of null (setting 'hidden')`、duty-matrix 的「僅最高管理者可執行此操作」）。
    現在 0 個 pageerror，拒絕說明照常顯示。
F4：我的帳號頁的角色要顯示中文名稱（最高管理者／業務…），不是 superadmin／sales 這種內部代碼。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

from tests._e2e_login import inject_login  # noqa: E402

ADMIN_PAGES = ["/pages/settings-center.html", "/pages/duty-roles.html"]


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["sales", "finance"])
@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_non_admin_opening_admin_url_gets_denial_and_no_pageerror(live_server, make_user, new_context, role, path):
    u = make_user(username="den_%s_%s" % (role, path.split("/")[-1][:6]), role=role)
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + path)
    page.get_by_text("您沒有這個頁面的權限").first.wait_for(state="visible", timeout=15000)      # 拒絕說明照常顯示
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)          # 讓頁面自己的載入（被 403 的請求）跑完再看錯誤
    assert errs == [], "%s 有 pageerror：%s" % (path, errs)


@pytest.mark.e2e
@pytest.mark.parametrize("role,label", [("superadmin", "最高管理者"), ("sales", "業務"), ("finance", "財務")])
def test_my_account_shows_role_in_chinese(live_server, make_user, new_context, role, label):
    u = make_user(username="ra_%s" % role, role=role)
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/my-account.html")
    box = page.get_by_test_id("profile-role")
    box.wait_for(state="visible", timeout=15000)
    expect(box).to_have_text(label, timeout=10000)
