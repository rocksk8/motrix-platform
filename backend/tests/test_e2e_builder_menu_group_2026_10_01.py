# -*- coding: utf-8 -*-
"""建構器「選單位置」：下拉列出主選單既有分組（來自 MOTRIX_MENU 宣告，不等側欄渲染）；選「我的工作」⇒ 模組成為該分組的選單項目。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_p8_gaps_2026_09_26 import _builder_body, _draft, _h, _page, _publish, _put_draft  # noqa: E402

SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


def _group_of(client, h, key):
    layout = client.get("/api/platform/menu", headers=h).json()["layout"]
    for g in layout["groups"]:
        for it in g["items"]:
            if it.get("custom") == key:
                return g["label"]
    return None


@pytest.mark.e2e
def test_builder_menu_group_picker_lists_existing_groups_and_places_module(live_server, make_user, new_context, client):
    admin = make_user(username="mg_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    body = _builder_body("mg_mod")
    body["menu"] = {"group": "自訂模組", "order": 10}
    _publish(client, h, "mg_mod", body)
    assert _group_of(client, h, "mg_mod") == "自訂模組"

    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html?key=mg_mod")
    page.wait_for_selector("#mb-menu-group")
    declared = page.evaluate("() => window.MOTRIX_MENU.groups.map(g => g.label)")
    opts = page.eval_on_selector_all("#mb-menu-group option", "els => els.map(e => e.value)")
    assert "我的工作" in declared
    assert set(declared) <= set(opts) and "自訂模組" in opts, (declared, opts)
    assert page.is_hidden("#mb-menu-group-missing")

    page.select_option("#mb-menu-group", "我的工作")
    page.wait_for_function(SAVED)
    assert _draft("mg_mod")["menu"]["group"] == "我的工作"
    assert client.post("/api/definitions/custom_module/mg_mod/publish", json={}, headers=h).status_code == 200
    assert _group_of(client, h, "mg_mod") == "我的工作"          # 併進既有分組、不另開
    assert not [g for g in client.get("/api/platform/menu", headers=h).json()["layout"]["groups"] if g["label"] == "自訂模組"]
    assert not errors, errors


@pytest.mark.e2e
def test_builder_menu_group_missing_is_kept_and_flagged(live_server, make_user, new_context, client):
    admin = make_user(username="mg2_admin", role="superadmin")
    make_user(username="p8g_b_mgr", role="viewer", modules=[])
    h = _h(client, admin)
    body = _builder_body("mg_gone")
    body["menu"] = {"group": "已不存在的分組", "order": 10}
    _put_draft(client, h, "mg_gone", body)          # 只有草稿：沒有已發布模組用到這個分組名稱
    errors = []
    page = _page(new_context, live_server, admin, errors)
    page.goto(live_server + "/pages/module-builder.html?key=mg_gone")
    page.wait_for_selector("#mb-menu-group")
    assert page.input_value("#mb-menu-group") == "已不存在的分組"
    assert page.is_visible("#mb-menu-group-missing")
    assert not errors, errors
