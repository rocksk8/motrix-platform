# -*- coding: utf-8 -*-
"""守門：測試不可以在**共用的 backend/tests 目錄**建暫存檔（改建在 tmp_path 底下）。

成因（2026-09-30 列車全量）：`test_zz_gf_commit_*.py` 這類暫存測試檔由某一題建立又刪除；同時間另一題的子 pytest 收集同一個目錄，
剛好撞到檔案被刪 ⇒ FileNotFoundError ⇒ `test_module_selection::test_after_restart_the_module_is_gone_and_data_stays` 紅一次
（O6 同型：`_hardcap_probe_*` 目錄被同時刪掉）。單獨重跑綠——是題目之間共用目錄的競態，不是產品問題。

判準（AST，靜態）：測試函式內，凡是把「含 `__file__` 或同時含 "backend"／"tests" 字串常數的路徑運算」指定給變數，
又對該變數呼叫 write_text／write_bytes／mkdir／touch／unlink／rmdir／rename／replace ⇒ 命中。
白名單要寫理由；次數要一致（多了少了都紅）。
"""
import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
WRITE_ATTRS = {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename", "replace"}

#: (相對 backend 的路徑, 函式) → (命中次數, 理由)
ALLOWED = {
    ("tests/test_exception_detail_leak_2026_09_23.py", "test_em3_the_scanner_still_catches_a_synthetic_leak"): (
        2, "誘餌檔必須在 ROOT（backend/）底下（掃描器對結果算 relative_to）；檔名不是 test_*.py（pytest 不收集）且加 uuid（互不覆蓋）"),
}


def _const_strs(node):
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _shared_vars(fn):
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.BinOp):
            strs = _const_strs(n.value)
            if ("backend" in strs and "tests" in strs) or any(isinstance(x, ast.Name) and x.id == "__file__" for x in ast.walk(n.value)):
                names.add(n.targets[0].id)
    return names


def scan_source(src):
    """⇒ [(函式, 行, 變數.方法)]"""
    tree = ast.parse(src)
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        vs = _shared_vars(fn)
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITE_ATTRS
                    and isinstance(n.func.value, ast.Name) and n.func.value.id in vs):
                out.append((fn.name, n.lineno, "%s.%s" % (n.func.value.id, n.func.attr)))
    return out


def scan_tree(root=BACKEND):
    hits = []
    for p in sorted(Path(root).rglob("test_*.py")):
        rel = p.relative_to(root).as_posix()
        if "node_modules" in rel or rel == "tests/platform/test_no_temp_files_in_shared_tests_dir_2026_09_30.py":
            continue
        try:
            src = p.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        hits += [(rel,) + h for h in scan_source(src)]
    return hits


def problems(hits, allowed=None):
    allowed = ALLOWED if allowed is None else allowed
    counts = {}
    for rel, fn, _line, _what in hits:
        counts[(rel, fn)] = counts.get((rel, fn), 0) + 1
    out = []
    for k, n in sorted(counts.items()):
        a = allowed.get(k)
        if a is None:
            out.append("%s::%s 在共用的 tests 目錄建／刪檔 ×%d（改建在 tmp_path 底下）" % (k[0], k[1], n))
        elif a[0] != n:
            out.append("%s::%s 白名單登記 %d 次，實際 %d 次（理由：%s）" % (k[0], k[1], a[0], n, a[1]))
    for k, (n, why) in sorted(allowed.items()):
        if k not in counts:
            out.append("白名單過期：%s::%s 已不再建暫存檔（%s）" % (k[0], k[1], why))
    return out


def test_no_test_creates_temp_files_in_the_shared_tests_dir():
    probs = problems(scan_tree())
    assert probs == [], "\n".join(probs)


def test_scanner_positive_controls():
    bad = ('import pathlib\n\ndef test_x():\n    p = pathlib.Path(__file__).resolve().parent / "t.py"\n    p.write_text("x")\n    p.unlink()\n')
    assert [(f, w) for f, _l, w in scan_source(bad)] == [("test_x", "p.write_text"), ("test_x", "p.unlink")]
    bad2 = 'def test_y(REPO):\n    f = REPO / "backend" / "tests" / "test_zz.py"\n    f.write_text("x")\n'
    assert [w for _f, _l, w in scan_source(bad2)] == ["f.write_text"]


def test_scanner_does_not_flag_tmp_path_work():
    ok = 'def test_z(tmp_path):\n    p = tmp_path / "a.py"\n    p.write_text("x")\n    p.unlink()\n'
    assert scan_source(ok) == []
    ok2 = 'def test_w(tmp_path, REPO):\n    r = tmp_path / "backend" / "tests"\n    r.mkdir(parents=True)\n'
    # tmp_path 底下的 backend/tests 也含 "backend"／"tests" 常數 ⇒ 會被啟發式判成命中——刻意保守，白名單處理；此處只記錄行為
    assert [w for _f, _l, w in scan_source(ok2)] == ["r.mkdir"]


def test_allowlist_counts_and_staleness_are_enforced():
    hits = [("a.py", "f", 1, "p.write_text"), ("a.py", "f", 2, "p.unlink")]
    assert problems(hits, {("a.py", "f"): (2, "x")}) == []
    assert problems(hits, {("a.py", "f"): (1, "x")}) and problems(hits, {}) and problems([], {("a.py", "f"): (1, "x")})
