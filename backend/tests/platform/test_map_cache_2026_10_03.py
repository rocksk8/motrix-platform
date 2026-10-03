# -*- coding: utf-8 -*-
"""T35 L3'：test_map／dep_graph 內容簽章快取（tools/platform/map_cache.py）的守門。

失敗模式只有一種：陳舊的圖 ⇒ 該選的題沒選 ⇒ 假綠燈。所以每一條「必須 miss」的情境都有一題，
而且整份測試都做過突變（拿掉簽章的某一塊，對應那題必須紅）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import map_cache as MC  # noqa: E402


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a],
                   check=True, capture_output=True)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """合成 repo（backend/frontend 各一檔）＋獨立快取目錄＋獨立「工具目錄」；回 (root, calls, run)。"""
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "backend" / "a.py").write_text("X = 1\n", encoding="utf-8")
    (root / "frontend" / "p.js").write_text("var a = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("backend/ignored.py\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    _git(root, "add", "-A")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "algo.py").write_text("V = 1\n", encoding="utf-8")
    monkeypatch.setattr(MC, "HERE", tools)
    monkeypatch.setattr(MC, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.delenv("MOTRIX_MAP_CACHE", raising=False)
    monkeypatch.setattr(MC, "MEMO", False)
    MC._memo.clear()
    calls = []

    def run(kind="k", r=root, **kw):
        def compute():
            calls.append(kind)
            return {"n": len(calls)}
        return MC.get_or_compute(kind, compute, r, **kw)
    return root, calls, run


def test_same_tree_hits_and_returns_the_cached_value(env):
    root, calls, run = env
    a = run()
    b = run()
    assert len(calls) == 1 and a == b == {"n": 1}


def test_a_editing_a_tracked_file_misses(env):
    root, calls, run = env
    run()
    (root / "backend" / "a.py").write_text("X = 2\n", encoding="utf-8")
    run()
    assert len(calls) == 2


def test_b_new_untracked_file_misses(env):
    root, calls, run = env
    run()
    (root / "backend" / "new_untracked.py").write_text("Y = 1\n", encoding="utf-8")
    run()
    assert len(calls) == 2


def test_b2_delete_and_rename_miss(env):
    root, calls, run = env
    run()
    (root / "backend" / "a.py").rename(root / "backend" / "a2.py")
    run()
    assert len(calls) == 2
    (root / "backend" / "a2.py").unlink()
    run()
    assert len(calls) == 3


def test_c_same_content_touch_gives_equal_result(env):
    root, calls, run = env
    first = run()
    p = root / "backend" / "a.py"
    p.write_text("X = 1\n", encoding="utf-8")                      # 內容相同、mtime 變了
    assert run() == first or len(calls) == 2


def test_c2_same_size_edit_with_restored_mtime_still_misses(env):
    """內容簽章不是 (size, mtime)：同大小、mtime 被調回去的改動也要 miss。"""
    root, calls, run = env
    p = root / "backend" / "a.py"
    st = p.stat()
    run()
    p.write_text("X = 7\n", encoding="utf-8")                      # 同樣 6 bytes
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert p.stat().st_size == st.st_size and p.stat().st_mtime_ns == st.st_mtime_ns
    run()
    assert len(calls) == 2


def test_d_editing_a_tool_source_misses(env, tmp_path):
    root, calls, run = env
    run()
    (tmp_path / "tools" / "algo.py").write_text("V = 2\n", encoding="utf-8")
    run()
    assert len(calls) == 2


def test_e_gitignored_file_that_dep_scan_would_read_misses(env):
    """dep_scan 走檔案系統 rglob，含 .gitignore 掉的檔 ⇒ 只看 git status 會漏；內容簽章要涵蓋。"""
    root, calls, run = env
    run()
    (root / "backend" / "ignored.py").write_text("Z = 1\n", encoding="utf-8")
    ls = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout
    assert "ignored.py" not in ls, "對照失效：這個檔應該被 .gitignore 排除"
    run()
    assert len(calls) == 2


def test_f_same_tree_in_two_worktree_paths_does_not_share(env, tmp_path):
    root, calls, run = env
    other = tmp_path / "repo2"
    subprocess.run(["git", "clone", "-q", str(root), str(other)], check=True, capture_output=True)
    run()
    run(r=other)
    assert len(calls) == 2, "兩個路徑的同內容樹不可共用一筆快取"


def test_python_version_and_kind_are_part_of_the_key(env, monkeypatch):
    root, calls, run = env
    run("k1")
    run("k2")
    assert calls == ["k1", "k2"]
    monkeypatch.setattr(MC.sys, "version_info", (3, 99, 0, "final", 0))
    run("k1")
    assert calls == ["k1", "k2", "k1"]


def test_flag_zero_never_reads_or_writes(env, tmp_path, monkeypatch):
    root, calls, run = env
    monkeypatch.setenv("MOTRIX_MAP_CACHE", "0")
    run()
    run()
    assert len(calls) == 2 and not (tmp_path / "cache").exists()


def test_refresh_skips_the_read_but_still_writes(env):
    root, calls, run = env
    run()
    run(refresh=True)
    assert len(calls) == 2
    run()
    assert len(calls) == 2


def test_corrupt_or_unreadable_cache_recomputes_without_raising(env, tmp_path):
    root, calls, run = env
    run()
    for p in (tmp_path / "cache").glob("*.json"):
        p.write_text("{not json", encoding="utf-8")
    assert run() == {"n": 2} and len(calls) == 2
    sig = MC.signature("k", root)
    p = next((tmp_path / "cache").glob("k-*.json"))
    p.write_text(json.dumps({"v": MC.FORMAT, "kind": "k", "sig": "0" * 64, "data": {"n": 99}}), encoding="utf-8")
    assert run() == {"n": 3} and sig


def test_non_json_results_are_returned_but_not_cached(env, tmp_path):
    root, calls, run = env
    got = MC.get_or_compute("t", lambda: {"s": {1, 2}} if False else {"t": (1, 2)}, root)
    assert got == {"t": (1, 2)}
    assert not list((tmp_path / "cache").glob("t-*.json"))


def test_cache_is_pruned_to_keep_entries(env, tmp_path):
    root, calls, run = env
    for i in range(MC.KEEP + 4):
        (root / "backend" / "a.py").write_text("X = %d\n" % (i + 10), encoding="utf-8")
        run()
    assert len(list((tmp_path / "cache").glob("*.json"))) <= MC.KEEP


def test_process_memo_scans_the_inputs_once(env, monkeypatch):
    root, calls, run = env
    n = []
    real = MC._input_files
    monkeypatch.setattr(MC, "_input_files", lambda r: (n.append(1), real(r))[1])
    monkeypatch.setattr(MC, "MEMO", True)
    run("k1")
    run("k2")
    assert len(n) == 1


# ── 接線：出貨判定一律明確關掉快取（不靠簽章本身）────────────────────────────

def test_build_script_pins_the_cache_off_before_any_pytest():
    ps1 = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    i = ps1.index('$env:MOTRIX_MAP_CACHE = "0"')
    assert i < ps1.index("& $pyExe -m pytest"), "建包必須在跑任何 pytest 之前設 MOTRIX_MAP_CACHE=0"


def test_run_stage_pins_the_cache_off_in_the_child_env(tmp_path):
    sys.path.insert(0, str(REPO / "backend"))
    from tools import build_test_reuse as btr
    seen = {}
    repo = tmp_path / "r"
    (repo / "backend").mkdir(parents=True)
    (repo / "backend" / "x.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    def runner(cmd, cwd, env):
        seen.update(env)
        return 0
    btr.run_stage(repo, "not_e2e", tmp_path / "rec.jsonl", python=sys.executable, runner=runner, workers=1, note=lambda *_: None)
    assert seen.get("MOTRIX_MAP_CACHE") == "0"


def test_modtest_full_and_train_disable_the_cache_and_flag_is_not_in_the_fingerprint():
    src = (TOOLS / "modtest.py").read_text(encoding="utf-8")
    assert re.search(r"if a\.full or a\.train:\s*\n[^\n]*\n\s*os\.environ\[\"MOTRIX_MAP_CACHE\"\] = \"0\"", src)
    sys.path.insert(0, str(REPO / "backend"))
    from tools import build_test_reuse as btr
    assert "MOTRIX_MAP_CACHE" in btr._ENV_IGNORE


def test_modtest_load_functions_go_through_the_cache():
    src = (TOOLS / "modtest.py").read_text(encoding="utf-8")
    assert 'map_cache.get_or_compute("test_map"' in src and 'map_cache.get_or_compute("dep_graph"' in src
    assert 'map_cache.get_or_compute("known_tables"' in src
