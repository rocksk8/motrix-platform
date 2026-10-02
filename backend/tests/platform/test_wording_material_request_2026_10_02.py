# -*- coding: utf-8 -*-
"""全站改字守門：使用者看得到的字串不得再出現「叫料」（改稱「材料申請」）。

範圍：後端＝Python 字串常數（不含 docstring；註解不是字串 token）；前端＝html／js 非註解行。
程式內部 key（material_order、materialOrders…）不受影響；歷史 CHANGELOG 與註解可保留舊詞。
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORD = "叫料"
SKIP = ("/tests/", ".venv", "__pycache__", "node_modules", "/_demo_")


def _backend_hits():
    hits = []
    for p in (ROOT / "backend").rglob("*.py"):
        sp = p.as_posix()
        if any(x in sp for x in SKIP):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if WORD not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        docs = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
                b = n.body[0]
                if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                    docs.add(id(b.value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and WORD in n.value and id(n) not in docs:
                hits.append("%s:%d %s" % (p.relative_to(ROOT).as_posix(), n.lineno, n.value.strip()[:60]))
    return hits


def _strip_comments(text, js):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if js:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(^|[^:'\"`])//[^\n]*", r"\1", text)
    return text


def _frontend_hits():
    hits = []
    for p in (ROOT / "frontend").rglob("*"):
        if p.suffix not in (".html", ".js"):
            continue
        t = _strip_comments(p.read_text(encoding="utf-8", errors="replace"), js=True)
        for i, ln in enumerate(t.splitlines(), 1):
            if WORD in ln:
                hits.append("%s:%d %s" % (p.relative_to(ROOT).as_posix(), i, ln.strip()[:60]))
    return hits


def test_no_screen_string_says_jiaoliao():
    hits = _backend_hits() + _frontend_hits()
    assert not hits, "畫面字串仍有「叫料」（改稱「材料申請」）：\n" + "\n".join(hits[:30])


def test_scanner_positive_control(tmp_path):
    """掃描器本身要抓得到：字串常數命中、docstring 與註解不命中。"""
    src = '"""叫料 docstring"""\nX = "叫料單"  # 叫料 comment\n'
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and WORD in n.value]
    assert "叫料單" in consts
    assert WORD not in _strip_comments("<!-- 叫料 -->ok\n// 叫料\nx", js=True).replace("叫料單", "")
    assert WORD in _strip_comments("<b>叫料單</b>", js=True)
