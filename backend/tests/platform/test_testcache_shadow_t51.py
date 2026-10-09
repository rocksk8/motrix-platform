# -*- coding: utf-8 -*-
"""測試結果快取『影子錄製器』（tools/platform/testcache_shadow.py；第 51 班）：只觀察、預設關閉、不改任何結果。

每題在暫存專案裡起一個真的 pytest 子行程（MOTRIX_TESTCACHE_ROOT 指到暫存專案、MOTRIX_TESTCACHE_DIR 指到暫存快取），
所以不碰真實 repo／D:\\MOTRIX-TESTCACHE。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"

TEST_SRC = '''
import subprocess, os
from pathlib import Path

def test_reads_data():
    assert Path("data.txt").read_text(encoding="utf-8") == "v1" or True

def test_missing_file_probe():
    try:
        open("not_there.txt").read()
    except OSError:
        pass
'''


def _project(tmp_path, data="v1", extra=""):
    (tmp_path / "t_a.py").write_text(TEST_SRC + extra, encoding="utf-8")
    (tmp_path / "data.txt").write_text(data, encoding="utf-8")
    return tmp_path


def _run(tmp_path, cache, shadow=True, run_id=None, args=()):
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = str(TOOLS)
    env["MOTRIX_TESTCACHE_ROOT"] = str(tmp_path)
    env["MOTRIX_TESTCACHE_DIR"] = str(cache)
    env.pop("MOTRIX_TESTCACHE_SHADOW", None)
    if shadow:
        env["MOTRIX_TESTCACHE_SHADOW"] = "1"
    if run_id:
        env["MOTRIX_TESTCACHE_RUN"] = run_id
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "testcache_shadow", "t_a.py", *args],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return p


def _record(cache, run_id):
    d = Path(cache) / "shadow" / run_id
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in d.glob("*.json")]
    assert len(docs) == 1, docs
    return docs[0]["files"]["t_a.py"]


def test_off_by_default_writes_nothing_and_changes_nothing(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj")
    cache = tmp_path / "cache"
    p = _run(proj, cache, shadow=False)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not cache.exists(), "旗標沒開 ⇒ 不可建立任何快取目錄"


def test_records_deps_with_content_hash_and_absent_paths(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj", data="v1")
    cache = tmp_path / "cache"
    p = _run(proj, cache, run_id="r1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "testcache_shadow:" in p.stdout and "沒跳過任何一題" in p.stdout
    rec = _record(cache, "r1")
    assert rec["green"] is True and len(rec["nodeids"]) == 2
    deps = rec["deps"]
    assert deps.get("data.txt") and deps["data.txt"] != "ABSENT"
    assert deps.get("not_there.txt") == "ABSENT", "打開失敗的路徑要記成 ABSENT（之後該檔出現就必須換鍵）"
    assert "t_a.py" in deps
    # 專案內沒有被寫入任何錄製檔
    assert not any(x.name.endswith(".json") for x in proj.rglob("*") if x.is_file())


def test_key_is_stable_and_changes_when_a_dependency_changes_or_appears(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj", data="v1")
    cache = tmp_path / "cache"
    _run(proj, cache, run_id="r1")
    _run(proj, cache, run_id="r2")
    k1, k2 = _record(cache, "r1")["key"], _record(cache, "r2")["key"]
    assert k1 == k2, "同樣的輸入 ⇒ 同一把鍵"
    (proj / "data.txt").write_text("v2", encoding="utf-8")
    _run(proj, cache, run_id="r3")
    assert _record(cache, "r3")["key"] != k1, "依賴內容變了 ⇒ 鍵必須變"
    (proj / "data.txt").write_text("v1", encoding="utf-8")
    (proj / "not_there.txt").write_text("now exists", encoding="utf-8")
    _run(proj, cache, run_id="r4")
    assert _record(cache, "r4")["key"] != k1, "原本 ABSENT 的路徑出現了 ⇒ 鍵必須變"


def test_never_changes_outcomes_or_exit_codes(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj", extra="\ndef test_fails():\n    assert False\n")
    cache = tmp_path / "cache"
    on = _run(proj, cache, run_id="r1")
    off = _run(proj, tmp_path / "cache2", shadow=False)
    assert on.returncode == off.returncode == 1
    assert "1 failed, 2 passed" in on.stdout and "1 failed, 2 passed" in off.stdout
    rec = _record(cache, "r1")
    assert rec["green"] is False and sorted(rec["nodeids"].values()).count("failed") == 1


def test_flags_git_subprocess_and_time_reads(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj", extra='\ndef test_git():\n    subprocess.run(["git", "--version"], capture_output=True)\n\ndef test_time():\n    import time\n    time.time()\n')
    cache = tmp_path / "cache"
    _run(proj, cache, run_id="r1")
    flags = _record(cache, "r1")["flags"]
    assert "git" in flags and "subprocess" in flags and "time" in flags, flags


def test_report_counts_would_hit_from_a_green_previous_run(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj")
    cache = tmp_path / "cache"
    _run(proj, cache, run_id="r1")
    _run(proj, cache, run_id="r2")
    (proj / "data.txt").write_text("changed", encoding="utf-8")
    _run(proj, cache, run_id="r3")
    p = subprocess.run([sys.executable, str(TOOLS / "testcache_shadow.py"), "report", "--dir", str(cache)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0, p.stderr
    rows = {ln.split()[0]: ln.split() for ln in p.stdout.splitlines() if ln.split() and ln.split()[0].startswith("r")}
    assert rows["r2"][2] == "1", p.stdout       # r2 與 r1 同鍵 ⇒ 會命中 1 檔
    assert rows["r3"][2] == "0", p.stdout       # r3 的依賴變了 ⇒ 不會命中


def test_recorder_failure_is_swallowed(tmp_path):
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj")
    bad = tmp_path / "cache_is_a_file"
    bad.write_text("x", encoding="utf-8")          # 快取目錄其實是個檔 ⇒ 寫入失敗
    p = _run(proj, bad, run_id="r1")
    assert p.returncode == 0, "錄製失敗不可影響測試結果：" + p.stdout + p.stderr
    assert "passed" in p.stdout


def test_cache_dir_inside_the_repo_is_refused_and_nothing_is_written(tmp_path):
    """MOTRIX_TESTCACHE_DIR 解析後落在被觀察的 repo／worktree 裡 ⇒ 錄製器自己停用（清楚訊息、不丟例外、測試照跑），不寫任何檔。"""
    (tmp_path / "proj").mkdir()
    proj = _project(tmp_path / "proj")
    inside = proj / "tc_cache"
    p = _run(proj, inside, run_id="r1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "testcache_shadow: 停用" in p.stderr and "repo" in p.stderr
    assert "passed" in p.stdout and "testcache_shadow: 錄了" not in p.stdout
    assert not inside.exists(), "拒絕後不可建立任何檔案"
    # 用 .. 繞進去也一樣（解析後判斷）
    sneaky = proj / "sub" / ".." / "tc_cache2"
    p = _run(proj, sneaky, run_id="r2")
    assert p.returncode == 0 and "testcache_shadow: 停用" in p.stderr and not (proj / "tc_cache2").exists()
    # 對照：repo 外的目錄照常錄
    out = tmp_path / "outside_cache"
    p = _run(proj, out, run_id="r3")
    assert p.returncode == 0 and (out / "shadow" / "r3").is_dir()
