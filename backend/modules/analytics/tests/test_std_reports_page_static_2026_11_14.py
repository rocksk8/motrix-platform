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


# ── h5 複審後補的守門（2026-11-14）──────────────────────────────────────────

def test_toggle_and_tab_buttons_expose_state_to_assistive_tech():
    """口徑切換要有 aria-pressed；頁籤不宣告 tablist/tab（沒有 tabpanel／方向鍵就不要冒充）。"""
    assert PAGE.count(":aria-pressed=") >= 2
    assert 'role="tablist"' not in PAGE and 'role="tab"' not in PAGE
    assert ":aria-current=" in PAGE


def test_monthly_chart_has_a_text_alternative():
    """柱狀圖只靠視覺／滑鼠提示不夠（手機沒有 hover、讀屏讀不到）：圖對輔助科技隱藏，旁邊給逐月數字表。"""
    assert re.search(r'class="sr-bars"[^>]*role="img"[^>]*:aria-label="seriesSummary"', PAGE)
    assert "aria-hidden" not in PAGE.split('class="sr-bars"')[1].split(">")[0]
    assert 'data-testid="sr-series-table"' in PAGE
    assert ":title=" not in PAGE


def test_dash_is_only_for_masked_money_and_empty_stages_carry_no_amount():
    """「—」只代表看不到金額：0 件的階段不帶金額；算不出來的百分比寫明原因，不用「—」。"""
    js = _script()
    dev = js[js.index("get devFunnel()"):]
    dev = dev[:dev.index("get quoteFunnel()")]
    assert "d.count === 0" in dev and "'0 件'" in dev
    fmt = js[js.index("fmt(v, type, kpi)"):]
    fmt = fmt[:fmt.index("// ── 營收逐月圖")]
    assert "type === 'pct'" in fmt and "無法計算" in fmt


def test_kpis_of_a_data_class_the_user_has_no_access_to_are_not_drawn():
    js = _script()
    assert "get visibleKpis()" in js and 'x-for="k in visibleKpis"' in PAGE


def test_page_uses_the_auto_crumb_and_user_facing_wording():
    assert 'class="pg__crumb" data-crumb-auto' in PAGE
    assert "管理員" not in PAGE and "・即時" not in PAGE


# ── h5 實機複審 nit（2026-11-14）─────────────────────────────────────────────

def test_funnel_missing_count_never_wraps_inside_the_parenthesis():
    assert re.search(r'class="sr-nb"[^>]*x-text="d\.miss"', PAGE)


def test_empty_date_cells_say_why_and_dash_stays_for_masked_money():
    js = _script()
    cell = js[js.index("cell(v, c)"):]
    cell = cell[:cell.index("isNum(c)")]
    assert "c.type === 'date'" in cell and "未填" in cell and "尚無跟進" in cell
    assert 'x-text="cell(r[c.key], c)"' in PAGE


def test_apply_button_stays_enabled_while_loading_and_guards_double_submit():
    btn = re.search(r'<button[^>]*data-testid="sr-run"[^>]*>', PAGE).group(0)
    assert ":disabled" not in btn
    assert ":aria-busy=" in btn and "if (!loading) run()" in btn


def test_hash_change_switches_the_report():
    assert "addEventListener('hashchange'" in _script()


def test_chart_has_a_summary_label_and_a_swipe_hint_only_when_it_scrolls():
    js = _script()
    assert "get seriesSummary()" in js
    assert re.search(r'data-testid="sr-swipe"[^>]*x-show="barsScroll"', PAGE)
    assert "scrollWidth > b.clientWidth" in js and "addEventListener('resize'" in js


def test_month_labels_are_thinned_on_narrow_screens_when_there_are_many_months():
    js = _script()
    assert "showLabel" in js and "Math.ceil(s.length / 12)" in js
    assert "p.showLabel ? p.label" in PAGE
