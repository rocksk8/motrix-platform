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
from tests._builder_nav import go_step, start_blank  # noqa: E402

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
    start_blank(page, KEY)                       # 第三輪：新模組先出「從範本開始」，選空白
    go_step(page, 2)
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
    # 〔改題 2026-09-30〕第三輪元件列依目錄分組，一個型別可有多個元件（單選／下拉都是選項型）⇒ 比集合，順序不再等於 fieldTypes
    assert set(types) == set(catalog["fieldTypes"]), (types, catalog["fieldTypes"])
    btns = page.locator('#mb-palette [data-palette-element]')
    for i in range(btns.count()):
        btn = btns.nth(i)
        assert btn.locator("svg").count() == 1, "元件 %s 沒有 icon" % btn.get_attribute("data-palette-element")
        assert btn.inner_text().strip(), "元件 %s 沒有文字" % btn.get_attribute("data-palette-element")
    page.locator('#mb-palette [data-palette-element="date"]').first.focus()
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
    page.wait_for_selector('#mb-props-pane #mb-f-label')          # 第三輪：屬性在右欄屬性面板（id 不變）
    page.fill("#mb-f-label", "設備名稱")
    page.select_option("#mb-f-required", "true")
    page.locator('.mb-fc[data-field-index="1"] [data-quick-required="1"]').check()
    _saved(page)
    f0, f1 = _draft()["fields"]
    assert f0["label"] == "設備名稱" and f0["required"] is True, f0
    assert f1["required"] is True, f1
    assert not errors, errors


@pytest.mark.e2e
def test_three_tabs_replace_the_seven_thumbnails_and_publish_is_a_drawer(live_server, make_user, new_context):
    """〔改題 2026-09-30 建構器第三輪：使用者要求「三頁籤（作業資訊／表單設計／流程設計）＋發布獨立為主按鈕」，
    取代 2026-09-27 第二輪的七格縮圖；內部步驟號 1、2、4、5、6 與 #mb-step-N 保留（沒有第 3 步）〕
    頂列三個頁籤；作業資訊＝步驟 1＋5、表單設計＝2、流程設計＝4；「發布」是頂列主按鈕、開同頁抽屜（步驟 6）、Esc 關閉；
    有問題的頁籤帶 data-has-problems=1（參照欄沒選對象 ⇒ 表單設計頁籤）；舊縮圖導覽已不存在。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_nav")
    assert page.locator(".mb-tab").count() == 3 and page.locator("#mb-nav").count() == 0
    assert page.locator('#mb-step-3').count() == 0 and page.locator('.mb-step').count() == 0
    go_step(page, 1)
    assert page.locator("#mb-step-5").is_visible() and not page.locator("#mb-step-2").is_visible()      # 作業資訊 ＝ 基本＋輸出
    go_step(page, 4)
    assert page.locator("#mb-step-4").is_visible() and not page.locator("#mb-step-1").is_visible()
    assert page.locator("#mb-sec-workflow").is_visible() and page.locator("#mb-sec-approval").count() == 1
    go_step(page, 2)
    page.click('#mb-palette [data-palette-type="ref"]')
    _saved(page)
    page.wait_for_function("() => document.querySelector('.mb-tab[data-tab=\"form\"]').dataset.hasProblems === '1'")
    # 發布：同頁抽屜，不跳頁、不開彈窗
    url = page.url
    page.click("#mb-publish-open")
    page.wait_for_selector("#mb-drawer #mb-step-6", state="visible")
    assert page.url == url and len(page.context.pages) == 1
    page.keyboard.press("Escape")
    page.wait_for_selector("#mb-drawer", state="hidden")
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
def test_output_and_list_previews_follow_the_canvas_on_the_same_screen(live_server, make_user, new_context):
    """〔改題 2026-09-27 第二輪：原題驗右側「表單」iframe 預覽與框選；使用者要「預覽都在同一個頁面」——
    畫布本身就是表單，右側改成同時顯示輸出預覽（A 的 mode:'output'）與列表預覽（mode:'list'），不用頁籤切換〕
    加欄位、改名稱 ⇒ 兩個預覽都跟著變；兩個 iframe 同時在畫面上；改名稱時焦點不離開輸入框。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_pv")
    assert page.locator("#mb-preview-mode").count() == 0, "不再有預覽切換"
    page.click('#mb-palette [data-palette-type="text"]')
    page.wait_for_selector("#mb-f-label")
    page.locator("#mb-f-label").click()
    page.keyboard.type("設備名稱甲", delay=40)
    _saved(page)
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == "mb-f-label"
    page.fill("#mb-f-label", "設備名稱乙")
    _saved(page)
    # 〔改題 2026-09-30 建構器第三輪：輸出預覽與列表預覽改成右欄同頁頁籤（屬性｜輸出預覽｜列表預覽），不再同時顯示；
    # 仍不跳頁、不開彈窗。預覽只在該頁籤開著時渲染 ⇒ 切過去再等內容跟上最新名稱〕
    page.click("#mb-side-output")
    out = page.frame_locator("#mb-output-host iframe")
    out.locator("body:has-text('設備名稱乙')").wait_for(state="attached", timeout=15000)
    assert page.locator("#mb-output-host iframe").is_visible() and not page.locator("#mb-list-host iframe").is_visible()
    page.click("#mb-side-list")
    lst = page.frame_locator("#mb-list-host iframe")
    lst.locator("body:has-text('設備名稱乙')").wait_for(state="attached", timeout=15000)
    assert page.locator("#mb-list-host iframe").is_visible() and not page.locator("#mb-output-host iframe").is_visible()
    assert not errors, errors


LAYOUT_JS = Path(__file__).resolve().parents[2] / "frontend" / "static" / "custom-layout.js"


@pytest.mark.e2e
def test_formula_readable_swaps_keys_for_labels_and_operators_for_math_signs(new_context):
    """使用者 2026-09-27：「帶入公式需要註解或是說明這公式是甚麼」⇒ 可讀式子（建構器卡片與執行頁共用 L.formulaReadable）。"""
    page = new_context().new_page()
    page.set_content("<html><body></body></html>")
    page.add_script_tag(path=str(LAYOUT_JS))
    d = {"fields": [{"key": "qty", "label": "數量", "type": "number"},
                    {"key": "unit_price", "label": "單價", "type": "number"},
                    {"key": "note", "type": "text"},
                    {"key": "amount", "label": "金額", "type": "formula", "formula": "qty*unit_price"}]}
    got = page.evaluate("""(d) => { const R = (f) => window.MotrixCustomLayout.formulaReadable(d, f); return [
      R(d.fields[3]),
      R({key: 'avg', label: '平均', type: 'formula', formula: 'round(qty / unit_price, 2)'}),
      R({key: 'x', label: '判斷', type: 'formula', formula: 'if(qty >= 10, "qty", note)'}),
      R({key: 'y', label: 'Y', type: 'formula', formula: 'qty - unknown_key'}),
      R({key: 'z', label: 'Z', type: 'formula', formula: '   '}),
      R(d.fields[0]),
    ] }""", d)
    assert got == ["金額 ＝ 數量 × 單價",
                   "平均 ＝ round(數量 ÷ 單價, 2)",
                   '判斷 ＝ if(數量 ≥ 10, "qty", note)',        # 字串常值原樣；沒標籤的欄位用代號
                   "Y ＝ 數量 - unknown_key",
                   "", ""], got


def _label(page, i, text):
    page.click('.mb-fc[data-field-index="%d"]' % i)
    page.wait_for_selector('#mb-props-pane [data-props-for="%d"] #mb-f-label' % i)
    page.fill("#mb-f-label", text)


@pytest.mark.e2e
def test_formula_card_shows_readable_formula_or_plain_error_and_help_lands_in_draft_and_preview(live_server, make_user, new_context):
    """卡片上看得到「金額 ＝ 數量 × 單價」；公式寫錯 ⇒ 同一處用人話說哪裡錯（沿用公式檢查）；
    說明（help）存進草稿 DB；預覽（＝執行頁）欄位下方顯示說明與可讀式子。"""
    page, errors = _open(new_context, live_server, make_user, "dnd_help")
    for t in ("number", "number", "formula"):
        page.click('#mb-palette [data-palette-type="%s"]' % t)
    page.wait_for_selector('.mb-fc[data-field-index="2"]')
    _label(page, 0, "數量")
    _label(page, 1, "單價")
    _label(page, 2, "金額")
    _saved(page)
    k0, k1, k2 = _keys()
    fx = '.mb-fc[data-field-index="2"] [data-fx-readable="%s"]' % k2
    page.fill("#mb-f-formula", "%s * %s" % (k0, k1))
    page.wait_for_function("(s) => { const e = document.querySelector(s); return e && e.dataset.fxState === 'ok' && e.textContent.trim() === '金額 ＝ 數量 × 單價' }",
                           arg=fx, timeout=15000)
    page.fill("#mb-f-formula", "%s * " % k0)
    page.wait_for_function("(s) => { const e = document.querySelector(s); return e && e.dataset.fxState === 'bad' && e.textContent.startsWith('公式有誤：') }",
                           arg=fx, timeout=15000)
    page.fill("#mb-f-formula", "%s * %s" % (k0, k1))
    page.wait_for_function("(s) => document.querySelector(s).dataset.fxState === 'ok'", arg=fx, timeout=15000)
    page.fill("#mb-f-help", "含稅金額，依數量與單價計算")
    page.wait_for_selector('.mb-fc[data-field-index="2"] [data-field-help="%s"]' % k2)
    _saved(page)
    f2 = _draft()["fields"][2]
    assert f2["help"] == "含稅金額，依數量與單價計算" and f2["formula"] == "%s * %s" % (k0, k1), f2
    assert "help" not in _draft()["fields"][0]                   # 沒填 ⇒ 不帶鍵（只新增）
    # 〔改題 2026-09-27 第二輪：右側不再有表單 iframe；執行頁顯示說明與可讀式子改由畫布一致性題（test_e2e_builder_form_canvas）驗〕
    page.fill("#mb-f-help", "")
    _saved(page)
    assert "help" not in _draft()["fields"][2]                   # 清空 ⇒ 拿掉鍵
    assert not errors, errors
