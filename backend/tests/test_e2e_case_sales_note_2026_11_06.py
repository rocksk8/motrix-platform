"""瀏覽器端對端：案件頁「報價人」標籤、業績歸屬說明、「報價人≠業績歸屬」提示（2026-11-06，選項 A）。

- 清單卡片／詳情頭標「報價人」；角色下拉標「業績歸屬（業務負責）」並帶一句說明。
- 報價人與業績歸屬同一人 ⇒ 沒有提示條；不同人 ⇒ 有提示條（中性樣式）。
- 在畫面上改業績歸屬 ⇒ 提示條即時變化；存檔後 quotations.sales_person／sales_person_id 完全不變（只改文字，不改讀寫）。
設 E2E_SHOT_DIR 環境變數時，把兩種情況的截圖存到該目錄（人工驗收用）。
"""
import json
import os

import pytest

from tests._requires import requires_module  # noqa: E402
needs_m01 = requires_module("case", '本題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象')

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401,E402  (live_server 是 fixture)
    DATA_JS, _login,
)

SALES_SELECT = ".cm-fgrid--people select >> nth=1"
NOTE = "[data-testid=cm-sales-diff-note]"
HINT = "[data-testid=cm-role-sales-hint]"


def _seed(no, sales_person, sales_person_id, roles_sales):
    import db
    cr = {"roles": {"filler": "", "sales": roles_sales, "executor": ""},
          "payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "received": False, "note": ""}]}, "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "小林機械廠", "案", 100, 95,
             json.dumps({"dealTag": "已成案", "caseRecord": cr, "salesPerson": sales_person}, ensure_ascii=False),
             now, now, "已成案", sales_person, sales_person_id))
        conn.commit()
    finally:
        conn.close()


def _db_sales(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT sales_person, sales_person_id FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return r[0], r[1]
    finally:
        conn.close()


def _open(browser, base, user, no):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    page.goto(f"{base}/pages/case-management.html?q={no}")
    page.locator(SALES_SELECT).wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{no}'", timeout=10000)
    page.wait_for_function(f"() => ({DATA_JS}.selectableUsers || []).length > 0", timeout=10000)
    return page


def _shot(page, name):
    d = os.environ.get("E2E_SHOT_DIR")
    if d:
        os.makedirs(d, exist_ok=True)
        page.locator(NOTE if page.locator(NOTE).is_visible() else HINT).scroll_into_view_if_needed()
        page.screenshot(path=os.path.join(d, name), full_page=False)


@needs_m01
@pytest.mark.e2e
def test_labels_and_no_note_when_same_person(live_server, make_user, e2e_browser):
    adm = make_user(username="sn_admin", role="admin")
    make_user(username="sn_huang", role="sales")
    no = "MQ-SALESNOTE-001"
    _seed(no, "黃玉龍", None, {"username": "sn_huang", "display": "黃玉龍"})
    page = _open(e2e_browser, live_server, adm, no)
    # 卡片與詳情頭
    assert "報價人：黃玉龍" in page.locator(".cm-card__sales").first.inner_text()
    assert page.locator(".cm-meta__lbl", has_text="報價人").count() >= 1
    assert page.locator(".cm-meta__lbl", has_text="負責業務").count() == 0
    # 角色下拉標籤與說明
    assert "業績歸屬（業務負責）" in page.locator("label[for=cm-role-sales]").inner_text()
    assert "業務獎金依報價人計算，與此欄位無關" in page.locator(HINT).inner_text()
    # 同一人 ⇒ 沒有提示條
    assert not page.locator(NOTE).is_visible()
    _shot(page, "same_person.png")


@needs_m01
@pytest.mark.e2e
def test_note_when_different_and_live_update_without_touching_sales_person(live_server, make_user, e2e_browser):
    adm = make_user(username="sn_admin2", role="admin")
    make_user(username="sn_kao", role="sales")
    no = "MQ-SALESNOTE-002"
    _seed(no, "黃玉龍", None, {"username": "sn_kao", "display": "高晟耀"})
    page = _open(e2e_browser, live_server, adm, no)
    note = page.locator(NOTE)
    note.wait_for(state="visible", timeout=10000)
    txt = note.inner_text()
    assert "報價人（黃玉龍）與業績歸屬（高晟耀）不是同一人" in txt and "業務獎金依報價人" in txt
    # 中性樣式：不是錯誤／警告色（取計算後樣式比對 tone 變數的色值不可行，改驗 class 與 inline style 不含 danger／warning）
    cls_style = note.evaluate("e => (e.className + ' ' + (e.getAttribute('style') || ''))")
    assert "danger" not in cls_style and "warning" not in cls_style
    _shot(page, "different_person.png")
    # 清空業績歸屬 ⇒ 提示條消失（報表此時退回報價人）
    page.locator(SALES_SELECT).select_option("")
    page.wait_for_function("() => !document.querySelector('[data-testid=cm-sales-diff-note]').offsetParent", timeout=5000)
    # 改回別人 ⇒ 提示條回來，存檔後報價人欄位完全不變
    page.locator(SALES_SELECT).select_option("sn_kao")
    note.wait_for(state="visible", timeout=5000)
    msg = page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")
    assert "已儲存" in msg
    assert _db_sales(no) == ("黃玉龍", None)
