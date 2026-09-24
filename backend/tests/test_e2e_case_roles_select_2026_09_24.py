"""瀏覽器端對端：案件角色選單存帳號（CM3）。

- 選一個人 ⇒ 資料庫存 {"username", "display"}（不是顯示名稱字串）
- 未轉換的舊字串 ⇒ 選單顯示「原值（未對應帳號）」，不會變成空白、也不會被靜默改掉
- 已存的物件 ⇒ 選單選中那個帳號
觀測點打在資料庫落地值。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, _login, live_server,
)

NO = "MQ-ROLESEL-001"
SALES_SELECT = ".cm-fgrid--people select >> nth=1"


def _seed(roles):
    import db
    cr = {"roles": roles, "payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "received": False,
                                                 "note": ""}]}, "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


def _roles():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])[
            "caseRecord"]["roles"]
    finally:
        conn.close()


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    # CU5（2026-09-24）：收款搬到「財務」分頁，收款備註不再是案件資訊分頁的就緒訊號
    # ⇒ 改等這一題真正要操作的人員角色選單
    page.locator(SALES_SELECT).wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=10000)
    page.wait_for_function(f"() => ({DATA_JS}.selectableUsers || []).length > 0", timeout=10000)
    return page


def _save(page):
    return page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")


@pytest.mark.e2e
def test_picking_a_person_stores_username_and_legacy_value_is_shown(live_server, make_user):
    adm = make_user(username="rs_admin", role="admin")
    make_user(username="rs_amy", role="sales")
    _seed({"filler": "", "sales": "查無此人", "executor": ""})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, adm)
            sel = page.locator(SALES_SELECT)
            assert "查無此人（未對應帳號）" in sel.evaluate("s => s.options[s.selectedIndex].text")
            sel.select_option("rs_amy")
            assert "已儲存" in _save(page)
            assert _roles()["sales"] == {"username": "rs_amy", "display": "rs_amy"}
        finally:
            browser.close()


@pytest.mark.e2e
def test_stored_object_selects_that_account(live_server, make_user):
    adm = make_user(username="rs_admin2", role="admin")
    make_user(username="rs_bob", role="sales")
    _seed({"filler": "", "sales": {"username": "rs_bob", "display": "舊名字"}, "executor": ""})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, adm)
            assert page.locator(SALES_SELECT).input_value() == "rs_bob"
        finally:
            browser.close()


@pytest.mark.e2e
def test_users_page_lists_unmapped_case_roles(live_server, make_user):
    sa = make_user(username="rs_sa", role="superadmin")
    _seed({"filler": "", "sales": "查無此人", "executor": ""})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            _login(page, live_server, *sa)
            page.goto(f"{live_server}/pages/users.html")
            box = page.locator("[data-testid=case-roles-unmapped]")
            box.locator("td", has_text="查無此人").wait_for(timeout=15000)
            assert "業務負責" in box.inner_text() and NO in box.inner_text()
        finally:
            browser.close()
