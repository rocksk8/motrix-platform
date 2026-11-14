# -*- coding: utf-8 -*-
"""使用狀況頁：非最高管理者看到說明，且不丟任何 pageerror（2026-11-14，h4 T86 回報）。

以前：側欄的「沒有權限」畫面（或頁面自己的 init()）在 Alpine 還沒處理完子節點時把 <main> 換掉，
已排進佇列的 x-show／x-text／x-for 對脫離文件的節點求值 ⇒ 一頁 19 個
「end/items/loadErr/members/online/showPaths/start/trail is not defined」。
現在：頁面本體包在 <template x-if="isSuper">，init() 對非授權者不動 DOM。
"""
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["admin", "user"])
def test_non_super_sees_denial_and_no_pageerror(live_server, make_user, new_page, login_as, role):
    user = make_user(username="e2e_osdeny_" + role, role=role)
    page = new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/online-stats.html")
    page.get_by_text("您沒有這個頁面的權限").first.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(1500)  # 讓 Alpine 把佇列裡的 effect 跑完再數
    assert not errs, "非最高管理者不該有任何 pageerror：%s" % errs
    assert page.locator('[data-testid="load-error"]').count() == 0
    assert page.locator('[data-testid="os-body"]').count() == 0, "頁面本體不該出現在非授權者畫面"


@pytest.mark.e2e
def test_superadmin_still_gets_the_page_and_no_pageerror(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_ossuper", role="superadmin")
    page = new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/online-stats.html")
    page.locator('[data-testid="os-body"]').wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(1000)
    assert not errs, errs
    assert page.get_by_text("您沒有這個頁面的權限").count() == 0
