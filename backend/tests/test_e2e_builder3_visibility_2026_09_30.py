# -*- coding: utf-8 -*-
"""建構器第三輪 S3 — 「誰看得到」面板（畫面＋DB）：欄位的可見角色／人員與選單的可見角色／人員，落到草稿；
全部取消勾選 ⇒ 拿掉鍵（回到所有人）；必填欄位設成受限 ⇒ 標出問題；角色清單來自目錄（不寫死在頁面）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._builder_nav import go_step, start_blank  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


def _draft(key):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft' "
                         "ORDER BY rowid DESC LIMIT 1", (key,)).fetchone()
        return json.loads(r["body_json"]) if r else None
    finally:
        conn.close()


@pytest.mark.e2e
def test_field_and_menu_visibility_panels_land_in_the_draft(live_server, make_user, new_context):
    boss = make_user(username="b3v_boss", role="superadmin")
    make_user(username="b3v_amy", role="user")
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/module-builder.html")
    start_blank(page, "b3v_mod")
    # 選單可見（作業資訊頁籤）
    assert page.locator('[data-vis="menu"] [data-vis-role]').count() == 5                 # 角色清單來自目錄
    assert "所有人" in page.locator('[data-vis="menu"] [data-vis-summary]').inner_text()
    page.check('[data-vis="menu"] [data-vis-role="admin"]')
    page.locator('[data-vis="menu"] summary').click()
    page.check('[data-vis="menu"] [data-vis-user="b3v_amy"]')
    page.wait_for_function(SAVED, timeout=15000)
    assert _draft("b3v_mod")["menu"]["visibleTo"] == {"roles": ["admin"], "users": ["b3v_amy"]}
    assert "限：" in page.locator('[data-vis="menu"] [data-vis-summary]').inner_text()
    page.uncheck('[data-vis="menu"] [data-vis-role="admin"]')
    page.uncheck('[data-vis="menu"] [data-vis-user="b3v_amy"]')
    page.wait_for_function(SAVED, timeout=15000)
    assert "visibleTo" not in _draft("b3v_mod")["menu"]                                    # 全取消 ⇒ 拿掉鍵（回到所有人）
    # 欄位可見（表單設計頁籤）
    go_step(page, 2)
    page.click('#mb-palette [data-palette-element="number"]')
    page.wait_for_selector('#mb-props-pane [data-vis="field"]')
    page.check('#mb-props-pane [data-vis="field"] [data-vis-role="sales"]')
    page.fill("#mb-f-label", "成本")
    page.wait_for_function(SAVED, timeout=15000)
    f = _draft("b3v_mod")["fields"][0]
    assert f["access"] == {"visibleTo": {"roles": ["sales"], "users": []}}
    # 必填＋受限 ⇒ 問題（發布驗證會擋）
    page.check('.mb-fc[data-field-key="field_1"] [data-quick-required]')
    page.wait_for_function(SAVED, timeout=15000)
    page.wait_for_selector('.mb-fc[data-field-key="field_1"].is-bad', timeout=10000)          # 卡片標紅
    page.wait_for_function("() => document.querySelector('.mb-tab[data-tab=form]').dataset.hasProblems === '1'")
    page.click('.mb-tab[data-tab="form"]')
    page.click('.mb-fc[data-field-key="field_1"]')
    page.uncheck('#mb-props-pane [data-vis="field"] [data-vis-role="sales"]')
    page.wait_for_function(SAVED, timeout=15000)
    assert "access" not in _draft("b3v_mod")["fields"][0]                                  # 取消 ⇒ 連 access 一併拿掉
    page.wait_for_selector('.mb-fc[data-field-key="field_1"].is-bad', state="detached", timeout=10000)   # 問題跟著消失（反向控制）
    assert not errors, errors
