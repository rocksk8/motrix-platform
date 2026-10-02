# -*- coding: utf-8 -*-
"""
反向控制（睡眠隱患修正，docs/platform/plans/E2E-SLEEP-HAZARD-AUDIT.md）：請求被扣住時，舊寫法（睡一下再看資料庫）假綠；新寫法（看頁面送出的請求）紅。
用 `test_e2e_quote_number_input` 的 `_watch_writes` 原樣；另有正對照（真的標紅時沒送請求＝綠）。
"""
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_quote_number_input_2026_09_24 import (  # noqa: E402,F401
    PRICE, _login, _open, _saved_item, _seed, _watch_writes)


@pytest.mark.e2e
def test_stuck_request_old_pattern_false_green_new_pattern_red(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rev1", role="superadmin")
    _seed()
    page = e2e_browser.new_page()
    _login(page, live_server, username, password)
    _open(page, live_server)
    held = []
    page.route("**/api/quotations/**", lambda route: held.append(route) if route.request.method in ("PUT", "PATCH", "POST") else route.continue_())
    page.fill(PRICE, "12,500")                                  # 有效值：頁面「確實會送出」存檔，我們把它扣在瀏覽器裡
    writes = _watch_writes(page)
    page.click('button:has-text("儲存草稿")')
    page.wait_for_timeout(1000)
    assert held, "前提：存檔請求確實送出並被扣住"
    time.sleep(0.2)
    assert _saved_item()["unitPrice"] == 1650                   # 舊寫法：只看資料庫 ⇒ 通過＝假綠（頁面其實送了存檔）
    assert writes != [], "新寫法看得到被扣住的請求"
    with pytest.raises(AssertionError):
        assert writes == [], "標紅時不可以送出任何存檔請求：%s" % writes   # d7 新斷言原文 ⇒ 紅


@pytest.mark.e2e
def test_real_red_field_sends_nothing_new_pattern_green(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rev2", role="superadmin")
    _seed()
    page = e2e_browser.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    _login(page, live_server, username, password)
    _open(page, live_server)
    page.fill(PRICE, "12a")
    writes = _watch_writes(page)
    page.click('button:has-text("儲存草稿")')
    page.wait_for_timeout(1500)
    assert any("無法辨識" in m for m in dialogs) and writes == []
