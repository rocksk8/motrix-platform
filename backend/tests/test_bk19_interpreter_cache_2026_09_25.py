"""BK19 只放行「執行中環境底下的 __pycache__」（conftest._bk19_interpreter_bytecode_cache）。

2026-09-25：改用專案 .venv 後，從 worktree 跑測試時 Python 在 .venv 的 site-packages 建 __pycache__，
被 BK19 當成「寫到 repo 外」的事故。放行範圍要窄：名字要是 __pycache__、位置要在 sys.prefix／base_prefix 底下。
"""
import sys
from pathlib import Path

import conftest


def test_bytecode_cache_under_the_running_environment_is_allowed():
    p = Path(sys.prefix) / "Lib" / "site-packages" / "anyio" / "__pycache__" / "x.cpython.pyc"
    assert conftest._bk19_write_allowed(p)


def test_other_writes_under_the_environment_are_still_blocked():
    p = Path(sys.prefix) / "Lib" / "site-packages" / "evil.txt"
    assert not conftest._bk19_write_allowed(p)


def test_pycache_outside_the_environment_is_still_blocked():
    """反向控制：只看名字不看位置的放行，會讓任何地方的 __pycache__ 都能寫。"""
    p = Path("Q:/") / "somewhere" / "__pycache__" / "x.pyc"
    assert not conftest._bk19_write_allowed(p)
