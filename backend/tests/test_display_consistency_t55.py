# -*- coding: utf-8 -*-
"""第 55 班：三處畫面不一致的統一（M1）。
① 直接毛利率顏色門檻只有一個來源 `static/margin-tone.js`（原本表單 30/40、列表 30/35）；兩頁都用它、不再有行內門檻
② 報價單列表的空列／載入列 colspan 與表頭（含可選的拖曳欄）一致，且等於分區標題列的 colspan
③ 案件管理『已成案』頁籤徽章用自己的 `summaryWon()`，不再借用『進行中』的 `summaryActive()`
"""
import json
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FE = os.path.join(ROOT, "frontend")
JS = os.path.join(FE, "static", "margin-tone.js")


def _read(*p):
    with open(os.path.join(FE, *p), encoding="utf-8") as f:
        return f.read()


def _node(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 node")
    code = "var m=require(%s);process.stdout.write(JSON.stringify(%s))" % (json.dumps(JS.replace("\\", "/")), expr)
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── ① 毛利率門檻 ──

def test_margin_thresholds_are_30_and_40_with_exact_boundaries():
    got = _node("[29.99, 30, 39.99, 40, 55].map(function(p){return m.tone(p)})")
    assert got == ["danger", "warning", "warning", "success", "success"]
    assert _node("[m.DANGER_BELOW, m.WARN_BELOW]") == [30, 40]


def test_margin_tone_handles_missing_values_like_the_old_inline_expression():
    # 沿用舊行內算式 `x < 30 ? … : x < 40 ? … : …` 的 JS 比較語意：null／空字串／0 ⇒ danger；undefined／非數字 ⇒ success；不丟例外
    assert _node("[null, '', 0, undefined, 'abc'].map(function(p){return m.tone(p)})") == ["danger"] * 3 + ["success"] * 2
    assert _node("m.style(35)") == "color:var(--warning);font-weight:600"


def test_both_pages_use_the_shared_source_and_no_inline_thresholds_remain():
    form, lst = _read("pages", "quotation-form.html"), _read("pages", "quotations.html")
    assert "MotrixMargin.tone(tot.directMarginPct)" in form and "MotrixMargin.style(q.direct_margin_pct)" in lst
    for name, src in (("quotation-form.html", form), ("quotations.html", lst)):
        assert not re.search(r"[dD]irect_?[mM]argin_?[pP]ct\s*<\s*\d", src), name + " 還有行內的直接毛利率門檻"
        assert "margin-tone.js" in src, name
    assert lst.index("margin-tone.js") < lst.index("alpine-"), "門檻腳本要在 Alpine 之前載入"


# ── ② colspan ──

def test_quotation_list_empty_rows_span_all_columns_like_the_lane_header():
    src = _read("pages", "quotations.html")
    head = src[src.index("<thead>"):src.index("</thead>")]
    cols = len(re.findall(r"<th[ >]", head))              # 含 `x-show` 的拖曳欄（自訂排序時才出現）
    lane = re.search(r'class="ql-lane"[^>]*>\s*<td colspan="(\d+)"', src)
    empties = re.findall(r'<td colspan="(\d+)" style="text-align:center;padding:(?:40|24)px', src)
    assert lane and len(empties) == 2
    assert {int(lane.group(1)), *map(int, empties)} == {cols}, (cols, lane.group(1), empties)


# ── ③ 徽章 ──

def test_won_tab_badge_has_its_own_accessor():
    html, js = _read("pages", "case-management.html"), _read("js", "case-management-list.js")
    i = html.index("setListTab('已成案')")
    block = html[i:html.index("</button>", i)]
    assert "summaryWon()" in block and "summaryActive()" not in block
    assert re.search(r"summaryWon\(\)\s*\{\s*return this\.caseCounts \? this\.caseCounts\.active : 0", js)
    j = html.index("setListTab('all')")
    assert "summaryActive()" in html[j:html.index("</button>", j)]                 # 『進行中』頁籤不變
