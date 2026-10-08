"""測試樹不得在 import／收集期取系統日期（跨午夜會與伺服器當下日期不一致 ⇒ 偶發紅燈）。

掃描所有測試檔的『函式本體以外』（模組層、類別層、裝飾器、預設參數）：
出現 `.today()` / `.now()` / `.utcnow()` / `time.strftime(` 即違規。
修法：改成函式或在測試內計算；真要凍結就用固定日期（如 date(2031, 6, 10)）。
"""
import ast
import pathlib
import warnings

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLOCK_ATTRS = {"today", "now", "utcnow"}


def _clock_calls(node, out, in_func=False):
    """遞迴；函式本體跳過，但裝飾器與預設參數仍算收集期。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        pre = list(getattr(node, "decorator_list", [])) + list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
        for p in pre:
            _clock_calls(p, out)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        a = node.func
        if a.attr in CLOCK_ATTRS or (a.attr == "strftime" and isinstance(a.value, ast.Name) and a.value.id == "time"):
            out.append(node.lineno)
    for ch in ast.iter_child_nodes(node):
        _clock_calls(ch, out)


def scan(src: str):
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(src)
    _clock_calls(tree, out)
    return out


def test_scanner_positive_control():
    assert scan("from datetime import date\nTODAY = date.today()\n") == [2]
    assert scan("import pytest\n@pytest.mark.parametrize('x', [date.today()])\ndef t(x): pass\n") == [2]
    assert scan("def f():\n    return date.today()\nclass A:\n    def g(self, d=None): return datetime.now()\n") == []


def test_no_clock_read_at_import_time():
    bad = []
    files = [p for p in ROOT.rglob("test_*.py") if ".venv" not in p.parts and "node_modules" not in p.parts]
    assert len(files) > 100          # 掃描器真的有掃到東西
    for p in files:
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "today(" not in src and "now(" not in src and "strftime" not in src:
            continue
        for ln in scan(src):
            bad.append("%s:%d" % (p.relative_to(ROOT).as_posix(), ln))
    assert not bad, "收集期取系統時鐘（跨午夜會偶發失敗）：\n" + "\n".join(bad)
