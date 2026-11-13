# -*- coding: utf-8 -*-
"""頁面 <style> 括號必須平衡（2026-11-13，T83 併修）。

起因：quotations.html 第一個 <style> 的 `@media (max-width:1023px) {` 沒關括號，T84 合併進來的整段樣式
（.ql-sum／.ql-cond／.ql-only-m…）被包進平板 media query ⇒ 桌機上三顆數字按鈕變瀏覽器預設灰鈕、手機專用元件沒被藏。
瀏覽器對少關的括號不報錯，只是把後面全吞進去，所以只有看畫面才發現。這裡靜態守門：
① 全部頁面每個 <style> 區塊括號深度最後＝0、中途不為負；
② quotations.html：T84 的 .ql-sum 規則必須在最外層（深度 0）；「新增估價單」是 ghost 次要鈕。
"""
import re

import pytest

from core.source_tree import page_file, page_files


def _strip(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\"[^\"\n]*\"|'[^'\n]*'", '""', css)
    return re.sub(r"\{\{.*?\}\}", "", css)


def _depth_report(css):
    """⇒ (最後深度, 最低深度, [(規則選擇器行, 該行開始前的深度)…])"""
    d = lo = 0
    lines = []
    for ln in _strip(css).split("\n"):
        lines.append((ln.strip(), d))
        d += ln.count("{") - ln.count("}")
        lo = min(lo, d)
    return d, lo, lines


def _indent_violations(css):
    """縮排對帳：整頁深度＝0 擋不到「這裡少一個 }、別處多一個 }」一來一回的錯。
    頂層 @media 區塊內的每一行縮排必須比 @media 那行深；收尾的 } 必須與 @media 同縮排。
    （頂層 @media 沒關好時，後面本來在最外層的規則縮排會 ≤ @media，立刻被抓。）"""
    bad = []
    media_indent = None
    depth = 0
    for n, raw in enumerate(_strip(css).split("\n"), 1):
        ln = raw.strip()
        ind = len(raw) - len(raw.lstrip(" "))
        if not ln:
            continue
        if media_indent is None:
            if depth == 0 and ln.startswith("@media") and ln.count("{") > ln.count("}"):
                media_indent = ind
        else:
            if ln.startswith("}") and depth == 1:
                if ind != media_indent:
                    bad.append((n, "收尾 } 縮排 %d ≠ @media 縮排 %d" % (ind, media_indent)))
            elif ind <= media_indent:
                bad.append((n, "@media 區塊內的行縮排 %d 不比 @media（%d）深：%s" % (ind, media_indent, ln[:50])))
        depth += ln.count("{") - ln.count("}")
        if depth <= 0:
            media_indent = None
            depth = max(depth, 0)
    return bad


def _style_blocks(html):
    return re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)


@pytest.mark.parametrize("p", page_files(), ids=lambda p: p.name)
def test_every_style_block_is_balanced(p):
    for n, css in enumerate(_style_blocks(p.read_text(encoding="utf-8"))):
        final, lo, _ = _depth_report(css)
        assert final == 0 and lo >= 0, "%s 第 %d 個 <style> 括號不平衡（最後深度 %d、最低 %d）" % (p.name, n + 1, final, lo)


@pytest.mark.parametrize("p", page_files(), ids=lambda p: p.name)
def test_media_blocks_close_where_they_are_indented(p):
    for n, css in enumerate(_style_blocks(p.read_text(encoding="utf-8"))):
        assert not _indent_violations(css), "%s 第 %d 個 <style>：%s" % (p.name, n + 1, _indent_violations(css)[:3])


def test_indent_check_catches_offsetting_errors():
    """正對照：少一個 }（1023）又多一個 }（別處）⇒ 整頁深度仍 0，但縮排對帳要抓到。"""
    css = ("    @media (max-width:1023px) {\n      a { x:y }\n"
           "    .top { x:y }\n"
           "    @media (max-width:767px) {\n      b { x:y }\n    }\n    }\n")
    assert _depth_report(css)[0] == 0 and _depth_report(css)[1] >= 0
    assert _indent_violations(css)
    ok = "    @media (a) {\n      a { x:y }\n    }\n    .top { x:y }\n"
    assert not _indent_violations(ok)


def test_detector_catches_unclosed_media():
    """正對照：偵測器要真的抓得到『media 少關括號』（不然上面全綠也不代表什麼）。"""
    bad = "@media (max-width:1023px) {\n a{x:y}\n}\n@media (hover:none) {\n b{x:y}\n"
    assert _depth_report(bad)[0] == 1
    assert _depth_report("a{x:y}\n}\n")[1] < 0
    assert _depth_report("@media (a) {\n a{x:y}\n}\n")[0] == 0


def test_quotations_t84_rules_are_top_level_and_new_estimate_is_ghost():
    html = page_file("quotations.html").read_text(encoding="utf-8")
    _, _, lines = _depth_report(_style_blocks(html)[0])
    for sel in (".ql-sum {", ".ql-only-m {", ".ql-cond__chip {", ".ql-colpick {"):
        hits = [d for ln, d in lines if ln.startswith(sel)]
        assert hits, "找不到 %s" % sel
        # 手機 media 裡也會有同名覆寫（深度 1）；基底規則必須至少有一條在最外層
        assert 0 in hits, "%s 的基底規則被包進 @media（深度 %s）——桌機會吃不到樣式" % (sel, hits)
    m = re.search(r'<a [^>]*data-testid="ql-new-estimate"[^>]*>', html)
    assert m and "action-btn--ghost" in m.group(0), "「新增估價單」要用 action-btn--ghost（否則沒外框）"
