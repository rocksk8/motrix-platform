# -*- coding: utf-8 -*-
"""T86：全新安裝（沒有任何資料）的最高管理者開首頁與幾個「資料還沒回來／沒有資料」的頁面，不能有任何 pageerror。

起因：通知設定頁的 LINE 用量區塊在資料回來前 `quota` 是 null，Alpine 會連隱藏（x-show）區塊裡的 x-text／:style 一起算，
每次開頁丟 3 個「Cannot read properties of null」（checked_at／percent／used）。全站 89 頁掃過一遍，另外抓到匯入精靈（warnings／errors）
與標案雷達（辦公室地址、版面編輯器的 work）同型問題，一併修。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

PAGES = ["/index.html", "/pages/notification-settings.html", "/pages/import-wizard.html",
         "/pages/tender-radar.html", "/pages/system-hub.html"]


@pytest.mark.e2e
@pytest.mark.parametrize("path", PAGES)
def test_fresh_install_pages_have_no_pageerror(live_server, make_user, new_context, path, monkeypatch):
    from helpers import geo
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)      # 標案雷達開頁會由伺服器探測圖磚：測試不連外
    root = make_user(username="home_empty_root", role="superadmin")
    ctx = new_context(viewport={"width": 1440, "height": 900})
    ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=204))      # 標案雷達的地圖底圖：測試不連外
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, live_server, root[0], root[1])
    page.goto(live_server + path)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)          # 讓非同步載入（用量、清單）跑完再看
    assert errs == [], "%s 有 pageerror：%s" % (path, errs)


@pytest.mark.e2e
def test_line_quota_block_shows_neutral_state_when_there_is_no_data(live_server, make_user, new_context):
    root = make_user(username="home_empty_root2", role="superadmin")
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    # 用量端點讀不到（網路錯誤）⇒ 區塊顯示「尚無用量資料」，不丟錯
    page.route("**/api/settings/line-notify/quota*", lambda r: r.abort())
    inject_login(page, live_server, root[0], root[1])
    page.goto(live_server + "/pages/notification-settings.html")
    page.locator("[data-testid=line-quota-error]").filter(has_text="尚無用量資料").wait_for(state="visible", timeout=15000)
    assert errs == []
