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


def callers(sources: dict) -> list:
    """{相對路徑: 原始碼} → 呼叫或匯入了寫入函式的檔案（名稱出現在 Call／Import／Attribute 上）。"""
    bad = []
    for rel, src in sources.items():
        if rel == OWNER:
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
        if hit:
            bad.append("%s：%s" % (rel, "、".join(sorted(hit))))
    return bad


def test_positive_control_detects_calls_imports_and_attribute_use():
    assert callers({"routers/x.py": "from modules.permmatrix.service import set_role_cap\n"})
    assert callers({"routers/x.py": "from modules.permmatrix import service as S\nS.set_user_override(c, a, 1, 'k', 'allow')\n"})
    assert callers({"modules/other/api/y.py": "fn = activate_due\n"})
    assert not callers({OWNER: "def set_role_cap():\n    pass\nset_role_cap()\n"})            # 定義處本身不算
    assert not callers({"routers/x.py": "from modules.permmatrix import service as S\nS.load_matrix(None)\nS.list_pending(c)\n"})   # 讀取函式不算


def test_no_product_code_calls_the_permmatrix_write_functions():
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    assert OWNER in srcs, "找不到 service.py ⇒ 路徑比對失效"
    bad = callers(srcs)
    assert not bad, "P0 寫入函式是過渡實作，帳本接上前不得有人呼叫（SPEC PMX14）：\n  " + "\n  ".join(bad)


def test_permmatrix_module_declares_no_routers():
    import modules.permmatrix as PM
    assert list(PM.MODULE.routers) == []
