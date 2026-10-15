# -*- coding: utf-8 -*-
"""T65 F7 S1b：掃出口檔案裡『直接呼叫四支角色函式』的次數（AST；不讀字串，註解與 import 不算）。"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROLE_FNS = ("quote_money_visible", "money_visible", "material_money_visible", "has_cashier_access")
#: 這些檔案本身就是角色函式的定義處／對映處，不算出口
OWNERS = ("helpers/financial_mask.py", "helpers/field_policy.py", "helpers/auth.py")


def count_calls(src: str) -> int:
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in ROLE_FNS:
                n += 1
    return n


def scan() -> dict:
    out = {}
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        parts = rel.split("/")
        if "tests" in parts or rel.startswith("tests/") or rel in OWNERS or "rollback_snapshots" in parts or ".venv" in rel:
            continue
        try:
            n = count_calls(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if n:
            out[rel] = n
    return dict(sorted(out.items()))
