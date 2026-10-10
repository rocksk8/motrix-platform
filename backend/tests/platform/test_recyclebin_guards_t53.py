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
_SKIP_DIRS = {"tests", "__pycache__", "migrations_frozen", "node_modules", ".git", "_demo_pdf_archive"}
_SKIP_TOP = {"tools"}                                  # 只跳 backend/tools（離線工具）；模組裡剛好叫 tools 的資料夾要掃
_SKIP_REL = ("modules/", "core/")                      # 這些底下的 migrations 資料夾不掃（凍結的建表／升版 SQL）


def product_files():
    """{相對 backend 的路徑(/): 原始碼}——產品碼（不含測試、凍結 migration、離線工具）。"""
    base = source_tree.BACKEND
    out = {}
    for d, dirs, files in os.walk(base):
        rel_dir = Path(d).relative_to(base).as_posix()
        dirs[:] = [x for x in dirs if x not in _SKIP_DIRS and not (rel_dir == "." and x in _SKIP_TOP)
                   and not (x == "migrations" and rel_dir.startswith(_SKIP_REL))]
        for fn in files:
            if fn.endswith(".py") and not fn.startswith("test_") and fn != "conftest.py":
                p = Path(d) / fn
                out[p.relative_to(base).as_posix()] = p.read_text(encoding="utf-8")
    return out


def _is_adapter(rel):
    return rel.rsplit("/", 1)[-1] == ADAPTER_FILE


# ── 1 路由 ─────────────────────────────────────────────────────────────────────
def _bin_aliases(tree):
    """這個檔把 `helpers.recycle_bin` 取了哪些名字：({模組別名}, {直接 import 的 delete 別名})。預設名 recycle_bin／RB 也算。"""
    mods, fns = {"recycle_bin", "RB"}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if (n.module or "") == "helpers" and a.name == "recycle_bin":
                    mods.add(a.asname or a.name)
                elif (n.module or "") == "helpers.recycle_bin" and a.name == "delete":
                    fns.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "helpers.recycle_bin" and a.asname:
                    mods.add(a.asname)
    return mods, fns


def _calls_bin_delete(fn, aliases=None):
    mods, fns = aliases or ({"recycle_bin", "RB"}, set())
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "delete":
                v = f.value
                if (isinstance(v, ast.Name) and v.id in mods) or (isinstance(v, ast.Attribute) and v.attr == "recycle_bin"):
                    return True
            elif isinstance(f, ast.Name) and f.id in fns:
                return True
    return False


def _delete_route_paths(fn):
    """函式上所有『DELETE 路由』裝飾器的路徑：`@x.delete(p)`、`@x.api_route(p, methods=[..'DELETE'..])`、`@x.route(...)`。`add_api_route(p, fn, methods=[...])` 另在 scan_routes 處理。"""
    out = []
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args):
            continue
        a = d.args[0]
        path = a.value if isinstance(a, ast.Constant) else (ast.unparse(a) if hasattr(ast, "unparse") else "?")
        if d.func.attr == "delete":
            out.append(path)
        elif d.func.attr in ("api_route", "route") and any(
                k.arg == "methods" and "DELETE" in ast.unparse(k.value).upper() for k in d.keywords):
            out.append(path)
    return out


def scan_routes(files):
    """⇒ {key: migrated(bool)}；key＝`檔::函式::DELETE 路徑`。只認 `@<x>.delete("<path>")` 形式的裝飾器。"""
    out = {}
    for rel, src in files.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        aliases = _bin_aliases(tree)
        funcs = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            funcs.setdefault(fn.name, fn)
            for path in _delete_route_paths(fn):
                out["%s::%s::DELETE %s" % (rel, fn.name, path)] = _calls_bin_delete(fn, aliases)
        for c in ast.walk(tree):                       # app.add_api_route("/x", handler, methods=["DELETE"])
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "add_api_route" and len(c.args) >= 2
                    and any(k.arg == "methods" and "DELETE" in ast.unparse(k.value).upper() for k in c.keywords)):
                a, h = c.args[0], c.args[1]
                path = a.value if isinstance(a, ast.Constant) else ast.unparse(a)
                name = h.id if isinstance(h, ast.Name) else ast.unparse(h)
                out["%s::%s::DELETE %s" % (rel, name, path)] = bool(funcs.get(name)) and _calls_bin_delete(funcs[name], aliases)
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
_DEL_SQL = re.compile(r"DELETE\s+FROM\s+([\"'`\[]?[A-Za-z_{][A-Za-z0-9_{}.]*[\"'`\]]?)", re.I)


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
            text = None
            if isinstance(n, ast.JoinedStr):                       # f-string：把 {表達式} 還原成文字（表名常常是 {tbl}），其下的常數片段不再單獨算
                text = "".join(v.value if isinstance(v, ast.Constant) else "{%s}" % ast.unparse(v.value) for v in n.values if isinstance(v, (ast.Constant, ast.FormattedValue)))
                doc_nodes.update(id(v) for v in n.values if isinstance(v, ast.Constant))
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes:
                text = n.value
            if text is not None:
                for m in _DEL_SQL.finditer(text):
                    key = "%s::%s" % (rel, m.group(1).strip("\"'`[]").lower())
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
        os_names, sh_names, direct = {"os"}, {"shutil"}, set()
        for c in ast.walk(tree):                       # 別名：import os as _os／import shutil as sh／from os import remove as rm
            if isinstance(c, ast.Import):
                for a in c.names:
                    if a.name == "os":
                        os_names.add(a.asname or "os")
                    elif a.name == "shutil":
                        sh_names.add(a.asname or "shutil")
            elif isinstance(c, ast.ImportFrom) and c.module in ("os", "shutil"):
                for a in c.names:
                    if (c.module, a.name) in _REMOVERS:
                        direct.add(a.asname or a.name)
        pairs = {(b, "remove") for b in os_names} | {(b, "unlink") for b in os_names} | {(b, "rmdir") for b in os_names} | {(b, "removedirs") for b in os_names} \
            | {(b, "rmtree") for b in sh_names}
        for c in ast.walk(tree):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in direct:
                n += 1
            elif isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute):
                base = c.func.value
                if isinstance(base, ast.Name) and (base.id, c.func.attr) in pairs:
                    n += 1
                elif c.func.attr == "unlink" and (not c.args or (len(c.args) == 1 and isinstance(base, ast.Name) and base.id in ("Path", "pathlib"))):
                    n += 1                              # p.unlink()／Path.unlink(p)
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
    migrated = sum(1 for v in scan_routes(product_files()).values() if v)
    assert sum(1 for r in b["routes"].values() if r.startswith("p1:")) + migrated >= 9, "第一期核心單據的 DELETE 路由：基線 p1: ＋ 已接入的 ≥ 9"


# 稽核補強（1d）：別名 import、api_route／add_api_route、f-string 表名、from os import remove 等不再是盲點
def test_scanners_have_no_alias_or_dynamic_blind_spots():
    aliased = "from helpers import recycle_bin as _rb\n@router.delete('/a/{i}')\ndef f(i):\n    _rb.delete(conn, 't', i, u)\n"
    assert list(scan_routes({"x.py": aliased}).values()) == [True], "別名 import 的已接入路由要認得"
    direct = "from helpers.recycle_bin import delete as bd\n@router.delete('/a/{i}')\ndef f(i):\n    bd(conn, 't', i, u)\n"
    assert list(scan_routes({"x.py": direct}).values()) == [True]
    api_route = "@router.api_route('/b/{i}', methods=['GET', 'DELETE'])\ndef g(i):\n    pass\n"
    assert list(scan_routes({"x.py": api_route}).values()) == [False], "api_route(methods=[DELETE]) 也是刪除路由"
    added = "def h(i):\n    pass\napp.add_api_route('/c/{i}', h, methods=['DELETE'])\n"
    assert list(scan_routes({"x.py": added}).values()) == [False]
    assert scan_routes({"x.py": "@router.get('/d')\ndef k():\n    pass\n"}) == {}
    sql = 'conn.execute(f"DELETE FROM {tbl} WHERE id=?")\nconn.execute(\'DELETE FROM "quoted_t" WHERE 1\')\nconn.execute("delete from [br_t]")'
    assert scan_delete_sql({"x.py": sql}) == {"x.py::{tbl}": 1, "x.py::quoted_t": 1, "x.py::br_t": 1}
    rm = ("import os as _os\nimport shutil as sh\nfrom os import remove as rm\nfrom pathlib import Path\n"
          "_os.remove(a)\nsh.rmtree(b)\nrm(c)\nPath.unlink(d)\np.unlink()\nPL.unlink(conn, 1)\n")
    assert scan_file_removals({"x.py": rm}) == {"x.py": 5}, "別名與 Path.unlink(p) 都數；領域方法 PL.unlink(conn, …) 不數"


def test_recyclebin_own_purge_route_is_baselined_not_skipped():
    routes = scan_routes(product_files())
    key = "modules/recyclebin/api.py::bin_purge::DELETE /api/recycle-bin/{bin_id}"
    assert routes.get(key) is False and _baseline()["routes"][key].startswith("exempt:")


# ── 第 53 班 R5：delete_scope 只能用在一般 `def` 端點 ───────────────────────────────────────────
# delete_scope 用 threading.local 記「這個區塊內的刪除」；`async def` 端點在事件迴圈執行緒上跑，多個請求交錯 ⇒ 登記會串到別的請求。
def _async_funcs_using_delete_scope(src: str) -> list:
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.AsyncFunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    if (isinstance(f, ast.Attribute) and f.attr == "delete_scope") or (isinstance(f, ast.Name) and f.id == "delete_scope"):
                        out.append(node.name)
                        break
    return out


def _sync_funcs_using_delete_scope(src: str) -> list:
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "delete_scope":
                    out.append(node.name)
                    break
    return out


def test_delete_scope_is_never_used_inside_an_async_endpoint():
    bad = {rel: _async_funcs_using_delete_scope(src) for rel, src in product_files().items() if "delete_scope" in src}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "delete_scope 不可用在 async def 端點（threading.local 會串到別的請求）：%s" % bad


def test_the_delete_scope_scanner_sees_both_kinds_and_the_endpoints_use_it():
    assert _async_funcs_using_delete_scope("async def f():\n    with recycle_bin.delete_scope():\n        pass\n") == ["f"], "正對照：抓得到 async 誤用"
    assert _async_funcs_using_delete_scope("def f():\n    with recycle_bin.delete_scope():\n        pass\n") == []
    users = [rel for rel, src in product_files().items() if "delete_scope" in src and _sync_funcs_using_delete_scope(src)]
    assert len(users) >= 9, "掃描器要看得到現有的刪除端點（基數檢查）：%s" % users
