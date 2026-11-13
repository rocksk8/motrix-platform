# -*- coding: utf-8 -*-
"""S1c：設定中心使用者可見字串的禁用詞守門（SPEC §11、UX-PRINCIPLES §6.5）。

掃 helpers/settings_groups*.py 與 settings_registry.py 的字串常數（AST；docstring 與註解豁免）。
禁用詞：確認期間、影子、閘門、true／false（開發者看的 ValueError 也一併改成白話）。
正對照：故意含禁用詞的原始碼必須被抓到；docstring／註解裡的詞不算。
注意：禁用詞清單在 h12 的盤點腳本（scan_banned_words）與這裡各有一份；改其中一份要同步另一份，否則兩邊會漂移。
"""
import ast
import re
from pathlib import Path

HELPERS = Path(__file__).resolve().parents[2] / "helpers"
BANNED = re.compile(r"確認期間|影子|閘門|true／false|true/false")
FILES = sorted(HELPERS.glob("settings_groups*.py")) + [HELPERS / "settings_registry.py"]


def _hits(src):
    tree = ast.parse(src)
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            doc.add(id(n.body[0].value))
    return [(n.lineno, n.value[:40]) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc and BANNED.search(n.value)]


def test_positive_control_the_scanner_sees_a_banned_string_but_not_docstrings_or_comments():
    src = '"""確認期間 在 docstring 裡不算"""\n# 影子 在註解裡不算\nX = "要等確認期間"\nY = "ok"\n'
    assert [h[0] for h in _hits(src)] == [3]


def test_no_user_visible_string_in_the_settings_registry_uses_a_banned_word():
    assert FILES and all(f.exists() for f in FILES)
    bad = {f.name: _hits(f.read_text(encoding="utf-8")) for f in FILES}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, bad
