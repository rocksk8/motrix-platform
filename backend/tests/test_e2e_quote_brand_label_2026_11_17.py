"""瀏覽器端對端：報價單品項表欄名可自訂——「品名 / 規格說明」與「廠牌 / 型號」（2026-11-17）。

編輯畫面：表頭預設原名稱；點表頭旁的鉛筆可改（常用選項＋自己打字）；改了之後表頭、欄位 placeholder 同步；
存檔後寫進單據（data_json.columnLabels）、重新載入還在；清空＝回預設；舊單沒有這個鍵＝預設；估價單（共用同一張表單）比照報價單。
選擇器一律用 data-testid，不跟著欄名走。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
DEFAULT = "廠牌 / 型號"
ITEM = "品名 / 規格說明"


def _seed(no, doc_type="quote", labels=None):
    import db
    d = {"quoteNo": no, "customerName": "欄名客戶", "projectName": "欄名專案", "status": "草稿", "docType": doc_type,
         "items": [{"id": 1, "description": "品項 1", "brand": "Cisco", "notes": "", "qty": 1, "cost": 1000,
                    "margin": 0.35, "unitPrice": 1650, "amount": 1650}],
         "tot": {"total": 1575, "pretax": 1500, "directMarginPct": 0, "netMarginPct": 0}}
    if labels:
        d["columnLabels"] = labels
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (no,))
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, deal_tag, quote_date, doc_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "草稿", "欄名客戶", "欄名專案", 1575, 1500, json.dumps(d, ensure_ascii=False),
             "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01", doc_type))
        conn.commit()
    finally:
        conn.close()


def _open(live_server, make_user, e2e_browser, no, name):
    username, password = make_user(username=name, role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1400, "height": 900})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function("() => document.body.innerText.includes('欄名客戶')", timeout=20000)
    return page


def _stored_labels(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
    finally:
        conn.close()
    return json.loads(r["data_json"]).get("columnLabels")


def _th_text(page, col):
    """表頭欄名文字。編輯框收起（blur）與文字顯示是 Alpine x-show 的下一個影格：先等文字元素可見再讀（不要點完立刻 assert）。"""
    el = page.locator(f"[data-testid='qf-col-label-text-{col}']")
    el.wait_for(state="visible")
    return el.inner_text().strip()


def _rename(page, col, value):
    page.locator(f"[data-testid='qf-col-label-edit-{col}']").click()
    box = page.locator(f"[data-testid='qf-col-label-{col}']")
    box.wait_for(state="visible")
    box.fill(value)
    box.press("Enter")


@pytest.mark.e2e
def test_defaults_then_edit_brand_syncs_header_and_placeholder(live_server, make_user, e2e_browser):
    no = "MQ-202611-911"
    _seed(no)
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl1")
    cell = page.locator("[data-testid='qf-item-brand']").first
    assert _th_text(page, "brand") == DEFAULT and _th_text(page, "item") == ITEM
    assert cell.get_attribute("placeholder") == DEFAULT
    assert page.locator("[data-testid='qf-col-label-brand']").is_hidden()
    page.locator("[data-testid='qf-col-label-edit-brand']").click()
    page.locator("[data-testid='qf-col-label-brand']").wait_for(state="visible")
    # 常用選項在 datalist 裡
    opts = page.evaluate("[...document.querySelectorAll('#col-label-options-brand option')].map(o => o.value)")
    assert opts == ["料號", "型號", "規格", DEFAULT]
    page.locator("[data-testid='qf-col-label-brand']").fill("料號")
    page.locator("[data-testid='qf-col-label-brand']").press("Enter")
    assert _th_text(page, "brand") == "料號"
    assert cell.get_attribute("placeholder") == "料號"
    assert _th_text(page, "item") == ITEM, "改一欄不影響另一欄"
    assert page.evaluate(f"{DATA}.isDirty") is True
    _rename(page, "brand", "原廠料號 / 序號")        # 自己打字
    assert _th_text(page, "brand") == "原廠料號 / 序號"


@pytest.mark.e2e
def test_edit_item_column_label(live_server, make_user, e2e_browser):
    no = "MQ-202611-914"
    _seed(no)
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl5")
    opts = page.evaluate("[...document.querySelectorAll('#col-label-options-item option')].map(o => o.value)")
    assert ITEM in opts and "品名" in opts
    _rename(page, "item", "品項")
    assert _th_text(page, "item") == "品項" and _th_text(page, "brand") == DEFAULT
    desc = page.locator("tbody textarea").first
    assert desc.get_attribute("placeholder") == "品項"


@pytest.mark.e2e
def test_saved_labels_persist_and_clearing_returns_to_default(live_server, make_user, e2e_browser):
    no = "MQ-202611-912"
    _seed(no)
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl2")
    _rename(page, "brand", "  規格 ")
    _rename(page, "item", "品項")
    ok = page.evaluate(f"{DATA}.apiSave(false).then(r => !!r)")
    assert ok, "存檔失敗"
    assert _stored_labels(no) == {"brand": "規格", "item": "品項"}
    page.reload()
    page.wait_for_function("() => document.body.innerText.includes('欄名客戶')", timeout=20000)
    assert _th_text(page, "brand") == "規格" and _th_text(page, "item") == "品項"
    # 清空 ⇒ 回預設，單據上不留鍵
    _rename(page, "brand", "")
    _rename(page, "item", "")
    assert _th_text(page, "brand") == DEFAULT and _th_text(page, "item") == ITEM
    assert page.evaluate(f"{DATA}.apiSave(false).then(r => !!r)")
    assert _stored_labels(no) is None


@pytest.mark.e2e
def test_legacy_quote_without_field_shows_defaults(live_server, make_user, e2e_browser):
    no = "MQ-202611-913"
    _seed(no)
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl3")
    assert _th_text(page, "brand") == DEFAULT and _th_text(page, "item") == ITEM
    assert page.evaluate(f"{DATA}.q.columnLabels") in (None, {})


@pytest.mark.e2e
def test_estimate_shows_saved_labels_and_can_edit_and_save(live_server, make_user, e2e_browser):
    no = "ME-202611-911"
    _seed(no, doc_type="estimate", labels={"brand": "料號", "item": "品項"})
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl4")
    assert page.evaluate(f"{DATA}.q.docType") == "estimate"
    for col in ("item", "brand"):
        assert page.locator(f"[data-testid='qf-col-label-edit-{col}']").is_visible(), "估價單也有修改鈕"
    assert _th_text(page, "brand") == "料號" and _th_text(page, "item") == "品項"
    assert page.locator("[data-testid='qf-item-brand']").first.get_attribute("placeholder") == "料號"
    _rename(page, "brand", "規格")
    _rename(page, "item", "")                          # 清空 ⇒ 該欄回預設
    assert _th_text(page, "brand") == "規格" and _th_text(page, "item") == ITEM
    assert page.evaluate(f"{DATA}.apiSave(false).then(r => !!r)"), "存檔失敗"
    assert _stored_labels(no) == {"brand": "規格"}
    page.reload()
    page.wait_for_function("() => document.body.innerText.includes('欄名客戶')", timeout=20000)
    assert _th_text(page, "brand") == "規格" and _th_text(page, "item") == ITEM


@pytest.mark.e2e
def test_legacy_estimate_without_field_shows_defaults(live_server, make_user, e2e_browser):
    no = "ME-202611-912"
    _seed(no, doc_type="estimate")
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl6")
    assert _th_text(page, "brand") == DEFAULT and _th_text(page, "item") == ITEM
    assert page.locator("[data-testid='qf-item-brand']").first.get_attribute("placeholder") == DEFAULT


@pytest.mark.e2e
def test_display_strips_invisible_chars_and_submit_notes_list_changed_columns(live_server, make_user, e2e_browser):
    no = "MQ-202611-913"
    _seed(no)
    page = _open(live_server, make_user, e2e_browser, no, "e2e_bl7")
    # 顯示函式與後端 normalize 同規則：零寬字元／控制字元去掉、與預設相同＝預設
    got = page.evaluate("""() => { const d = %s; d.q.columnLabels = {brand: '料' + String.fromCharCode(0x200b) + '號' + String.fromCharCode(0xfeff), item: '%s'};
        return [d.columnLabel('brand'), d.columnLabel('item'), d.columnLabelNotes()] }""" % (DATA, ITEM))
    assert got[0] == "料號" and got[1] == ITEM
    assert got[2] == ["欄名已由「廠牌 / 型號」變更為「料號」"], got
    # 送簽確認視窗列出欄名變更；沒改就不出現
    page.evaluate("() => { %s.showSubmitModal = true }" % DATA)
    page.locator("[data-testid='qf-submit-col-notes']").wait_for(state="visible", timeout=10000)
    assert "欄名已由「廠牌 / 型號」變更為「料號」" in page.locator("[data-testid='qf-submit-col-notes']").inner_text()
    page.evaluate("() => { %s.q.columnLabels = {} }" % DATA)
    page.locator("[data-testid='qf-submit-col-notes']").wait_for(state="detached", timeout=10000)
