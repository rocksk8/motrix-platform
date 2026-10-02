# -*- coding: utf-8 -*-
"""c7 對 wip/t32-sleep-fix-d7 的審查探針（反向控制）：請求被扣住時，舊寫法（睡一下再看資料庫）假綠；d7 的新寫法（看請求）紅。
用 d7 的 `_watch_writes`／`_wait_dialog` 原樣。不隨產品出貨；可併入 d7 的修正當正式反向控制。"""
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
