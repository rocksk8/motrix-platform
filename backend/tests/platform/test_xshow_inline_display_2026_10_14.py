# -*- coding: utf-8 -*-
"""旗標關閉時畫面必須與舊版逐位元相同：Alpine 的 x-show 為真時會移除行內 display，
所以由版面引擎／自訂欄位／自訂按鈕加上的 x-show 不得掛在帶靜態 style="display:..." 的元素上
（要 flex 就放進 CSS class，或把 x-show 移到子元素）。涵蓋 BP-1／S4／S5／S6 動過的頁面。"""
import re

import pytest

from core import source_tree

PAGES = ["case-management.html", "suppliers.html", "procurement.html", "devices.html", "vendor-contractors.html",
         "quotations.html", "quotation-form.html"]
# 任何 `<字母>Shown(`（l／f／c／t／T／b…）都算旗標函式：原本 bp1 的 c1／c2／q2／quote_form 四份各用不同字母集合，這裡取聯集（c2 的 `[a-zA-Z]Shown(` 是最寬的）
FLAG_GATED = re.compile(r"\b[a-zA-Z]Shown\(|\blayoutOn\b|\$store\.layout|\$store\.cf\b|\$store\.ub\b")


def drift(html):
    bad = []
    for m in re.finditer(r"<[a-zA-Z][^<>]*?>", html, re.S):
        tag = m.group(0)
        xs = re.search(r'x-show="([^"]*)"', tag)
        if not xs or not FLAG_GATED.search(xs.group(1)):
            continue
        st = re.search(r'(?<![:\w-])style="([^"]*)"', tag)
        if st and re.search(r"(^|;)\s*display\s*:", st.group(1)):
            bad.append(re.sub(r"\s+", " ", tag)[:120])
    return bad


@pytest.mark.parametrize("page", PAGES)
def test_flag_gated_x_show_has_no_static_inline_display(page):
    p = source_tree.page_file(page)
    assert not drift(p.read_text(encoding="utf-8")), page


def test_positive_control_detects_the_known_bad_shape():
    assert drift('<span style="display:flex;gap:6px" x-show="lShown(\'a\')"></span>')
    assert not drift('<span class="row" x-show="lShown(\'a\')"></span>')
    assert not drift('<span style="display:flex" x-show="v.code"></span>')
    for fn in ("cShown", "tShown", "bShown", "TShown"):                                  # 併入原 c1／q2 用的函式名
        assert drift('<span style="display:flex" x-show="%s(\'a\')"></span>' % fn), fn
