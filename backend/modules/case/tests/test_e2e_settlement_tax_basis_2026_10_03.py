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
def test_draft_shows_pretax_cost_the_tax_split_and_a_dismissible_one_line_note(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert page.evaluate("() => %s.summary.dispatchTotal" % S) == 12000
    assert page.evaluate("() => %s.summary.dispatchBasis" % S) == "pretax" and page.evaluate("() => %s.summary.dispatchTax" % S) == 500
    assert "12,000" in _txt(page, "stl-dispatch-subtotal") and "500" in _txt(page, "stl-dispatch-tax-total")
    split = _txt(page, "stl-dispatch-split")
    for part in ("未稅承攬費 NT$ 10,000", "外包人員 NT$ 2,000", "計入成本 NT$ 12,000", "承攬商稅額 NT$ 500", "進項稅額，不計成本", "含稅合計 NT$ 12,500"):
        assert part in split, (part, split)
    note = _txt(page, "stl-dispatch-basis-note")
    assert "承攬商成本現以未稅計入（稅額為進項稅額，不計成本）；與先前顯示相差承攬商稅額" in note and "500" in note
    page.locator('[data-testid="stl-dispatch-basis-note-dismiss"]').click()
    assert page.locator('[data-testid="stl-dispatch-basis-note"]').count() == 0
    page.reload()
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert page.locator('[data-testid="stl-dispatch-basis-note"]').count() == 0, "「知道了」之後同一個瀏覽器不再顯示"
    assert page.locator('[data-testid="stl-dispatch-old-basis-note"]').count() == 0


@pytest.mark.e2e
def test_old_finalized_case_keeps_the_tax_inclusive_numbers_with_a_neutral_note_and_no_false_stale(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 11025, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 23525}})
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert "12,500" in _txt(page, "stl-dispatch-subtotal") and page.evaluate("() => %s.summary.dispatchTotal" % S) == 12500     # 與完結當下存的數字逐位相同
    assert page.evaluate("() => %s.summary.dispatchBasis" % S) == "taxed"
    old = _txt(page, "stl-dispatch-old-basis-note")
    assert "此精算完結於含稅口徑" in old and "兩者相差承攬商稅額" in old and "已完結的數字不改寫" in old
    assert page.locator('[data-testid="stl-dispatch-basis-note"]').count() == 0 and not page.locator('[data-testid="stl-dispatch-tax-total"]').is_visible()
    assert page.locator(".stale-banner").count() == 0, "舊口徑（含稅）完結案：存檔 12,500 與含稅現算 12,500 相同，不可以誤報過期"


@pytest.mark.e2e
def test_new_finalized_case_uses_the_marker_compares_pretax_and_still_detects_real_changes(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 11025, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 23025,
                                                                                   "dispatchBasis": "pretax"}})
    page = open_page(live_server, e2e_browser, sa)
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert "12,000" in _txt(page, "stl-dispatch-subtotal")
    assert page.locator('[data-testid="stl-dispatch-old-basis-note"]').count() == 0 and page.locator(".stale-banner").count() == 0
    # 完結後承攬商成本真的異動 ⇒ 仍會提醒（新口徑對新口徑）
    _dispatch(1000, 0)
    page.reload()
    page.locator('[data-testid="stl-dispatch-subtotal"]').wait_for(state="visible", timeout=15000)
    assert page.locator(".stale-banner").count() == 1 and "13,000" in page.locator(".stale-banner").inner_text()


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
def test_case_page_stale_check_pairs_the_basis_and_shows_pretax_cost_with_the_tax_note(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    _dispatch(10000, 2000)
    stale = "() => %s.financeDispatchStale()" % CM
    # 舊完結案（沒有標記、存含稅 12,500）⇒ 與含稅現算比 ⇒ 不誤報
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501}})
    page = _case_page(live_server, e2e_browser, sa)
    assert page.evaluate(stale) is None
    assert page.evaluate("() => %s.dispatchTotalCost()" % CM) == 12000                                    # 外包總成本＝未稅＋人員
    assert page.evaluate("() => %s.dispatchTaxCost()" % CM) == 500
    # 新完結案（標記 pretax、存 12,000）⇒ 與未稅現算比 ⇒ 不誤報
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12000, "totalActualCost": 12001, "dispatchBasis": "pretax"}})
    _reload_case(page, live_server)
    assert page.evaluate(stale) is None
    # 標未稅卻存了含稅值（口徑錯配）⇒ 照樣抓到
    _set_settlement({"status": "finalized", "items": [], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 12501, "dispatchBasis": "pretax"}})
    _reload_case(page, live_server)
    s = page.evaluate(stale)
    assert s and s["frozen"] == 12500 and s["live"] == 12000
