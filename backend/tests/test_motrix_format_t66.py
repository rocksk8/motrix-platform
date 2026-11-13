# -*- coding: utf-8 -*-
"""T66：格式器遷移的剩餘頁面（audit-log／schema-status／change-password／vendor-contractors／customers）。
不再有裸的 toLocale*String；頁面載入 motrix-format.js 並帶內嵌後備。純文字檢查，不跑 node／瀏覽器。"""
import re

from core import source_tree

# change-password 已併入 my-account.html（帳號安全），該檔只剩轉址頁、沒有任何日期／數字格式化，故不在此列（2026-11-13，hichan-1）。
NAMES = ["audit-log", "schema-status", "vendor-contractors", "customers"]
_RAW = re.compile(r"\.toLocale(?:Date|Time)?String\(")
_FALLBACK = re.compile(r"<script>/\* 後備：格式器沒載入時.*?</script>", re.S)


def test_t66_pages_use_motrix_format_and_have_fallback():
    for n in NAMES:
        html = source_tree.page_file(n + ".html").read_text(encoding="utf-8")
        assert 'src="../static/motrix-format.js"' in html, n
        assert _FALLBACK.search(html), n
        assert not _RAW.search(_FALLBACK.sub("", html)), n + " 還有裸的 toLocale*String"
        assert "MotrixFormat." in _FALLBACK.sub("", html), n


def test_t66_lint_positive_control():
    assert _RAW.search("d.toLocaleString('zh-TW', {})") and _RAW.search("x.toLocaleDateString()")
