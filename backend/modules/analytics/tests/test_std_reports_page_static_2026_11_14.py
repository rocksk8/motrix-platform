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


def _balanced(src: str, start: int, open_ch: str, close_ch: str) -> int:
    """src[start] 是 open_ch ⇒ 回傳配對的 close_ch 之後一格的位置（略過字串與註解裡的括號）。"""
    depth, i, n = 0, start, len(src)
    while i < n:
        ch, two = src[i], src[i:i + 2]
        if two == "//":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if two == "/*":
            i = n if src.find("*/", i + 2) < 0 else src.find("*/", i + 2) + 2
            continue
        if ch in "'\"`":
            i += 1
            while i < n and src[i] != ch:
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise AssertionError("括號沒有配對：%r" % src[start:start + 40])


def _member(js: str, name: str) -> str:
    """元件物件裡 `name(...) { ... }`（含 async／get 前綴）的整段原始碼：靠「行首縮排＋名稱＋括號」的結構找，不靠文案。"""
    m = re.search(r"^[ \t]+(?:async[ \t]+|get[ \t]+)?%s[ \t]*\(" % re.escape(name), js, flags=re.M)
    assert m, "找不到成員：%s" % name
    after_params = _balanced(js, m.end() - 1, "(", ")")
    brace = re.compile(r"\s*\{").match(js, after_params)
    assert brace, "成員 %s 沒有函式本體" % name
    return js[m.start():_balanced(js, brace.end() - 1, "{", "}")]


def _tag(html: str, pattern: str) -> str:
    """第一個符合 pattern 的開頭標籤全文（pattern 寫在 `<` 之後、`>` 之前的內容）。"""
    m = re.search(r"<(?:%s)[^>]*>" % pattern, html)
    assert m, pattern
    return m.group(0)


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
    assert "self.has(k)" in _member(js, "_qs")


def test_value_semantics_are_distinct():
    """null＝看不到、{state}＝沒填／未精算、0＝真的 0：三種在畫面上不可混為一談。"""
    js = _script()
    assert "'unfilled'" in js and "'unsettled'" in js
    fmt = _member(js, "fmt")
    assert re.search(r"v === null", fmt).start() < re.search(r"isState\(v\)", fmt).start()
    assert "=== ''" in fmt and "v === 0" not in fmt, "0 不能被當成空值"


def test_export_downloads_the_snapshot_not_the_live_form():
    js = _script()
    dl = _member(js, "download")
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
    for tid in ("sr-basis-cash", "sr-basis-accrual"):
        assert ":aria-pressed=" in _tag(PAGE, r'button[^>]*data-testid="%s"' % tid), tid
    assert 'role="tablist"' not in PAGE and 'role="tab"' not in PAGE
    assert ":aria-current=" in PAGE


def test_monthly_chart_has_a_text_alternative():
    """柱狀圖只靠視覺／滑鼠提示不夠（手機沒有 hover、讀屏讀不到）：圖對輔助科技隱藏，旁邊給逐月數字表。"""
    assert re.search(r'class="sr-bars"[^>]*role="img"[^>]*:aria-label="seriesSummary"', PAGE)
    assert "aria-hidden" not in _tag(PAGE, r'div class="sr-bars"')
    assert 'data-testid="sr-series-table"' in PAGE
    assert ":title=" not in PAGE


def test_dash_is_only_for_masked_money_and_empty_stages_carry_no_amount():
    """「—」只代表看不到金額：0 件的階段不帶金額；算不出來的百分比寫明原因，不用「—」。"""
    js = _script()
    dev = _member(js, "devFunnel")
    assert "d.count === 0" in dev and "'0 件'" in dev
    fmt = _member(js, "fmt")
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
    cell = _member(js, "cell")
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
