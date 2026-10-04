"""第 39 班前端：
- 公益金下限：虧損案（毛利＜0）公益金以 0 計——精算頁（實際側／原始側）、報價單表單；已完結照存檔值顯示。
- 實際成本 0＝真的 0：新頁面存檔帶 schemaVersion 2；填 0 ⇒ 來源「手填」、毛利＝報價；空白＝未填（用估計，來源「估計」）；
  舊存檔（沒有標記）0＝未填，載入後數字與舊版一致。
終點以頁面 DOM、頁面狀態與資料庫為準。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed, _settlement  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

S = "Alpine.$data(document.body)"


def _set_data(mutator):
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        mutator(d)
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()


def _open(browser, base, user, width=1400):
    page = browser.new_context(viewport={"width": width, "height": 1000}).new_page()
    _login(page, base, *user)
    page.goto(f"{base}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-strip"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    return page


def _save(page):
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)


@pytest.mark.e2e
def test_typed_zero_is_a_real_zero_and_blank_means_use_the_estimate(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    # 新頁面：沒填 ⇒ 用估計 10500，來源「估計」，輸入框空白、placeholder 是預設單價
    assert page.evaluate(f"() => {S}.itemActual({S}.settlement.items[0])") == 10500
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert page.locator('[data-testid="stl-unitcost-a"]').input_value() == ""
    assert "預設" in page.locator('[data-testid="stl-unitcost-a"]').get_attribute("placeholder")
    assert "未填" in page.locator('[data-testid="stl-filled-a"]').inner_text()
    # 填 0 ⇒ 真的 0：來源「手填」、毛利＝報價 20000、顯示 NT$ 0（不是 —）
    page.locator('[data-testid="stl-unitcost-a"]').fill("0")
    page.wait_for_function(f"() => {S}.itemActual({S}.settlement.items[0]) === 0", timeout=5000)
    assert "來源：手填" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert page.evaluate(f"() => {S}.itemProfit({S}.settlement.items[0])") == 20000
    assert "NT$ 0" in page.locator('[data-testid="stl-actual-total-a"]').inner_text()
    assert "已填 0" in page.locator('[data-testid="stl-filled-a"]').inner_text()
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["itemActualTotal"] == 0 + 800
    # 存檔 ⇒ schemaVersion 2，0 存成 0；重新載入仍是 0
    _save(page)
    saved = _settlement()
    assert saved["schemaVersion"] == 2 and saved["items"][0]["actualTotalCost"] == 0, saved["items"][0]
    page.reload()
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.totalActualCost >= 0 && {S}.settlement.items.length", timeout=20000)
    assert page.evaluate(f"() => {S}.settlement.items[0].actualTotalCost") == 0
    assert page.locator('[data-testid="stl-unitcost-a"]').input_value() == "0"
    assert page.evaluate(f"() => {S}.itemProfit({S}.settlement.items[0])") == 20000
    # 「清除」⇒ 回到未填（空白、用估計、來源「估計」）；存檔後 actualTotalCost 為 null
    page.locator('[data-testid="stl-clear-a"]').click()
    page.wait_for_function(f"() => {S}.itemActual({S}.settlement.items[0]) === 10500", timeout=5000)
    assert page.locator('[data-testid="stl-unitcost-a"]').input_value() == ""
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    _save(page)
    assert _settlement()["items"][0]["actualTotalCost"] is None


@pytest.mark.e2e
def test_legacy_saved_zero_still_means_unfilled_until_resaved(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    # 舊草稿：沒有 schemaVersion，品項 a 的實際成本存成 0（舊意義＝沒填 ⇒ 用估計）
    _set_data(lambda d: d.__setitem__("settlement", {
        "status": "draft", "items": [{"id": "a", "actualQty": 10, "actualUnitCost": 0, "actualTotalCost": 0, "actualCostTaxMode": "taxed_gross", "adoptSystem": False},
                                     {"id": "b", "actualQty": 100, "actualUnitCost": 5, "actualTotalCost": 525, "actualCostTaxMode": "taxed_gross", "adoptSystem": True}],
        "offsets": []}))
    page = _open(e2e_browser, live_server, sa)
    assert page.evaluate(f"() => {S}.itemActual({S}.settlement.items[0])") == 10500                 # 與舊版一致：0＝沒填 ⇒ 估計
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert page.locator('[data-testid="stl-unitcost-a"]').input_value() == ""
    assert "schemaVersion" not in _settlement()                                                      # 只載入、沒存 ⇒ 存檔不變
    _save(page)
    saved = _settlement()
    assert saved["schemaVersion"] == 2 and saved["items"][0]["actualTotalCost"] is None             # 重新存檔才升級；舊的 0 轉成「未填」


@pytest.mark.e2e
def test_loss_case_charity_is_zero_with_a_note_and_profitable_case_is_unchanged(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    _set_data(lambda d: d.__setitem__("tot", {"pretax": 5000, "total": 5250}))                      # 報價 5000 ＜ 成本 ⇒ 虧損
    page = _open(e2e_browser, live_server, sa)
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["grossProfit"] < 0 and s["charityDonation"] == 0, s
    assert s["netProfit"] == s["grossProfit"] - s["adminCost"], s                                    # 淨利＝毛利 − 管銷（公益 0）
    assert s["origDirectProfit"] < 0 and s["origCharity"] == 0 and s["origNetProfit"] == s["origDirectProfit"] - s["origAdminCost"], s
    note = page.locator('[data-testid="stl-charity-floor-note"]')
    note.wait_for(state="visible", timeout=5000)
    assert "虧損案公益金以 0 計" in note.inner_text()
    assert "0" in page.locator('[data-testid="stl-b2-ch"]').inner_text()
    # 賺錢的案子：公益 1%、沒有提示
    _set_data(lambda d: d.__setitem__("tot", {"pretax": 20000, "total": 21000}))
    page.reload()
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.quotedPretax === 20000", timeout=20000)
    s2 = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s2["grossProfit"] > 0 and s2["charityDonation"] > 0, s2                                  # 賺錢案：公益 1%（正數）照舊
    assert not page.locator('[data-testid="stl-charity-floor-note"]').is_visible()


@pytest.mark.e2e
def test_finalized_loss_settlement_shows_the_stored_charity(live_server, make_user, e2e_browser):
    """已完結的舊虧損案（存的公益金是負數）照存檔值顯示，不因新規則回頭改寫。"""
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    _set_data(lambda d: (d.__setitem__("tot", {"pretax": 5000, "total": 5250}), d.__setitem__("settlement", {
        "status": "finalized", "finalizedAt": "2026-09-01T00:00:00", "finalizedBy": "舊人員",
        "items": [{"id": "a", "actualTotalCost": 10500}, {"id": "b", "actualTotalCost": 800}],
        "summary": {"itemActualTotal": 11300, "extraTotal": 0, "charityDonation": -77, "grossProfit": -7700, "adminCost": 500, "netProfit": -8123}})))
    page = _open(e2e_browser, live_server, sa)
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["charityDonation"] == -77, s
    assert not page.locator('[data-testid="stl-charity-floor-note"]').is_visible()


@pytest.mark.e2e
def test_quotation_form_charity_floor(live_server, make_user, e2e_browser):
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    c = db.get_db()
    try:
        data = {"quoteNo": "MQ-LOSS-1", "customerName": "客", "projectName": "虧損案", "status": "草稿",
                "items": [{"id": "x", "description": "虧本品項", "qty": 1, "unit": "式", "unitPrice": 1000, "amount": 1000, "cost": 3000}]}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("MQ-LOSS-1", "草稿", "客", "虧損案", 1050, 1000, json.dumps(data, ensure_ascii=False),
                                                       "2026-10-04T00:00:00", "2026-10-04T00:00:00", "", "2026-10-04"))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/quotation-form.html?id=MQ-LOSS-1")
    page.wait_for_function(f"() => {{ const d = {S}; return d && d.q && d.q.items && d.q.items.length && d.tot && d.tot.pretax > 0 }}", timeout=20000)
    t = page.evaluate(f"() => ({{...{S}.tot}})")
    assert t["directProfit"] < 0 and t["charityDonation"] == 0, t                                    # 虧損 ⇒ 公益 0（不是負數）
    assert t["netProfit"] == t["directProfit"] - t["totalIndirect"], t                               # 淨利＝直接毛利 − 間接（含管銷；公益 0）
    note = page.locator('[data-testid="qf-charity-floor-note"]')
    note.wait_for(state="visible", timeout=5000)
    assert "虧損案公益金以 0 計" in note.inner_text()
    assert "0" in page.locator('[data-testid="qf-charity-value"]').inner_text()


@pytest.mark.e2e
def test_original_column_shows_the_indirect_reserve_so_it_adds_up(live_server, make_user, e2e_browser):
    """報價單的「間接成本預算」（tot.totalIndirect − 管銷 − 公益，例：物流 5,000）：原始欄多一列資訊列，原始淨利＝報價單淨利；
    差額欄在最終淨利列說明「其中 間接成本預算 X；實際端以單據為準」；補上等額的實際支出後，淨利只因公益金差一點點。"""
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    _set_data(lambda d: d.__setitem__("tot", {"pretax": 20000, "total": 21000, "directProfit": 9000, "adminCost": 2000, "charityDonation": 90,
                                              "totalIndirect": 2000 + 90 + 5000, "netProfit": 9000 - 2000 - 90 - 5000, "totalCost": 11025}))
    page = _open(e2e_browser, live_server, sa)
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["origNetProfit"] == 1910, s                                                              # ＝報價單淨利
    assert s["origIndirectReserve"] == 5000 and s["origDirectProfit"] - s["origAdminCost"] - s["origCharity"] - s["origIndirectReserve"] == s["origNetProfit"]  # 原始欄加得起來
    row = page.locator('[data-testid="stl-b2-reserve"]')
    row.wait_for(state="visible", timeout=5000)
    assert "5,000" in row.inner_text() and "報價預留間接成本" in row.inner_text()
    assert "以單據為準（已含於實際總成本）" in row.locator("td").nth(2).inner_text() and row.locator("td").nth(3).inner_text().strip() == "—"     # 實際端不算
    note = page.locator('[data-testid="stl-diffnote-b2-net"]').inner_text()
    assert "其中報價預留間接成本 5,000（原始預估已扣、實際只計單據）" in note, note
    net_before, ch_before = s["netProfit"], s["charityDonation"]
    # 補一筆等額 5,000 的實際（額外）支出 ⇒ 實際端淨利減少 5,000，只因公益金（1% 毛利）少一點點而差一些
    c = db.get_db()
    try:
        c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                  "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                  (NO, "物流", "物流費", 1, "式", 5000, 5000, "", "2026-10-02", "", "sa_sa", "sa_sa", "sa_sa", "sa_sa",
                   "2026-10-02T00:00:00", "2026-10-02T00:00:00", "sa_sa", "已核准"))
        c.commit()
    finally:
        c.close()
    page.reload()
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    s2 = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s2["netProfit"] - net_before == -5000 + (ch_before - s2["charityDonation"]), (s, s2)
    # 沒有報價單間接預算（舊報價單／沒填）⇒ 不出現資訊列、淨利列沒有說明
    _set_data(lambda d: d.__setitem__("tot", {"pretax": 20000, "total": 21000}))
    page.reload()
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.quotedPretax === 20000", timeout=20000)
    assert not page.locator('[data-testid="stl-b2-reserve"]').is_visible()
