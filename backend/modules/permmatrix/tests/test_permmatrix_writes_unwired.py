# -*- coding: utf-8 -*-
"""權限矩陣的 P0 寫入函式尚未接線（PM-S0 起待生效已是『第二位最高管理者核准＋確認期』）。
T67 PM-S0 已改走設定帳本（確認期間＋雙人核准）；端點與頁面屬 PM-S2／S3，在那之前任何端點、頁面或其他產品碼都不得呼叫它們（SPEC PMX14）。本守門在有人呼叫時變紅。
"""
import ast
from pathlib import Path

from core import source_tree

WRITE_FUNCS = {"set_role_cap", "set_user_override", "clear_user_override", "create_delegation", "revoke_delegation",
               "restore_version", "undo_last_change", "cancel_pending", "approve_pending", "activate_due", "kick_activation"}
OWNER = "modules/permmatrix/service.py"       # 定義處與它自己的內部呼叫（restore 內部用 set_*、load_matrix 啟動背景轉態）
#: 模組自己的檔案：宣告檔（登記提供者，只取 load_matrix）、PM-S2 起的端點層 api.py 與唯讀檢視 views.py。其他產品碼一律不得取用 service。
OWN_PACKAGE = {OWNER, "modules/permmatrix/__init__.py", "modules/permmatrix/api.py", "modules/permmatrix/views.py"}
PKG = "modules.permmatrix"


def _fold(n):
    """把 `'a' + 'b'` 這種純字串常數相加折成一個字串；折不了回 None（只防不小心，不防刻意規避——SPEC PMX14）。"""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        l, r = _fold(n.left), _fold(n.right)
        if l is not None and r is not None:
            return l + r
    return None


def _touches_service(n) -> str:
    """這個節點是不是在取用 permmatrix 的 service（匯入、字串、屬性鏈）；回說明或空字串。堵住 getattr／importlib／globals() 之類的間接呼叫。"""
    if isinstance(n, ast.Import):
        for a in n.names:
            if a.name == PKG + ".service" or a.name.startswith(PKG + ".service."):
                return "import " + a.name
    elif isinstance(n, ast.ImportFrom):
        m = n.module or ""
        if m == PKG + ".service" or m.startswith(PKG + ".service."):
            return "from %s import …" % m
        if m == PKG and any(a.name in ("service", "*") for a in n.names):
            return "from %s import service/*" % PKG
    elif isinstance(n, (ast.Constant, ast.BinOp)):
        v = _fold(n)
        if v is not None and (v in WRITE_FUNCS or v == PKG + ".service" or v.startswith(PKG + ".service.")):
            return "字串 %r" % v
    elif isinstance(n, ast.Attribute) and n.attr == "service":
        try:
            if "permmatrix" in ast.unparse(n.value):
                return "屬性 %s" % ast.unparse(n)
        except Exception:                                                   # noqa: BLE001
            pass
    return ""


#: 與權限矩陣寫入函式同名、但屬於『設定帳本／定義』的模組（config_ledger.restore_version／cancel_pending 等）。
#: 只認『該檔自己 import 進來的別名』：`from helpers import config_ledger as ledger` ⇒ `ledger.restore_version(...)` 不算；
#: 其餘（含 getattr／字串／importlib 間接取用 permmatrix service）照舊全抓。
LEDGER_MODULES = {"config_ledger"}


def _ledger_imports(tree):
    """這個檔案裡綁到 config_ledger 的名稱：(模組別名集合, 從它 import 進來的函式名集合)。"""
    mods, names = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[-1] in LEDGER_MODULES:
                    if a.asname or "." not in a.name:
                        mods.add(a.asname or a.name)
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[-1] in LEDGER_MODULES:
                names |= {a.asname or a.name for a in n.names}
            else:
                for a in n.names:
                    if a.name in LEDGER_MODULES:
                        mods.add(a.asname or a.name)
    return mods, names


def callers(sources: dict) -> list:
    """{相對路徑: 原始碼} → 呼叫、匯入或以字串／屬性間接取用了寫入函式的檔案。
    名稱出現在 Call／Import／Attribute／Name，或字串常數等於函式名，或取用 permmatrix 的 service（匯入、字串、`xxx.permmatrix.service`）都算。"""
    bad = []
    for rel, src in sources.items():
        if rel in OWN_PACKAGE:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        hit = set()
        ledger_mods, ledger_names = _ledger_imports(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in WRITE_FUNCS:
                if isinstance(n.value, ast.Name) and n.value.id in ledger_mods:        # config_ledger.restore_version 等：同名但不是權限矩陣
                    continue
                hit.add(n.attr)
            elif isinstance(n, ast.Name) and n.id in WRITE_FUNCS and isinstance(n.ctx, ast.Load):
                if n.id in ledger_names:
                    continue
                hit.add(n.id)
            elif isinstance(n, ast.ImportFrom) and any(a.name in WRITE_FUNCS for a in n.names):
                if (n.module or "").split(".")[-1] in LEDGER_MODULES:
                    continue
                hit |= {a.name for a in n.names if a.name in WRITE_FUNCS}
            why = _touches_service(n)
            if why:
                hit.add(why)
        if hit:
            bad.append("%s：%s" % (rel, "、".join(sorted(hit))))
    return bad


_BAD_SAMPLES = {
    "from-import": "from modules.permmatrix.service import set_role_cap\n",
    "from-import alias": "from modules.permmatrix.service import set_role_cap as g\n",
    "from-package service": "from modules.permmatrix import service as S\nS.set_user_override(c, a, 1, 'k', 'allow')\n",
    "import-as + attribute": "import modules.permmatrix.service as S\nS.clear_user_override(c, a, 1, 'k')\n",
    "importlib + attribute": "import importlib\nm = importlib.import_module('modules.permmatrix.service')\nm.create_delegation()\n",
    "star-import": "from modules.permmatrix.service import *\n",
    "bare name load": "fn = activate_due\n",
    "getattr literal": "from modules.permmatrix import service as S\ngetattr(S, 'set_role_cap')(c, a, 'r', 'k', True)\n",
    "getattr concat": "import importlib\nS = importlib.import_module('modules.' + 'permmatrix.service')\ngetattr(S, 'set_' + 'role_cap')()\n",
    "globals lookup": "g = globals()['set_role_cap']\n",
    "dict-string dispatch": "TABLE = {'role': 'set_role_cap'}\n",
    "attribute chain": "import modules\nx = modules.permmatrix.service\n",
}


def test_same_name_functions_of_the_settings_ledger_are_not_flagged_but_permmatrix_ones_still_are():
    ok = "from helpers import config_ledger as ledger\nledger.restore_version(c, 'setting:x', 'x', 1, 'a')\nledger.cancel_pending(c, 1)\n"
    assert not callers({"routers/settings_center.py": ok})
    assert not callers({"routers/x.py": "from helpers.config_ledger import restore_version, cancel_pending\nrestore_version(c, 'd', 'k', 1, 'a')\n"})
    assert not callers({"routers/x.py": "from helpers import config_ledger\nconfig_ledger.restore_version(c)\n"})
    # 正對照：同一個檔案裡真正的權限矩陣呼叫仍然紅；別的別名（非帳本）呼叫同名函式也紅
    assert callers({"routers/x.py": ok + "from modules.permmatrix import service as S\nS.restore_version(c, a, 1, 'r')\n"})
    assert callers({"routers/x.py": "from helpers import perm as P\nP.restore_version(c, a, 1, 'r')\n"})
    assert callers({"routers/x.py": "from helpers import config_ledger as ledger\nother.restore_version(c)\n"})


def test_positive_control_detects_every_way_of_reaching_the_write_functions():
    missed = [k for k, src in _BAD_SAMPLES.items() if not callers({"routers/x.py": src})]
    assert not missed, "守門漏掉這些寫法：%s" % missed


def test_negative_control_definition_site_module_declaration_and_reads_are_not_flagged():
    assert not callers({OWNER: "def set_role_cap():\n    pass\nset_role_cap()\n"})
    assert not callers({"modules/permmatrix/__init__.py": "from modules.permmatrix import service\nx = service.load_matrix\n"})
    assert not callers({"routers/x.py": "from helpers import perm as P\nP.can(u, 'k')\nP.invalidate()\n"})


def test_no_product_code_calls_the_permmatrix_write_functions():
    """範圍註記：`source_tree.product_files()` 不含 backend/tools 與各層 tests（可接受：它們不是產品執行路徑）。"""
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    assert OWNER in srcs, "找不到 service.py ⇒ 路徑比對失效"
    bad = callers(srcs)
    assert not bad, "P0 寫入函式是過渡實作，帳本接上前不得有人呼叫（SPEC PMX14）：\n  " + "\n  ".join(bad)


def test_views_module_is_read_only():
    """PM-S2：`views.py` 只讀——不得出現任何寫入函式名（守門放行它取用 service 的前提）。"""
    src = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (names & WRITE_FUNCS), names & WRITE_FUNCS


def test_permmatrix_module_declares_exactly_the_reviewed_routes():
    """PM-S2 唯讀檢視＋PM-S3 寫入端點的完整清單（新增或移除路由要同一個 commit 改這份、route_inventory 與金標案例）。
    寫入端點全部在這個模組的 api.py，且 api.py 只做驗證＋呼叫服務層；其他產品碼仍不得取用 service（上面的守門）。"""
    import modules.permmatrix as PM
    assert len(PM.MODULE.routers) == 1
    routes = sorted((m, r.path) for r in PM.MODULE.routers[0].routes for m in r.methods)
    assert routes == sorted([
        ("GET", "/api/permmatrix/status"), ("GET", "/api/permmatrix/matrix"), ("GET", "/api/permmatrix/users"),
        ("GET", "/api/permmatrix/users/{user_id}/effective"), ("GET", "/api/permmatrix/pending"), ("GET", "/api/permmatrix/versions"),
        ("GET", "/api/permmatrix/delegations"),
        ("POST", "/api/permmatrix/role-cap"), ("POST", "/api/permmatrix/role-cap/preview"),
        ("POST", "/api/permmatrix/user-override"), ("POST", "/api/permmatrix/user-override/preview"), ("DELETE", "/api/permmatrix/user-override"),
        ("POST", "/api/permmatrix/pending/{pid}/cancel"), ("POST", "/api/permmatrix/pending/{pid}/approve"),
        ("POST", "/api/permmatrix/versions/{version_id}/restore"), ("POST", "/api/permmatrix/undo")])


def test_every_write_endpoint_checks_superadmin_first():
    """api.py 的每個非 GET 路由函式第一行都得先 `_su(authorization)`（縱深：服務層還會再查一次）。"""
    src = (Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    writes = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("post", "put", "patch", "delete"):
                writes.append(fn)
    assert len(writes) == 9, [f.name for f in writes]
    for fn in writes:
        first = ast.unparse(fn.body[0])
        assert "_su(authorization)" in first, (fn.name, first)
