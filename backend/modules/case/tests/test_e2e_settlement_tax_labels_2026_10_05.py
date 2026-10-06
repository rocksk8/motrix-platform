"""精算頁稅基標示（只加文字，不改任何數字）：品項估計含稅 ×1.05、採購單／材料申請含稅、額外支出未分稅、承攬商派發未稅（＋外包人員）；
總結有一行口徑說明與 ⓘ。數字與標示前完全相同。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed  # noqa: E402
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

S = "Alpine.$data(document.body)"


def _open(browser, base, user):
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, base, *user)
    page.goto(f"{base}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-strip"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => !{S}.loading && {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    return page


@pytest.mark.e2e
def test_every_cost_source_shows_its_tax_basis_and_numbers_are_unchanged(live_server, make_user, e2e_browser):
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 20000, "total": 21000}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    d1 = _dispatch(10000, 2000, quote_no=NO)                                  # 未稅 10,000＋外包人員 2,000 ⇒ 含稅計入 12,500（未對應）
    page = _open(e2e_browser, live_server, sa)
    # 數字與加標示前完全相同：品項 a 估計 10,500、b 材料申請 800、額外 700＋未對應材料 250、派發 12,000
    s = page.evaluate(f"() => ({{...{S}.summary}})")
    assert s["itemActualTotal"] == 10500 + 800 and s["dispatchTotal"] == 12500 and s["totalActualCost"] == 10500 + 800 + 950 + 12500, s
    # 品項：估計含稅 ×1.05；b（材料申請，已對應）含稅
    assert "×1.05" in page.locator('[data-testid="stl-basis-a"]').inner_text() and "含稅" in page.locator('[data-testid="stl-basis-a"]').inner_text()
    assert "材料申請 含稅" in page.locator('[data-testid="stl-basis-b"]').inner_text()
    # 未對應列：材料 含稅、額外 未分稅、派發 未稅（＋外包人員）
    assert "含稅" in page.locator('[data-testid="stl-kindbasis-material-X"]').inner_text()
    assert "未拆稅" in page.locator('[data-testid^="stl-kindbasis-extra-"]').first.inner_text()
    assert "外包人員" in page.locator(f'[data-testid="stl-kindbasis-dispatch-{d1}"]').inner_text()
    # 賺賠表的未對應項目列
    assert "未拆稅" in page.locator('[data-testid="stl-pt-basis-extra"]').inner_text()
    assert "含稅" in page.locator('[data-testid="stl-pt-basis-dispatch"]').inner_text()
    # 口徑說明一句話＋ⓘ（可聚焦、有 aria-label、title 帶完整稅基矩陣）
    note = page.locator('[data-testid="stl-basis-note"]').inner_text()
    assert "原始總成本為未稅" in note and "原始毛利已另扣進項稅 5%" in note and "含稅（估計 ×1.05）" in note, note
    info = page.locator('[data-testid="stl-basis-info"]')
    assert (info.get_attribute("aria-label") or "").startswith("口徑說明") and "含稅最終金額" in (info.get_attribute("title") or "")
    info.focus()
    assert page.evaluate("() => document.activeElement && document.activeElement.dataset.testid") == "stl-basis-info"
    # 總結區塊文案：原始／精算後的成本與毛利口徑寫在副標；列標籤（獎金明細逐字對照）不變
    cost_row = page.locator('[data-testid="stl-b1-cost"]').inner_text()
    assert "實際總成本" in cost_row and "未稅" in cost_row and "含稅" in cost_row, cost_row
    assert "進項稅 5%" in page.locator('[data-testid="stl-b1-gp"]').inner_text()


@pytest.mark.e2e
def test_manual_cost_shows_its_tax_mode_and_the_server_tax_basis_wins_when_present(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    before = page.evaluate(f"() => ({{...{S}.summary}})")
    # 手填：稅別三種各自的說明（只換說明文字；金額照原本的換算）
    for mode, text in (("pretax", "手填未稅（原值）"), ("taxed", "÷1.05"), ("taxed_gross", "×1.05")):
        page.evaluate(f"""() => {{ const d = {S}; const a = d.settlement.items[0]; a.adoptSystem = false; a.actualCostTaxMode = '{mode}'; a.actualUnitCost = 1000; d.calcItemCost(a); d.calcSummary() }}""")
        assert text in page.locator('[data-testid="stl-basis-a"]').inner_text(), (mode, page.locator('[data-testid="stl-basis-a"]').inner_text())
    # 伺服器之後回 taxBasis ⇒ 以它為準（沒回就用常數）
    page.evaluate(f"""() => {{ const d = {S}; d.settlement.items[0].actualUnitCost = null; d.calcItemCost(d.settlement.items[0]); d.calcSummary(); d.actuals = Object.assign({{}}, d.actuals, {{ taxBasis: {{ itemEstimate: {{ label: '伺服器稅基' }} }} }}) }}""")
    assert "伺服器稅基" in page.locator('[data-testid="stl-basis-a"]').inner_text()
    # 數字：清除手填後回到加標示前的數字
    after = page.evaluate(f"() => ({{...{S}.summary}})")
    assert after["itemActualTotal"] == before["itemActualTotal"] and after["totalActualCost"] == before["totalActualCost"], (before, after)


@pytest.mark.e2e
def test_each_tax_tag_text_comes_from_the_server_value_when_present(live_server, make_user, e2e_browser):
    """前端內部鍵 ⇒ 伺服器 TAX_BASIS 鍵（estimate⇒itemEstimate、po⇒purchase、remit⇒remitFee、custom⇒customExpense，其餘同名）：
    伺服器有值就用它的 label；沒有才退回常數。逐鍵覆蓋驗證。"""
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, sa)
    server = page.evaluate(f"() => ({{...{S}.actuals.taxBasis}})")
    pairs = {"estimate": "itemEstimate", "po": "purchase", "material": "material", "extra": "extra", "dispatch": "dispatch", "remit": "remitFee", "custom": "customExpense"}
    # 真實伺服器回的值：每個內部鍵取到的就是伺服器對應鍵的 label（不是前端常數）
    for fe, sv in pairs.items():
        assert page.evaluate(f"() => {S}.taxBasis('{fe}')") == server[sv]["label"], (fe, sv)
    # 逐鍵覆蓋：換成獨特字串，取到的必須是覆蓋值
    ov = {sv: {"label": "覆蓋-" + sv} for sv in pairs.values()}
    page.evaluate(f"() => {{ const d = {S}; d.actuals = Object.assign({{}}, d.actuals, {{ taxBasis: {json.dumps(ov)} }}) }}")
    for fe, sv in pairs.items():
        assert page.evaluate(f"() => {S}.taxBasis('{fe}')") == "覆蓋-" + sv, (fe, sv)
    # 畫面：品項估計列、未對應材料／額外列與賺賠表額外列都跟著覆蓋值
    assert "覆蓋-itemEstimate" in page.locator('[data-testid="stl-basis-a"]').inner_text()
    assert "覆蓋-material" in page.locator('[data-testid="stl-kindbasis-material-X"]').inner_text()
    assert "覆蓋-extra" in page.locator('[data-testid^="stl-kindbasis-extra-"]').first.inner_text()
    assert "覆蓋-extra" in page.locator('[data-testid="stl-pt-basis-extra"]').inner_text()
    # 伺服器沒回 taxBasis（舊後端）⇒ 常數
    page.evaluate(f"() => {{ const d = {S}; const a = Object.assign({{}}, d.actuals); delete a.taxBasis; d.actuals = a }}")
    assert page.evaluate(f"() => {S}.taxBasis('estimate')") == "含稅 ×1.05（假設不可扣抵）"
    assert page.evaluate(f"() => {S}.taxBasis('remit')") == "實付金額（不分稅）"
