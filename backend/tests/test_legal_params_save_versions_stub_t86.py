# -*- coding: utf-8 -*-
"""T86（PM 裁示 A）：`legal_params.save_versions` 已停用——保留介面（不刪 L1 公開介面 ⇒ 不用升主版號），呼叫會報白話錯誤；全庫沒有呼叫點。

[單位] helper:legal_params
"""
import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_stub_raises_a_plain_error_and_writes_nothing():
    from helpers import legal_params as LP
    with pytest.raises(RuntimeError) as e:
        LP.save_versions([{"effective_date": "2026-01-01"}])
    assert "已移除" in str(e.value) and "設定登錄表" in str(e.value)


def test_interface_is_kept():
    """不刪名字：L1 介面快照裡仍有它（刪除要升主版號）。"""
    from helpers import legal_params as LP
    assert callable(LP.save_versions)


def test_nobody_calls_save_versions_anywhere():
    """全庫（backend／tools，含測試）沒有任何 `save_versions(...)` 呼叫；只有定義本身。"""
    calls = []
    roots = [BACKEND, BACKEND.parent / "tools"]
    for root in roots:
        for p in root.rglob("*.py"):
            parts = set(p.parts)
            if parts & {".venv", ".venv312", "node_modules", "__pycache__", "site-packages"}:
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if name == "save_versions":
                        calls.append(f"{p.relative_to(BACKEND.parent)}:{n.lineno}")
    assert not calls, "還有人呼叫已停用的 legal_params.save_versions：" + "、".join(calls)


def test_positive_control_scanner_sees_a_call(tmp_path):
    """正對照：同一套判斷抓得到一個真的呼叫（不是掃不到才綠）。"""
    tree = ast.parse("import x\nx.save_versions([])\nsave_versions(1)\n")
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            names.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None))
    assert names.count("save_versions") == 2
