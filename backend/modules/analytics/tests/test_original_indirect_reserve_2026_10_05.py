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
NEW_HEADERS = ["報價預留間接成本", "其中：預留未被實際成本抵用", "其中：其他"]

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
    for h in ("報價預留間接成本", "其中：預留未被實際成本抵用", "其中：其他"):
        assert h in ix, h
    assert [ws.cell(3, i).value for i in range(1, 25)] == LEGACY_HEADERS + NEW_HEADERS      # 既有欄號不動，新欄在最右
    rows = {r[0].value: r for r in ws.iter_rows(min_row=4) if r[0].value in ("T39-R-NEW", "T39-R-OLD")}
    new, old = rows["T39-R-NEW"], rows["T39-R-OLD"]
    diff_amt = new[ix["差異金額"]].value
    assert new[ix["報價預留間接成本"]].value == 5000
    assert new[ix["其中：預留未被實際成本抵用"]].value == 5000
    assert new[ix["其中：其他"]].value == diff_amt - 5000                   # 兩項相加＝差異金額
    assert old[ix["報價預留間接成本"]].value == 0 and old[ix["其中：預留未被實際成本抵用"]].value == 0
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
    assert "原始預估已扣報價預留間接成本 NT$ 5,000（實際只計單據）" in new and "其中未被實際成本抵用 NT$ 5,000" in new
    assert "報價預留間接成本" not in old and "以單據為準" not in old


def test_net_profit_and_bonus_basis_are_untouched_by_the_reserve(client):
    from modules.analytics.api.reports import _collect
    _seed()
    cases = {c["quoteNo"]: c for c in _collect("2026-01-01", "2026-12-31")["casesAll"]}
    assert cases["T39-R-NEW"]["grossProfit"] == cases["T39-R-OLD"]["grossProfit"] == 26630
    assert cases["T39-R-NEW"]["actualMarginPct"] == cases["T39-R-OLD"]["actualMarginPct"] == 26.6


# ── 預留與單據的關係：只解釋「沒被實際成本抵用」的那一塊（稽核 T39 S-1）────────────────────────
# 報價預留 R = 5,000；實際直接成本比原始多出 C = 原始直接毛利 − 真實毛利。未被抵用 Y = clamp(R − max(C, 0), 0, R)。
def _cov(origin_gross, gross, net, quote_no):
    summ = BASE | {"origIndirectReserve": 5000, "origDirectProfit": origin_gross, "grossProfit": gross,
                   "netProfit": net, "profitDiff": net - 21630}
    _insert_case(quote_no, deal_tag="已結案", settlement={"status": "finalized", "summary": summ})


CASES = [            # (案號, 真實毛利, 真實淨利, 預期 Y, 預期「其他」)
    ("T39-C-NODOC", 37000, 26630, 5000, 0),         # 沒有單據：差額 +5,000 全是預留沒發生
    ("T39-C-FULL", 32000, 21680, 0, 50),            # 單據 5,000 ＝ 預留：差額只剩公益金 50
    ("T39-C-PART", 35000, 24650, 3000, 20),         # 單據 2,000：預留只剩 3,000 未被抵用
    ("T39-C-OVER", 30000, 19700, 0, -1930),         # 單據 7,000 > 預留：Y 不為負，其餘差額照實
    ("T39-C-SAVE", 40000, 29600, 5000, 2970),       # 成本比原始少（C < 0）：預留仍未被抵用，節省歸「其他」
]


def test_pdf_explains_only_the_part_of_the_reserve_not_covered_by_actual_cost(client):
    from modules.analytics.api.reports import _build_report_html
    for no, gross, net, _y, _o in CASES:
        _cov(37000, gross, net, no)
    lab, data = _data()
    html = _build_report_html(data, lab, "t")
    blocks = html.split("各案件利潤分析明細")[1].split("page-break-inside:avoid")
    for no, _g, _n, y, other in CASES:
        b = [x for x in blocks if no in x][0]
        sign = "-" if other < 0 else ""
        assert "其中未被實際成本抵用 NT$ %s" % format(y, ",") in b, no
        assert "其他 NT$ %s%s" % (sign, format(abs(other), ",")) in b or "其他 NT$ %s" % format(other, ",") in b, (no, other)


def test_excel_split_columns_follow_the_same_rule_and_add_up_to_the_diff(client):
    _seed_nothing = None
    for no, gross, net, _y, _o in CASES:
        _cov(37000, gross, net, no)
    ws = _sheet()
    ix = _header_index(ws)
    rows = {r[0].value: r for r in ws.iter_rows(min_row=4) if r[0].value in {c[0] for c in CASES}}
    for no, _g, _n, y, _o in CASES:
        r = rows[no]
        assert r[ix["報價預留間接成本"]].value == 5000, no
        assert r[ix["其中：預留未被實際成本抵用"]].value == y, no
        assert r[ix["其中：預留未被實際成本抵用"]].value + r[ix["其中：其他"]].value == r[ix["差異金額"]].value, no
