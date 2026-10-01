# -*- coding: utf-8 -*-
"""建構器方案 B 的「掛載到內建頁面」欄位（作業資訊頁）：下拉列出已載入模組宣告的掛載點 ⇒ 選了就自動存草稿（mount.point／label）；
已存的目標若不存在 ⇒ 保留並標示（不悄悄清掉）；選回「不掛載」⇒ 草稿裡沒有 mount。斷言打在草稿的 DB 內容，不打畫面文字。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_p8_gaps_2026_09_26 import _builder_body, _draft, _h, _page, _put_draft, _publish  # noqa: E402

POINT = "daily_tasks.daily-tasks"
SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


@pytest.mark.e2e
def test_builder_mount_select_saves_the_target_and_label(live_server, make_user, new_context, client):
    admin = make_user(username="bb_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    _publish(client, h, "bb_mod", _builder_body("bb_mod"))
    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html?key=bb_mod")
    page.wait_for_selector('[data-testid="mb-mount-point"]')
    opts = page.eval_on_selector_all('[data-testid="mb-mount-point"] option', "els => els.map(e => e.value)")
    assert "" in opts and POINT in opts, opts                                           # 下拉列出已載入模組宣告的點
    assert page.locator("#mb-mount-label").count() == 0                                 # 沒選目標 ⇒ 不顯示頁籤文字欄
    page.select_option('[data-testid="mb-mount-point"]', POINT)
    page.fill("#mb-mount-label", "請款單")
    page.wait_for_function(SAVED)
    d = _draft("bb_mod")
    assert d["mount"] == {"point": POINT, "label": "請款單"}, d.get("mount")             # 該點沒有 context ⇒ 沒有 contextField 欄、值為空不存
    assert page.locator("#mb-mount-context").count() == 0
    assert client.post("/api/definitions/custom_module/bb_mod/publish", headers=h, json={}).status_code == 200      # 草稿能通過後端驗證並發布
    # 選回「不掛載」
    page.select_option('[data-testid="mb-mount-point"]', "")
    page.wait_for_function(SAVED)
    assert "mount" not in _draft("bb_mod")
    assert not errors, errors


@pytest.mark.e2e
def test_builder_keeps_and_flags_a_stale_mount_target(live_server, make_user, new_context, client):
    admin = make_user(username="bb2_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    body = _builder_body("bb_stale")
    body["mount"] = {"point": "gone_module.gone-point", "label": "舊目標"}
    _put_draft(client, h, "bb_stale", body)                                              # 草稿可存（驗證問題只在發布時擋）
    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html?key=bb_stale")
    page.wait_for_selector('[data-testid="mb-mount-point"]')
    assert page.input_value('[data-testid="mb-mount-point"]') == "gone_module.gone-point"      # 保留，不悄悄換掉
    assert page.locator('[data-testid="mb-mount-missing"]').is_visible()
    page.wait_for_timeout(1500)                                                          # 自動存檔窗口：不可把目標改掉
    assert _draft("bb_stale")["mount"]["point"] == "gone_module.gone-point"
    assert not errors, errors
