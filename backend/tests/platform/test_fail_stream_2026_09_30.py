# -*- coding: utf-8 -*-
"""tools/platform/fail_stream.py：失敗先行出 log（pytest plugin ＋ tail CLI）。

每題失敗當下就寫 JSONL（整輪結束前讀得到）、xdist 下不重複、綠的 run 只有 summary、不改測試結果與 exit code、
summary 帶每個測試檔耗時前 20 名。用真的子行程 pytest 跑合成的小測試套件驗證（不打專案自己的測試）。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLAT = REPO / "tools" / "platform"
spec = importlib.util.spec_from_file_location("_fail_stream_t", PLAT / "fail_stream.py")
FS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FS)

HAS_XDIST = importlib.util.find_spec("xdist") is not None
needs_xdist = pytest.mark.skipif(not HAS_XDIST, reason="這個 Python 沒有 pytest-xdist")

SUITE = {
    "test_mixed.py": '''
import pytest, time

def test_ok():
    pass

def test_fail():
    assert 1 == 2, "boom-fail"

@pytest.fixture
def bad_setup():
    raise RuntimeError("boom-setup")

def test_setup_error(bad_setup):
    pass

@pytest.fixture
def bad_teardown():
    yield 1
    raise RuntimeError("boom-teardown")

def test_teardown_error(bad_teardown):
    pass

def test_slow():
    time.sleep(0.3)

@pytest.mark.skip(reason="x")
def test_skipped():
    pass
''',
    "modules/foo/tests/test_foo.py": '''
def test_foo_fail():
    assert False, "boom-foo"
''',
    "modules/bar/tests/test_bar.py": '''
def test_bar_fail():
    assert False, "boom-bar"
def test_bar_ok():
    pass
''',
}


def _write_suite(root, files=SUITE):
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _env(out, run="t1", **extra):
    e = dict(os.environ)
    e["PYTHONPATH"] = str(PLAT) + os.pathsep + e.get("PYTHONPATH", "")
    e["MOTRIX_FAIL_STREAM_DIR"] = str(out)
    e["MOTRIX_FAIL_STREAM_RUN"] = run
    e.update(extra)
    return e


def _pytest(root, args, env, plugin=True, timeout=180):
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *(["-p", "fail_stream"] if plugin else []), *args]
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=timeout)
    return r


def _records(out, run="t1"):
    p = Path(out) / (run + ".jsonl")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _counts(text):
    return dict((k, int(n)) for n, k in re.findall(r"(\d+) (passed|failed|error|errors|skipped)", text))


# ── 基本：每種失敗都記、摘要、模組、longrepr ─────────────────────────────────────────

def test_records_every_kind_of_failure_with_module_and_summary(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root)
    r = _pytest(root, ["."], _env(out))
    recs = _records(out)
    fails = {(x["nodeid"].split("::")[-1], x["when"]) for x in recs if x["type"] == "fail"}
    assert ("test_fail", "call") in fails and ("test_setup_error", "setup") in fails and ("test_teardown_error", "teardown") in fails, fails
    assert ("test_foo_fail", "call") in fails and ("test_bar_fail", "call") in fails
    by = {x["nodeid"].split("::")[-1]: x for x in recs if x["type"] == "fail"}
    assert by["test_foo_fail"]["module"] == "foo" and by["test_bar_fail"]["module"] == "bar" and by["test_fail"]["module"] == "core"
    assert "boom-fail" in by["test_fail"]["summary"] and "boom-fail" in by["test_fail"]["longrepr"]
    assert "FAIL-EARLY" in r.stdout and "boom-foo" in r.stdout
    assert "FAIL-STREAM run=t1" in r.stdout
    assert recs[-1]["type"] == "summary" and recs[-1]["failed"] == 3 and recs[-1]["errors"] == 2 and recs[-1]["skipped"] == 1
    assert [x["seq"] for x in recs] == sorted(x["seq"] for x in recs)


def test_collection_errors_are_recorded(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root, {"test_bad.py": "import module_that_does_not_exist_xyz\n\ndef test_x():\n    pass\n"})
    _pytest(root, ["."], _env(out))
    recs = [x for x in _records(out) if x["type"] == "fail"]
    assert len(recs) == 1 and recs[0]["when"] == "collect" and "module_that_does_not_exist_xyz" in recs[0]["longrepr"]


def test_longrepr_is_truncated_to_4kb(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root, {"test_big.py": "def test_big():\n    assert False, 'x' * 20000\n"})
    _pytest(root, ["."], _env(out))
    rec = [x for x in _records(out) if x["type"] == "fail"][0]
    assert 0 < len(rec["longrepr"]) <= 4096 and len(rec["summary"]) <= 200


# ── 即時性：整輪結束前就讀得到 ─────────────────────────────────────────────────────────

def test_a_failure_is_readable_before_the_run_ends(tmp_path):
    root, out, flag = tmp_path / "s", tmp_path / "out", tmp_path / "go.flag"
    _write_suite(root, {"test_live.py": (
        "import os, time\n\ndef test_1_fails_first():\n    assert False, 'early-boom'\n\n"
        "def test_2_waits():\n    end = time.time() + 60\n    while not os.path.exists(%r) and time.time() < end:\n        time.sleep(0.1)\n" % str(flag))})
    proc = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "fail_stream", "."], cwd=str(root),
                            env=_env(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 60
        seen = None
        while time.time() < deadline:
            recs = _records(out)
            seen = next((x for x in recs if x["type"] == "fail"), None)
            if seen:
                break
            time.sleep(0.2)
        assert seen and "early-boom" in seen["summary"], "失敗沒有在整輪結束前出現"
        assert proc.poll() is None, "行程已經結束了：這題沒有驗到『結束前就讀得到』"
        assert not any(x["type"] == "summary" for x in _records(out))
    finally:
        flag.write_text("go")
        proc.communicate(timeout=120)
    assert _records(out)[-1]["type"] == "summary"


# ── xdist：只在 controller 收、不重複 ──────────────────────────────────────────────────

@needs_xdist
def test_xdist_records_each_failure_once(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    files = {"test_many_%d.py" % i: "".join("def test_f%d_%d():\n    assert False, 'b%d_%d'\n\ndef test_p%d_%d():\n    pass\n" % (i, j, i, j, i, j) for j in range(4)) for i in range(4)}
    _write_suite(root, files)
    _pytest(root, ["-n", "2", "."], _env(out))
    fails = [x["nodeid"] for x in _records(out) if x["type"] == "fail"]
    assert len(fails) == 16 and len(set(fails)) == 16, "重複或漏記：%d 筆、%d 個不同" % (len(fails), len(set(fails)))
    workers = {x["worker"] for x in _records(out) if x["type"] == "fail"}
    assert workers <= {"gw0", "gw1"} and len(workers) >= 1
    assert sum(1 for x in _records(out) if x["type"] == "summary") == 1


@needs_xdist
def test_xdist_worker_crash_is_recorded(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root, {"test_crash.py": "import os\n\ndef test_dies():\n    os._exit(3)\n\ndef test_fine():\n    pass\n"})
    r = _pytest(root, ["-n", "2", "."], _env(out))
    recs = _records(out)
    assert any(x["type"] == "fail" and "test_dies" in x["nodeid"] and "crash" in (x["longrepr"] + x["summary"]).lower() for x in recs), recs
    assert any(x["type"] == "node_down" for x in recs)
    assert "FAIL-EARLY" in r.stdout


# ── 綠的 run／不改結果／summary ────────────────────────────────────────────────────────

def test_a_green_run_has_only_the_summary(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root, {"test_green.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"})
    r = _pytest(root, ["."], _env(out))
    recs = _records(out)
    assert r.returncode == 0 and len(recs) == 1 and recs[0]["type"] == "summary" and recs[0]["passed"] == 2 and recs[0]["failed"] == 0
    assert "FAIL-EARLY" not in r.stdout


def test_the_plugin_does_not_change_results_or_exit_code(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root)
    with_p = _pytest(root, ["."], _env(out))
    without = _pytest(root, ["."], _env(tmp_path / "out2"), plugin=False)
    assert with_p.returncode == without.returncode == 1
    assert _counts(with_p.stdout) == _counts(without.stdout) and _counts(without.stdout).get("failed") == 3


def test_summary_lists_the_slowest_test_files_top_20(tmp_path):
    root, out = tmp_path / "s", tmp_path / "out"
    files = {"test_f%02d.py" % i: "import time\n\ndef test_x():\n    time.sleep(%s)\n" % (0.4 if i == 7 else 0.0) for i in range(25)}
    _write_suite(root, files)
    _pytest(root, ["."], _env(out))
    s = _records(out)[-1]
    assert len(s["slowest_files"]) == 20 and s["slowest_files"][0]["file"].endswith("test_f07.py") and s["slowest_files"][0]["seconds"] >= 0.4
    assert [x["seconds"] for x in s["slowest_files"]] == sorted((x["seconds"] for x in s["slowest_files"]), reverse=True)


def test_an_unwritable_stream_never_breaks_the_tests(tmp_path):
    root = tmp_path / "s"
    _write_suite(root)
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    r = _pytest(root, ["."], _env(blocker / "sub"))              # 目錄建不出來（上層是檔案）
    without = _pytest(root, ["."], _env(tmp_path / "o2"), plugin=False)
    assert r.returncode == without.returncode == 1
    assert r.stderr.count("[fail_stream] 寫不出") + r.stdout.count("[fail_stream] 寫不出") == 1, "只該說一次"


# ── 模組推導、CLI ──────────────────────────────────────────────────────────────────────

def test_modules_of_uses_path_then_test_map():
    assert FS.modules_of("modules/tender_radar/tests/test_x.py::t")[0] == "tender_radar"
    assert FS.modules_of("backend/modules/case/tests/test_x.py::t")[0] == "case"
    tm = FS._test_map()
    mapped = next((k for k, v in tm.items() if k.startswith("backend/tests/") and any(u.startswith("dir:backend/modules/") for u in v.get("units", []))), None)
    if mapped:
        rel = mapped[len("backend/"):]
        key, keys = FS.modules_of(rel + "::t")
        assert key != "core" and key in keys
    assert FS.modules_of("tests/no_such_file_anywhere.py::t") == ("core", ["core"])


def test_cli_tail_filters_by_module_and_reads_latest(tmp_path, capsys):
    root, out = tmp_path / "s", tmp_path / "out"
    _write_suite(root)
    _pytest(root, ["."], _env(out, run="run_a"))
    assert FS.main(["--dir", str(out), "tail", "latest", "--module", "foo"]) == 0
    text = capsys.readouterr().out
    assert "test_foo_fail" in text and "test_bar_fail" not in text and "test_fail" not in text.replace("test_foo_fail", "")
    assert "SUMMARY" in text and "1 筆失敗" in text
    assert FS.main(["--dir", str(out), "tail", "run_a", "--json"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    assert json.loads(lines[-1])["type"] == "summary"
    assert FS.main(["--dir", str(out), "tail", "no_such_run"]) == 1


def test_cli_tail_follow_stops_at_the_summary(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "r.jsonl").write_text(json.dumps({"type": "fail", "module": "x", "modules": ["x"], "nodeid": "n", "when": "call", "summary": "s", "t": "t"}) + "\n" +
                                 json.dumps({"type": "summary", "t": "t", "stage": "", "exitstatus": 1, "failed": 1, "errors": 0, "passed": 0, "duration_s": 1}) + "\n", encoding="utf-8")
    t0 = time.time()
    assert FS.main(["--dir", str(out), "tail", "r", "--follow", "--interval", "0.1", "--timeout", "30"]) == 0
    assert time.time() - t0 < 5


def test_modtest_loads_the_plugin_in_every_non_collect_run():
    """modtest 的每一次實跑（--train／--full／差異）都帶 -p fail_stream 與 PYTHONPATH；collect-only 不帶。"""
    spec = importlib.util.spec_from_file_location("_modtest_fs", PLAT / "modtest.py")
    mt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mt)
    assert mt._fail_stream_args() == ["-p", "fail_stream"]
    env = mt._fail_stream_env("w1")
    assert str(PLAT) in env["PYTHONPATH"].split(os.pathsep) and env["MOTRIX_FAIL_STREAM_STAGE"] == "w1"
    assert env["MOTRIX_FAIL_STREAM_RUN"] == mt._fail_stream_env("w2")["MOTRIX_FAIL_STREAM_RUN"], "同一次 modtest 的各段要共用 run-id"
    src = (PLAT / "modtest.py").read_text(encoding="utf-8")
    assert src.count("_fail_stream_args()") >= 2 and "env=_fail_stream_env(window)" in src


def test_stream_dir_is_gitignored():
    assert "tools/platform/fail_stream/" in (REPO / ".gitignore").read_text(encoding="utf-8")
