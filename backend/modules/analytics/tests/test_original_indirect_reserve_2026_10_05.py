# -*- coding: utf-8 -*-
"""T39：利潤分析在「原始側」列出報價預留的間接成本，並把淨利差額拆成「預留未發生」與「其他」。

精算摘要的 `origIndirectReserve`＝報價 tot.totalIndirect − 管銷 − 公益（M01 完結時凍結）。
實際側不變（只有單據）：報價預留 5,000、沒有運費單據時，淨利會比原始多 5,000——那是預留沒發生，不是省下。
舊精算沒有這個鍵 ⇒ 0、PDF 不多出任何列。Excel 工作表名「毛利分析」不變。
"""
import io

import openpyxl

from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case

#: 既有「毛利分析」表（T39 之前）的表頭與欄號（1 起算）：使用者為依賴這份匯出的人／工具保留了工作表名，欄號同樣不可動
LEGACY_HEADERS = [
    "案件號", "客戶", "專案名稱", "業務員", "案件進度", "報價稅前",
    "原始成本", "原始毛利率", "原始淨利率", "原始預估淨利",
    "品項成本", "額外支出", "實際總成本", "真實毛利率", "真實淨利率", "真實淨利",
    "差異(pp)", "差異金額",
    "精算狀態", "精算日期", "完結人",
]
NEW_HEADERS = ["報價預留間接成本", "其中：報價預留間接成本", "其中：其他"]

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
    for h in ("報價預留間接成本", "其中：報價預留間接成本", "其中：其他"):
        assert h in ix, h
    assert [ws.cell(3, i).value for i in range(1, 25)] == LEGACY_HEADERS + NEW_HEADERS      # 既有欄號不動，新欄在最右
    rows = {r[0].value: r for r in ws.iter_rows(min_row=4) if r[0].value in ("T39-R-NEW", "T39-R-OLD")}
    new, old = rows["T39-R-NEW"], rows["T39-R-OLD"]
    diff_amt = new[ix["差異金額"]].value
    assert new[ix["報價預留間接成本"]].value == 5000
    assert new[ix["其中：報價預留間接成本"]].value == 5000
    assert new[ix["其中：其他"]].value == diff_amt - 5000                   # 兩項相加＝差異金額
    assert old[ix["報價預留間接成本"]].value == 0 and old[ix["其中：報價預留間接成本"]].value == 0
    assert old[ix["其中：其他"]].value == old[ix["差異金額"]].value        # 舊精算：差額原封不動


def test_existing_group_headers_keep_their_columns_and_the_new_group_is_at_the_far_right(client):
    _seed()
    ws = _sheet()
    spans = {ws.cell(2, m.min_col).value: (m.min_col, m.max_col) for m in ws.merged_cells.ranges if m.min_row == 2}
    assert spans["基本資訊"] == (1, 6) and spans["原始報價預估"] == (7, 10)
    assert spans["實際成本精算"] == (11, 16) and spans["差異"] == (17, 18) and spans["精算資訊"] == (19, 21)
    assert spans["報價預留間接成本"] == (22, 24)


def test_legacy_columns_hold_the_same_values_with_or_without_a_reserve(client):
    """既有欄的值與有無 origIndirectReserve 無關（新欄只多不改）。"""
    _seed()
    ws = _sheet()
    rows = {r[0].value: r for r in ws.iter_rows(min_row=4) if r[0].value in ("T39-R-NEW", "T39-R-OLD")}
    new, old = rows["T39-R-NEW"], rows["T39-R-OLD"]
    for i in range(1, 21):                                       # 案件號以外都應相同（兩案內容相同，僅差預留）
        if i > 1:
            assert new[i].value == old[i].value, (LEGACY_HEADERS[i], new[i].value, old[i].value)


def test_excel_total_row_sums_the_reserve(client):
    _seed()
    ws = _sheet()
    ix = _header_index(ws)
    tot = [r for r in ws.iter_rows(min_row=4) if r[0].value == "合計"][-1]
    assert tot[ix["報價預留間接成本"]].value == 5000


def test_pdf_original_table_lists_the_reserve_and_the_diff_split_only_when_present(client):
    from modules.analytics.api.reports import _build_report_html
    _seed()
    lab, data = _data()
    html = _build_report_html(data, lab, "t")
    blocks = html.split("各案件利潤分析明細")[1].split("page-break-inside:avoid")
    new = [b for b in blocks if "T39-R-NEW" in b][0]
    old = [b for b in blocks if "T39-R-OLD" in b][0]
    assert "報價預留間接成本" in new and "NT$ 5,000" in new
    assert "以單據為準（已含於實際總成本）" in new                                   # 實際欄
    assert "其中報價預留間接成本 NT$ 5,000（原始預估已扣、實際只計單據）" in new
    assert "報價預留間接成本" not in old and "以單據為準" not in old


def test_net_profit_and_bonus_basis_are_untouched_by_the_reserve(client):
    from modules.analytics.api.reports import _collect
    _seed()
    cases = {c["quoteNo"]: c for c in _collect("2026-01-01", "2026-12-31")["casesAll"]}
    assert cases["T39-R-NEW"]["grossProfit"] == cases["T39-R-OLD"]["grossProfit"] == 26630
    assert cases["T39-R-NEW"]["actualMarginPct"] == cases["T39-R-OLD"]["actualMarginPct"] == 26.6
