# -*- coding: utf-8 -*-
"""P8 總開關的前端（真瀏覽器）：builder_custom_modules.enabled 關著 ⇒ 模組建構器隱藏「建立」入口、直接帶新代號的網址也不進範本挑選；
既有模組清單照常能開啟；開著 ⇒ 建立入口出現。斷言打在畫面與伺服器狀態。"""
import pytest

pytest.importorskip("playwright.sync_api")

import db  # noqa: E402
from helpers import settings_registry as SR  # noqa: E402
from tests.test_e2e_p8_gaps_2026_09_26 import _builder_body, _h, _page, _publish, _q  # noqa: E402

pytestmark = pytest.mark.custom_switch_default


def _flag(on):
    c = db.get_db()
    try:
        SR.publish("builder_custom_modules", {"enabled": 1 if on else 0}, reason="t78", user="t78", conn=c)
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_builder_hides_create_entry_when_flag_off_but_opens_existing(live_server, make_user, new_context, client):
    admin = make_user(username="sw_e2e_admin", role="superadmin")
    h = _h(client, admin)
    _flag(True)
    _publish(client, h, "sw_exist", _builder_body("sw_exist"))
    _flag(False)

    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html")
    page.wait_for_selector('#mb-module-list[data-loaded="1"] tr[data-def-key="sw_exist"]')
    assert page.is_visible('[data-testid="mb-create-off"]')                    # 關著：說明在
    assert not page.is_visible('#mb-key') and not page.is_visible('#mb-open')  # 建立入口不見
    page.click('[data-open-module="sw_exist"]')                                # 既有模組照常能開
    page.wait_for_selector('#mb-pick', state='detached')
    assert "key=sw_exist" in page.url

    # 直接帶新代號的網址：不進範本挑選，顯示原因
    page2 = _page(new_context, live_server, admin, errors)
    page2.goto(live_server + "/pages/module-builder.html?key=sw_brand_new")
    page2.wait_for_selector('#mb-pick')
    assert not page2.is_visible('#mb-tpl-pick')
    assert "尚未開放建立" in page2.inner_text('#mb-pick')
    assert not _q("SELECT 1 FROM ui_definitions WHERE kind='custom_module' AND key='sw_brand_new'")      # 沒有留下任何草稿
    assert not errors, errors


@pytest.mark.e2e
def test_builder_shows_create_entry_when_flag_on(live_server, make_user, new_context, client):
    admin = make_user(username="sw_e2e_admin2", role="superadmin")
    _flag(True)
    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html")
    page.wait_for_selector('#mb-open', state='visible')
    assert not page.is_visible('[data-testid="mb-create-off"]')
    page.fill('#mb-key', 'sw_made')
    page.click('#mb-open')
    page.wait_for_selector('#mb-tpl-pick')                                      # 開著：照舊進範本挑選
    assert not errors, errors
