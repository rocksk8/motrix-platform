# -*- coding: utf-8 -*-
"""第 53 班 P0：刪除暫存區頁面（瀏覽器）——最高管理者看得到列表、詳情（敏感欄位遮罩）、還原、永久刪除（二次確認）；一般管理員打不開資料。
合成單據與 adapter 沿用 test_recyclebin_p0_t53（in-process 伺服器讀同一份 registry）。"""
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from modules.recyclebin.tests.test_recyclebin_p0_t53 import ET, _abs, _delete, _doc, env  # noqa: E402,F401  (env 是 autouse fixture)


@pytest.mark.e2e
def test_superadmin_sees_masks_restores_and_purges(live_server, make_user, new_context):
    boss = make_user(username="rb_e2e_boss", role="superadmin", modules=[])
    rels = _doc("E1")
    _doc("E2", nfiles=0)
    r1 = _delete("E1", {"username": "someone", "display_name": "某人", "role": "admin"})
    r2 = _delete("E2", {"username": "someone", "display_name": "某人", "role": "admin"})
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, boss[0], boss[1])

    page.goto(live_server + "/pages/recycle-bin.html")
    page.wait_for_selector('[data-testid="rb-row-%d"]' % r1["bin_id"], timeout=15000)
    assert page.locator('[data-testid="rb-row-%d"]' % r2["bin_id"]).count() == 1
    assert "30" in page.locator('[data-testid="rb-status"]').inner_text()
    assert not page.locator('[data-testid="rb-no-types"]').is_visible()      # 合成 adapter 已登記 ⇒ 有可選類型

    # 詳情：敏感欄位遮罩、非敏感照顯示
    page.click('[data-testid="rb-detail-%d"]' % r1["bin_id"])
    page.wait_for_selector('[data-testid="rb-snapshot"]', state="visible", timeout=10000)
    snap = page.locator('[data-testid="rb-snapshot"]').inner_text()
    assert "012345678901" not in snap and "＊＊＊" in snap and "王小明" in snap
    page.click('[data-testid="rb-detail-close"]')
    page.wait_for_selector('[data-testid="rb-detail-modal"]', state="hidden", timeout=5000)

    # 還原：資料與附件回來、列表少一筆
    page.click('[data-testid="rb-restore-%d"]' % r1["bin_id"])
    page.wait_for_selector('[data-testid="rb-msg"]', state="visible", timeout=15000)
    page.wait_for_selector('[data-testid="rb-row-%d"]' % r1["bin_id"], state="detached", timeout=10000)
    assert all(os.path.exists(_abs(x)) for x in rels)

    # 永久刪除：沒輸入確認字不能按；輸入後才刪
    page.click('[data-testid="rb-purge-%d"]' % r2["bin_id"])
    page.wait_for_selector('[data-testid="rb-purge-modal"]', state="visible", timeout=5000)
    assert page.locator('[data-testid="rb-purge-go"]').is_disabled()
    page.fill('[data-testid="rb-purge-input"]', "永久刪除")
    page.click('[data-testid="rb-purge-go"]')
    page.wait_for_selector('[data-testid="rb-row-%d"]' % r2["bin_id"], state="detached", timeout=10000)
    page.select_option('[data-testid="rb-status-filter"]', "purged")
    page.wait_for_selector('[data-testid="rb-row-%d"]' % r2["bin_id"], timeout=10000)      # 墓碑列：狀態 purged
    assert not errors, errors


@pytest.mark.e2e
def test_plain_admin_gets_an_error_and_no_data(live_server, make_user, new_context):
    adm = make_user(username="rb_e2e_admin", role="admin", modules=[])
    _doc("E3")
    _delete("E3", {"username": "someone", "role": "admin"})
    page = new_context().new_page()
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/recycle-bin.html")
    # 一般管理員：平台的權限頁（選單 perm=superadmin）取代頁面內容——**不可以**看到任何暫存區資料
    page.wait_for_selector("text=你沒有這個頁面的權限", timeout=15000)
    assert page.locator('[data-testid^="rb-row-"]').count() == 0
    assert "E3" not in page.locator("body").inner_text()
