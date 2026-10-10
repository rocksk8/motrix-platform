# -*- coding: utf-8 -*-
"""第 53 班 P0：刪除暫存區的三道守門——『沒有任何刪除路徑被漏掉』（設計 RECYCLE-BIN-DESIGN-T52.md §4）。

為什麼要守：暫存區的承諾是『任何刪除先進暫存區』。只要有一條刪除路徑繞過去（新增的 DELETE 路由、手寫的 `DELETE FROM`、直接 `os.remove` 刪附件），
那條路徑刪掉的東西就永遠救不回來，而且沒有人會發現——所以要用**掃描**守，不靠記性。

三道（都是『棘輪』：基線 `recyclebin_baseline_t53.json` 只准縮小，新增的刪除路徑一律先擋下）：
1. 路由表：所有 `@router.delete(...)` 路由。呼叫 `recycle_bin.delete(` 的＝已接入；其餘必須在基線 `routes` 登記並寫理由——
   `p1:`＝第一期核心單據（待接入）、`p2:`＝其他業務資料（之後）、`exempt:`＝不是使用者資料（session、設定、快取…）。已接入的不可還留在基線（棘輪）。
2. `DELETE FROM <表>` 表覆蓋：每個（檔案, 表）一筆基線；次數只准減少；adapter 檔（檔名 `recycle_adapter.py`）內的 DELETE FROM 是 `delete_in_tx` 的實作，免登記。
3. 直接刪檔：`os.remove／os.unlink／shutil.rmtree／….unlink()` 每個檔一筆基線；`recyclebin/quarantine.py` 與 adapter 檔免登記。
每一道都有 EXEMPT（＝基線裡的 `exempt:`／`tmp:` 類，必須寫非空理由）、正對照（掃描器抓得到）與突變題（改壞一個就紅）。
"""
import ast
import json
import os
import re
from pathlib import Path

from core import source_tree

BASELINE = Path(__file__).with_name("recyclebin_baseline_t53.json")
ADAPTER_FILE = "recycle_adapter.py"
QUARANTINE = "modules/recyclebin/quarantine.py"
REASON_PREFIXES = ("p1:", "p2:", "exempt:", "tmp:")
_SKIP_DIRS = {"tests", "__pycache__", "migrations_frozen", "node_modules", ".git", "tools", "migrations", "_demo_pdf_archive"}


def product_files():
    """{相對 backend 的路徑(/): 原始碼}——產品碼（不含測試、凍結 migration、離線工具）。"""
    base = source_tree.BACKEND
    out = {}
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in _SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py") and not fn.startswith("test_") and fn != "conftest.py":
                p = Path(d) / fn
                out[p.relative_to(base).as_posix()] = p.read_text(encoding="utf-8")
    return out


def _is_adapter(rel):
    return rel.rsplit("/", 1)[-1] == ADAPTER_FILE


# ── 1 路由 ─────────────────────────────────────────────────────────────────────
def _calls_bin_delete(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "delete":
            v = n.func.value
            if (isinstance(v, ast.Name) and v.id in ("recycle_bin", "RB")) or (isinstance(v, ast.Attribute) and v.attr == "recycle_bin"):
                return True
    return False


def scan_routes(files):
    """⇒ {key: migrated(bool)}；key＝`檔::函式::DELETE 路徑`。只認 `@<x>.delete("<path>")` 形式的裝飾器。"""
    out = {}
    for rel, src in files.items():
        if rel == "modules/recyclebin/api.py":
            continue                                   # 暫存區自己的『永久刪除』：本身就是暫存區的最後一步，不能再進暫存區（見基線 exempt 說明）
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in fn.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "delete" and d.args):
                    a = d.args[0]
                    path = a.value if isinstance(a, ast.Constant) else (ast.unparse(a) if hasattr(ast, "unparse") else "?")
                    out["%s::%s::DELETE %s" % (rel, fn.name, path)] = _calls_bin_delete(fn)
    return out


def check_routes(found, baseline_routes):
    problems = []
    for key, migrated in sorted(found.items()):
        if migrated:
            if key in baseline_routes:
                problems.append("已接入暫存區的路由還留在基線（棘輪：請從基線移除）：%s" % key)
        elif key not in baseline_routes:
            problems.append("新的 DELETE 路由沒有進暫存區（改呼叫 helpers.recycle_bin.delete，或在基線登記 exempt: 並寫理由）：%s" % key)
    for key, reason in baseline_routes.items():
        if key not in found:
            problems.append("基線登記的路由已不存在（請移除）：%s" % key)
        if not str(reason).startswith(REASON_PREFIXES) or len(str(reason).split(":", 1)[1].strip()) < 2:
            problems.append("基線理由必須以 %s 開頭並寫具體內容：%s → %r" % ("/".join(REASON_PREFIXES), key, reason))
    return problems


# ── 2 DELETE FROM ─────────────────────────────────────────────────────────────
_DEL_SQL = re.compile(r"DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)


def scan_delete_sql(files):
    """⇒ {`檔::表`: 次數}。adapter 檔略過。只數字串常數裡的 SQL（避開註解／docstring 的說明文字：AST 取 Constant）。"""
    out = {}
    for rel, src in files.items():
        if _is_adapter(rel):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        doc_nodes = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                    and isinstance(getattr(n.body[0], "value", None), ast.Constant):
                doc_nodes.add(id(n.body[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes:
                for m in _DEL_SQL.finditer(n.value):
                    key = "%s::%s" % (rel, m.group(1).lower())
                    out[key] = out.get(key, 0) + 1
    return out


def check_sql(found, baseline_sql):
    problems = []
    for key, n in sorted(found.items()):
        if key not in baseline_sql:
            problems.append("新的 DELETE FROM 沒有進暫存區（放進 adapter 的 delete_in_tx 並走 helpers.recycle_bin.delete，或在基線登記並寫理由）：%s ×%d" % (key, n))
        elif n > int(baseline_sql[key]["count"]):
            problems.append("DELETE FROM 次數增加（基線 %s，現在 %d）：%s" % (baseline_sql[key]["count"], n, key))
    for key, ent in baseline_sql.items():
        if key not in found:
            problems.append("基線登記的 DELETE FROM 已不存在（請移除）：%s" % key)
        elif found[key] < int(ent["count"]):
            problems.append("DELETE FROM 次數減少了（基線 %s，現在 %d）——請把基線調成 %d（棘輪只准縮小）：%s" % (ent["count"], found[key], found[key], key))
        r = str(ent.get("reason", ""))
        if not r.startswith(REASON_PREFIXES) or len(r.split(":", 1)[-1].strip()) < 2:
            problems.append("基線理由必須以 %s 開頭並寫具體內容：%s" % ("/".join(REASON_PREFIXES), key))
    return problems


# ── 3 直接刪檔 ────────────────────────────────────────────────────────────────
_REMOVERS = {("os", "remove"), ("os", "unlink"), ("shutil", "rmtree"), ("os", "rmdir"), ("os", "removedirs")}


def scan_file_removals(files):
    """⇒ {檔: 次數}。`os.remove／os.unlink／shutil.rmtree／os.rmdir／os.removedirs` 與任何不帶位置參數的 `<x>.unlink()`（Path.unlink；`PL.unlink(conn, …)` 這類領域方法不算）。quarantine 與 adapter 檔略過。"""
    out = {}
    for rel, src in files.items():
        if rel == QUARANTINE or _is_adapter(rel):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        n = 0
        for c in ast.walk(tree):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute):
                base = c.func.value
                if isinstance(base, ast.Name) and (base.id, c.func.attr) in _REMOVERS:
                    n += 1
                elif c.func.attr == "unlink" and not c.args:
                    n += 1
        if n:
            out[rel] = n
    return out


def check_removals(found, baseline_rm):
    problems = []
    for rel, n in sorted(found.items()):
        if rel not in baseline_rm:
            problems.append("新的直接刪檔（用戶資料的附件請交給暫存區 adapter；暫存檔／備份輪替請在基線登記 tmp:／exempt: 並寫理由）：%s ×%d" % (rel, n))
        elif n > int(baseline_rm[rel]["count"]):
            problems.append("直接刪檔次數增加（基線 %s，現在 %d）：%s" % (baseline_rm[rel]["count"], n, rel))
    for rel, ent in baseline_rm.items():
        if rel not in found:
            problems.append("基線登記的直接刪檔已不存在（請移除）：%s" % rel)
        elif found[rel] < int(ent["count"]):
            problems.append("直接刪檔次數減少了（基線 %s，現在 %d）——請把基線調成 %d：%s" % (ent["count"], found[rel], found[rel], rel))
        r = str(ent.get("reason", ""))
        if not r.startswith(REASON_PREFIXES) or len(r.split(":", 1)[-1].strip()) < 2:
            problems.append("基線理由必須以 %s 開頭並寫具體內容：%s" % ("/".join(REASON_PREFIXES), rel))
    return problems


# ── 題目 ──────────────────────────────────────────────────────────────────────
def _baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_every_delete_route_goes_to_the_bin_or_is_baselined():
    assert check_routes(scan_routes(product_files()), _baseline()["routes"]) == []


def test_every_delete_from_table_is_baselined_and_only_shrinks():
    assert check_sql(scan_delete_sql(product_files()), _baseline()["delete_from"]) == []


def test_every_direct_file_removal_is_baselined_and_only_shrinks():
    assert check_removals(scan_file_removals(product_files()), _baseline()["file_removals"]) == []


# 正對照：掃描器真的抓得到（否則『全綠』可能只是掃不到）
def test_scanners_see_the_real_tree():
    files = product_files()
    routes, sql, rm = scan_routes(files), scan_delete_sql(files), scan_file_removals(files)
    assert any("quotations.py::delete_quotation::DELETE /api/quotations/{quote_no}" in k for k in routes), "抓不到最核心的刪除路由"
    assert len(routes) >= 50 and any(k.endswith("::quotations") for k in sql) and any(k.endswith("helpers/uploads.py") for k in rm)
    assert not any(k.startswith("modules/recyclebin/") for k in rm), "quarantine.py 與模組其餘檔案不應出現在直接刪檔清單"


_ROUTE_SRC = '''
from fastapi import APIRouter
router = APIRouter()
@router.delete("/api/things/{tid}")
def delete_thing(tid):
    conn.execute("DELETE FROM things WHERE id=?", (tid,))
    os.remove(path)
'''
_ROUTE_MIGRATED = '''
from helpers import recycle_bin
@router.delete("/api/things/{tid}")
def delete_thing(tid):
    recycle_bin.delete(conn, "thing", tid, user)
'''


# 突變：加一條沒進暫存區的 DELETE 路由／DELETE FROM／直接刪檔 ⇒ 各自轉紅
def test_mutation_new_delete_route_turns_red():
    base = scan_routes(product_files())
    mutated = scan_routes({"routers/zzz.py": _ROUTE_SRC})
    assert list(mutated.values()) == [False]
    probs = check_routes({**base, **mutated}, _baseline()["routes"])
    assert len(probs) == 1 and "routers/zzz.py::delete_thing" in probs[0]
    migrated = scan_routes({"routers/zzz.py": _ROUTE_MIGRATED})
    assert list(migrated.values()) == [True] and check_routes({**base, **migrated}, _baseline()["routes"]) == [], "已接入的新路由不用登記"


def test_mutation_ratchet_rejects_a_baselined_route_that_is_now_migrated_or_gone():
    key = "routers/zzz.py::delete_thing::DELETE /api/things/{tid}"
    assert any("棘輪" in p for p in check_routes({key: True}, {key: "p1: 測試"}))
    assert any("已不存在" in p for p in check_routes({}, {key: "p1: 測試"}))
    assert any("理由" in p for p in check_routes({key: False}, {key: ""}))
    assert any("理由" in p for p in check_routes({key: False}, {key: "later"}))


def test_mutation_new_delete_from_and_more_of_the_same_turn_red():
    base = scan_delete_sql(product_files())
    new = scan_delete_sql({"routers/zzz.py": _ROUTE_SRC})
    assert new == {"routers/zzz.py::things": 1}
    assert any("routers/zzz.py::things" in p for p in check_sql({**base, **new}, _baseline()["delete_from"]))
    key = next(iter(base))
    more = dict(base)
    more[key] += 1
    assert any("次數增加" in p for p in check_sql(more, _baseline()["delete_from"]))
    less = dict(base)
    less[key] -= 1 if less[key] > 1 else 0
    if less[key] != base[key]:
        assert any("次數減少" in p for p in check_sql(less, _baseline()["delete_from"]))


def test_adapter_files_and_comments_are_not_flagged():
    assert scan_delete_sql({"modules/x/recycle_adapter.py": _ROUTE_SRC}) == {} and scan_file_removals({"modules/x/recycle_adapter.py": _ROUTE_SRC}) == {}
    commented = '"""說明：這裡原本有 DELETE FROM things 與 os.remove(x)"""\n# DELETE FROM things\nx = 1\n'
    assert scan_delete_sql({"a.py": commented}) == {} and scan_file_removals({"a.py": commented}) == {}


def test_mutation_new_direct_file_removal_turns_red():
    base = scan_file_removals(product_files())
    new = scan_file_removals({"routers/zzz.py": _ROUTE_SRC})
    assert new == {"routers/zzz.py": 1}
    assert any("routers/zzz.py" in p for p in check_removals({**base, **new}, _baseline()["file_removals"]))
    pathlib_style = scan_file_removals({"routers/yyy.py": "from pathlib import Path\nPath(p).unlink()\n"})
    assert pathlib_style == {"routers/yyy.py": 1}, "Path.unlink 也算"
    assert scan_file_removals({QUARANTINE: _ROUTE_SRC}) == {}, "quarantine.py 免登記"


def test_recyclebin_module_files_do_not_remove_files_outside_quarantine():
    mine = {k: v for k, v in product_files().items() if k.startswith("modules/recyclebin/") and k != QUARANTINE}
    assert mine and scan_file_removals(mine) == {} and scan_delete_sql(mine) == {}


def test_baseline_file_is_well_formed():
    b = _baseline()
    assert set(b) == {"_doc", "routes", "delete_from", "file_removals"}
    assert len(b["routes"]) >= 50
    assert sum(1 for r in b["routes"].values() if r.startswith("p1:")) >= 9, "第一期核心單據的 DELETE 路由要列在基線（p1:）"
    assert any(k.endswith("::case_material_approvals") and v["reason"].startswith("p1:") for k, v in b["delete_from"].items()), "材料申請（採購單）是存檔 diff 內的隱性刪除，要列 p1:"
