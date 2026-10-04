# -*- coding: utf-8 -*-
"""T39：利潤分析在「原始側」列出報價預留的間接成本，並把淨利差額拆成「預留未發生」與「其他」。

精算摘要的 `origIndirectReserve`＝報價 tot.totalIndirect − 管銷 − 公益（M01 完結時凍結）。
實際側不變（只有單據）：報價預留 5,000、沒有運費單據時，淨利會比原始多 5,000——那是預留沒發生，不是省下。
舊精算沒有這個鍵 ⇒ 0、PDF 不多出任何列。Excel 工作表名「毛利分析」不變。
"""
import io

import openpyxl

from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case

BASE = {"netProfit": 26630, "netMarginPct": 26.6, "grossProfit": 37000, "grossMarginPct": 37.0,
        "itemActualTotal": 60000, "extraTotal": 0, "totalActualCost": 63000,
        "origTotalCost": 60000, "origNetProfit": 21630, "origNetMarginPct": 21.6,
        "profitDiff": 5000}
WITH = BASE | {"origIndirectReserve": 5000}


def _seed():
    _insert_case("T39-R-NEW", deal_tag="已結案", settlement={"status": "finalized", "summary": WITH})
    _insert_case("T39-R-OLD", deal_tag="已結案", settlement={"status": "finalized", "summary": BASE})


def _data():
    from modules.analytics.api.reports import _augment_with_targets, _build_income_expense_scopes, _collect, _parse_period
    lab, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    data["arAging"] = []
    data.update(_build_income_expense_scopes(2026, "2026-03", None, basis="accrual"))
    return lab, data


def _sheet():
    from modules.analytics.api.reports import _build_excel
    lab, data = _data()
    wb = openpyxl.load_workbook(io.BytesIO(_build_excel(data, lab, "t")))
    assert "毛利分析" in wb.sheetnames                                     # 工作表名不變
    return wb["毛利分析"]


def _header_index(ws):
    hdr = [c.value for c in ws[3]]
    return {h: i for i, h in enumerate(hdr) if h}


def test_excel_original_group_has_the_reserve_column_and_diff_is_split(client):
    _seed()
    ws = _sheet()
    ix = _header_index(ws)
    for h in ("間接成本預算", "其中：間接成本預算未發生", "其中：其他"):
        assert h in ix, h
    assert ix["間接成本預算"] == ix["原始預估淨利"] + 1                      # 在原始側群組內
    rows = {r[0].value: r for r in ws.iter_rows(min_row=4) if r[0].value in ("T39-R-NEW", "T39-R-OLD")}
    new, old = rows["T39-R-NEW"], rows["T39-R-OLD"]
    diff_amt = new[ix["差異金額"]].value
    assert new[ix["間接成本預算"]].value == 5000
    assert new[ix["其中：間接成本預算未發生"]].value == 5000
    assert new[ix["其中：其他"]].value == diff_amt - 5000                   # 兩項相加＝差異金額
    assert old[ix["間接成本預算"]].value == 0 and old[ix["其中：間接成本預算未發生"]].value == 0
    assert old[ix["其中：其他"]].value == old[ix["差異金額"]].value        # 舊精算：差額原封不動


def test_excel_group_header_spans_the_new_column(client):
    _seed()
    ws = _sheet()
    ix = _header_index(ws)
    merged = {str(m): m for m in ws.merged_cells.ranges}
    orig = [m for m in ws.merged_cells.ranges if m.min_row == 2 and ws.cell(2, m.min_col).value == "原始報價預估"][0]
    assert orig.min_col == ix["原始成本"] + 1 and orig.max_col == ix["間接成本預算"] + 1


def test_excel_total_row_sums_the_reserve(client):
    _seed()
    ws = _sheet()
    ix = _header_index(ws)
    tot = [r for r in ws.iter_rows(min_row=4) if r[0].value == "合計"][-1]
    assert tot[ix["間接成本預算"]].value == 5000


def test_pdf_original_table_lists_the_reserve_and_the_diff_split_only_when_present(client):
    from modules.analytics.api.reports import _build_report_html
    _seed()
    lab, data = _data()
    html = _build_report_html(data, lab, "t")
    blocks = html.split("各案件利潤分析明細")[1].split("page-break-inside:avoid")
    new = [b for b in blocks if "T39-R-NEW" in b][0]
    old = [b for b in blocks if "T39-R-OLD" in b][0]
    assert "間接成本預算" in new and "NT$ 5,000" in new
    assert "其中 間接成本預算未發生 NT$ 5,000" in new and "其他 NT$ 0" in new
    assert "間接成本預算" not in old and "其中 間接成本預算未發生" not in old


def test_net_profit_and_bonus_basis_are_untouched_by_the_reserve(client):
    from modules.analytics.api.reports import _collect
    _seed()
    cases = {c["quoteNo"]: c for c in _collect("2026-01-01", "2026-12-31")["casesAll"]}
    assert cases["T39-R-NEW"]["grossProfit"] == cases["T39-R-OLD"]["grossProfit"] == 26630
    assert cases["T39-R-NEW"]["actualMarginPct"] == cases["T39-R-OLD"]["actualMarginPct"] == 26.6
