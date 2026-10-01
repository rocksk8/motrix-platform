# -*- coding: utf-8 -*-
"""建構器首頁「刪除模組」e2e：取消不刪；無單據 ⇒ 確認後整個消失；有單據 ⇒ 第二次確認才連單據刪。
斷言打在伺服器狀態（DB）；等待一律等終點狀態。"""
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_p8_gaps_2026_09_26 import _builder_body, _h, _page, _publish, _q  # noqa: E402

OK, CANCEL, DLG = '[data-testid="ui-dialog-ok"]', '[data-testid="ui-dialog-cancel"]', '[data-testid="ui-dialog"]'
GONE = '#mb-module-list[data-loaded="1"]:not(:has(tr[data-def-key="%s"]))'


@pytest.mark.e2e
def test_builder_home_delete_module_button(live_server, make_user, new_context, client):
    admin = make_user(username="dm_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    _publish(client, h, "dm_empty", _builder_body("dm_empty"))
    _publish(client, h, "dm_used", _builder_body("dm_used"))
    r = client.post("/api/custom/dm_used/records", headers=h, json={"values": {"a": "x", "n": 1}})
    assert r.status_code == 200, r.text

    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html")
    page.wait_for_selector('#mb-module-list[data-loaded="1"] tr[data-def-key="dm_empty"]')

    page.click('[data-delete-module="dm_empty"]')           # 取消 ⇒ 不刪
    page.click(CANCEL)
    page.wait_for_selector(DLG, state="detached")
    assert _q("SELECT 1 FROM ui_definitions WHERE key='dm_empty'")

    page.click('[data-delete-module="dm_empty"]')           # 確認 ⇒ 消失
    page.click(OK)
    page.wait_for_selector(GONE % "dm_empty")
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key='dm_empty'")

    page.click('[data-delete-module="dm_used"]')            # 有單據：第一次確認 ⇒ 後端 409 ⇒ 第二次確認
    page.click(OK)
    page.wait_for_selector(DLG)
    page.click(CANCEL)                                       # 第二次取消 ⇒ 單據與模組都在
    page.wait_for_selector(DLG, state="detached")
    assert _q("SELECT COUNT(*) AS n FROM custom_records WHERE module_key='dm_used'")[0]["n"] == 1
    assert _q("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key='dm_used'")

    page.click('[data-delete-module="dm_used"]')
    page.click(OK)
    page.wait_for_selector(DLG)
    shot = os.environ.get("MB_DELETE_SHOT")
    if shot:
        page.screenshot(path=shot)
    page.click(OK)
    page.wait_for_selector(GONE % "dm_used")
    assert _q("SELECT COUNT(*) AS n FROM custom_records WHERE module_key='dm_used'")[0]["n"] == 0
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key='dm_used'")
    if shot:
        page.screenshot(path=shot.replace(".png", "_after.png"))
    assert not errors, errors
