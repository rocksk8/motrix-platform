# -*- coding: utf-8 -*-
"""第 52 班：公益捐款列標籤依基數戳記——新基（charityBasis=total）「公益捐款（報價含稅 1%）」；舊基／無戳記「公益捐款（直接毛利 1%）」。

標籤永遠跟數字同源（summary／tot 的戳記），不看目前模式。後端 pdf_gen.charity_cost_label ＝ 獎金明細 bonus.row_label ＝ 前端三處（精算頁／案件頁／報表頁）。
"""
import os
import re

import pdf_gen
from modules.payroll import bonus

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NEW, OLD = "公益捐款（報價含稅 1%）", "公益捐款（直接毛利 1%）"


def _read(rel):
    return open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()


def _page(name):
    """頁面路徑集中（tests/platform/test_page_paths_centralized）：頁面一律走 source_tree.page_file。"""
    from core import source_tree
    return source_tree.page_file(name).read_text(encoding="utf-8")


def test_python_labels_follow_the_stamp_not_the_mode():
    assert pdf_gen.charity_cost_label({"charityBasis": "total"}) == NEW
    assert pdf_gen.charity_cost_label({}) == OLD and pdf_gen.charity_cost_label(None) == OLD
    assert pdf_gen.charity_cost_label({"charityBasis": "direct"}) == OLD
    assert pdf_gen.charity_cost_label({"formulaVer": 2}) == OLD, "只有 formulaVer 2 沒有公益戳記 ⇒ 舊基"
    # 原始側看 origCharityBasis，與實際側分開
    s = {"charityBasis": "total"}
    assert pdf_gen.charity_cost_label(s, True) == OLD
    s = {"origCharityBasis": "total"}
    assert pdf_gen.charity_cost_label(s, True) == NEW and pdf_gen.charity_cost_label(s) == OLD


def test_bonus_row_label_matches():
    base = next(r[1] for r in bonus.SETTLEMENT_ROWS if r[0] == "charityDonation")
    assert bonus.row_label("charityDonation", base, {"charityBasis": "total"}) == NEW
    assert bonus.row_label("charityDonation", base, {}) == OLD
    assert bonus.row_label("charityDonation", base, None) == OLD
    assert bonus.row_label("grossProfit", "真實毛利", {"charityBasis": "total"}) == "真實毛利"


def test_frontend_label_helpers_exist_with_the_same_strings():
    for rel, fn in (("frontend/js/case-management-fin.js", "caseSettleCharityLabel"), ("frontend/js/reports.js", "stlCharityLabel")):
        s = _read(rel)
        i = s.index(fn + "(sm, orig)")
        body = s[i:i + 420]
        assert NEW in body and OLD in body and "origCharityBasis" in body and "charityBasis" in body, rel
    st = _page("settlement.html")
    assert re.search(r"charityLbl\(sm, orig\)", st) and NEW in st and OLD in st
    q = _page("quotation-form.html")
    assert "qf-charity-label" in q and NEW in q and OLD in q


def test_no_hardcoded_old_charity_label_left_in_display_code():
    stray = {}
    for name in ("case-management.html", "reports.html", "settlement.html"):
        n = _page(name).count("公益捐款（1%）")
        if n:
            stray[name] = n
    for rel in ("backend/pdf_gen.py", "backend/modules/analytics/api/reports.py"):
        n = _read(rel).count("公益捐款（1%）")
        if n:
            stray[rel] = n
    assert not stray, "畫面／PDF 不可再寫死『公益捐款（1%）』（要用依基數戳記的標籤）：%s" % stray
