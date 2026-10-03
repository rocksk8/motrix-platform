# -*- coding: utf-8 -*-
"""建構器第三輪 S1（2026-09-30）— 單頁編排（畫面＋DB 草稿）：
新模組先「從範本開始」；元件列（分組、搜尋、預設屬性）；屬性面板由目錄規格產生；畫布「編輯｜預覽」就地切換；
明細表欄位編輯與 total() 公式檢查；複製欄位、區塊欄數；金流性質與入帳狀態；行動版抽屜。
觀測點都打在草稿的 DB 落地值（ui_definitions.body_json）與畫面狀態。"""
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


def _saved(page):
    page.wait_for_function(SAVED, timeout=15000)


def _new_page(new_context, live_server, make_user, name, viewport=None):
    user = make_user(username=name, role="superadmin")
    ctx = new_context()
    page = ctx.new_page()
    if viewport:
        page.set_viewport_size(viewport)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/module-builder.html")
    return page, errors


def _blank_form(new_context, live_server, make_user, name, key, viewport=None):
    page, errors = _new_page(new_context, live_server, make_user, name, viewport)
    start_blank(page, key)
    go_step(page, 2)
    return page, errors


@pytest.mark.e2e
def test_new_module_starts_from_a_template_or_blank(live_server, make_user, new_context):
    """新模組先出「從範本開始」：空白＋目錄的範本（報價單）；選報價單 ⇒ 草稿是範本的內容（明細表、公式、金流欄），套用後可改；
    取消回首頁；範本清單來自目錄（頁面沒有寫死）。"""
    page, errors = _new_page(new_context, live_server, make_user, "b3s_tpl")
    page.fill("#mb-key", "b3s_qt")
    page.click("#mb-open")
    page.wait_for_selector("#mb-tpl-pick", state="visible")
    assert page.locator("#mb-tpl-blank").is_visible() and page.locator('[data-template="quotation"]').is_visible()
    page.click("#mb-tpl-cancel")                                               # 取消 ⇒ 回首頁，沒有建草稿
    page.wait_for_selector("#mb-pick", state="visible")
    assert _draft("b3s_qt") is None
    page.fill("#mb-key", "b3s_qt")
    page.click("#mb-open")
    page.click('[data-template="quotation"]')
    page.wait_for_selector("#mb-step-1", state="visible")
    _saved(page)
    d = _draft("b3s_qt")
    assert d["name"] == "報價單" and d["permission"] == "custom.b3s_qt"          # 權限 key 用新模組的代號
    assert [f["type"] for f in d["fields"] if f["key"] == "lines"] == ["table"]
    assert any(f.get("finance", {}).get("kind") == "income" for f in d["fields"])
    go_step(page, 2)
    page.wait_for_selector('#mb-canvas .mb-fc[data-field-key="lines"]')
    assert page.locator("#mb-canvas .mb-fc").count() == len(d["fields"])
    assert not errors, errors


@pytest.mark.e2e
def test_palette_groups_search_and_presets(live_server, make_user, new_context):
    """元件列依目錄分組（基礎／版面／進階）、可收合、可搜尋；元件帶預設屬性：日期時間＝withTime、單選＝預設選項、明細表＝預設四欄。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_pal", "b3s_pal")
    assert {"basic", "layout", "advanced"} <= set(page.eval_on_selector_all("[data-palette-group]", "els => els.map(e => e.dataset.paletteGroup)"))
    page.click('#mb-palette [data-palette-group="basic"] .mb-pal__g')          # 收合基礎
    page.wait_for_function("() => !document.querySelector('#mb-palette [data-palette-element=\"text\"]')")
    page.click('#mb-palette [data-palette-group="basic"] .mb-pal__g')
    page.wait_for_selector('#mb-palette [data-palette-element="text"]')
    page.fill("#mb-palette-q", "單選")                                           # 搜尋：單選、下拉單選、人員（單選）、部門（單選）
    els = page.eval_on_selector_all("[data-palette-element]", "els => els.map(e => e.dataset.paletteElement)")
    assert set(els) == {"radio", "select", "user", "dept"}, els                 # 人員／部門（單選）也含「單選」；複選、文字等不在
    page.fill("#mb-palette-q", "")
    for eid in ("datetime", "radio", "table", "textarea"):
        page.click('#mb-palette [data-palette-element="%s"]' % eid)
    _saved(page)
    d = _draft("b3s_pal")
    by_type = {f["type"]: f for f in d["fields"]}
    assert d["fields"][0]["type"] == "date" and d["fields"][0]["withTime"] is True
    assert by_type["radio"]["options"] == ["選項一", "選項二"]
    assert [c["key"] for c in by_type["table"]["columns"]] == ["item", "qty", "price", "amt"]
    assert by_type["table"]["columns"][3] == {"key": "amt", "label": "金額", "type": "formula", "formula": "qty * price"}
    assert by_type["textarea"]["required"] is False
    assert not errors, errors


@pytest.mark.e2e
def test_property_panel_is_driven_by_catalog_specs(live_server, make_user, new_context):
    """屬性面板依目錄的型別規格產生：文字有最大長度／不可重複、數字有最小／最大、單選有「其他」；設定值落到草稿，清空就拿掉。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_prop", "b3s_prop")
    page.click('#mb-palette [data-palette-type="text"]')
    page.wait_for_selector('#mb-props-pane [data-attr="maxLength"]')
    assert page.locator('#mb-props-pane [data-attr="unique"]').count() == 1
    page.locator('#mb-props-pane [data-attr="maxLength"] input').fill("8")
    page.locator('#mb-props-pane [data-attr="unique"] input').check()
    page.fill("#mb-f-label", "代碼")
    _saved(page)
    f = _draft("b3s_prop")["fields"][0]
    assert f["maxLength"] == 8 and f["unique"] is True and f["label"] == "代碼"
    page.locator('#mb-props-pane [data-attr="maxLength"] input').fill("")
    page.locator('#mb-props-pane [data-attr="unique"] input').uncheck()
    _saved(page)
    f = _draft("b3s_prop")["fields"][0]
    assert "maxLength" not in f and "unique" not in f                            # 清空／取消勾選 ⇒ 拿掉這個鍵
    page.click('#mb-palette [data-palette-type="number"]')
    page.wait_for_selector('#mb-props-pane [data-attr="min"]')
    page.locator('#mb-props-pane [data-attr="min"] input').fill("0")
    page.locator('#mb-props-pane [data-attr="max"] input').fill("99.5")
    page.click('#mb-palette [data-palette-type="radio"]')
    page.wait_for_selector('#mb-props-pane [data-attr="allowOther"]')
    page.locator('#mb-props-pane [data-attr="allowOther"] input').check()
    page.fill("#mb-f-options", "甲\n乙\n甲\n丙")                                  # 重複的選項被去掉
    _saved(page)
    d = _draft("b3s_prop")
    assert (d["fields"][1]["min"], d["fields"][1]["max"]) == (0, 99.5)
    assert d["fields"][2]["allowOther"] is True and d["fields"][2]["options"] == ["甲", "乙", "丙"]
    assert not errors, errors


@pytest.mark.e2e
def test_edit_preview_toggle_swaps_the_same_canvas_in_place(live_server, make_user, new_context):
    """畫布上方「編輯｜預覽」就地切換：同一個畫布（不跳頁、不彈窗）；預覽＝使用者填單視角（拿掉把手與屬性、區塊標題列出、
    動作列出現、控制項可操作、明細表可試按「新增一列」）；回到編輯時選中的欄位與屬性面板保留。"""
    page, errors = _new_page(new_context, live_server, make_user, "b3s_pv")
    page.fill("#mb-key", "b3s_pv")
    page.click("#mb-open")
    page.click('[data-template="quotation"]')
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.click('.mb-fc[data-field-key="cust"]')
    page.wait_for_selector('#mb-props-pane [data-props-for]')
    url, pages = page.url, len(page.context.pages)
    handle = page.evaluate("() => { window.__cv = document.getElementById('mb-canvas'); return true }")
    page.click("#mb-mode-preview")
    page.wait_for_selector("#mb-canvas.is-preview")
    assert page.evaluate("() => window.__cv === document.getElementById('mb-canvas')") is True     # 同一個畫布元素
    assert page.url == url and len(page.context.pages) == pages
    # T35 L6：切到預覽後畫布是非同步重畫；負載下 wait_for_selector(is-preview) 之後立刻 is_visible() 會搶在重畫前
    # （2026-10-03 -n 2 實測紅：報價明細標題尚未出現，單獨重跑 2/2 綠）。改用 expect 的自動等待（斷言內容不變）。
    from playwright.sync_api import expect
    expect(page.locator("#mb-canvas .mb-fc__bar").first).not_to_be_visible()
    expect(page.locator("#mb-canvas .cr-sec__t", has_text="報價明細").first).to_be_visible()     # 區塊標題以填單樣式列出
    assert page.locator("#mb-preview-actions button").count() >= 1
    assert page.locator('.mb-fc[data-field-key="cust"] input').first.is_enabled()                 # 可操作（不存檔）
    n0 = page.locator('[data-mock-table="lines"] tbody tr').count()
    page.click('[data-mock-table="lines"] .cr-tbl__add')
    expect(page.locator('[data-mock-table="lines"] tbody tr')).to_have_count(n0 + 1)
    assert page.locator('[data-field-key="tax"] input[type=radio]').count() >= 3                   # 稅別是單選
    page.click("#mb-mode-edit")
    page.wait_for_selector("#mb-canvas:not(.is-preview)")
    assert page.locator('.mb-fc[data-field-key="cust"].is-sel').count() == 1                        # 選中狀態保留
    assert page.locator('#mb-props-pane [data-props-for]').count() == 1
    expect(page.locator("#mb-canvas .mb-fc__bar").first).to_be_visible()
    assert not errors, errors


@pytest.mark.e2e
def test_table_column_editor_and_total_formula_check(live_server, make_user, new_context):
    """明細表的欄在屬性面板編輯（新增欄、改名、換型別、列內公式、刪欄）；表外公式 total(表,"欄") 由伺服器檢查：對的通過、
    不是數值欄／不是明細表 ⇒ 指出位置。落到草稿 DB。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_tbl", "b3s_tbl")
    page.click('#mb-palette [data-palette-element="table"]')
    page.wait_for_selector("[data-columns-editor]")
    assert page.locator("[data-columns-editor] .mb-col").count() == 4
    page.locator('[data-columns-editor] .mb-col[data-col-index="0"] input[aria-label="欄名"]').fill("品名")
    page.click('[data-add-column="number"]')
    assert page.locator("[data-columns-editor] .mb-col").count() == 5
    page.locator('[data-columns-editor] .mb-col[data-col-index="4"] input[aria-label="欄名"]').fill("折扣")
    page.locator('[data-columns-editor] .mb-col[data-col-index="3"] input[data-col-formula="3"]').fill("qty * price - c1")
    page.click('[data-add-column="formula"]')
    page.locator('[data-columns-editor] .mb-col[data-col-index="5"] input[data-col-formula="5"]').fill("qty * 2")
    page.click('[data-remove-column="5"]')
    _saved(page)
    t = _draft("b3s_tbl")["fields"][0]
    assert [c["key"] for c in t["columns"]] == ["item", "qty", "price", "amt", "c1"]
    assert t["columns"][0]["label"] == "品名" and t["columns"][4]["label"] == "折扣" and t["columns"][3]["formula"] == "qty * price - c1"
    # 表外公式：小計＝total(表, "amt")
    page.click('#mb-palette [data-palette-type="formula"]')
    page.wait_for_selector("#mb-f-formula")
    page.fill("#mb-f-formula", 'total(%s, "amt")' % t["key"])
    page.wait_for_selector('#mb-f-formula-problems[data-state="ok"]', timeout=10000)
    page.fill("#mb-f-formula", 'total(%s, "item")' % t["key"])                                   # item 是文字欄，不能加總
    page.wait_for_selector('#mb-f-formula-problems[data-state="bad"]', timeout=10000)
    assert "沒有可加總的數值欄" in page.locator("#mb-f-formula-problems").inner_text()
    page.fill("#mb-f-formula", "%s + 1" % t["key"])                                                # 明細表不能直接運算
    page.wait_for_selector('#mb-f-formula-problems[data-state="bad"]', timeout=10000)
    assert "不能直接運算" in page.locator("#mb-f-formula-problems").inner_text()
    assert not errors, errors


@pytest.mark.e2e
def test_duplicate_field_and_group_columns(live_server, make_user, new_context):
    """複製欄位：新代號、名稱加「複本」、放在原欄位後面；區塊欄數 1～4 存進 ui.form.groups[].columns，畫布網格照設定。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_dup", "b3s_dup")
    page.click('#mb-palette [data-palette-type="text"]')
    page.fill("#mb-f-label", "客戶")
    page.click("#mb-add-group")
    page.wait_for_selector('[data-group-title="0"]')
    page.click('.mb-fc[data-field-key="field_1"] [data-duplicate-field]')
    page.wait_for_selector('.mb-fc[data-field-key="field_2"]')
    _saved(page)
    d = _draft("b3s_dup")
    assert [f["key"] for f in d["fields"]] == ["field_1", "field_2"] and d["fields"][1]["label"] == "客戶 複本"
    page.locator('[data-group-columns="0"]').select_option("3")
    _saved(page)
    assert _draft("b3s_dup")["ui"]["form"]["groups"][0]["columns"] == 3
    page.locator('[data-group-columns="0"]').select_option("0")                                   # 自動 ⇒ 拿掉
    _saved(page)
    assert "columns" not in _draft("b3s_dup")["ui"]["form"]["groups"][0]
    assert not errors, errors


@pytest.mark.e2e
def test_finance_panel_and_post_states(live_server, make_user, new_context):
    """數字／公式欄的屬性面板有「金流性質」：不計／收入／支出；選了才出現日期欄、現金日期欄、現金金額欄、關聯案件欄（只列對應型別的欄位）；
    「流程設計」有金流欄位時才出現入帳狀態；沒設金流的模組沒有這一區（反向控制）。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_fin", "b3s_fin")
    for eid in ("number", "date", "text"):
        page.click('#mb-palette [data-palette-element="%s"]' % eid)
    page.click('.mb-fc[data-field-key="field_1"]')
    page.wait_for_selector("#mb-f-fin-kind")
    assert page.locator("#mb-f-fin-date").count() == 0                                            # 不計 ⇒ 沒有細項
    go_step(page, 4)
    assert not page.locator("#mb-sec-finance").is_visible()                                       # 沒有金流欄位 ⇒ 沒有入帳狀態區
    go_step(page, 2)
    page.click('.mb-fc[data-field-key="field_1"]')
    page.select_option("#mb-f-fin-kind", "income")
    page.wait_for_selector("#mb-f-fin-date")
    opts = page.eval_on_selector_all("#mb-f-fin-date option", "els => els.map(e => e.value)")
    assert opts == ["", "field_2"], opts                                                          # 只列日期欄
    assert page.eval_on_selector_all("#mb-f-fin-case option", "els => els.map(e => e.value)") == ["", "field_3"]   # 只列文字／參照欄
    page.select_option("#mb-f-fin-date", "field_2")
    page.select_option("#mb-f-fin-case", "field_3")
    _saved(page)
    fin = _draft("b3s_fin")["fields"][0]["finance"]
    assert fin == {"kind": "income", "dateField": "field_2", "caseField": "field_3"}
    go_step(page, 4)
    page.wait_for_selector("#mb-sec-finance", state="visible")
    page.check('[data-post-state="done"]')
    _saved(page)
    assert _draft("b3s_fin")["finance"] == {"postStates": ["done"]}
    go_step(page, 2)
    page.click('.mb-fc[data-field-key="field_1"]')
    page.select_option("#mb-f-fin-kind", "none")                                                  # 改回不計 ⇒ 拿掉 finance
    _saved(page)
    assert "finance" not in _draft("b3s_fin")["fields"][0]
    assert not errors, errors


@pytest.mark.e2e
def test_mobile_layout_uses_palette_and_property_drawers(live_server, make_user, new_context):
    """窄螢幕：元件列與屬性面板收成抽屜——預設不佔畫面，按「＋ 元件」開元件抽屜、加入後自動關；選欄位自動開屬性抽屜。"""
    page, errors = _blank_form(new_context, live_server, make_user, "b3s_mob", "b3s_mob", viewport={"width": 390, "height": 800})
    assert not page.locator("#mb-palette").is_visible()
    page.click("#mb-pal-open")
    page.wait_for_selector("#mb-palette", state="visible")
    page.click('#mb-palette [data-palette-element="text"]')
    page.wait_for_selector("#mb-palette", state="hidden")
    page.wait_for_selector('.mb-fc[data-field-key="field_1"]')
    page.click('.mb-fc[data-field-key="field_1"]')
    page.wait_for_selector("#mb-props-pane", state="visible")
    page.fill("#mb-f-label", "手機上填的")
    _saved(page)
    assert _draft("b3s_mob")["fields"][0]["label"] == "手機上填的"
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1") is True   # 沒有橫向捲動
    assert not errors, errors
