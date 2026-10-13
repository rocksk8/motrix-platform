# -*- coding: utf-8 -*-
"""未經範圍讀取的 AST 掃描器（FRAMEWORK-ORG-UNITS-T57 §14.10 #6）。

對『帶單位欄位（owner_unit_id／unit_id／legal_entity_id）的業務表』的每個 SELECT（含 f-string／`+` 串接／`%`／`.format()`
組出的 SQL），若所在函式沒有經過 `filter_sql` 或核准的查詢 helper，就登記為一筆：

    id       = "<相對 backend 路徑>::<函式限定名>::<表>"        （不含行號，改行不動 id）
    category = "unscoped"   表名可解析、函式內沒有核准 helper
               "dynamic"    SQL 組出來看不到表名（`FROM {tbl}`、整句由參數傳入…）——單獨計數，不靜默放行

表清單取自 U0a core migration 常數（`U0A_OWNER_UNIT_TABLES`／`U0A_UNIT_ID_TABLES`／`U0A_LEGAL_ENTITY_TABLES`），不另抄一份。
`vouchers` 是 `vouchers_all` 的 VIEW，視同同一張表。

粒度（刻意粗）：核准 helper 只要出現在『同一函式（含外層函式）』內就算該函式的讀取都有走範圍；掃描器管的是『有沒有人想過範圍』，
不是證明每一句都過濾正確（那是 U1 起逐領域強制＋跨單位金標的事）。

重新產生基準：`cd backend && python -m tests.platform._unscoped_reads --write`（只在縮小時用；新增請先補範圍）。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from core import source_tree
from core.migrations import U0A_LEGAL_ENTITY_TABLES, U0A_OWNER_UNIT_TABLES, U0A_UNIT_ID_TABLES

BASELINE_PATH = Path(__file__).with_name("unscoped_reads_baseline.json")

#: 帶單位欄位的表（+ VIEW 別名）
UNIT_TABLES = frozenset(U0A_OWNER_UNIT_TABLES) | frozenset(U0A_UNIT_ID_TABLES) | frozenset(U0A_LEGAL_ENTITY_TABLES) | {"vouchers"}

#: 核准的範圍 helper（呼叫名，Name 或 Attribute 的最後一段）。新增前先確認它真的把單位／列權限收進查詢或判斷。
APPROVED_HELPERS = frozenset({
    "filter_sql",                                        # helpers/row_access：SQL 過濾
    "visible", "require",                                # helpers/row_access：單筆判斷
    "guard_case_access", "case_access_allowed",          # helpers/case_access：案件存取
    "require_case", "require_case_money",
    "case_owner_readable", "case_documents_readable", "case_page_readable",
})

_DYN = "\x00"                                            # 組字串時無法解析的片段
_SELECT = re.compile(r"\bSELECT\b", re.I)
_FROM_JOIN = re.compile(r"\b(?:FROM|JOIN)\s+(\(|\x00|[A-Za-z_]\w*)", re.I)
_FROM_CLAUSE = re.compile(r"\bFROM\s+(.*?)(?=\bWHERE\b|\bJOIN\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|\bHAVING\b|\bUNION\b|\)|$)", re.I | re.S)
#: 不掃：遷移／DDL 檔（一次性、不是使用者讀取路徑）
SKIP_PREFIXES = ("core/migrations.py",)
SKIP_PARTS = ("/migrations/",)
_EXEC_ATTRS = frozenset({"execute", "executemany", "executescript"})


def flatten(node):
    """字串組裝運算式 → 文字（無法解析的片段以 \\x00 佔位）；不是字串組裝回 None。"""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else _DYN for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        a = flatten(node.left)
        if isinstance(node.op, ast.Mod):
            return None if a is None else a.replace("%s", _DYN) if "%s" in a else a
        b = flatten(node.right)
        if a is None and b is None:
            return None
        return (_DYN if a is None else a) + (_DYN if b is None else b)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        a = flatten(node.func.value)
        return None if a is None else re.sub(r"\{[^{}]*\}", _DYN, a)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
        return _DYN if flatten(node.func.value) is not None else None
    return None


def tables_in(text: str):
    """SQL 文字 → (表名集合, 是否有看不到表名的 FROM/JOIN)。只有含 SELECT 的文字才算。"""
    if not _SELECT.search(text):
        return set(), False
    names, dyn = set(), False
    for m in _FROM_JOIN.finditer(text):
        tok = m.group(1)
        if tok == _DYN:
            dyn = True
        elif tok != "(":
            names.add(tok.lower())
    for m in _FROM_CLAUSE.finditer(text):                # `FROM a, b` 逗號串
        for part in m.group(1).split(",")[1:]:
            w = re.match(r"\s*([A-Za-z_]\w*)", part)
            if w:
                names.add(w.group(1).lower())
    if not names and not dyn and _DYN in text:           # SELECT 有、FROM 整段由別處拼進來
        dyn = True
    return names, dyn


def _call_name(call: ast.Call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


class _Scope:
    __slots__ = ("qual", "approved", "reads", "assigned", "exec_args")

    def __init__(self, qual, approved):
        self.qual, self.approved = qual, approved
        self.reads = []              # (表 | None, category)
        self.assigned = set()        # 本函式內以字串組裝賦值的變數名
        self.exec_args = []          # execute(<Name>) 的 Name


def _scan_scope(body_nodes, scope, module_sql_names, out_scopes, parent_approved):
    """走一個函式（或模組）本體；遇到巢狀 def／class 另開 scope。"""
    stack = list(body_nodes)
    expr_ids = set()
    nested = []                                          # 巢狀 def／class 等本體走完（helper 呼叫都看到了）再處理
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.append(node)
            for d in node.decorator_list + node.args.defaults:
                stack.append(d)
            continue
        if isinstance(node, ast.ClassDef):
            nested.append(node)
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                                     # docstring／孤立字串不是 SQL
        if isinstance(node, ast.Call):
            if _call_name(node) in APPROVED_HELPERS:
                scope.approved = True
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in _EXEC_ATTRS and node.args and isinstance(node.args[0], ast.Name):
                scope.exec_args.append(node.args[0].id)
        if isinstance(node, ast.expr) and id(node) not in expr_ids and isinstance(
                node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Call)):
            txt = flatten(node)
            if txt is not None:
                for sub in ast.walk(node):               # 最大運算式算一個：子運算式不重複計
                    expr_ids.add(id(sub))
                names, dyn = tables_in(txt)
                for t in sorted(names & UNIT_TABLES):
                    scope.reads.append((t, "unscoped"))
                if dyn:
                    scope.reads.append((None, "dynamic:from"))
                continue
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) for t in node.targets):
            if flatten(node.value) is not None:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        scope.assigned.add(t.id)
        stack.extend(ast.iter_child_nodes(node))
    out_scopes.append(scope)
    for node in nested:
        child = _Scope(scope.qual + "." + node.name if scope.qual != "<module>" else node.name, scope.approved)
        _scan_scope(node.body, child, module_sql_names, out_scopes, scope.approved)


def scan_source(rel: str, source: str) -> dict:
    """單一檔案 → {id: category}。語法錯誤的檔案回空（不會安靜放過：整套測試另有『能解析的檔案數』下限）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    scopes: list = []
    mod = _Scope("<module>", False)
    _scan_scope(tree.body, mod, set(), scopes, False)
    module_names = mod.assigned
    out: dict = {}
    for sc in scopes:
        for name in sc.exec_args:                        # execute(sql) 的 sql 在本函式／模組內沒有組裝 ⇒ 看不到
            if name not in sc.assigned and name not in module_names:
                sc.reads.append((None, "dynamic:arg:" + name))
        if sc.approved:
            continue
        for table, cat in sc.reads:
            if table is not None:
                out["%s::%s::%s" % (rel, sc.qual, table)] = "unscoped"
            else:
                out["%s::%s::<%s>" % (rel, sc.qual, cat[len("dynamic:"):])] = "dynamic"
    return out


def scan_all() -> dict:
    out: dict = {}
    for p in source_tree.product_files():
        r = source_tree.rel(p)
        if r.startswith(SKIP_PREFIXES) or any(x in "/" + r for x in SKIP_PARTS):
            continue
        out.update(scan_source(r, p.read_text(encoding="utf-8")))
    return dict(sorted(out.items()))


def counts(entries: dict) -> dict:
    c: dict = {}
    for v in entries.values():
        c[v] = c.get(v, 0) + 1
    return dict(sorted(c.items()))


def dump(entries: dict) -> str:
    """基準檔格式：一筆一行、依 id 排序（rebase 衝突只在相鄰行）。"""
    lines = ['  %s: %s' % (json.dumps(k, ensure_ascii=False), json.dumps(v)) for k, v in sorted(entries.items())]
    return '{\n "entries": {\n%s\n }\n}\n' % ",\n".join(lines)


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["entries"]


if __name__ == "__main__":                                # python -m tests.platform._unscoped_reads [--write]
    cur = scan_all()
    print("entries=%d %s" % (len(cur), counts(cur)))
    if "--write" in sys.argv:
        BASELINE_PATH.write_text(dump(cur), encoding="utf-8", newline="\n")
        print("wrote", BASELINE_PATH)
