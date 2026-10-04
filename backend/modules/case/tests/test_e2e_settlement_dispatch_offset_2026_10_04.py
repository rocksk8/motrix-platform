"""36 瀏覽器端對端（一題連續流程）：承攬商派發回推報價單——未對應列（色塊／未稅金額／稅額／待審核）→ 對應到品項（規則 A 取代估計，
不重複計入總成本）→ 頁面總成本＝後端 totals.totalActualCost → 存草稿重開還在 → 取消／不採用時總成本回到基準（守恆）→ 完結 200（不被 409）→ 唯讀。
終點以資料庫與頁面狀態為準；截圖存 logs/e2e-shots/wip-t36-dispatch-fe。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed, _settlement  # noqa: E402
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-t36-dispatch-fe")
S = "Alpine.$data(document.body)"


def _shot(page, name, full=False):
    os.makedirs(SHOTS, exist_ok=True)
    if name[0] in "123":
        page.evaluate("() => document.querySelector('[data-testid=\"stl-unassigned\"]').scrollIntoView({block: 'start'})")
    page.screenshot(path=os.path.join(SHOTS, "36-%s.png" % name), full_page=full)


def _tot(page):
    return page.evaluate(f"() => ({{...{S}.summary}})")


@pytest.mark.e2e
def test_dispatch_rows_map_to_items_without_double_counting_and_finalize_passes(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    d1 = _dispatch(10000, 2000, quote_no=NO)                       # report 12000、稅 500（已核准）
    d2 = _dispatch(3000, 0, approval="待審核", quote_no=NO)        # report 3000、待審核（照計）
    _dispatch(999, 0, status="cancelled", quote_no=NO)             # 不計
    _dispatch(888, 0, approval="草稿", quote_no=NO)                # 不計
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1100}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)

    # ── 1. 未對應：兩張派發（取消、草稿不算），類型色塊、未稅金額粗體、稅額灰字、待審核徽章
    r1 = page.locator(f'[data-testid="stl-un-dispatch-{d1}"]')
    r2 = page.locator(f'[data-testid="stl-un-dispatch-{d2}"]')
    assert r1.count() == 1 and r2.count() == 1 and page.locator('[data-testid^="stl-un-dispatch-"]').count() == 2
    assert "承攬商派發" in r1.inner_text() and "12,000" in r1.inner_text() and "稅額 500" in r1.inner_text()
    assert "待審核" in r2.inner_text()
    assert r1.locator("b").first.evaluate("e => getComputedStyle(e).fontWeight") in ("700", "bold")
    bar = page.locator('[data-testid="stl-sumbar"]').inner_text()
    assert "未對應 4 件" in bar, bar                                   # 派發 2＋材料申請 X＋額外支出 1
    s0 = _tot(page)
    assert s0["dispatchTotal"] == 15000 and s0["dispatchAbsorbed"] == 0
    base = s0["totalActualCost"]
    assert base == page.evaluate(f"() => {S}.actuals.totals.totalActualCost")        # 沒有派發對應 ⇒ 與後端逐位相同
    _shot(page, "1-unassigned")

    # ── 2. 對應 d1 → 品項 a（預設採用）：a 實際＝12000 取代估計 10500，總成本＝品項實際＋額外＋派發−被吸收（不重複）
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12000", timeout=10000)
    s1 = _tot(page)
    assert s1["itemActualTotal"] == 12000 + 800 and s1["dispatchTotal"] == 15000
    assert s1["totalActualCost"] == s1["itemActualTotal"] + s1["extraTotal"] + s1["dispatchTotal"] - 12000
    assert page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').count() == 1 and page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').count() == 0
    assert "已對應" in page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').inner_text()
    assert "稅額 500" in page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').inner_text()
    assert page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').evaluate("e => getComputedStyle(e.firstElementChild).backgroundColor") != "rgba(0, 0, 0, 0)"
    assert "來源：已對應" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert "3 件" in page.locator('[data-testid="stl-sumbar"]').inner_text()
    eq = page.locator('[data-testid="stl-conserve"]').inner_text()
    # 守恆：未對應（派發 d2 3000＋材料 X 250＋額外 700）＋已對應（派發 d1 12000＋材料 N 800）＝全部 16750
    assert "未對應 NT$ 3,950 ＋ 已對應 NT$ 12,800 ＝ NT$ 16,750" in eq, eq
    _shot(page, "2-mapped")

    # ── 3. 不採用 ⇒ 估計不變，派發仍以 dispatchTotal 計入 ⇒ 總成本回到基準（互移守恆）
    page.evaluate(f"() => {{ const d = {S}; d.toggleAdopt(d.settlement.items[0]) }}")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 0", timeout=10000)
    assert _tot(page)["totalActualCost"] == base
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    page.evaluate(f"() => {{ const d = {S}; d.toggleAdopt(d.settlement.items[0]) }}")      # 再採用
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12000", timeout=10000)

    # ── 4. 存草稿 ⇒ offsets 含 dispatch；重開還在；頁面總成本＝後端（存檔後後端用存的採用狀態）
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    saved = _settlement()
    assert {"kind": "dispatch", "ref": str(d1), "itemId": "a"} in saved["offsets"], saved["offsets"]
    page.reload()
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.dispatchAbsorbed === 12000", timeout=20000)
    assert page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').input_value() == "a"
    s2 = _tot(page)
    t2 = page.evaluate(f"() => {S}.actuals.totals")
    assert s2["totalActualCost"] == t2["totalActualCost"], (s2, t2)
    if "dispatchAbsorbedTotal" in t2:                             # BE 之後加的 additive 鍵
        assert t2["dispatchAbsorbedTotal"] == 12000

    # ── 5. 取消對應 ⇒ 回未對應、仍計入；總成本＝估計 10500＋派發 15000…（與基準同）
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 0", timeout=10000)
    assert _tot(page)["totalActualCost"] == base
    assert page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').count() == 1
    # 再對應回去，準備完結
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12000", timeout=10000)

    # ── 6. 完結：頁面送的 summary 與後端重算一致（不被 409），完結後全部唯讀並標示
    page.locator('[data-testid="stl-finalize"]').click()
    page.get_by_role("button", name="確認完結").click()
    page.wait_for_function(f"() => {S}.settlement.status === 'finalized' && !{S}.saving", timeout=15000)
    fin = _settlement()
    assert fin["status"] == "finalized" and fin["summary"]["totalActualCost"] == s2["totalActualCost"], fin["summary"]
    assert page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').is_disabled()
    assert "已完結" in page.locator('[data-testid="stl-sumbar"]').inner_text()
    _shot(page, "3-finalized")

    # ── 手機寬度截圖（本頁整體是桌面版型，只留存證）
    page.set_viewport_size({"width": 390, "height": 900})
    page.wait_for_timeout(300)
    page.locator('[data-testid="stl-unassigned"]').scroll_into_view_if_needed()
    _shot(page, "4-phone")


@pytest.mark.e2e
def test_item_without_purchase_shows_hint_manual_actual_with_source_tag_roundtrip(live_server, make_user, e2e_browser):
    """無採購／對應紀錄的品項：醒目提示＋手填實際成本＋來源標籤（手填／歷史未建系統／人力）；標籤純顯示——不進合計，存檔重開還在。"""
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1100}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    # 品項 a 沒有採購／對應 ⇒ 來源＝估計＋提示；品項 b 有材料申請 ⇒ 來源＝已對應、無提示
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert page.locator('[data-testid="stl-nopurchase-a"]').is_visible() and not page.locator('[data-testid="stl-nopurchase-b"]').is_visible()
    assert "來源：已對應" in page.locator('[data-testid="stl-source-b"]').inner_text()
    _shot(page, "5-no-purchase-hint")
    before = _tot(page)["totalActualCost"]
    # 手填實際：單位成本 1000 → 1500（×10 台，含稅 5% 自動加總 ⇒ 15750）；來源標「人力」
    page.evaluate(f"() => {{ const d = {S}; const a = d.settlement.items[0]; a.actualUnitCost = 1500; d.calcItemCost(a); d.calcSummary() }}")
    assert "來源：手填" in page.locator('[data-testid="stl-source-a"]').inner_text()
    mid = _tot(page)["totalActualCost"]
    assert mid == before - 10500 + 15750
    page.locator('[data-testid="stl-actual-source-a"]').select_option("labor")
    assert "手填・人力" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert _tot(page)["totalActualCost"] == mid                       # 標籤不進任何合計
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert [i.get("actualSource") for i in _settlement()["items"]] == ["labor", "manual"]
    page.reload()
    page.wait_for_function(f"() => {S}._actualsOk && {S}.settlement.items.length", timeout=20000)
    assert page.locator('[data-testid="stl-actual-source-a"]').input_value() == "labor"
    assert "手填・人力" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert _tot(page)["totalActualCost"] == mid == page.evaluate(f"() => {S}.actuals.totals.totalActualCost")
    _shot(page, "6-manual-labor")
