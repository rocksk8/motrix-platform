# -*- coding: utf-8 -*-
"""模組建構器拖曳式、縮圖化（docs/platform/BUILDER-UX.md §6-2；使用者裁示「欄位階段就已經有預覽，用拖曳拉 icon 跟文字…更為簡易」）。

斷言打在畫面（DOM）與伺服器狀態（草稿存在定義庫：ui_definitions kind=custom_module status=draft），不讀 Alpine 模型（§G5 #9）；
等待一律等終點（草稿存檔完成：#mb-save-state 的 data-dirty／saving／state），不用 sleep。
既有 test_e2e_p8_module_builder／test_e2e_p8_gaps 不改題（BUILDER-UX §5）。
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

KEY = "dnd_probe"
SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""
PREVIEW_JS = Path(__file__).resolve().parents[2] / "frontend" / "static" / "form-preview.js"


def _draft():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft' "
                         "ORDER BY rowid DESC LIMIT 1", (KEY,)).fetchone()
        return json.loads(r["body_json"]) if r else None
    finally:
        conn.close()


def _open(new_context, base, make_user, name):
    user = make_user(username=name, role="superadmin")
    ctx = new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/module-builder.html")
    page.fill("#mb-key", KEY)
    page.click("#mb-open")
    page.wait_for_selector("#mb-step-1", state="visible")
    page.click('.mb-step[data-step="2"]')
    page.wait_for_selector("#mb-step-2", state="visible")
    return page, errors


def _saved(page):
    page.wait_for_function(SAVED, timeout=15000)


def _keys():
    return [f["key"] for f in (_draft() or {}).get("fields", [])]


@pytest.mark.e2e
def test_palette_is_icon_and_text_for_every_catalog_type_and_enter_adds(live_server, make_user, new_context, client):
    """工具列＝catalog 的每個型別一格：有 icon（svg）＋文字；聚焦後按 Enter ⇒ 加到最後（鍵盤替代拖曳）。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_pal")
    types = page.evaluate("() => [...document.querySelectorAll('#mb-palette [data-palette-type]')].map(b => b.dataset.paletteType)")
    u, pw = make_user(username="dnd_pal_api", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    catalog = client.get("/api/custom-modules/catalog", headers={"Authorization": "Bearer " + tok}).json()
    assert types == catalog["fieldTypes"], (types, catalog["fieldTypes"])     # 只來自 catalog，順序照舊
    for t in types:
        btn = page.locator('#mb-palette [data-palette-type="%s"]' % t)
        assert btn.locator("svg").count() == 1, "型別 %s 沒有 icon" % t
        assert btn.inner_text().strip(), "型別 %s 沒有文字" % t
    page.locator('#mb-palette [data-palette-type="date"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_selector('.mb-fc[data-field-index="0"]')
    _saved(page)
    assert [f["type"] for f in _draft()["fields"]] == ["date"]
    assert not errors, errors


@pytest.mark.e2e
def test_keyboard_reorders_and_deletes_with_focus_following_the_card(live_server, make_user, new_context):
    """Alt＋↑ 移動 ⇒ 草稿 DB 的欄位順序跟著變，焦點跟著卡片、aria-live 念出新位置；Delete ⇒ 確認後刪除。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_kb")
    for t in ("text", "number", "date"):
        page.click('#mb-palette [data-palette-type="%s"]' % t)
    page.wait_for_selector('.mb-fc[data-field-index="2"]')
    _saved(page)
    before = _keys()
    assert len(before) == 3, before
    page.locator('.mb-fc[data-field-index="2"]').focus()
    page.keyboard.press("Alt+ArrowUp")
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.fieldIndex === '1'")
    page.wait_for_function("() => (document.getElementById('mb-live').textContent || '').includes('移到第 2 個')")
    _saved(page)
    assert _keys() == [before[0], before[2], before[1]]
    page.keyboard.press("Delete")
    page.locator('[data-testid="ui-dialog-ok"]').click()
    page.wait_for_function("() => document.querySelectorAll('#mb-canvas .mb-fc').length === 2")
    _saved(page)
    assert _keys() == [before[0], before[1]]
    assert not errors, errors


@pytest.mark.e2e
def test_in_place_label_and_required_land_in_the_draft(live_server, make_user, new_context):
    """選中的卡片就地改標籤與必填（#mb-f-*，id 不變）；沒選中的卡片用「必填」勾選 ⇒ 草稿 DB 是布林。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_inline")
    page.click('#mb-palette [data-palette-type="text"]')
    page.click('#mb-palette [data-palette-type="number"]')
    page.click('.mb-fc[data-field-index="0"]')
    page.wait_for_selector('.mb-fc[data-field-index="0"] #mb-f-label')
    page.fill("#mb-f-label", "設備名稱")
    page.select_option("#mb-f-required", "true")
    page.locator('.mb-fc[data-field-index="1"] [data-quick-required="1"]').check()
    _saved(page)
    f0, f1 = _draft()["fields"]
    assert f0["label"] == "設備名稱" and f0["required"] is True, f0
    assert f1["required"] is True, f1
    assert not errors, errors


@pytest.mark.e2e
def test_nav_has_eight_thumbnails_and_the_three_workflow_ones_scroll_within_step_4(live_server, make_user, new_context):
    """縮圖導覽 8 格；`.mb-step[data-step="4"]` 只有一個（既有 e2e 的選擇器不多抓）；簽核／通知兩格 ⇒ 第 4 步、捲到對應區塊；
    有問題的步驟縮圖帶 data-has-problems=1（參照欄沒選對象）。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_nav")
    assert page.locator("#mb-nav [data-nav]").count() == 8
    assert page.locator('.mb-step[data-step="4"]').count() == 1
    assert page.locator('#mb-nav [data-step="4"]').count() == 1, "簽核／通知兩格不可以帶 data-step（用 data-step-alias）"
    assert page.locator('#mb-nav [data-step-alias="4"]').count() == 2
    assert page.locator("#mb-nav [data-nav] .mb-nav__thumb").count() == 8
    for nav, anchor in (("approval", "mb-sec-approval"), ("notify", "mb-sec-notify")):
        page.click('#mb-nav [data-nav="%s"]' % nav)
        page.wait_for_selector("#mb-step-4", state="visible")
        page.wait_for_function("(n) => document.querySelector('#mb-nav [data-nav=\"' + n + '\"]').classList.contains('is-on')", arg=nav)
        page.wait_for_function("(a) => { const r = document.getElementById(a).getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight }",
                               arg=anchor)
    page.click('.mb-step[data-step="2"]')
    page.click('#mb-palette [data-palette-type="ref"]')
    _saved(page)
    page.wait_for_function("() => document.querySelector('.mb-step[data-step=\"2\"]').dataset.hasProblems === '1'")
    assert not errors, errors


@pytest.mark.e2e
def test_typing_a_label_keeps_focus_and_the_full_value(live_server, make_user, new_context):
    """主持驗收（〈先渲染再非同步載入＝競態〉）：連續打字時草稿自動存、預覽重畫，焦點不離開、打的字不被蓋掉。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_type")
    page.click('#mb-palette [data-palette-type="text"]')
    page.wait_for_selector("#mb-f-label")
    text = "借用設備的完整名稱與型號"
    page.locator("#mb-f-label").click()
    page.keyboard.type(text, delay=60)                       # 跨過 700ms 自動存與 250ms 預覽節流好幾次
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "mb-f-label"
    assert page.locator("#mb-f-label").input_value() == text
    _saved(page)
    assert _draft()["fields"][0]["label"] == text
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "mb-f-label"
    assert not errors, errors


@pytest.mark.e2e
@pytest.mark.skipif(not PREVIEW_JS.is_file(), reason="A 的 frontend/static/form-preview.js 還沒合進來（BUILDER-UX §7：A 先推、B 接上）")
def test_live_preview_shows_a_new_field(live_server, make_user, new_context):
    """即時預覽＝執行頁本身（iframe custom-records.html?preview=1）：加一個欄位 ⇒ 預覽裡出現 [data-field=<key>]。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_pv")
    page.click('#mb-palette [data-palette-type="text"]')
    _saved(page)
    key = _keys()[0]
    frame = page.frame_locator("#mb-preview-host iframe")
    frame.locator('[data-field="%s"]' % key).wait_for(state="attached", timeout=15000)
    # 選中卡片 ⇒ 預覽裡那個欄位被框起（A 的 setHighlight ⇒ .is-preview-hl）；換一張 ⇒ 框跟著換
    page.click('#mb-palette [data-palette-type="number"]')
    _saved(page)
    k2 = _keys()[1]
    frame.locator('[data-field="%s"]' % k2).wait_for(state="attached", timeout=15000)
    page.click('.mb-fc[data-field-index="0"]')
    frame.locator('.is-preview-hl[data-field="%s"]' % key).wait_for(state="attached", timeout=15000)
    page.click('.mb-fc[data-field-index="1"]')
    frame.locator('.is-preview-hl[data-field="%s"]' % k2).wait_for(state="attached", timeout=15000)
    assert frame.locator(".is-preview-hl").count() == 1
    assert not errors, errors
