# -*- coding: utf-8 -*-
"""SQL 裡的 `json_extract(` 只准變少（主持派工，§G5 #2；2026-09-27）。

成因：`json_extract(data_json, …)` 在 SQLite 裡**逐列**解析 JSON——資料表裡壞一筆（非法 JSON），
整個查詢丟例外，那一整類資料一起消失（AL2-M2、c-queue-json）。新寫的程式一律逐筆 Python 解析
（`approval_json_of` 那一種：壞的一筆跳過並記 ERROR）；既有的使用處列在 ROADMAP 階段 G 的 G8，逐步改掉。

- 範圍：`core.source_tree.product_files()`（backend 根、core、routers、helpers、modules/*，不含 tests／tools）。
- 算法（AST）：字串常數與 f-string 的常數片段裡 `json_extract(` 出現的次數（docstring 不算、`#` 註解 AST 看不到）；
  ＋引用「值裡含 json_extract 的模組層常數」的次數（例：`SQL_DEAL_TAG`——換個檔 import 它，不寫字面值也算）。
- 判準：每個檔的次數 ≤ 基線（json_extract_baseline.json）；基線沒有的檔出現 ⇒ 紅；降下來了 ⇒ 同一個 commit 重產基線
  （`python tests/platform/test_json_extract_ratchet.py --update`），不調的話之後加回去會照綠。模組不在（選配）⇒ 它的條目不比。
"""
import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "json_extract_baseline.json"
NEEDLE = "json_extract("


def _docstring_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _strings(tree):
    docs = _docstring_nodes(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            yield n.value


def constant_names(trees):
    """值裡含 json_extract 的模組層常數名（跨檔收集）。"""
    names = set()
    for tree in trees.values():
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(NEEDLE in s for s in _strings(ast.Module(body=[n], type_ignores=[]))):
                names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return names


def counts(sources):
    """{相對路徑: 原始碼} ⇒ {相對路徑: 次數}（只列 > 0）。"""
    trees = {rel: ast.parse(src) for rel, src in sources.items()}
    consts = constant_names(trees)
    out = {}
    for rel, tree in trees.items():
        n = sum(s.count(NEEDLE) for s in _strings(tree))
        for node in ast.walk(tree):
            name = node.id if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) else (
                node.attr if isinstance(node, ast.Attribute) else None)
            if name in consts:                   # 引用含 json_extract 的常數（定義那一行是 Store，不算）
                n += 1
        if n:
            out[rel] = n
    return out


def problems(found, baseline, installed=lambda rel: True):
    msgs = []
    for rel, n in sorted(found.items()):
        b = baseline.get(rel)
        if b is None:
            msgs.append("%s：新出現 %d 處 json_extract（新程式一律逐筆解析，§G5 #2）" % (rel, n))
        elif n > b:
            msgs.append("%s：json_extract %d 處，超過基線 %d（只准變少）" % (rel, n, b))
    for rel, b in sorted(baseline.items()):
        if not installed(rel):
            continue
        n = found.get(rel, 0)
        if n < b:
            msgs.append("%s：已降到 %d 處（基線 %d）⇒ 同一個 commit 重產基線（--update），否則之後加回去會照綠" % (rel, n, b))
    return msgs


def _real_sources():
    from core import source_tree
    return {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}


def test_json_extract_only_decreases():
    from core import source_tree
    sources = _real_sources()
    found = counts(sources)
    assert found, "正對照：掃不到任何 json_extract——量尺量不到東西（L1 的 db.py 本身就有）"
    if source_tree.module_installed("modules/case/"):
        assert "SQL_DEAL_TAG" in constant_names({r: ast.parse(s) for r, s in sources.items()}), "常數引用沒認出來"
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    msgs = problems(found, baseline, installed=source_tree.module_installed)
    assert not msgs, "\n".join(msgs)


def test_the_counter_sees_constants_and_skips_docstrings():
    """正對照＋反向控制（合成，不綁特定模組）。"""
    src = {
        "helpers/a.py": 'SQL_X = "COALESCE(json_extract(data_json,\'$.k\'), \'\')"\n'
                        'def f(c):\n    return c.execute("SELECT " + SQL_X + " FROM t")\n',
        "modules/zz/b.py": "from helpers.a import SQL_X\ndef g(c):\n    return c.execute(f'SELECT {SQL_X} FROM t')\n",
        "modules/zz/c.py": '"""說明裡提到 json_extract( 不算。"""\n# 註解 json_extract( 也不算\ndef h():\n    """json_extract( 在 docstring。"""\n    return 1\n',
        "modules/zz/d.py": "def k(c):\n    return c.execute(\"SELECT json_extract(a,'$.x'), json_extract(a,'$.y') FROM t\")\n",
    }
    got = counts(src)
    assert got == {"helpers/a.py": 2, "modules/zz/b.py": 1, "modules/zz/d.py": 2}, got
    base = {"helpers/a.py": 2, "modules/zz/d.py": 2}
    msgs = problems(got, base)
    assert len(msgs) == 1 and msgs[0].startswith("modules/zz/b.py：新出現"), msgs      # 換檔引用常數 ⇒ 紅
    assert problems(got, dict(base, **{"modules/zz/b.py": 1})) == []
    assert problems(dict(got, **{"modules/zz/d.py": 3}), dict(base, **{"modules/zz/b.py": 1}))[0].startswith(
        "modules/zz/d.py：json_extract 3 處，超過基線 2")
    lower = problems(dict(got, **{"modules/zz/d.py": 1}), dict(base, **{"modules/zz/b.py": 1}))
    assert len(lower) == 1 and "已降到 1 處" in lower[0], lower
    assert problems({}, {"modules/zz/d.py": 2}, installed=lambda rel: not rel.startswith("modules/zz/")) == []


def roadmap_rows(found):
    return ["| `%s` | %d |" % (rel, n) for rel, n in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


if __name__ == "__main__" and "--update" in sys.argv:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(HERE.parents[1]))
    found = counts(_real_sources())
    BASELINE.write_text(json.dumps(found, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print("已重產基線：%d 檔、%d 處" % (len(found), sum(found.values())))
    if "--roadmap" in sys.argv:
        print("\n".join(roadmap_rows(found)))
