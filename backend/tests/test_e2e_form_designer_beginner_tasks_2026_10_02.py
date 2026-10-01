# -*- coding: utf-8 -*-
"""新版表單設計器（模組建構器 ② 表單，?designer=1）：五個「只靠點擊」的新手任務（FORM-DESIGNER-DESIGN §7）。

任務一律用點／拖／在輸入框打字完成，不碰內部代碼與公式；斷言打在草稿 DB（fields／ui），不讀內部模型。
1 加一個「備註」長文字框；2 把「地點」改成選單（國內／國外）；3 把「金額」搬到最後一個區塊；
4 讓「總額」自動加總費用明細的小計；5 把「備註」從清單中隱藏。
另驗：選項清單按 Enter 新增下一格、貼多行拆格、跨區塊 Alt+↓、刪除後「復原」、被引用的欄位不能刪、不動就不改定義（來回切換不弄髒草稿）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step  # noqa: E402

KEY = "fd_demo"
SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""


def _draft():
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft' "
                         "ORDER BY rowid DESC LIMIT 1", (KEY,)).fetchone()
        return json.loads(r["body_json"]) if r else None
    finally:
        conn.close()


def _body():
    lines = {"key": "lines", "label": "費用明細", "type": "table", "dataClass": "T1", "minRows": 0, "maxRows": 200, "addLabel": "新增一列",
             "columns": [{"key": "item", "label": "項目", "type": "text"}, {"key": "qty", "label": "數量", "type": "number"},
                         {"key": "unit_cost", "label": "單價", "type": "number"},
                         {"key": "amount", "label": "小計", "type": "formula", "formula": "round_half_up(qty * unit_cost)"}]}
    return {"name": "設計器測試", "icon": "", "permission": "custom." + KEY,
            "numbering": {"prefix": "FD", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "place", "label": "地點", "type": "text", "dataClass": "T1", "required": True},
                       {"key": "amount", "label": "金額", "type": "number", "dataClass": "T1", "min": 0},
                       lines,
                       {"key": "total", "label": "總額", "type": "formula", "dataClass": "T1", "formula": ""},
                       {"key": "memo", "label": "備忘", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": [{"title": "基本資料", "fields": ["place", "amount"]}, {"title": "費用", "fields": ["lines", "total"]},
                                       {"title": "其他", "fields": ["memo"]}]},
                   "list": {"columns": ["place", "amount", "total"]}}}


@pytest.fixture()
def designer(live_server, client, make_user, new_context):
    user = make_user(username="fd_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    page = new_context(viewport={"width": 1600, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/module-builder.html?key=%s&designer=1" % (live_server, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.errors = errors
    return page


def _saved(page):
    page.wait_for_function(SAVED, timeout=15000)


def _field(page, label):
    return page.locator(".fd-fld", has=page.locator("label", has_text=label)).first


def _label_of(draft, key):
    return next(f for f in draft["fields"] if f["key"] == key)


@pytest.mark.e2e
def test_task1_add_a_memo_textarea(designer):
    page = designer
    page.click('.fd-left [data-add="textarea"]')
    page.fill('.fd-right [data-fd="label"]', "備註")
    _saved(page)
    d = _draft()
    f = next(x for x in d["fields"] if x["label"] == "備註")
    assert f["type"] == "textarea"
    assert f["key"] in d["ui"]["list"]["columns"], "新加的欄位預設會出現在清單"
    assert any(f["key"] in g["fields"] for g in d["ui"]["form"]["groups"]), "新欄位要進某個區塊"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_task2_make_place_a_menu_with_two_options(designer):
    page = designer
    _field(page, "地點").click()
    page.select_option('.fd-right [data-fd="conv"]', "select")
    page.wait_for_selector('.fd-right [data-item="opt:0"]')
    page.fill('.fd-right [data-item="opt:0"]', "國內")
    page.fill('.fd-right [data-item="opt:1"]', "國外")
    _saved(page)
    f = _label_of(_draft(), "place")
    assert f["type"] == "select" and f["options"] == ["國內", "國外"]


@pytest.mark.e2e
def test_task3_move_amount_to_the_last_section(designer):
    page = designer
    _field(page, "金額").click()
    for _ in range(6):                                  # 在區塊邊緣再按「往下」就會跨到下一個區塊
        if page.locator('.fd-sec').last.locator('.fd-fld', has=page.locator("label", has_text="金額")).count():
            break
        page.click('.fd-fld.is-sel [data-act="down"]')
    _saved(page)
    groups = _draft()["ui"]["form"]["groups"]
    assert "amount" in groups[-1]["fields"] and all("amount" not in g["fields"] for g in groups[:-1])


@pytest.mark.e2e
def test_task3b_drag_amount_to_the_last_section(designer):
    page = designer
    # 🔴 Playwright 的 drag_to 在這個環境只會送出 dragstart（真滑鼠按下去也會，實測），之後的 dragenter／dragover／drop 不會產生；
    #    所以用同一個 DataTransfer 依序送出整串拖放事件——驗的是設計器自己的處理（落在哪條插入線），不是瀏覽器的拖放啟動。
    last_slot = page.locator('.fd-sec').last.locator('.fd-slot').last
    src = page.locator('.fd-fld[data-key="amount"]')
    dt = page.evaluate_handle("() => new DataTransfer()")
    src.dispatch_event("dragstart", {"dataTransfer": dt})
    last_slot.dispatch_event("dragover", {"dataTransfer": dt})
    last_slot.dispatch_event("drop", {"dataTransfer": dt})
    src.dispatch_event("dragend", {"dataTransfer": dt})
    _saved(page)
    groups = _draft()["ui"]["form"]["groups"]
    assert "amount" in groups[-1]["fields"]


@pytest.mark.e2e
def test_task4_total_adds_up_the_line_amounts_and_shows_a_live_example(designer):
    page = designer
    _field(page, "總額").click()
    page.click('.fd-right input[data-fd="calc"][value="sumtable"]')
    page.select_option('.fd-right [data-fd="cpT"]', "lines|amount")
    _saved(page)
    assert _label_of(_draft(), "total")["formula"] == 'total(lines, "amount")'
    assert "6,000" in page.inner_text(".fd-center"), "預覽要顯示活範例數字"


@pytest.mark.e2e
def test_task5_hide_memo_from_the_list(designer):
    page = designer
    page.click('.fd-left [data-add="textarea"]')
    page.fill('.fd-right [data-fd="label"]', "備註")
    _saved(page)
    key = next(x for x in _draft()["fields"] if x["label"] == "備註")["key"]
    assert key in _draft()["ui"]["list"]["columns"]
    page.click('.fd-right [data-sw="listed"]')
    _saved(page)
    assert key not in _draft()["ui"]["list"]["columns"]


@pytest.mark.e2e
def test_options_enter_adds_the_next_row_and_paste_splits_lines(designer):
    page = designer
    _field(page, "地點").click()
    page.select_option('.fd-right [data-fd="conv"]', "radio")
    page.wait_for_selector('.fd-right [data-item="opt:1"]')
    page.click('.fd-right [data-item="opt:1"]')
    page.keyboard.press("Enter")                               # 在最後一格按 Enter ⇒ 下一格，游標跟過去
    page.keyboard.type("第三個")
    assert page.locator('.fd-right [data-items="opt"] li').count() == 3
    # 貼上多行：游標所在格有字 ⇒ 多行接在它後面（2 + Enter 的 1 + 貼上的 3 ＝ 6 格）；所在格是空的 ⇒ 第一行填進該格
    page.evaluate("""() => { const i = document.querySelector('.fd-right [data-item="opt:2"]'); i.focus();
        const dt = new DataTransfer(); dt.setData('text', 'A\\nB\\nC'); i.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })) }""")
    page.wait_for_function("() => document.querySelectorAll('.fd-right [data-items=\"opt\"] li').length === 6")
    _saved(page)
    assert _label_of(_draft(), "place")["options"][-3:] == ["A", "B", "C"]


@pytest.mark.e2e
def test_delete_can_be_undone_and_a_referenced_field_cannot_be_deleted(designer):
    page = designer
    _field(page, "備忘").click()
    page.click('.fd-right [data-fd-act="delsel"]')
    page.wait_for_selector(".fd-toast")
    _saved(page)
    assert all(f["key"] != "memo" for f in _draft()["fields"])
    page.click(".fd-toast button")                              # 復原
    _saved(page)
    assert any(f["key"] == "memo" for f in _draft()["fields"])
    # 先把「總額」設成加總明細，再刪「費用明細」⇒ 被擋下並列出使用處
    _field(page, "總額").click()
    page.click('.fd-right input[data-fd="calc"][value="sumtable"]')
    page.select_option('.fd-right [data-fd="cpT"]', "lines|amount")
    _field(page, "費用明細").click()
    page.click('.fd-right [data-fd-act="delsel"]')
    page.wait_for_selector("dialog.fd-dlg[open]")
    assert "總額" in page.inner_text("dialog.fd-dlg")
    page.click("dialog.fd-dlg [data-r]")
    _saved(page)
    assert any(f["key"] == "lines" for f in _draft()["fields"])


@pytest.mark.e2e
def test_opening_the_designer_and_switching_back_does_not_change_the_draft(designer):
    page = designer
    before = _draft()
    page.click("#mb-fd-toggle")                                 # 關掉新版 ⇒ 舊畫面
    page.wait_for_selector("#mb-canvas", state="visible")
    page.click("#mb-fd-toggle")
    page.wait_for_selector(".fd .fd-paper", state="visible")
    page.wait_for_timeout(1200)                                 # 沒有改動就不會有存檔（要證明「沒發生」只能等）
    assert _draft() == before


@pytest.mark.e2e
def test_deleting_a_published_or_fixed_field_asks_first_and_cancel_keeps_it(designer):
    """已發布版本有的欄位（舊單據用得到）與固定欄位：刪除前一律確認（復原不跨重新整理）；取消＝不動；確定才刪（並仍可按復原）。"""
    page = designer
    page.evaluate("() => { Alpine.$data(document.body)._fd.caps.publishedKeys = ['memo'] }")
    _field(page, "備忘").click()
    page.click('.fd-right [data-fd-act="delsel"]')
    page.wait_for_selector("dialog.fd-dlg[open]")
    assert "已經在發布的版本" in page.inner_text("dialog.fd-dlg") and "重新整理" in page.inner_text("dialog.fd-dlg")
    page.click('dialog.fd-dlg [data-r="0"]')                          # 取消
    page.wait_for_selector("dialog.fd-dlg", state="detached")
    assert page.locator(".fd-fld", has=page.locator("label", has_text="備忘")).count() == 1
    page.click('.fd-right [data-fd-act="delsel"]')
    page.wait_for_selector("dialog.fd-dlg[open]")
    page.click('dialog.fd-dlg [data-r="1"]')                          # 確定刪除
    page.wait_for_selector(".fd-toast")
    _saved(page)
    assert all(f["key"] != "memo" for f in _draft()["fields"])
    page.click(".fd-toast button")                                    # 仍可復原
    _saved(page)
    assert any(f["key"] == "memo" for f in _draft()["fields"])
    # 固定欄位（請款類型的保留欄位）：同樣要確認
    page.evaluate("() => { Alpine.$data(document.body)._fd.caps.fixedTypeKeys = { place: 'text' } }")
    _field(page, "地點").click()
    assert page.locator('.fd-right [data-fd="conv"]').count() == 0, "固定欄位不能改種類"
    page.click('.fd-right [data-fd-act="delsel"]')
    page.wait_for_selector("dialog.fd-dlg[open]")
    assert "固定欄位" in page.inner_text("dialog.fd-dlg")
    page.click('dialog.fd-dlg [data-r="0"]')


@pytest.mark.e2e
def test_table_column_presets_add_fixed_key_columns(designer):
    """caps.columnPresets：欄代碼固定的常用欄（請款單明細的 數量＋單價、發票號碼）從按鈕加入，已有的不重複加。"""
    page = designer
    page.evaluate("""() => { Alpine.$data(document.body)._fd.caps.columnPresets = [
        { label: '數量＋單價', desc: '兩欄一起加', cols: [{ key: 'qty2', label: '數量', type: 'number' }, { key: 'unit_cost2', label: '單價', type: 'number' }] },
        { label: '發票號碼', cols: [{ key: 'invoice_no', label: '發票號碼', type: 'text' }] }] }""")
    _field(page, "費用明細").click()
    page.click('.fd-right [data-col-preset="0"]')
    _saved(page)
    keys = [c["key"] for c in _label_of(_draft(), "lines")["columns"]]
    assert keys.count("qty2") == 1 and keys.count("unit_cost2") == 1, keys
    assert page.locator('.fd-right [data-col-preset]').count() == 1, "加過的組合不再出現"
    page.click('.fd-right [data-col-preset]')
    _saved(page)
    assert "invoice_no" in [c["key"] for c in _label_of(_draft(), "lines")["columns"]]
    assert page.locator('.fd-right [data-col-preset]').count() == 0


@pytest.mark.e2e
def test_fixed_options_are_read_only_and_a_mismatch_is_flagged_without_changing_the_draft(designer):
    page = designer
    _field(page, "地點").click()
    page.select_option('.fd-right [data-fd="conv"]', "select")            # 選項 選項一／選項二
    _saved(page)
    before = _draft()
    page.evaluate("() => { const f = Alpine.$data(document.body)._fd; f.caps.fixedOptions = { place: ['國內', '國外'] }; f.setDef(f.getDef()); f.select('place') }")
    page.wait_for_selector('.fd-right [data-fd-fixedopts]')
    assert page.locator('.fd-right [data-item]').count() == 0, "固定選項不可編輯（沒有輸入格）"
    assert "固定" in page.inner_text('.fd-right [data-fd-fixedopts]') and "國內、國外" in page.inner_text('.fd-right [data-fd-fixedopts]')
    assert "必須固定為：國內、國外" in page.inner_text(".fd-right")       # 與固定值不一致 ⇒ 右欄列為要修改（工具列的計數也會增加）
    page.wait_for_timeout(1200)
    assert _draft() == before, "只回報不偷改：草稿不變"
