# -*- coding: utf-8 -*-
"""權限矩陣的 P0 寫入函式是**過渡實作**（單人 24 小時待生效，不是『第二位最高管理者核准＋確認期』）。
在設定帳本（config_ledger）接上之前，任何端點、頁面或其他產品碼都不得呼叫它們（SPEC PMX14）。本守門在有人呼叫時變紅。
"""
import ast
from pathlib import Path

from core import source_tree

WRITE_FUNCS = {"set_role_cap", "set_user_override", "clear_user_override", "create_delegation", "revoke_delegation",
               "restore_version", "undo_last_change", "cancel_pending", "activate_due", "kick_activation"}
OWNER = "modules/permmatrix/service.py"       # 定義處與它自己的內部呼叫（restore 內部用 set_*、load_matrix 啟動背景轉態）
OWN_PACKAGE = {OWNER, "modules/permmatrix/__init__.py"}      # 模組宣告檔：匯入 service 登記提供者（只取 load_matrix）
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
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in WRITE_FUNCS:
                hit.add(n.attr)
            elif isinstance(n, ast.Name) and n.id in WRITE_FUNCS and isinstance(n.ctx, ast.Load):
                hit.add(n.id)
            elif isinstance(n, ast.ImportFrom) and any(a.name in WRITE_FUNCS for a in n.names):
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


def test_permmatrix_module_declares_only_the_status_probe_route():
    """1.0.2：只有唯讀狀態探針（D7 要求 provides.probes）；沒有任何寫入端點。"""
    import modules.permmatrix as PM
    assert len(PM.MODULE.routers) == 1
    routes = [(sorted(r.methods), r.path) for r in PM.MODULE.routers[0].routes]
    assert routes == [(["GET"], "/api/permmatrix/status")]
