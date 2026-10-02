"""33-B1/B2 瀏覽器端對端（一個檔、一題連續流程）：精算頁用後端單一來源——材料申請（連品項／沒連）與額外支出 →
規則 A（有採購取代估計）→ 未對應清單 → 沖銷對應到品項（預覽不存檔）→ 存草稿 → 重開還在 → 取消沖銷。
終點以資料庫與頁面狀態為準；截圖存 logs/e2e-shots。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-SA-1"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t33-settlement-b1-2e")
ITEMS = [{"id": "a", "description": "交換器", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
         {"id": "b", "description": "線材", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5}]


def _order(item_id, total, **kw):
    d = {"itemId": item_id, "itemName": "料" + item_id, "quantity": 1, "unit": "批", "unitPrice": total, "totalPrice": total,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "invoiceDate": "2026-10-02"}
    d.update(kw)
    return d


def _seed():
    import db
    c = db.get_db()
    try:
        data = {"items": ITEMS, "dealTag": "已成案", "caseRecord": {"materialOrders": [_order("X", 250), _order("N", 800, quoteItemId="b")]}}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "sa_sa"))
        for iid in ("X", "N"):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (NO, iid, "已核准"))
        c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                  "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                  (NO, "其他", "雜支", 1, "式", 700, 700, "", "2026-10-02", "", "sa_sa", "sa_sa", "sa_sa", "sa_sa",
                   "2026-10-02T00:00:00", "2026-10-02T00:00:00", "sa_sa", "已核准"))
        c.commit()
    finally:
        c.close()


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "33b1-%s.png" % name), full_page=False)


def _settlement():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("settlement") or {}
    finally:
        c.close()


@pytest.mark.e2e
def test_settlement_page_rule_a_unassigned_list_and_offsets(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1100}).new_page()
    _login(page, live_server, *sa)
    S = "Alpine.$data(document.body)"
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    s0 = page.evaluate(f"() => ({{...{S}.summary}})")
    # 品項 b 有材料申請 800（連品項、沒連採購單）⇒ 實際 800 取代估計 525；品項 a 沒採購 ⇒ 估計 10500；
    # 未對應：材料申請 X 250＋額外支出 700 ⇒ 都計入 extraTotal
    assert s0["itemActualTotal"] == 10500 + 800 and s0["extraTotal"] == 700 + 250 and s0["purchasedTotal"] == 800 + 250 + 700, s0
    assert page.locator('[data-testid="stl-un-material-X"]').count() == 1 and page.locator('[data-testid^="stl-un-extra-"]').count() == 1
    assert "250" in page.locator('[data-testid="stl-mat-unassigned"]').inner_text()
    assert "已採用" in page.locator('[data-testid="stl-po-b"]').inner_text()
    _shot(page, "1-unassigned")

    # 沖銷：材料申請 X 對應到品項 a ⇒ a 實際＝250（規則 A：有採購就取代估計），錢從未對應搬到品項，採購類總額不變
    page.locator('[data-testid="stl-offset-material-X"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.extraTotal === 700", timeout=10000)
    s1 = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s1["itemActualTotal"] == 250 + 800 and s1["extraTotal"] == 700 and s1["purchasedTotal"] == 800 + 250 + 700, s1
    assert page.locator('[data-testid="stl-mat-unassigned"]').is_visible() is False
    assert _settlement() == {}                                                              # 預覽：還沒存
    _shot(page, "2-offset")

    # 存草稿 ⇒ offsets 進精算資料；重開還在
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    saved = _settlement()
    assert saved["offsets"] == [{"kind": "material", "ref": "X", "itemId": "a"}] and [i["adoptSystem"] for i in saved["items"]] == [True, True]
    page.reload()
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    assert page.locator('[data-testid="stl-offset-material-X"]').input_value() == "a"
    assert page.evaluate(f"() => {S}.summary.itemActualTotal") == 250 + 800

    # 取消沖銷 ⇒ 回到未對應（仍計入）
    page.locator('[data-testid="stl-offset-material-X"]').select_option("")
    page.wait_for_function(f"() => {S}.summary.extraTotal === 950", timeout=10000)
    assert page.evaluate(f"() => {S}.summary.itemActualTotal") == 10500 + 800
