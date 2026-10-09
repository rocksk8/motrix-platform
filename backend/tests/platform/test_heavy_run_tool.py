# -*- coding: utf-8 -*-
"""tools/platform/heavy_run.py（SPEEDUP-PIPELINE-T50 步驟 0＋2）：票根／優先序／獨佔／過期清除／包裝執行／狀態行。純檔案與假行程，不跑 pytest 子行程。"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import heavy_run as H  # noqa: E402

ALIVE = lambda pid: True        # noqa: E731
NOW = 1_000_000.0


def _t(q, name, cls, window="w", started=None, pid=1234, enq=NOW):
    q.mkdir(parents=True, exist_ok=True)
    p = q / name
    p.write_text(json.dumps({"pid": pid, "window": window, "class": cls, "cmd": "x", "enqueued": enq, "started": started}), encoding="utf-8")
    return p


def test_load_tickets_orders_by_priority_then_time_and_cleans_dead_and_stale(tmp_path):
    q = tmp_path / "q"
    _t(q, "1-heavy.json", "heavy", enq=NOW - 50)
    _t(q, "2-official.json", "official", enq=NOW - 10)
    _t(q, "3-e2e.json", "e2e", enq=NOW - 40)
    _t(q, "4-dead.json", "heavy", pid=99999999, enq=NOW)
    _t(q, "5-stale.json", "heavy", enq=NOW - H.STALE_SECONDS - 5)
    (q / "6-bad.json").write_text("{not json", encoding="utf-8")
    (q / "7-unknown.json").write_text(json.dumps({"pid": 1, "class": "zzz", "enqueued": NOW}), encoding="utf-8")
    got = H.load_tickets(q, NOW, alive=lambda pid: pid != 99999999)
    assert [Path(t["_file"]).name for t in got] == ["2-official.json", "3-e2e.json", "1-heavy.json"]
    assert sorted(p.name for p in q.glob("*.json")) == ["1-heavy.json", "2-official.json", "3-e2e.json"], "壞檔／死行程／過期的被清掉"


def _tickets(q):
    return H.load_tickets(q, NOW, alive=ALIVE, clean=False)


def _by(ts, name):
    return next(t for t in ts if t["_file"].endswith(name))


def test_can_start_rules(tmp_path):
    q = tmp_path / "q"
    _t(q, "a-heavy-run.json", "heavy", started=NOW - 5, enq=NOW - 100)
    _t(q, "b-heavy-wait.json", "heavy", enq=NOW - 90)
    _t(q, "c-e2e-wait.json", "e2e", enq=NOW - 80)
    _t(q, "d-light.json", "light", enq=NOW - 70)
    ts = _tickets(q)
    assert H.can_start(_by(ts, "d-light.json"), ts) is True, "light 永遠能"
    assert H.can_start(_by(ts, "b-heavy-wait.json"), ts) is False, "已有一個重型在跑"
    assert H.can_start(_by(ts, "c-e2e-wait.json"), ts) is False, "e2e 獨佔：等重型結束"
    (q / "a-heavy-run.json").unlink()
    ts = _tickets(q)
    assert H.can_start(_by(ts, "c-e2e-wait.json"), ts) is True, "e2e 優先序高於較早入列的 heavy ⇒ 先跑"
    assert H.can_start(_by(ts, "b-heavy-wait.json"), ts) is False, "有更高優先序的在等 ⇒ 不插隊"


def test_exclusive_running_blocks_everyone_and_official_beats_e2e(tmp_path):
    q = tmp_path / "q"
    _t(q, "a-e2e-run.json", "e2e", started=NOW - 5, enq=NOW - 100)
    _t(q, "b-official-wait.json", "official", enq=NOW - 10)
    _t(q, "c-heavy-wait.json", "heavy", enq=NOW - 200)
    ts = _tickets(q)
    assert H.can_start(_by(ts, "b-official-wait.json"), ts) is False and H.can_start(_by(ts, "c-heavy-wait.json"), ts) is False
    (q / "a-e2e-run.json").unlink()
    ts = _tickets(q)
    assert H.can_start(_by(ts, "b-official-wait.json"), ts) is True and H.can_start(_by(ts, "c-heavy-wait.json"), ts) is False


def test_watcher_is_lowest_and_never_runs_beside_anything(tmp_path):
    q = tmp_path / "q"
    _t(q, "a-watcher.json", "watcher", enq=NOW - 500)
    _t(q, "b-heavy-run.json", "heavy", started=NOW - 1, enq=NOW - 10)
    ts = _tickets(q)
    assert H.can_start(_by(ts, "a-watcher.json"), ts) is False
    (q / "b-heavy-run.json").unlink()
    _t(q, "c-heavy-wait.json", "heavy", enq=NOW)
    ts = _tickets(q)
    assert H.can_start(_by(ts, "a-watcher.json"), ts) is False, "更高優先序的在等，watcher 讓位"
    assert H.can_start(_by(ts, "c-heavy-wait.json"), ts) is True


def test_run_wraps_command_sets_priority_returns_exit_code_and_removes_ticket(tmp_path):
    q = tmp_path / "q"
    seen = {}

    def runner(cmd, env, flags):
        seen.update(cmd=cmd, flags=flags, ticket=env.get("MOTRIX_CI_TICKET"))
        assert Path(seen["ticket"]).exists() and json.loads(Path(seen["ticket"]).read_text(encoding="utf-8"))["started"], "執行中票根存在且已標開始"
        return 3
    rc = H.run(["echo", "x"], "heavy", "ab", qdir=q, runner=runner, note=lambda *_: None)
    assert rc == 3 and seen["cmd"] == ["echo", "x"]
    assert not list(q.glob("*.json")), "結束後票根一定收掉"
    if os.name == "nt":
        assert seen["flags"] == 0x4000, "重型降到 BELOW_NORMAL"
    seen.clear()
    H.run(["gate"], "official", "b7", qdir=q, runner=runner, note=lambda *_: None)
    assert seen["flags"] == 0, "正式閘門不降權"


def test_run_removes_ticket_even_when_the_command_raises(tmp_path):
    q = tmp_path / "q"

    def boom(cmd, env, flags):
        raise RuntimeError("x")
    with pytest.raises(RuntimeError):
        H.run(["x"], "heavy", "ab", qdir=q, runner=boom, note=lambda *_: None)
    assert not list(q.glob("*.json"))


def test_run_waits_for_a_running_heavy_then_goes(tmp_path):
    q = tmp_path / "q"
    blocker = _t(q, "0-blocker.json", "heavy", started=time.time(), enq=time.time() - 5, pid=os.getpid())
    polls = []

    def sleep(s):
        polls.append(s)
        if len(polls) == 2:
            blocker.unlink()                                   # 前一個重型結束
    notes = []
    rc = H.run(["x"], "heavy", "ab", qdir=q, runner=lambda c, e, f: 0, sleep=sleep, note=notes.append)
    assert rc == 0 and len(polls) == 2 and any("排隊中" in n for n in notes)


def test_run_gives_up_with_75_when_max_wait_exceeded_and_light_skips_the_queue(tmp_path):
    q = tmp_path / "q"
    _t(q, "0-blocker.json", "e2e", started=time.time(), enq=time.time() - 5, pid=os.getpid())
    ran = []
    rc = H.run(["x"], "heavy", "ab", qdir=q, runner=lambda c, e, f: ran.append(1) or 0, sleep=lambda s: None, note=lambda *_: None, max_wait=-1)
    assert rc == 75 and not ran
    assert not [p for p in q.glob("*.json") if "heavy" in p.name], "放棄時也收票"
    assert H.run(["x"], "light", "ab", qdir=q, runner=lambda c, e, f: ran.append(1) or 0, note=lambda *_: None) == 0 and ran, "light 不排隊"
    assert len(list(q.glob("*.json"))) == 1, "light 沒有 --track 就不留票根"


def test_status_line_and_conftest_locks(tmp_path):
    q = tmp_path / "q"
    _t(q, "a.json", "e2e", window="b7", started=NOW - 125, enq=NOW - 300, pid=111)
    _t(q, "b.json", "heavy", window="05", enq=NOW - 100)
    _t(q, "c.json", "light", window="ab", enq=NOW - 100)
    ts = H.load_tickets(q, NOW, alive=ALIVE, clean=False)
    line = H.status_line(ts, [("motrix-pytest-full-regression.lock", 56192, 128, "x")], NOW)
    assert "b7 e2e(pid 111, 2m05s)" in line and "等：05 heavy" in line and "輕：1" in line and "lock pid 56192 2m08s" in line, line
    assert H.status_line([], [], NOW) == "跑：無｜等：無｜輕：0｜conftest 鎖：無"
    lockdir = tmp_path / "tmp"
    lockdir.mkdir()
    (lockdir / "motrix-pytest-full-regression.lock").write_text(json.dumps({"pid": os.getpid(), "started_at": time.time() - 60, "basetemp": "bt"}), encoding="utf-8")
    (lockdir / "motrix-pytest-full-regression.lock.slot2").write_text(json.dumps({"pid": 99999999, "started_at": 1}), encoding="utf-8")
    got = H.conftest_locks(lockdir)
    assert [g[0] for g in got] == ["motrix-pytest-full-regression.lock"] and got[0][1] == os.getpid(), "死行程的鎖不列"


def test_main_status_and_requires_a_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    assert H.main(["--status"]) == 0
    assert "跑：無" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        H.main(["--class", "heavy"])
    rc = H.main(["--class", "light", "--", sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7, "結束碼＝被包指令的結束碼"
