"""32-S5 瀏覽器端對端（一個檔、一個瀏覽器、一題連續流程）：請款頁挑案件品項 → 帶入明細 → 超計畫要原因 → 送審核准 →
精算頁看到採購單連結金額（尚未採用也計入）→ 採用 ⇒ 品項實際成本＝採購單金額、總成本不變。終點以資料庫與頁面狀態為準；截圖存 logs/e2e-shots。
另一題：沒有任何連結列的歷史案件，精算金額逐位不變（與連結功能出現前的算法同值）。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-PL-1"
HIST = "MQ-E2E-PL-HIST"
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t32-prpo-s1-2e")
Q = {"items": [
    {"id": "a", "description": "交換器", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
    {"id": "b", "description": "線材", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5},
]}


def _seed(no, data=None):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "客", "案", 21000, 21000, json.dumps(data or Q), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "pe_sa"))
        c.commit()
    finally:
        c.close()


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, "32s5-%s.png" % name), full_page=False)


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@pytest.mark.e2e
def test_pick_items_raise_po_and_settlement_follows(live_server, make_user, e2e_browser):
    import db
    from helpers import _set_setting
    sa = make_user(username="pe_sa", role="superadmin")
    _seed(NO)
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})        # 沒設層 ⇒ 送審即核准
    c = db.get_db()
    c.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('營運處', 0, '2026-10-02')")
    div = c.execute("SELECT id FROM divisions WHERE name='營運處'").fetchone()["id"]
    c.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?, '業務部', 0, '2026-10-02')", (div,))
    dept = c.execute("SELECT id FROM departments WHERE name='業務部'").fetchone()["id"]
    c.commit()
    c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, live_server, *sa)
    D = "Alpine.$data(document.querySelector('[x-data]'))"

    # ── 請款頁：挑案件、選採購單、帶入品項 ──
    page.goto(f"{live_server}/pages/payment-request.html")
    page.locator(f'[data-case-pick="{NO}"]').click(timeout=20000)
    page.evaluate(f"async () => {{ const d = {D}; d.typeCode = 'purchase_order'; await d.selectType() }}")
    page.locator("#pr-item-picker").wait_for(state="visible", timeout=15000)
    assert page.locator('[data-pick-item="a"]').count() == 1 and page.locator('[data-pick-item="b"]').count() == 1
    page.locator('[data-pick-item="a"] input').check()
    page.locator("#pr-item-add").click()
    lines = page.evaluate(f"() => {D}._df.getValue().lines")
    assert len(lines) == 1 and lines[0]["itemId"] == "a" and lines[0]["qty"] == 10 and lines[0]["unitCost"] == 1000, lines
    _shot(page, "1-picked")

    # 補必填欄位，數量改成 12（計畫 10）⇒ 畫面提示超出
    page.evaluate("""async ([D, dept]) => {
        const d = Alpine.$data(document.querySelector('[x-data]'))
        const v = d._df.getValue()
        v.data.dept = String(dept); v.data.vendor = '甲廠商'
        v.lines[0].qty = 12; v.lines[0].category = v.lines[0].category || ''
        d._df.setValue({data: v.data, lines: v.lines}); d._syncLinked()
    }""", [D, dept])
    page.locator('[data-linked-item="a"]').wait_for(state="visible", timeout=5000)
    assert "超出報價計畫量 2" in page.locator('[data-linked-item="a"] label').inner_text()
    problems = page.evaluate(f"() => {D}._df.validate()")
    assert problems == [] or all("類別" in p["message"] for p in problems), problems       # 費用類別清單空 ⇒ 不驗證；只容許類別這種環境差異
    _shot(page, "2-over-plan")

    # 不填原因就送審 ⇒ 伺服器擋（草稿留著、訊息說明）
    page.locator("#pr-t-submit").click()
    page.wait_for_function("() => document.querySelector('#pr-t-error') && document.querySelector('#pr-t-error').innerText.includes('超出')", timeout=15000)
    drafts = _q("SELECT status FROM case_extra_expenses WHERE kind='purchase_order' AND quote_no=?", (NO,))
    assert [d["status"] for d in drafts] == ["草稿"]
    # 填原因再送 ⇒ 核准（沒設簽核層）
    page.locator("#pr-reason-a").fill("客戶加購")
    page.locator("#pr-t-submit").click()
    page.wait_for_function("() => document.querySelector('#pr-result') && document.querySelector('#pr-result').innerText.includes('已送審')", timeout=15000)
    rows = _q("SELECT status, lines_json FROM case_extra_expenses WHERE kind='purchase_order' AND quote_no=? ORDER BY id", (NO,))
    assert [r["status"] for r in rows] == ["草稿", "已核准"]
    line = json.loads(rows[1]["lines_json"])[0]
    assert (line["itemId"], line["qty"], line["amount"], line["overPlanQty"], line["overPlanReason"]) == ("a", 12, 12000, 2.0, "客戶加購"), line
    _shot(page, "3-submitted")

    # ── 精算頁：採購單連結金額（尚未採用也計入總成本；採用後品項實際成本＝採購單金額）──
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-po-a"]').wait_for(state="visible", timeout=20000)
    S = "Alpine.$data(document.body)"
    s0 = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s0["itemPoUnadopted"] == 12000 and s0["itemActualTotal"] == 10500 + 525          # 品項預設實際成本（qty×cost×1.05）不含採購單
    assert page.evaluate(f"() => {S}.xeTotal") == 0                                         # 連結列不再算額外支出
    assert s0["totalActualCost"] == 10500 + 525 + 12000
    _shot(page, "4-settlement")
    page.locator('[data-testid="stl-adopt-a"]').click()
    s1 = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s1["itemPoUnadopted"] == 0 and s1["itemActualTotal"] == 12000 + 525 and s1["totalActualCost"] == 12000 + 525
    page.wait_for_function("() => document.querySelector('[data-testid=\"stl-po-a\"]').innerText.includes('已採用')", timeout=5000)
    _shot(page, "5-adopted")
    # 存草稿 ⇒ adoptSystem 存進精算資料；重開還在
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    saved = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["settlement"]
    assert [i["adoptSystem"] for i in saved["items"]] == [True, False] and saved["items"][0]["actualTotalCost"] == 12000
    page.reload()
    page.locator('[data-testid="stl-po-a"]').wait_for(state="visible", timeout=20000)
    assert page.evaluate(f"() => {S}.summary.totalActualCost") == 12000 + 525


@pytest.mark.e2e
def test_history_case_without_links_settlement_is_unchanged(live_server, make_user, e2e_browser):
    """沒有任何連結列（歷史資料）：精算頁金額＝連結功能出現前的算法（品項＋額外支出＋派發）；沒有採購單區塊。"""
    import db
    sa = make_user(username="pe_sa2", role="superadmin")
    _seed(HIST)
    c = db.get_db()
    c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
              "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
              (HIST, "其他", "舊版支出", 1, "式", 700, 700, "", "2026-10-02", "", "pe_sa2", "pe_sa2", "pe_sa2", "pe_sa2",
               "2026-10-02T00:00:00", "2026-10-02T00:00:00", "pe_sa2", "已核准"))
    c.commit()
    c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={HIST}")
    S = "Alpine.$data(document.body)"
    page.wait_for_function(f"() => {S}.summary && {S}.summary.totalActualCost > 0", timeout=20000)
    s = page.evaluate(f"() => ({{...{S}.summary, xe: {S}.xeTotal}})")
    assert s["xe"] == 700 and s["itemPoUnadopted"] == 0 and s["extraTotal"] == 700
    assert s["totalActualCost"] == 10500 + 525 + 700                                        # 品項預設＋舊版額外支出；與沒有連結功能時逐位相同
    assert page.locator('[data-testid^="stl-po-"]:visible').count() == 0
    _shot(page, "6-history")
