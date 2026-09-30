# -*- coding: utf-8 -*-
"""模組建構器 ② 表單：畫布就是表單（使用者 2026-09-27 第二輪：「預覽都在同一個頁面，直接放入，現在是切換欄位版面」）。

- 一致性（主持核准的條件）：拿掉右側表單 iframe 之後畫布不是執行頁本身 ⇒ 同一份草稿，畫布上的區塊與欄位順序、標籤、必填、說明
  逐項等於執行頁（custom-records，經 A 的 MotrixFormPreview.render mode:'form' 載入的真頁面）實際畫出來的；
  公式欄的可讀式子（-3 的使用者意見 ①）也一起比。
- 放置：工具列拖進某區塊的某個位置、欄位跨區塊拖、區塊拖曳排序、鍵盤 Alt＋↑／↓ 跨區塊；斷言打在草稿 DB（ui.form.groups、fields 順序）。
斷言驗 DOM 與 DB，不讀 Alpine 模型（§G5 #9）；等待等草稿存檔完成的終點。
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step, start_blank  # noqa: E402

SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""
PREVIEW_JS = Path(__file__).resolve().parents[2] / "frontend" / "static" / "form-preview.js"


def _draft(key):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft' "
                         "ORDER BY rowid DESC LIMIT 1", (key,)).fetchone()
        return json.loads(r["body_json"]) if r else None
    finally:
        conn.close()


def _body(key, fields, groups):
    return {"name": "畫布測試", "icon": "", "permission": "custom." + key,
            "numbering": {"prefix": "CV", "date": "YYYYMMDD", "digits": 4}, "fields": fields,
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": groups}, "list": {"columns": []}}}


def _open(new_context, base, make_user, client, name, body, key):
    user = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": body}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, base, user[0], user[1])
    page.goto("%s/pages/module-builder.html?key=%s" % (base, key))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector("#mb-step-2", state="visible")
    return page, errors


def _saved(page):
    page.wait_for_function(SAVED, timeout=15000)


CANVAS = """() => [...document.querySelectorAll('#mb-canvas .mb-sec[data-empty="0"]')].map(s => {
  const ti = s.querySelector(':scope > .mb-sec__h [data-group-title]'), tt = s.querySelector(':scope > .cr-sec__t')
  const title = ti ? ti.value : (tt && tt.offsetParent ? tt.textContent.trim() : '')
  return { title, fields: [...s.querySelectorAll('.mb-fc')].map(f => ({
    key: f.dataset.fieldKey,
    label: f.querySelector(':scope > label > span').textContent.trim(),
    required: !!(f.querySelector(':scope > label .req') || {}).offsetParent,
    help: (() => { const h = f.querySelector(':scope > .cr-help'); return h && h.offsetParent ? h.textContent.trim() : '' })(),
    fx: (() => { const h = f.querySelector(':scope > .cr-fx'); return h && h.offsetParent ? h.textContent.trim() : '' })() })) } })"""
RUNTIME = """(d) => { const doc = window.__rt.iframe.contentDocument;
  return [...doc.querySelectorAll('#cr-form .cr-sec')].map(s => {
    const tt = s.querySelector(':scope > .cr-sec__t')
    return { title: tt && tt.offsetParent ? tt.textContent.trim() : '', fields: [...s.querySelectorAll('.cr-f[data-field]')].map(f => ({
      key: f.dataset.field,
      label: f.querySelector(':scope > label > span').textContent.trim(),
      required: !!(f.querySelector(':scope > label .req') || {}).offsetParent,
      help: (() => { const h = f.querySelector(':scope > .cr-help'); return h && h.offsetParent ? h.textContent.trim() : '' })(),
    fx: (() => { const h = f.querySelector(':scope > .cr-fx'); return h && h.offsetParent ? h.textContent.trim() : '' })() })) } }) }"""


@pytest.mark.e2e
@pytest.mark.skipif(not PREVIEW_JS.is_file(), reason="需要 A 的 form-preview.js 載入執行頁（BUILDER-UX §7）")
def test_canvas_sections_and_fields_equal_what_the_runtime_form_draws(live_server, make_user, new_context, client):
    """同一份草稿：畫布（非空的區塊）與執行頁表單逐項相同——區塊標題與順序、欄位順序、標籤（沒標籤用代號）、必填、說明。
    草稿故意讓 fields 的順序和分組順序不同、分組裡有已刪除的代號、有空的分組、有沒分組的欄位（「其他」）。"""
    key = "canvas_eq"
    fields = [
        {"key": "note", "label": "", "type": "text", "required": False, "dataClass": "T1", "help": "給承辦人看的備註"},
        {"key": "total", "label": "總值", "type": "formula", "formula": "qty * 2", "dataClass": "T1", "help": "數量的兩倍"},
        {"key": "qty", "label": "數量", "type": "number", "required": True, "dataClass": "T1"},
        {"key": "item", "label": "設備", "type": "text", "required": True, "dataClass": "T1", "help": "財產編號或名稱"},
        {"key": "back", "label": "歸還日", "type": "date", "required": False, "dataClass": "T1"},
    ]
    groups = [{"title": "借用資訊", "fields": ["item", "ghost", "qty"]}, {"title": "", "fields": ["note"]}, {"title": "空的", "fields": []}]
    page, errors = _open(new_context, live_server, make_user, client, "cv_eq", _body(key, fields, groups), key)
    page.wait_for_selector('#mb-canvas .mb-fc[data-field-key="back"]')
    page.evaluate("""(d) => { const h = document.createElement('div'); h.id = 'rt-host'; document.body.appendChild(h)
      window.__rt = window.MotrixFormPreview.render(h, d, { mode: 'form' }) }""", _body(key, fields, groups))
    page.wait_for_function("() => { const d = window.__rt && window.__rt.iframe.contentDocument; return !!(d && d.querySelectorAll('.cr-f[data-field]').length === 5) }",
                           timeout=15000)
    canvas, runtime = page.evaluate(CANVAS), page.evaluate(RUNTIME, None)
    assert [s["title"] for s in runtime] == ["借用資訊", "", "其他"], runtime       # 正對照：執行頁真的畫出了三塊
    assert runtime[2]["fields"][0]["fx"] == "總值 ＝ 數量 × 2" and runtime[0]["fields"][0]["help"] == "財產編號或名稱", runtime
    assert canvas == runtime, (canvas, runtime)
    assert page.locator('#mb-canvas .mb-sec[data-empty="1"] [data-group-title="2"]').count() == 1   # 空的分組畫布上看得到（放得進欄位）
    assert not errors, errors


def _drag(page, src, dst):
    page.drag_and_drop(src, dst)


@pytest.mark.e2e
def test_palette_drops_into_a_section_at_a_position_and_fields_move_across_sections(live_server, make_user, new_context, client):
    """工具列拖到卡片上 ⇒ 插在那張之前；拖到區塊標題列 ⇒ 區塊最後；欄位從「其他」拖進區塊；區塊拖曳排序。草稿 DB 跟著變。"""
    key = "canvas_drop"
    fields = [{"key": "a", "label": "甲", "type": "text", "required": False, "dataClass": "T1"},
              {"key": "b", "label": "乙", "type": "text", "required": False, "dataClass": "T1"},
              {"key": "c", "label": "丙", "type": "text", "required": False, "dataClass": "T1"}]
    groups = [{"title": "一", "fields": ["a", "b"]}, {"title": "二", "fields": []}]
    page, errors = _open(new_context, live_server, make_user, client, "cv_drop", _body(key, fields, groups), key)
    page.wait_for_selector('#mb-canvas .mb-fc[data-field-key="c"]')
    _drag(page, '#mb-palette [data-palette-type="number"]', '.mb-fc[data-field-key="b"]')             # 插在乙之前
    page.wait_for_selector('.mb-sec[data-section-group="0"] .mb-fc[data-field-key="field_1"]')
    _saved(page)
    d = _draft(key)
    assert d["ui"]["form"]["groups"][0]["fields"] == ["a", "field_1", "b"], d["ui"]
    assert [f["key"] for f in d["fields"]] == ["a", "field_1", "b", "c"]                            # fields 跟著畫布順序
    _drag(page, '.mb-fc[data-field-key="c"] .mb-fc__bar .h', '.mb-sec[data-section-group="1"] .mb-sec__h .h')   # 「其他」⇒ 區塊二
    page.wait_for_selector('.mb-sec[data-section-group="1"] .mb-fc[data-field-key="c"]')
    _drag(page, '#mb-palette [data-palette-type="date"]', '.mb-sec[data-section-group="1"] .mb-sec__h .h')     # 區塊二的最後
    page.wait_for_selector('.mb-sec[data-section-group="1"] .mb-fc[data-field-key="field_2"]')
    _saved(page)
    d = _draft(key)
    assert [g["fields"] for g in d["ui"]["form"]["groups"]] == [["a", "field_1", "b"], ["c", "field_2"]], d["ui"]
    _drag(page, '.mb-sec[data-section-group="1"] .mb-sec__h .h', '.mb-sec[data-section-group="0"] .mb-sec__h .h')  # 區塊二拖到最前
    page.wait_for_function("() => document.querySelector('[data-group-title=\"0\"]').value === '二'")
    _saved(page)
    d = _draft(key)
    assert [g["title"] for g in d["ui"]["form"]["groups"]] == ["二", "一"]
    assert [f["key"] for f in d["fields"]] == ["c", "field_2", "a", "field_1", "b"]
    assert not errors, errors


@pytest.mark.e2e
def test_keyboard_moves_cross_section_boundaries_and_announce_the_section(live_server, make_user, new_context, client):
    """鍵盤替代：Alt＋↓ 在區塊最後一個 ⇒ 移到下一塊的最前（「其他」也算一塊）；Alt＋↑ 在最前 ⇒ 移到上一塊的最後。
    焦點跟著卡片、aria-live 念出區塊名與位置。"""
    key = "canvas_kb"
    fields = [{"key": "a", "label": "甲", "type": "text", "required": False, "dataClass": "T1"},
              {"key": "b", "label": "乙", "type": "text", "required": False, "dataClass": "T1"},
              {"key": "c", "label": "丙", "type": "text", "required": False, "dataClass": "T1"}]
    groups = [{"title": "一", "fields": ["a"]}, {"title": "二", "fields": ["b"]}]
    page, errors = _open(new_context, live_server, make_user, client, "cv_kb", _body(key, fields, groups), key)
    page.wait_for_selector('#mb-canvas .mb-fc[data-field-key="c"]')
    page.locator('.mb-fc[data-field-key="a"]').focus()
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_function("() => (document.getElementById('mb-live').textContent || '').includes('甲 移到「二」第 1 個')")
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.fieldKey === 'a'")
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_function("() => (document.getElementById('mb-live').textContent || '').includes('甲 移到「二」第 2 個')")
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.fieldKey === 'a'")
    page.keyboard.press("Alt+ArrowDown")
    page.wait_for_function("() => (document.getElementById('mb-live').textContent || '').includes('甲 移到「其他」第 1 個')")
    _saved(page)
    d = _draft(key)
    assert [g["fields"] for g in d["ui"]["form"]["groups"]] == [[], ["b"]], d["ui"]
    assert [f["key"] for f in d["fields"]] == ["b", "a", "c"]
    page.wait_for_function("() => document.activeElement && document.activeElement.dataset.fieldKey === 'a'")
    page.keyboard.press("Alt+ArrowUp")
    page.wait_for_function("() => (document.getElementById('mb-live').textContent || '').includes('甲 移到「二」第 2 個')")
    _saved(page)
    assert [g["fields"] for g in _draft(key)["ui"]["form"]["groups"]] == [[], ["b", "a"]]
    assert not errors, errors


@pytest.mark.e2e
def test_deleting_a_section_with_fields_asks_first_and_moves_them_to_other(live_server, make_user, new_context, client):
    """刪有欄位的區塊要先確認；確認後欄位回到「其他」（不刪欄位）。"""
    key = "canvas_rm"
    fields = [{"key": "a", "label": "甲", "type": "text", "required": False, "dataClass": "T1"},
              {"key": "b", "label": "乙", "type": "text", "required": False, "dataClass": "T1"}]
    groups = [{"title": "一", "fields": ["b"]}]
    page, errors = _open(new_context, live_server, make_user, client, "cv_rm", _body(key, fields, groups), key)
    page.wait_for_selector('.mb-sec[data-section-group="0"] .mb-fc[data-field-key="b"]')
    page.click('[data-remove-group="0"]')
    page.locator('[data-testid="ui-dialog-ok"]').click()
    page.wait_for_function("() => !document.querySelector('[data-group-title]')")
    _saved(page)
    d = _draft(key)
    assert d["ui"]["form"]["groups"] == [] and [f["key"] for f in d["fields"]] == ["a", "b"], d
    assert not errors, errors
