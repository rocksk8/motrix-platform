"""basetemp 清理要刪得掉唯讀檔（conftest.remove_basetemp_tree）。

2026-09-25：測試在 tmp 建的 git repo，objects 是唯讀 ⇒ 舊版 `rmtree(ignore_errors=True)` 在 Windows 上
刪不掉、靜默略過，每一輪都留下目錄（使用者核心規則「測試暫存資料夾用完必刪」）。
"""
import os
import shutil
import subprocess

import pytest

import conftest


def _repo_with_readonly_objects(root):
    """真的建一個 git repo 並 add 一個檔 ⇒ .git/objects 底下有唯讀的物件檔。"""
    if shutil.which("git") is None:
        pytest.skip("這台機器沒有 git ⇒ 無法建立含唯讀 objects 的 repo（其餘判定照常在有 git 的機器上跑）")
    repo = root / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    objs = [p for p in (repo / ".git" / "objects").rglob("*") if p.is_file()]
    assert objs and all(not os.access(p, os.W_OK) for p in objs), "前提：objects 要是唯讀的"
    return repo


def test_readonly_git_objects_are_removed(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    _repo_with_readonly_objects(victim)
    assert conftest.remove_basetemp_tree(victim) is True
    assert not victim.exists()


def test_control_naive_rmtree_leaves_readonly_behind(tmp_path):
    """對照：拿掉「解除唯讀」那一步（＝舊版寫法）就刪不乾淨 ⇒ 上一題驗的確實是那一步。

    ⚠ 只在 Windows 成立（POSIX 上唯讀檔可由目錄權限刪除）；其他平台 skip 並寫明理由。
    """
    if os.name != "nt":
        pytest.skip("POSIX 上唯讀檔可隨目錄刪除，舊寫法不會失敗 ⇒ 對照只在 Windows 有意義")
    victim = tmp_path / "victim"
    victim.mkdir()
    _repo_with_readonly_objects(victim)
    shutil.rmtree(victim, ignore_errors=True)
    assert victim.exists(), "舊寫法居然刪乾淨了 ⇒ 這個 fixture 沒有造出唯讀難刪的情況，上一題不算數"
    assert conftest.remove_basetemp_tree(victim) is True     # 自己收尾


def test_sessionfinish_uses_the_readonly_aware_remover():
    """sessionfinish 必須走 remove_basetemp_tree，不是回到 rmtree(ignore_errors=True)。"""
    import inspect
    src = inspect.getsource(conftest.pytest_sessionfinish)
    assert "remove_basetemp_tree(" in src
    assert "ignore_errors=True" not in src
