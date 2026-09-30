# -*- coding: utf-8 -*-
"""fail_stream：外部終止（timeout／TaskStop／Ctrl-C）不是測試失敗——記 type=aborted，不記 fail／node_down。

成因（W2 實例 rc-modtest3 exit=124）：整個 run 被 timeout 砍掉時 xdist worker 先掉線，舊版把「worker 掉線」與「crashed while running」記成 FAIL-EARLY。
判準：崩潰類紀錄先保留 grace 秒；controller 收到中斷、或所有 worker 都掉了而沒有替補 ⇒ aborted；個別 worker 崩潰（別的還活著／有替補）⇒ 仍是 fail。
單元題用假 node 直接驅動 plugin（決定性、不靠 OS 信號）；整合題用真的 xdist（殺 worker／殺整棵樹）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
PLAT = REPO / "tools" / "platform"
spec = importlib.util.spec_from_file_location("_fail_stream_ab", PLAT / "fail_stream.py")
FS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FS)

HAS_XDIST = importlib.util.find_spec("xdist") is not None
needs_xdist = pytest.mark.skipif(not HAS_XDIST, reason="這個 Python 沒有 pytest-xdist")


def _stream(tmp_path, monkeypatch, grace="0.2"):
    monkeypatch.setenv(FS.DIR_ENV, str(tmp_path / "out"))
    monkeypatch.setenv(FS.RUN_ENV, "u1")
    monkeypatch.setenv(FS.GRACE_ENV, grace)
    cfg = SimpleNamespace(pluginmanager=SimpleNamespace(get_plugin=lambda n: None))
    return FS.FailStream(cfg)


def _node(wid):
    return SimpleNamespace(gateway=SimpleNamespace(id=wid))


def _crash_report(nodeid="test_x.py::test_dies", wid="gw0"):
    return SimpleNamespace(nodeid=nodeid, when="call", failed=True, skipped=False, passed=False, duration=0.0, node=_node(wid),
                           longreprtext="worker '%s' crashed while running '%s'" % (wid, nodeid), longrepr="")


def _types(fs):
    p = fs.path
    return [json.loads(l)["type"] for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def _drop(fs, wid, err="worker crashed"):
    fs.pytest_testnodedown(_node(wid), RuntimeError(err))


def test_all_workers_dropping_without_a_replacement_is_aborted_not_failed(tmp_path, monkeypatch):
    fs = _stream(tmp_path, monkeypatch)
    fs.pytest_testnodeready(_node("gw0")); fs.pytest_testnodeready(_node("gw1"))
    fs.pytest_runtest_logreport(_crash_report(wid="gw0"))
    _drop(fs, "gw0"); _drop(fs, "gw1")
    time.sleep(0.6)                                             # 超過保留期：沒有替補 ⇒ 判定
    assert "fail" not in _types(fs) and "node_down" not in _types(fs)
    assert _types(fs).count("aborted") == 3                     # 一筆 crashed-while-running ＋兩個 worker
    fs.pytest_sessionfinish(SimpleNamespace(), 1)
    summ = json.loads(fs.path.read_text(encoding="utf-8").splitlines()[-1])
    assert summ["type"] == "summary" and summ["aborted"] is True and summ["failed"] == 0 and summ["aborted_records"] == 3


def test_one_worker_crashing_while_another_lives_is_still_a_failure(tmp_path, monkeypatch):
    fs = _stream(tmp_path, monkeypatch)
    fs.pytest_testnodeready(_node("gw0")); fs.pytest_testnodeready(_node("gw1"))
    fs.pytest_runtest_logreport(_crash_report(wid="gw0"))
    _drop(fs, "gw0")
    time.sleep(0.6)
    assert _types(fs).count("fail") == 1 and _types(fs).count("node_down") == 1 and "aborted" not in _types(fs)
    fs.pytest_sessionfinish(SimpleNamespace(), 1)
    summ = json.loads(fs.path.read_text(encoding="utf-8").splitlines()[-1])
    assert summ["aborted"] is False and summ["failed"] == 1


def test_a_replacement_worker_before_the_grace_ends_means_a_real_crash(tmp_path, monkeypatch):
    """-n 1 的真崩潰：唯一的 worker 掉了、xdist 起替補 ⇒ 不是外部終止（記 fail，且立刻寫，不必等保留期）。"""
    fs = _stream(tmp_path, monkeypatch, grace="30")
    fs.pytest_testnodeready(_node("gw0"))
    fs.pytest_runtest_logreport(_crash_report(wid="gw0"))
    _drop(fs, "gw0")
    assert _types(fs) == []                                     # 保留中
    fs.pytest_testnodeready(_node("gw1"))                       # 替補起來
    assert _types(fs).count("fail") == 1 and _types(fs).count("node_down") == 1 and "aborted" not in _types(fs)


def test_an_interrupt_flag_turns_crash_records_into_aborted_even_if_a_worker_lives(tmp_path, monkeypatch):
    fs = _stream(tmp_path, monkeypatch)
    fs.pytest_testnodeready(_node("gw0")); fs.pytest_testnodeready(_node("gw1"))
    fs.pytest_runtest_logreport(_crash_report(wid="gw0"))
    _drop(fs, "gw0")
    fs.pytest_keyboard_interrupt(None)                          # Ctrl-C：controller 的 KeyboardInterrupt
    time.sleep(0.6)
    assert "fail" not in _types(fs) and _types(fs).count("aborted") == 2


def test_pending_records_are_flushed_at_session_end_and_interrupted_exit_is_aborted(tmp_path, monkeypatch):
    fs = _stream(tmp_path, monkeypatch, grace="30")             # 計時器還沒到、session 就結束了
    fs.pytest_testnodeready(_node("gw0")); fs.pytest_testnodeready(_node("gw1"))
    fs.pytest_runtest_logreport(_crash_report(wid="gw0"))
    _drop(fs, "gw0")
    fs.pytest_sessionfinish(SimpleNamespace(), 2)               # exit 2 ＝ INTERRUPTED
    types = _types(fs)
    assert types.count("aborted") == 2 and "fail" not in types and types[-1] == "summary"


def test_ordinary_failures_are_never_held_back(tmp_path, monkeypatch):
    fs = _stream(tmp_path, monkeypatch, grace="30")
    rep = SimpleNamespace(nodeid="test_a.py::test_f", when="call", failed=True, skipped=False, passed=False, duration=0.0, node=_node("gw0"),
                          longreprtext="E   AssertionError: boom", longrepr="")
    fs.pytest_runtest_logreport(rep)
    assert _types(fs) == ["fail"], "一般失敗要當下寫（不受保留期影響）"


def test_cli_does_not_count_aborted_as_failures(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / "r.jsonl").write_text(
        json.dumps({"type": "aborted", "module": "x", "modules": ["x"], "nodeid": "(worker gw0)", "when": "node_down", "summary": "s", "t": "t"}) + "\n" +
        json.dumps({"type": "summary", "t": "t", "stage": "", "exitstatus": 1, "failed": 0, "errors": 0, "passed": 3, "duration_s": 1, "aborted": True}) + "\n",
        encoding="utf-8")
    assert FS.main(["--dir", str(out), "tail", "r"]) == 0
    text = capsys.readouterr().out
    assert "ABORTED" in text and "# 0 筆失敗" in text


# ── 整合：真的 xdist ────────────────────────────────────────────────────────────────

def _env(out, run="a1", **extra):
    e = dict(os.environ)
    e["PYTHONPATH"] = str(PLAT) + os.pathsep + e.get("PYTHONPATH", "")
    e[FS.DIR_ENV] = str(out)
    e[FS.RUN_ENV] = run
    e[FS.GRACE_ENV] = "1"
    e.update(extra)
    return e


def _write_sleepers(root, pids):
    root.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (root / ("test_sleep_%d.py" % i)).write_text(
            "import os, time\n\ndef test_s():\n    open(%r %% os.getpid(), 'w').write('1')\n    time.sleep(120)\n" % (str(pids) + os.sep + "p%d"), encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _wait_pids(pids, n=2, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        got = [int(p.name[1:]) for p in pids.glob("p*")]
        if len(got) >= n:
            return got
        time.sleep(0.2)
    raise AssertionError("worker 沒有在時限內開始跑睡眠題")


def _kill(pid, tree=False):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F"] + (["/T"] if tree else []) + ["/PID", str(pid)], capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGKILL)


def _recs(out, run="a1"):
    p = Path(out) / (run + ".jsonl")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


@needs_xdist
def test_killing_every_worker_with_no_restart_is_recorded_as_aborted(tmp_path):
    """整合：--max-worker-restart=0、兩個 worker 都被砍（controller 活著）⇒ aborted，不是 fail／node_down。"""
    root, out, pids = tmp_path / "s", tmp_path / "out", tmp_path / "pids"
    pids.mkdir()
    _write_sleepers(root, pids)
    proc = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "fail_stream", "-n", "2", "--max-worker-restart=0", "."],
                            cwd=str(root), env=_env(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for pid in _wait_pids(pids):
            _kill(pid)
        proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            _kill(proc.pid, tree=True)
    types = [r["type"] for r in _recs(out)]
    assert "fail" not in types and "node_down" not in types, types
    assert "aborted" in types and types[-1] == "summary"
    assert _recs(out)[-1]["aborted"] is True and _recs(out)[-1]["failed"] == 0


@needs_xdist
def test_killing_the_whole_process_tree_leaves_no_failure_records(tmp_path):
    """整合：連 controller 一起砍（timeout 的實況）⇒ 檔裡沒有 fail／node_down（也沒有 summary）。"""
    root, out, pids = tmp_path / "s", tmp_path / "out", tmp_path / "pids"
    pids.mkdir()
    _write_sleepers(root, pids)
    proc = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "fail_stream", "-n", "2", "."],
                            cwd=str(root), env=_env(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        _wait_pids(pids)
        _kill(proc.pid, tree=True)
        proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            _kill(proc.pid, tree=True)
    time.sleep(1.5)                                             # 保留期過了也不會有人補寫（行程已死）
    types = [r["type"] for r in _recs(out)]
    assert "fail" not in types and "node_down" not in types, types
