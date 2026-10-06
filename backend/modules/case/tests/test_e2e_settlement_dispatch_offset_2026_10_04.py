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
    if name.split("-")[0] in ("1", "2", "3"):
        page.evaluate("() => document.querySelector('[data-testid=\"stl-unassigned\"]').scrollIntoView({block: 'start'})")
    page.screenshot(path=os.path.join(SHOTS, "36-%s.png" % name), full_page=full)


def _tot(page):
    return page.evaluate(f"() => ({{...{S}.summary}})")


@pytest.mark.e2e
def test_dispatch_rows_map_to_items_without_double_counting_and_finalize_passes(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    d1 = _dispatch(10000, 2000, quote_no=NO)                       # 含稅 12500（稅 500）（已核准）
    d2 = _dispatch(3000, 0, approval="待審核", quote_no=NO)        # 含稅 3150、待審核（照計）
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
    assert "承攬商派發" in r1.inner_text() and "12,500" in r1.inner_text() and "稅額 500" in r1.inner_text()
    assert "待審核" in r2.inner_text()
    assert r1.locator("b").first.evaluate("e => getComputedStyle(e).fontWeight") in ("700", "bold")
    bar = page.locator('[data-testid="stl-sumbar"]').inner_text()
    assert "未對應 4 件" in bar, bar                                   # 派發 2＋材料申請 X＋額外支出 1
    s0 = _tot(page)
    assert s0["dispatchTotal"] == 15650 and s0["dispatchAbsorbed"] == 0
    base = s0["totalActualCost"]
    assert base == page.evaluate(f"() => {S}.actuals.totals.totalActualCost")        # 沒有派發對應 ⇒ 與後端逐位相同
    _shot(page, "1-unassigned")

    # ── 2. 對應 d1 → 品項 a（預設採用）：a 實際＝12500 取代估計 10500，總成本＝品項實際＋額外＋派發−被吸收（不重複）
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12500", timeout=10000)
    s1 = _tot(page)
    assert s1["itemActualTotal"] == 12500 + 800 and s1["dispatchTotal"] == 15650
    assert s1["totalActualCost"] == s1["itemActualTotal"] + s1["extraTotal"] + s1["dispatchTotal"] - 12500
    assert page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').count() == 1 and page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').count() == 0
    assert "已對應" in page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').inner_text()
    assert "稅額 500" in page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').inner_text()
    assert page.locator(f'[data-testid="stl-mapped-dispatch-{d1}"]').evaluate("e => getComputedStyle(e.firstElementChild).backgroundColor") != "rgba(0, 0, 0, 0)"
    assert "來源：已對應" in page.locator('[data-testid="stl-source-a"]').inner_text()
    assert "3 件" in page.locator('[data-testid="stl-sumbar"]').inner_text()
    eq = page.locator('[data-testid="stl-conserve"]').inner_text()
    # 守恆：未對應（派發 d2 3150＋材料 X 250＋額外 700）＋已對應（派發 d1 12500＋材料 N 800）＝全部 17400
    assert "未對應 NT$ 4,100 ＋ 已對應 NT$ 13,300 ＝ NT$ 17,400" in eq, eq
    _shot(page, "2-mapped")

    # ── 3. 不採用 ⇒ 估計不變，派發仍以 dispatchTotal 計入 ⇒ 總成本回到基準（互移守恆）
    page.evaluate(f"() => {{ const d = {S}; d.toggleAdopt(d.settlement.items[0]) }}")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 0", timeout=10000)
    assert _tot(page)["totalActualCost"] == base
    assert "來源：估計" in page.locator('[data-testid="stl-source-a"]').inner_text()
    page.evaluate(f"() => {{ const d = {S}; d.toggleAdopt(d.settlement.items[0]) }}")      # 再採用
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12500", timeout=10000)

    # ── 4. 存草稿 ⇒ offsets 含 dispatch；重開還在；頁面總成本＝後端（存檔後後端用存的採用狀態）
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15650)
    saved = _settlement()
    assert {"kind": "dispatch", "ref": str(d1), "itemId": "a"} in saved["offsets"], saved["offsets"]
    page.reload()
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.dispatchAbsorbed === 12500", timeout=20000)
    assert page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').input_value() == "a"
    s2 = _tot(page)
    t2 = page.evaluate(f"() => {S}.actuals.totals")
    assert s2["totalActualCost"] == t2["totalActualCost"], (s2, t2)
    if "dispatchAbsorbedTotal" in t2:                             # BE 之後加的 additive 鍵
        assert t2["dispatchAbsorbedTotal"] == 12500

    # ── 5. 取消對應 ⇒ 回未對應、仍計入；總成本＝估計 10500＋派發 15650…（與基準同）
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 0", timeout=10000)
    assert _tot(page)["totalActualCost"] == base
    assert page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').count() == 1
    # 再對應回去，準備完結
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 12500", timeout=10000)

    # ── 6. 完結：頁面送的 summary 與後端重算一致（不被 409），完結後全部唯讀並標示
    page.locator('[data-testid="stl-finalize"]').click()
    page.get_by_role("button", name="確認完結").click()
    page.wait_for_function(f"() => {S}.settlement.status === 'finalized' && !{S}.saving", timeout=15650)
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


@pytest.mark.e2e
def test_profit_per_item_and_grand_total_table_reconcile_with_discount_row(live_server, make_user, e2e_browser):
    """每品項毛利（報價−實際成本）＋毛利比＋單件毛利；總結表列出每個品項、未對應項目、折扣／調整，加總與總成本對帳差額為 0；淨利只在利潤分析。"""
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    c = db.get_db()
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        d = json.loads(row["data_json"])
        d["tot"] = {"pretax": 20000, "total": 21000}            # 報價收入 20000 ＜ Σ品項報價 21000 ⇒ 折扣／調整 −1000
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1100}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-profit-card"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    # 品項 a：報價 20000、實際＝估計 10500 ⇒ 毛利 9500（47.5%）、單件毛利 2000−1050＝950；品項 b：報價 1000、實際 800（材料申請）⇒ 200（20.0%）、單件 2
    pa = page.locator('[data-testid="stl-profit-a"]').inner_text()
    assert "9,500" in pa and "47.5%" in pa and "單件毛利 950" in pa, pa
    pb = page.locator('[data-testid="stl-profit-b"]').inner_text()
    assert "200" in pb and "20.0%" in pb and "單件毛利 2" in pb, pb
    sizes = page.locator('[data-testid="stl-profit-a"] div').evaluate_all("els => els.map(e => parseFloat(getComputedStyle(e).fontSize))")
    assert sizes[0] > sizes[1] >= sizes[2] and sizes[0] >= 1.4 * sizes[1], sizes             # 毛利金額是這格最醒目的數字
    # 總結表：每個品項一列＋未對應項目（額外支出 700＋未對應材料 250＝950）＋折扣／調整 −1000＋合計
    t = page.locator('[data-testid="stl-profit-table"]')
    assert page.locator('[data-testid="stl-pt-a"]').count() == 1 and page.locator('[data-testid="stl-pt-b"]').count() == 1
    assert "950" in page.locator('[data-testid="stl-pt-un-extra"]').inner_text()
    assert "1,000" in page.locator('[data-testid="stl-pt-adjust"]').inner_text()
    tot = page.locator('[data-testid="stl-pt-total"]').inner_text()
    assert "20,000" in tot and "12,250" in tot and "7,750" in tot, tot                 # 報價 20000、成本 12250、毛利 7750
    s = _tot(page)
    assert s["totalActualCost"] == 12250 and s["grossProfit"] == 7750
    # Σ品項毛利＋（−未對應）＋調整 ＝ 合計毛利；兩條對帳差額 0
    assert 9500 + 200 - 950 - 1000 == s["grossProfit"]
    assert page.locator('[data-testid="stl-recon-quote-gap"]').inner_text().strip() == "0"
    assert page.locator('[data-testid="stl-recon-cost-gap"]').inner_text().strip() == "0"
    assert s["totalActualCost"] == page.evaluate(f"() => {S}.actuals.totals.totalActualCost")        # 與後端同一來源
    # 淨利只在利潤分析區，不在品項卡／品項表
    assert "淨利" not in t.inner_text() and "淨利" not in page.locator('[data-testid="stl-profit-a"]').inner_text()
    page.locator('[data-testid="stl-profit-card"]').scroll_into_view_if_needed()
    _shot(page, "7-profit-table")


@pytest.mark.e2e
def test_grand_total_two_blocks_original_vs_actual_with_headline(live_server, make_user, e2e_browser):
    """總結：標題（最終淨利比原始多／少）＋ ①扣費前（報價／總成本／毛利／毛利比）②扣費後（管理費／公益／最終淨利／淨利比），
    每格＝原始｜精算後｜差額（成本類高為紅）；數字取既有 summary 定義，淨利只出現在總結區塊。"""
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 20000, "total": 21000, "totalCost": 10500 + 525}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1100}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-headline"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    s = _tot(page)
    assert s["quotedPretax"] == 20000 and s["totalActualCost"] == 12250 and s["grossProfit"] == 7750
    assert s["adminCost"] == 2000 and s["charityDonation"] == 78 and s["netProfit"] == 7750 - 2000 - 78 == 5672     # 公益＝halfUp(7750×1%)＝78
    fmt = lambda n: f"{abs(int(n)):,}"
    row = lambda k: page.locator(f'[data-testid="stl-{k}"]').inner_text()
    # ① 扣費前：報價兩邊同、差額 0；總成本精算後 12,250；毛利 7,750；未扣費用淨利＝毛利
    assert fmt(20000) in row("b1-rev"), row("b1-rev")
    assert row("b1-rev").split("\t")[-1].strip() == "0", row("b1-rev")
    assert fmt(12250) in row("b1-cost") and fmt(7750) in row("b1-gp") and fmt(7750) in row("b1-pre")
    assert "38.8%" in row("b1-gpp")                                                       # 7750÷20000
    # ② 扣費後：管理費 2,000、公益 78、最終淨利 5,672、淨利比 28.4%（5672÷20000）
    assert fmt(2000) in row("b2-admin") and fmt(78) in row("b2-ch") and fmt(5672) in row("b2-net") and "28.4%" in row("b2-netp")
    # 差額＝精算−原始，成本類（總成本）上升為紅、下降為綠；與 summary 一致
    cost_diff = s["totalActualCost"] - s["origTotalCost"]
    cost_cell = page.locator('[data-testid="stl-b1-cost"] td:last-child')
    assert (cost_diff == 0) or (cost_cell.evaluate("e => getComputedStyle(e).color") == ("rgb(185, 28, 28)" if cost_diff > 0 else "rgb(21, 128, 61)"))
    # 標題：最終淨利大字＋比原始多／少（與 summary.profitDiff 同號）
    head = page.locator('[data-testid="stl-headline"]').inner_text()
    assert fmt(5672) in head and ("多" if s["profitDiff"] >= 0 else "少") in head and fmt(s["profitDiff"]) in head, (head, s["profitDiff"])
    big = page.locator('[data-testid="stl-net"]').evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    assert big >= 28, big
    # 淨利／管理費只在總結區塊：品項表與品項賺賠表都沒有
    assert "淨利" not in page.locator('[data-testid="stl-profit-table"]').inner_text()
    assert page.locator('[data-testid="stl-block-before"]').is_visible() and page.locator('[data-testid="stl-block-after"]').is_visible()
    page.locator('[data-testid="stl-headline"]').scroll_into_view_if_needed()
    _shot(page, "8-totals-blocks")
    page.set_viewport_size({"width": 700, "height": 1000})
    page.wait_for_timeout(300)
    boxes = [page.locator(f'[data-testid="stl-block-{k}"]').bounding_box() for k in ("before", "after")]
    assert boxes[1]["y"] > boxes[0]["y"] + boxes[0]["height"] - 2, boxes                 # 窄螢幕上下堆疊


@pytest.mark.e2e
def test_management_view_strip_exceptions_readiness_sort_filter_print(live_server, make_user, e2e_browser):
    """管理視角：5 張高階摘要卡＋需處理（可前往）＋完結閘門（未對應只警示、不擋完結；硬性阻擋才停用）＋品項排序／篩選＋列印版面無 sticky。"""
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    _dispatch(10000, 2000, quote_no=NO)
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 20000, "total": 21000, "totalCost": 10500 + 525}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-strip"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    # (a) 5 張摘要卡：報價／總成本／毛利／最終淨利／與原始差額；每張有 title（口徑與來源）
    keys = ["rev", "cost", "gp", "net", "diff"]
    for k in keys:
        card = page.locator(f'[data-testid="stl-k-{k}"]')
        assert card.is_visible() and card.get_attribute("title"), k
    assert "20,000" in page.locator('[data-testid="stl-k-rev"]').inner_text()
    page.evaluate("() => window.scrollTo(0, 1200)")
    top = page.locator('[data-testid="stl-strip"]').bounding_box()["y"]
    assert 40 < top < 200, top                                             # sticky：捲動後仍貼在工具列下方
    page.evaluate("() => window.scrollTo(0, 0)")
    # (b) 需處理：未對應（派發 d1 ＋ 材料 X ＋ 額外）、品項 b 毛利比比原始低 27.5pp、a／b 以外無虧損；折扣／調整
    assert page.locator('[data-testid="stl-exc-unassigned"]').is_visible()
    assert page.locator('[data-testid="stl-exc-drop-b"]').is_visible() and "27.5" in page.locator('[data-testid="stl-exc-drop-b"]').inner_text()
    assert page.locator('[data-testid="stl-exc-adjust"]').is_visible()
    page.locator('[data-testid="stl-exc-drop-b"] button').click()
    page.wait_for_timeout(800)
    row_b = page.locator("#stl-row-b").bounding_box()
    assert 0 <= row_b["y"] <= 900, row_b                                   # 「前往」捲到該列
    page.evaluate("() => window.scrollTo(0, 0)")
    # 完結閘門：未對應只警示、不擋完結（使用者裁示）
    ready = page.locator('[data-testid="stl-ready"]')
    assert ready.get_attribute("data-state") == "warn" and "有未對應項目（仍計入成本）" in ready.inner_text() and "不可完結" not in ready.inner_text()
    assert page.locator('[data-testid="stl-finalize"]').is_enabled()
    # 硬性阻擋才停用：把政策旗標改成「未對應擋完結」（單一設定處），按鈕停用並顯示原因
    page.evaluate(f"() => {{ STL_CONFIG.BLOCK_ON_UNASSIGNED = true; const d = {S}; d.summary = {{...d.summary}} }}")
    page.wait_for_function("() => document.querySelector('[data-testid=\"stl-ready\"]').dataset.state === 'blocked'", timeout=5000)
    assert page.locator('[data-testid="stl-finalize"]').is_disabled() and "不可完結" in page.locator('[data-testid="stl-ready"]').inner_text()
    assert "未對應" in (page.locator('[data-testid="stl-finalize"]').get_attribute("title") or "")
    page.evaluate(f"() => {{ STL_CONFIG.BLOCK_ON_UNASSIGNED = false; const d = {S}; d.summary = {{...d.summary}} }}")
    page.wait_for_function("() => document.querySelector('[data-testid=\"stl-ready\"]').dataset.state === 'warn'", timeout=5000)
    # (c) 品項賺賠表：篩選「虧損／低於原始」只剩 b；排序依毛利（高→低）a 在前、再點一次變 b 在前
    page.locator('[data-testid="stl-pf-loss"]').click()
    assert page.locator('[data-testid^="stl-pt-"][data-testid$="-a"], [data-testid="stl-pt-a"]').count() == 0 and page.locator('[data-testid="stl-pt-b"]').count() == 1
    page.locator('[data-testid="stl-pf-all"]').click()
    order = lambda: page.locator('[data-testid="stl-profit-table"] tbody tr[data-testid^="stl-pt-"]:not([data-testid^="stl-pt-un-"]):not([data-testid="stl-pt-adjust"]):not([data-testid="stl-pt-total"])').evaluate_all("els => els.map(e => e.dataset.testid)")
    page.locator('[data-testid="stl-sort-gp"]').click()
    assert order() == ["stl-pt-a", "stl-pt-b"], order()
    page.locator('[data-testid="stl-sort-gp"]').click()
    assert order() == ["stl-pt-b", "stl-pt-a"], order()
    # (e) 稽核頁尾：口徑、狀態、凍結時間
    assert "草稿" in page.locator('[data-testid="stl-audit-status"]').inner_text()
    # 列印：A4 版面不用 sticky／固定列、隱藏工具列
    page.emulate_media(media="print")
    assert page.locator('[data-testid="stl-strip"]').evaluate("e => getComputedStyle(e).position") == "static"
    assert page.locator(".stl-toolbar").evaluate("e => getComputedStyle(e).display") == "none"
    page.emulate_media(media="screen")
    # 有未對應項目照樣可完結（伺服器不擋）
    page.locator('[data-testid="stl-finalize"]').click()
    page.get_by_role("button", name="確認完結").click()
    page.wait_for_function(f"() => {S}.settlement.status === 'finalized' && !{S}.saving", timeout=15000)
    assert _settlement()["status"] == "finalized"
    assert "已完結" in page.locator('[data-testid="stl-audit-status"]').inner_text()
    page.evaluate("() => window.scrollTo(0, 0)")
    _shot(page, "9-management-view")


@pytest.mark.e2e
def test_summary_charts_exist_and_match_table_numbers(live_server, make_user, e2e_browser):
    """總結三張圖（橋接／原始 vs 精算後／各品項毛利）：inline SVG 存在，關鍵長條的值＝表格與 summary 同一組數字；虧損品項紅色＋✖；窄螢幕不撐破。"""
    import db
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 20000, "total": 21000, "totalCost": 10500 + 525}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, live_server, *sa)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-charts"]').wait_for(state="attached", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)
    v = lambda tid: float(page.locator(f'[data-testid="{tid}"]').get_attribute("data-v"))
    s = _tot(page)
    assert all(page.locator(f'svg[data-testid="{t}"]').count() == 1 for t in ("stl-ch-bridge", "stl-ch-pair", "stl-ch-items"))
    # ① 橋接：報價 20000、品項成本 11300、額外 950、毛利 7750、管理費 2000、公益 78、淨利 5672；扣減各段加總＝總成本
    assert v("stl-ch-bridge-rev") == s["quotedPretax"] == 20000
    assert v("stl-ch-bridge-gp") == s["grossProfit"] == 7750 and v("stl-ch-bridge-net") == s["netProfit"] == 5672
    assert v("stl-ch-bridge-admin") == s["adminCost"] == 2000 and v("stl-ch-bridge-ch") == s["charityDonation"] == 78
    parts = page.locator('[data-testid^="stl-ch-bridge-c-"]').evaluate_all("els => els.map(e => +e.dataset.v)")
    assert sum(parts) == s["totalActualCost"] == 12250, parts
    assert v("stl-ch-bridge-c-items") == s["itemActualTotal"]
    # 圖上的文字＝表格上的數字
    assert "5,672" in page.locator('[data-testid="stl-ch-bridge"]').text_content() and "5,672" in page.locator('[data-testid="stl-b2-net"]').inner_text()
    # ② 原始 vs 精算後：值＝summary；成本上升有 ▲ 文字（不只靠顏色）
    assert v("stl-ch-pair-cost-a") == s["totalActualCost"] and v("stl-ch-pair-cost-o") == s["origTotalCost"]
    assert v("stl-ch-pair-gp-a") == s["grossProfit"] and v("stl-ch-pair-net-a") == s["netProfit"]
    ptxt = page.locator('[data-testid="stl-ch-pair"]').text_content()
    assert ("▲" in ptxt) or ("▼" in ptxt), ptxt
    # ③ 各品項：a 9500、b 200；先排序高→低
    assert v("stl-ch-items-i-a") == 9500 and v("stl-ch-items-i-b") == 200
    rows = page.locator('[data-testid="stl-ch-items"] g[data-row]').evaluate_all("els => els.map(e => e.dataset.row)")
    assert rows == ["i-a", "i-b"], rows
    page.evaluate("() => document.querySelector('[data-testid=\"stl-charts\"]').scrollIntoView({block: 'start'})")
    page.evaluate("() => window.scrollBy(0, -170)")
    page.wait_for_timeout(200)
    _shot(page, "10-charts")
    # 虧損：b 不採用＋手填單位成本 20（×100 米×1.05＝2100 ＞ 報價 1000）⇒ 毛利 −1100：長條紅色＋✖
    page.evaluate(f"() => {{ const d = {S}; const b = d.settlement.items[1]; b.adoptSystem = false; b.actualUnitCost = 20; d.calcItemCost(b); d.calcSummary() }}")
    page.wait_for_function(f"() => {S}.itemProfit({S}.settlement.items[1]) === -1100", timeout=5000)
    assert v("stl-ch-items-i-b") == -1100
    assert page.locator('[data-testid="stl-ch-items-i-b"]').evaluate("e => getComputedStyle(e).fill") == "rgb(185, 28, 28)"        # --danger（走 token，不寫死色碼）
    assert "✖" in page.locator('[data-testid="stl-ch-items"]').text_content()
    assert v("stl-ch-bridge-gp") == _tot(page)["grossProfit"]
    # 窄螢幕：圖縮放不超出容器
    page.set_viewport_size({"width": 420, "height": 900})
    page.wait_for_timeout(300)
    widths = page.locator('[data-testid="stl-charts"] svg').evaluate_all("els => els.map(e => e.getBoundingClientRect().width <= e.parentElement.getBoundingClientRect().width + 1)")
    assert all(widths), widths
