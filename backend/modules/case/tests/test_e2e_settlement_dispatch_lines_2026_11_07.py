"""精算「二之二、承攬商派發逐行對應」瀏覽器端對端（一題連續流程；規格 DISPATCH-LINE-LINKAGE-PROPOSAL.md V9／V13／V15）：
展開行 → 整行選品項（金額含累計進位稅額）→ 拆分（餘額即時、填入餘額、平分、Σ>行紅字且不能存檔）→ 與整張對應互斥（停用／清除／確認）→
存檔後 offsets 含拆分份 amount（數字）、重載仍在、只改金額會被當成未存變更 → 完結不被 409、完結後唯讀；不可逐行的派發單顯示原因。
終點以資料庫與頁面狀態為準。"""
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

from modules.case import dispatch_lines as DL  # noqa: E402
from modules.case.tests.test_e2e_settlement_actuals_2026_10_03 import NO, _seed, _settlement  # noqa: E402
from modules.case.tests.test_settlement_dispatch_lines_2026_11_07 import _lines, _set_items  # noqa: E402
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch  # noqa: E402

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "logs", "e2e-shots", "wip-dispatch-lines")
S = "Alpine.$data(document.body)"


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.evaluate("() => document.querySelector('[data-testid=\"stl-dl-card\"]').scrollIntoView({block: 'start'})")
    page.screenshot(path=os.path.join(SHOTS, "dl-%s.png" % name), full_page=False)


def _ready(page, live_server):
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.locator('[data-testid="stl-dl-card"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.summary.totalActualCost > 0", timeout=20000)


def _refreshed(page):
    """每次對應變動都會重取預覽；等它跑完。"""
    page.wait_for_function(f"() => {S}._actualsOk", timeout=15000)


@pytest.mark.e2e
def test_dispatch_lines_map_split_and_finalize(live_server, make_user, e2e_browser):
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    d1 = _dispatch(6000, 0, quote_no=NO)                                    # 三行 1000／2000／3000，稅 5%：行稅額累計進位 50／100／150
    _set_items(d1, _lines([1000, 2000, 3000]))
    k1 = DL.line_key(_lines([1000, 2000, 3000])[1]["id"])                      # 第 2 行的行鍵（頁面也是取後端回的同一個）
    d2 = _dispatch(3000, 0, quote_no=NO)                                    # 各行加總 2000≠總額 3000：只能整張對應
    _set_items(d2, _lines([1000, 1000], base_id=1740000000000.25))
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1300}).new_page()
    page.on("dialog", lambda d: d.accept())                                  # 切換整張／逐行的確認一律同意（取消路徑另測）
    _login(page, live_server, *sa)
    _ready(page, live_server)

    # ── 1. 卡片：兩張派發單；展開 d1 看到三行；d2 顯示不可逐行的原因
    assert page.locator('[data-testid^="stl-dl-disp-"]').count() == 2
    page.locator(f'[data-testid="stl-dl-toggle-{d2}"]').click()
    assert "不能逐行對應" in page.locator(f'[data-testid="stl-dl-reason-{d2}"]').inner_text()
    page.locator(f'[data-testid="stl-dl-toggle-{d1}"]').click()
    assert page.locator(f'[data-testid^="stl-dl-line-{d1}-"]').count() == 3
    assert "50" in page.locator(f'[data-testid="stl-dl-line-{d1}-0"]').inner_text() and "1,050" in page.locator(f'[data-testid="stl-dl-line-{d1}-0"]').inner_text()
    assert page.evaluate(f"() => {S}.actuals.totals.dispatchTotal") == 6300 + 3150
    _shot(page, "1-expanded")

    # ── 2. 整行：第 1 行 → 品項 a（採用 ⇒ 吸收 1050）；二之一多一列已對應、剩餘一列未對應；總成本守恆
    page.locator(f'[data-testid="stl-dl-select-{d1}-0"]').select_option("a")
    page.wait_for_function(f"() => {S}.summary.dispatchAbsorbed === 1050", timeout=10000)
    t = page.evaluate(f"() => {S}.actuals.totals")
    assert t["dispatchAssignedTotal"] == 1050 and abs(t["dispatchAssignedTotal"] + t["dispatchUnassignedTotal"] - t["dispatchTotal"]) < 1e-6
    assert page.locator('[data-testid^="stl-mapped-dispatch-"]').count() == 1 and "逐行對應" in page.locator('[data-testid^="stl-linepart-dispatch-"]').first.inner_text()
    assert page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').count() == 1 and page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').is_disabled()   # 剩餘列不能再選整張
    assert "已逐行對應 1 / 3 行" in page.locator(f'[data-testid="stl-dl-summary-{d1}"]').inner_text()

    # ── 3. 拆分第 2 行（2000，稅 100）：品項 b 1200＋品項 a 500，餘額 300 即時顯示
    page.locator(f'[data-testid="stl-dl-split-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-editor-{d1}-1"]').wait_for(state="visible")
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-0"]').select_option("b")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').fill("1200")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').press("Tab")
    _refreshed(page)
    page.locator(f'[data-testid="stl-dl-add-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-1"]').select_option("a")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').fill("500")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').press("Tab")
    page.wait_for_function(f"() => {S}.offsets.filter(o => o.ref.split('#').length === 3).length === 2", timeout=10000)
    rem = page.locator(f'[data-testid="stl-dl-remainder-{d1}-1"]')
    assert "尚未分配餘額 NT$ 300" in rem.inner_text(), rem.inner_text()
    assert "稅額" in page.locator(f'[data-testid="stl-dl-part-gross-{d1}-1-0"]').inner_text()
    offs = page.evaluate(f"() => {S}.offsets.filter(o => o.amount !== undefined)")
    assert sorted(o["amount"] for o in offs) == [500, 1200] and all(isinstance(o["amount"], (int, float)) for o in offs)
    t = page.evaluate(f"() => {S}.actuals.totals")
    assert abs(t["dispatchAssignedTotal"] + t["dispatchUnassignedTotal"] - t["dispatchTotal"]) < 1e-6 and t["dispatchAssignedTotal"] > 1050
    _shot(page, "2-split")

    # ── 4. 填入餘額 → 餘額 0；改成超過 → 紅字＋不能存檔（資料庫沒有被寫入）；平分 → 兩份各 1000
    page.locator(f'[data-testid="stl-dl-fill-{d1}-1-1"]').click()
    page.wait_for_function(f"() => {S}.dlRows('{d1}', '{k1}')[1].amount === '800'", timeout=10000)
    assert "尚未分配餘額 NT$ 0" in rem.inner_text()
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').fill("900")
    assert "超過行金額 NT$ 100" in rem.inner_text() and rem.evaluate("e => getComputedStyle(e).color") == "rgb(185, 28, 28)"
    assert page.evaluate(f"() => {S}.dlInvalid()")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').press("Tab")
    puts = []
    page.on("request", lambda rq: puts.append(rq.url) if rq.method == "PUT" and "/settlement" in rq.url else None)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_timeout(800)
    assert puts == [], "超過行金額時前端不該送出存檔請求：%s" % puts
    assert not _settlement().get("offsets"), "超過行金額時不應該存檔"
    page.locator(f'[data-testid="stl-dl-even-{d1}-1"]').click()
    page.wait_for_function(f"() => {S}.dlRows('{d1}', '{k1}').every(r => r.amount === '1000')", timeout=10000)
    assert "尚未分配餘額 NT$ 0" in rem.inner_text() and page.evaluate(f"() => {S}.dlInvalid()") == ""

    # ── 5. 與整張對應互斥：已有拆分時直接整張對應（setOffset，UI 的整張下拉此時是停用的）⇒ 逐行被清；再逐行選品項（確認）⇒ 整張被取消；清除鈕 ⇒ 逐行全清、整張下拉恢復
    assert page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').is_disabled()
    page.evaluate(f"() => {S}.setOffset('dispatch', '{d1}', 'a')")
    page.wait_for_function(f"() => !{S}.dlHasLineOffsets('{d1}') && {S}.offsets.some(o => o.ref === '{d1}')", timeout=10000)
    page.locator(f'[data-testid="stl-dl-whole-{d1}"]').wait_for(state="attached", timeout=10000)
    assert "整張對應到" in page.locator(f'[data-testid="stl-dl-whole-{d1}"]').inner_text()
    page.locator(f'[data-testid="stl-dl-select-{d1}-2"]').select_option("b")
    page.wait_for_function(f"() => !{S}.offsets.some(o => o.ref === '{d1}') && {S}.offsets.some(o => o.ref.startsWith('{d1}#'))", timeout=10000)
    page.locator(f'[data-testid="stl-un-dispatch-{d1}"]').wait_for(state="attached", timeout=10000)      # 只歸了第 3 行，剩餘仍未對應（等預覽重取完）
    page.locator(f'[data-testid="stl-dl-clear-{d1}"]').click()
    page.wait_for_function(f"() => !{S}.dlHasLineOffsets('{d1}')", timeout=10000)
    page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').wait_for(state="attached", timeout=10000)
    assert page.locator(f'[data-testid="stl-offset-dispatch-{d1}"]').is_enabled()

    # ── 6. 重建最終對應（行1→a、行2 拆 b 1200＋a 800、行3→b），存草稿 ⇒ offsets 含 amount 數字；重載仍在
    page.locator(f'[data-testid="stl-dl-select-{d1}-0"]').select_option("a")
    page.locator(f'[data-testid="stl-dl-split-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-0"]').select_option("b")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').fill("1200")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').press("Tab")
    page.locator(f'[data-testid="stl-dl-add-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-1"]').select_option("a")
    page.locator(f'[data-testid="stl-dl-fill-{d1}-1-1"]').click()
    page.wait_for_function(f"() => {S}.offsets.filter(o => o.ref.split('#').length === 3).length === 2 && !{S}.dlInvalid()", timeout=10000)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    saved = _settlement()["offsets"]
    parts = sorted((o["amount"] for o in saved if "amount" in o))
    assert parts == [800, 1200] and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in parts), saved
    assert page.evaluate(f"() => {S}.dirtyList.length") == 0
    total_after = page.evaluate(f"() => {S}.actuals.totals")
    page.reload()
    page.locator('[data-testid="stl-dl-card"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk && {S}.offsets.filter(o => o.amount !== undefined).length === 2", timeout=20000)
    assert sorted(page.evaluate(f"() => {S}.offsets.filter(o => o.amount !== undefined).map(o => o.amount)")) == [800, 1200]       # 載入沒有把 amount 丟掉（V13）
    assert page.evaluate(f"() => {S}.actuals.totals.dispatchAssignedTotal") == total_after["dispatchAssignedTotal"]
    page.locator(f'[data-testid="stl-dl-toggle-{d1}"]').click()
    assert page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').input_value() == "1200" and page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').input_value() == "800"
    # 只改金額（品項不變）也要被當成未存變更（指紋含 amount）
    assert page.evaluate(f"() => {S}.dirtyList.length") == 0
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').fill("700")
    page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-1"]').press("Tab")
    page.wait_for_function(f"() => {S}.dirtyList.length > 0", timeout=10000)
    page.locator(f'[data-testid="stl-dl-fill-{d1}-1-1"]').click()                               # 填回 800 ⇒ 與存檔相同 ⇒ 不再算未存變更
    page.wait_for_function(f"() => {S}.dirtyList.length === 0", timeout=10000)

    # ── 7. 完結：頁面 summary 與後端重算一致（不被 409）；完結後唯讀
    page.locator('[data-testid="stl-finalize"]').click()
    page.get_by_role("button", name="確認完結").click()
    page.wait_for_function(f"() => {S}.settlement.status === 'finalized' && !{S}.saving", timeout=15000)
    fin = _settlement()
    assert fin["status"] == "finalized" and sorted(o["amount"] for o in fin["offsets"] if "amount" in o) == [800, 1200]
    assert page.locator(f'[data-testid="stl-dl-select-{d1}-0"]').is_disabled() and page.locator(f'[data-testid="stl-dl-split-{d1}-0"]').count() == 1
    assert not page.locator(f'[data-testid="stl-dl-split-{d1}-0"]').is_visible() and not page.locator(f'[data-testid="stl-dl-clear-{d1}"]').is_visible()
    assert page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]').is_disabled()
    _shot(page, "3-finalized")


@pytest.mark.e2e
def test_ignored_mappings_are_visible_and_bad_amount_text_is_not_misread(live_server, make_user, e2e_browser):
    """K 審：①金額欄打「1,000」不能被當成 1（格式不對 ⇒ 不寫進 offsets、不能存檔，訊息講清楚）；
    ②存檔後派發單被改、拆分超過行金額（整行拆分忽略、錢回未對應）⇒ 畫面要看得到（二之二警示＋完結提醒分開講），但不擋完結。"""
    sa = make_user(username="sa_sa", role="superadmin")
    _seed()
    d1 = _dispatch(6000, 0, quote_no=NO)
    _set_items(d1, _lines([1000, 2000, 3000]))
    k1 = DL.line_key(_lines([1000, 2000, 3000])[1]["id"])
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1300}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, live_server, *sa)
    _ready(page, live_server)
    page.locator(f'[data-testid="stl-dl-toggle-{d1}"]').click()
    page.locator(f'[data-testid="stl-dl-split-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-0"]').select_option("b")
    amt = page.locator(f'[data-testid="stl-dl-part-amt-{d1}-1-0"]')
    amt.fill("1,000")
    amt.press("Tab")
    _refreshed(page)
    assert page.evaluate(f"() => {S}.offsets.filter(o => o.amount !== undefined).length") == 0          # 「1,000」沒有被讀成 1 寫進去
    assert "金額格式不對" in page.evaluate(f"() => {S}.dlInvalid()")
    puts = []
    page.on("request", lambda rq: puts.append(rq.url) if rq.method == "PUT" and "/settlement" in rq.url else None)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_timeout(800)
    assert puts == []
    amt.fill("1200")
    amt.press("Tab")
    page.locator(f'[data-testid="stl-dl-add-{d1}-1"]').click()
    page.locator(f'[data-testid="stl-dl-part-item-{d1}-1-1"]').select_option("a")
    page.locator(f'[data-testid="stl-dl-fill-{d1}-1-1"]').click()
    page.wait_for_function(f"() => {S}.offsets.filter(o => o.amount !== undefined).length === 2 && !{S}.dlInvalid()", timeout=10000)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function(f"() => !{S}.saving", timeout=15000)
    assert sorted(o["amount"] for o in _settlement()["offsets"] if "amount" in o) == [800, 1200]
    assert page.locator('[data-testid="stl-dl-warnings"]').is_hidden()

    # 派發單被改：第 2 行 2000→1500（第 1 行補 500，總額不變仍可逐行）⇒ Σ份 2000 > 1500，拆分忽略
    _set_items(d1, _lines([1500, 1500, 3000]))
    page.reload()
    page.locator('[data-testid="stl-dl-card"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {S}._actualsOk", timeout=20000)
    w = page.locator('[data-testid="stl-dl-warnings"]')
    w.wait_for(state="visible", timeout=10000)
    assert "未生效" in w.inner_text() and "拆分金額加總超過" in w.inner_text(), w.inner_text()
    ready = page.locator('[data-testid="stl-ready"]').inner_text()
    assert "逐行對應有 1 處未生效" in ready and "未對應項目" in ready, ready          # 與一般「有未對應項目」分開講
    assert page.locator('[data-testid="stl-finalize"]').is_enabled()                  # 只警示、不擋完結（與 V5／BLOCK_ON_UNASSIGNED 一致）
    t = page.evaluate(f"() => {S}.actuals.totals")
    assert abs(t["dispatchAssignedTotal"] + t["dispatchUnassignedTotal"] - t["dispatchTotal"]) < 1e-6 and t["dispatchAssignedTotal"] == 0      # 錢全回未對應
