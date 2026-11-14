# -*- coding: utf-8 -*-
"""T87 B1 標準報表頁（reports-standard.html）靜態守門（hichan-10，2026-11-14）。

約定見 D:\\Claude-pm\\t87-design\\B1-api-contract.md。這裡只查頁面本身的結構與規矩（data-testid、只讀、只送適用條件、
遮罩語意、登記），不連後端；端點行為由後端測試負責。錨點一律用 data-testid／程式識別字，不寫死畫面文字。"""
import json
import re
from pathlib import Path

import pytest

from core import source_tree

ROOT = Path(__file__).resolve().parents[4]
PAGE = source_tree.page_file("reports-standard.html").read_text(encoding="utf-8")
MODULE = json.loads((ROOT / "backend/modules/analytics/module.json").read_text(encoding="utf-8"))

REPORT_IDS = ("revenue", "gross-margin", "ar-aging", "case-progress", "sales-funnel")


def _script() -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", PAGE, flags=re.S))


@pytest.mark.parametrize("tid", [
    "sr-filters", "sr-run", "sr-reset", "sr-excel", "sr-pdf", "sr-result", "sr-kpis", "sr-notes",
    "sr-blocked", "sr-load-error", "sr-error", "sr-stale", "sr-masked", "sr-filter-hint",
    "sr-param-date_from", "sr-param-date_to", "sr-param-sales_id", "sr-param-customer", "sr-param-department_id",
    "sr-basis-cash", "sr-basis-accrual", "sr-funnel-dev", "sr-funnel-quote", "sr-series", "sr-ar-basis",
])
def test_required_testids_exist(tid):
    assert 'data-testid="%s"' % tid in PAGE, tid


@pytest.mark.parametrize("prefix", ["sr-tab-", "sr-kpi-", "sr-table-"])
def test_dynamic_testids_follow_the_contract(prefix):
    assert ":data-testid=\"'%s' +" % prefix in PAGE, prefix


def test_page_is_read_only():
    """頁面只查詢：不送出任何會改資料的呼叫。"""
    js = _script()
    assert not re.search(r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)", js, flags=re.I)
    urls = {u.rstrip("/") for u in re.findall(r"""['"](/api/[^'"?]+)""", js)}
    assert urls == {"/api/std-reports"}, urls


def test_no_inline_styles_and_no_raw_to_locale_string():
    """UX 守門（ux_audit 棘輪）：新頁面行內樣式 0、數字走 MotrixFormat。"""
    body = re.sub(r"<script>.*?</script>", " ", PAGE, flags=re.S)
    assert not re.search(r"""\bstyle\s*=\s*\"""", body), "行內樣式：改用 class（動態寬高走 x-effect）"
    assert "toLocaleString(" not in PAGE
    assert "MotrixFormat" in PAGE


def test_query_only_carries_params_the_report_declares():
    """不適用的條件不能送出去（例如帳齡的日期）：後端對未知／不適用條件回 400。"""
    js = _script()
    qs = js[js.index("_qs()"):]
    qs = qs[:qs.index("async _fail")]
    assert "self.has(k)" in qs


def test_value_semantics_are_distinct():
    """null＝看不到、{state}＝沒填／未精算、0＝真的 0：三種在畫面上不可混為一談。"""
    js = _script()
    assert "'unfilled'" in js and "'unsettled'" in js
    fmt = js[js.index("fmt(v, type, kpi)"):]
    fmt = fmt[:fmt.index("// ── 營收逐月圖")]
    assert fmt.index("v === null") < fmt.index("isState(v)")
    assert "=== ''" in fmt and "v === 0" not in fmt, "0 不能被當成空值"


def test_export_downloads_the_snapshot_not_the_live_form():
    js = _script()
    dl = js[js.index("async download(kind)"):]
    dl = dl[:dl.index("isNum(c)")]
    assert "this.shown" in dl and "snap.qs" in dl
    assert "this._qs()" not in dl


def test_only_visible_reports_get_a_tab_and_no_request():
    """PM 裁示（同 U4）：看不到的報表不出頁籤、不送請求；原因只在「全部都看不到」的空狀態列出。"""
    js = _script()
    assert "t.available !== false" in js and "this.blocked" in js
    assert "sr-unavailable" not in PAGE
    assert 'x-for="t in reports"' in PAGE and 'x-for="b in blocked"' in PAGE


def test_ar_aging_states_basis_on_the_table_title():
    """PM 裁示：帳齡畫面要寫清楚依報價日計算（不只放頁尾備註）。"""
    assert re.search(r"data-testid=\"sr-ar-basis\"[^>]*\n?[^>]*x-show=\"result\.id === 'ar-aging'\"", PAGE)


def test_page_is_registered_with_a_menu_entry_that_includes_non_report_roles():
    entry = next(p for p in MODULE["pages"] if p["path"] == "reports-standard.html")
    menu = entry["menu"]
    assert menu["group"] == "analysis" and menu.get("section") and menu.get("desc")
    # PM 裁示：沒有 reports 模組的業務也能看案件進度／業務漏斗（各報表自己再判斷）
    assert {"finance", "reports", "dev_crm", "case_manage"} <= set(menu["perm"])


def test_text_style_banned_words_absent():
    for w in ("催收", "催辦", "卡住", "落後"):
        assert w not in PAGE, w


def test_report_ids_are_not_hardcoded_in_the_page():
    """報表清單來自後端目錄；頁面不寫死有哪些報表（只有營收口徑與漏斗版面這類報表專屬區塊會認 id）。"""
    js = _script()
    assert "j.reports" in js
    assert "/api/std-reports/' + encodeURIComponent" in js
    assert set(re.findall(r"result\.id === '([a-z-]+)'", PAGE)) <= set(REPORT_IDS)
