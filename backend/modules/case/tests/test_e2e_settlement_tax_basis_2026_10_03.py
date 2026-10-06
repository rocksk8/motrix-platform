# -*- coding: utf-8 -*-
"""35c 稅基 B 的畫面（真瀏覽器）：精算頁承攬商成本＝未稅＋外包人員、稅額透明並列、草稿的一行說明（可「知道了」）、舊完結案維持含稅口徑並有中性說明，
三處「過期」比對（精算頁、案件頁財務分頁；報表在 analytics 測試）口徑對口徑、不誤報。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401
from modules.case.tests.test_e2e_settlement_assigned_list_2026_10_03 import NO, open_page, seed  # noqa: E402
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch as _dispatch_for  # noqa: E402


def _dispatch(total=10000, personnel=2000, **kw):
    return _dispatch_for(total, personnel, quote_no=NO, **kw)


pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")
S = "Alpine.$data(document.body)"
CM = "Alpine.$data(document.querySelector('[x-data]'))"


def _set_settlement(settlement):
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["settlement"] = settlement
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()


def _txt(page, testid):
    return " ".join(page.locator('[data-testid="%s"]' % testid).inner_text().split())


@pytest.mark.e2e
def test_draft_shows_tax_inclusive_cost_with_the_tax_split(live_server, make_user, e2e_browser):
    """【2026-10-06 改：精算全含稅；原 35c 為未稅＋可關閉的一行說明】"""
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert page.evaluate("() => %s.summary.dispatchTotal" % S) == 12500
    assert page.evaluate("() => %s.summary.dispatchBasis" % S) == "taxed" and page.evaluate("() => %s.summary.dispatchTax" % S) == 500
    assert "12,500" in _txt(page, "stl-dispatch-subtotal") and "500" in _txt(page, "stl-dispatch-tax-total")
    split = _txt(page, "stl-dispatch-split")
    for part in ("未稅承攬費 NT$ 10,000", "稅額 NT$ 500", "外包人員 NT$ 2,000", "計入成本 NT$ 12,500"):
        assert part in split, (part, split)
    for tid in ("stl-dispatch-convert-banner", "stl-dispatch-old-basis-note"):
        assert page.locator('[data-testid="%s"]' % tid).count() == 0, tid


@pytest.mark.e2e
def test_old_finalized_case_without_a_marker_keeps_its_stored_tax_inclusive_numbers_and_no_false_stale(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 11025, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 23525}})
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert "12,500" in _txt(page, "stl-dispatch-subtotal") and page.evaluate("() => %s.summary.dispatchTotal" % S) == 12500     # 與完結當下存的數字逐位相同
    assert page.evaluate("() => %s.summary.dispatchBasis" % S) == "taxed"
    assert page.locator('[data-testid="stl-dispatch-old-basis-note"]').count() == 0 and page.locator('[data-testid="stl-dispatch-convert-banner"]').count() == 0
    assert page.locator(".stale-banner").count() == 0, "含稅完結案：存檔 12,500 與含稅現算 12,500 相同，不可以誤報過期"


@pytest.mark.e2e
def test_35c_finalized_case_stays_pretax_frozen_with_a_note_compares_pretax_and_still_detects_real_changes(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 11025, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 23025,
                                                                                   "dispatchBasis": "pretax"}})
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert "12,000" in _txt(page, "stl-dispatch-subtotal") and page.evaluate("() => %s.summary.dispatchBasis" % S) == "pretax"
    note = _txt(page, "stl-dispatch-old-basis-note")
    assert "35c 的未稅口徑" in note and "已完結的數字不改寫" in note, note
    assert page.locator(".stale-banner").count() == 0
    # 完結後承攬商成本真的異動 ⇒ 仍會提醒（未稅對未稅）
    _dispatch(1000, 0)
    page.reload()
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert page.locator(".stale-banner").count() == 1 and "13,000" in page.locator(".stale-banner").inner_text()


@pytest.mark.e2e
def test_a_35c_pretax_draft_stays_pretax_until_converted_and_cannot_finalize_before(live_server, make_user, e2e_browser):
    """Q5：35c 期間存的草稿（標記 pretax）打開維持未稅＋橫幅；完結鈕停用；按「轉為含稅口徑」後合計變含稅、可存檔、標記變 taxed、可完結。"""
    import db
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    _set_settlement({"status": "draft", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 12001,
                                                                               "dispatchBasis": "pretax"}})
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    page.wait_for_function("() => %s.summary && %s._actualsOk && !%s.loading" % (S, S, S), timeout=20000)
    assert page.evaluate("() => %s.summary.dispatchTotal" % S) == 12000 and page.evaluate("() => %s.summary.dispatchBasis" % S) == "pretax"
    banner = _txt(page, "stl-dispatch-convert-banner")
    assert "12,000" in banner and "12,500" in banner and "完結前必須轉換" in banner, banner
    assert page.locator('[data-testid="stl-finalize"]').is_disabled()
    page.locator('[data-testid="stl-dispatch-convert"]').click()
    assert page.evaluate("() => %s.summary.dispatchTotal" % S) == 12500 and page.evaluate("() => %s.summary.dispatchBasis" % S) == "taxed"
    assert page.locator('[data-testid="stl-dispatch-convert-banner"]').count() == 0
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function("() => !%s.saving" % S, timeout=15000)
    c = db.get_db()
    try:
        saved = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["summary"]
    finally:
        c.close()
    assert saved["dispatchBasis"] == "taxed" and saved["dispatchTotal"] == 12500


def _case_page(live_server, e2e_browser, sa):
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    _login(page, live_server, *sa)
    _reload_case(page, live_server)
    return page


def _reload_case(page, live_server):
    page.goto("%s/pages/case-management.html?q=%s" % (live_server, NO))
    page.wait_for_function("(no) => { const d = %s; return d && d.selected && d.selected.quote_no === no }" % CM, arg=NO, timeout=30000)
    page.wait_for_function("() => %s.dispatches.length > 0" % CM, timeout=20000)


@pytest.mark.e2e
def test_case_page_stale_check_pairs_the_basis_and_shows_the_tax_inclusive_cost(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    stale = "() => %s.financeDispatchStale()" % CM
    # 舊完結案（沒有標記、存含稅 12,500）⇒ 與含稅現算比 ⇒ 不誤報
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501}})
    page = _case_page(live_server, e2e_browser, sa)
    assert page.evaluate(stale) is None
    assert page.evaluate("() => %s.dispatchTotalCost()" % CM) == 12500                                    # 2026-10-06：派發日 2026-10-01 ≥ 切換日 ⇒ 外包總成本含稅（未稅 10000＋稅 500＋人員 2000）
    assert page.evaluate("() => %s.dispatchTaxCost()" % CM) == 500 and page.evaluate("() => %s.dispatchTaxExcludedCost()" % CM) == 0
    # 新完結案（標記 pretax、存 12,000）⇒ 與未稅現算比 ⇒ 不誤報
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 12001, "dispatchBasis": "pretax"}})
    _reload_case(page, live_server)
    assert page.evaluate(stale) is None
    # 標未稅卻存了含稅值（口徑錯配）⇒ 照樣抓到
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501, "dispatchBasis": "pretax"}})
    _reload_case(page, live_server)
    s = page.evaluate(stale)
    assert s and s["frozen"] == 12500 and s["live"] == 12000


@pytest.mark.e2e
def test_the_pages_own_finalize_payload_passes_the_server_recheck_on_the_new_basis(live_server, make_user, e2e_browser):
    """F1 的另一半：精算頁自己送出的完結 payload（含未稅承攬商成本、稅額、口徑標記、利潤線）要通過後端全欄位重算；存下來的數字與公式一致。"""
    import db
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 100000, "total": 105000}
        d["settlement"] = {"status": "draft", "items": [], "offsets": []}
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        c.commit()
    finally:
        c.close()
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    page.wait_for_function("() => %s.summary && %s._actualsOk && !%s.loading" % (S, S, S), timeout=20000)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function("() => !%s.saving" % S, timeout=15000)
    c = db.get_db()
    try:
        draft = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["summary"]
    finally:
        c.close()
    assert draft["dispatchTotal"] == 12500, draft["dispatchTotal"]
    page.locator('[data-testid="stl-finalize"]').click()
    with page.expect_response(lambda r: r.request.method == "PUT" and "/settlement" in r.url, timeout=20000) as resp:
        page.get_by_role("button", name="確認完結").click()
    assert resp.value.status == 200, "頁面自己的完結 payload 被後端擋下：%s %s" % (resp.value.status, resp.value.text()[:300])
    page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.saving" % (S, S), timeout=20000)
    c = db.get_db()
    try:
        saved = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]
    finally:
        c.close()
    assert saved["status"] == "finalized", "完結被後端擋下了：%s" % saved.get("status")
    s_ = saved["summary"]
    # 0c M2 驗收：真實頁面完結（草稿→按完結）存下的數字與草稿逐位相同、口徑標記是 taxed（2026-10-06 全含稅）
    assert s_["dispatchTotal"] == draft["dispatchTotal"] and s_["totalActualCost"] == draft["totalActualCost"], (s_["dispatchTotal"], draft["dispatchTotal"], s_["totalActualCost"], draft["totalActualCost"])
    assert s_["dispatchBasis"] == "taxed"
    from modules.analytics.api import reports as _R
    c = db.get_db()
    try:
        accrual = _R._live_dispatch_totals_by_quote(c)      # 2026-10-06：含稅（grandTotal，含外包人員）
    finally:
        c.close()
    assert accrual[NO] == s_["dispatchTotal"], "營運報表權責口徑 %s ≠ 完結存的承攬商成本 %s" % (accrual.get(NO), s_["dispatchTotal"])
    assert s_["dispatchTotal"] == 12500 and s_["dispatchBasis"] == "taxed" and s_["dispatchTax"] == 500 and s_["dispatchGrandTotal"] == 12500
    from helpers.legal_params import round_half_up
    gross = 100000 - s_["totalActualCost"]
    assert s_["grossProfit"] == gross and s_["adminCost"] == round_half_up(100000, 0.10) and s_["charityDonation"] == round_half_up(gross, 0.01)
    assert s_["netProfit"] == gross - s_["adminCost"] - s_["charityDonation"]


@pytest.mark.e2e
def test_case_page_finance_tab_follows_the_cutover_per_dispatch(live_server, make_user, e2e_browser):
    """使用者 2026-10-06：案件管理財務分頁的外包總成本與營運報表同一條規則——派發日 ≥ 2026-10-01 含稅；之前照舊未稅（稅額不計成本）。"""
    import db
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)                                                    # 派發日 2026-10-01：含稅 12,500（稅 500）
    c = db.get_db()
    try:
        vid = c.execute("SELECT id FROM vendor_contractors WHERE name='稅基測試承攬商'").fetchone()["id"]
        c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, personnel_json, status, approval_status,"
                  " invoice_no, invoice_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, vid, "2026-09-30", "amount", "[]", 4000, 0.05, "[]", "accepted", "", "ZZ9", "2026-10-02", "2026-09-30", "2026-09-30"))
        c.commit()
    finally:
        c.close()
    page = _case_page(live_server, e2e_browser, sa)
    page.wait_for_function("() => %s.dispatches.length > 1" % CM, timeout=20000)
    assert page.evaluate("() => %s.dispatchTotalCost()" % CM) == 12500 + 4000            # 9/30 派發（發票日在 10 月也一樣）仍未稅 4,000
    assert page.evaluate("() => %s.dispatchTaxCost()" % CM) == 500 and page.evaluate("() => %s.dispatchTaxExcludedCost()" % CM) == 200
    assert "16,500" in page.locator('[data-testid="dispatch-total-cost"]').inner_text()
    assert "其中稅額 NT$ 500" in page.locator('[data-testid="dispatch-tax-note"]').inner_text()
    assert "不計成本" in page.locator('[data-testid="dispatch-tax-excluded-note"]').inner_text()
