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
    assert H.status_line([], [], NOW, gate=None) == "跑：無｜等：無｜輕：0｜conftest 鎖：無｜閘門鎖：無"
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


# ── 閘門鎖（T82）：整合者持有期間，非閘門的重型自動等；conftest 的直接跑檢查用同一份判斷 ─────────────────────────

def test_gate_lock_acquire_renew_release_and_expiry(tmp_path):
    g = tmp_path / "gate.lock"
    assert H.read_gate(g, NOW) is None, "沒有檔 ⇒ 沒有鎖"
    ok, lock = H.gate_acquire("h7", "T82 閘門", 3600, path=g, now=NOW)
    assert ok and lock["window"] == "h7" and H.read_gate(g, NOW + 10)["token"] == lock["token"]
    ok2, other = H.gate_acquire("h9", path=g, now=NOW + 5)
    assert not ok2 and other["window"] == "h7", "別人持有 ⇒ 取不到、回對方的鎖"
    ok3, again = H.gate_acquire("h7", ttl=7200, path=g, now=NOW + 100)
    assert ok3 and again["token"] == lock["token"] and again["since"] == lock["since"] and again["expires"] == NOW + 100 + 7200, "同視窗再取＝續期，token／since 不變"
    assert H.gate_release("h9", path=g, now=NOW + 101) is False and H.read_gate(g, NOW + 101), "別人不能放"
    assert H.gate_release("h7", path=g, now=NOW + 102) is True and H.read_gate(g, NOW + 102) is None
    H.gate_acquire("h7", ttl=60, path=g, now=NOW)
    assert H.read_gate(g, NOW + 61) is None, "過期 ⇒ 等於沒有鎖（忘了放不會卡死）"
    ok4, taken = H.gate_acquire("h9", path=g, now=NOW + 61)
    assert ok4 and taken["window"] == "h9", "過期的鎖別人可以接手"
    ok5, forced = H.gate_acquire("h7", path=g, now=NOW + 62, force=True)
    assert ok5 and forced["window"] == "h7" and H.gate_release("h9", path=g, now=NOW + 63, force=True)
    g.write_text("{壞檔", encoding="utf-8")
    assert H.read_gate(g, NOW) is None and H.gate_acquire("h1", path=g, now=NOW)[0], "壞檔視為沒有鎖、可取"


def test_gate_exempt_rules():
    lock = {"window": "h7", "token": "abc", "expires": NOW + 1}
    assert H.gate_exempt("heavy", "h9", None, {}) is True, "沒鎖誰都放行"
    assert H.gate_exempt("heavy", "h9", lock, {}) is False and H.gate_exempt("e2e", "h9", lock, {}) is False and H.gate_exempt("watcher", "h9", lock, {}) is False
    assert H.gate_exempt("official", "h9", lock, {}) is True, "official 就是閘門"
    assert H.gate_exempt("heavy", "h7", lock, {}) is True, "持有者視窗的票放行（自己的預演／修紅重跑）"
    assert H.gate_exempt("heavy", "h9", lock, {H.GATE_TOKEN_ENV: "abc"}) is True and H.gate_exempt("heavy", "h9", lock, {H.GATE_TOKEN_ENV: "zzz"}) is False


def test_run_waits_automatically_while_gate_lock_held_and_goes_after_release(tmp_path):
    q = tmp_path / "ci" / "queue"
    g = tmp_path / "ci" / H.GATE_FILE
    H.gate_acquire("h7", "T82", 3600, path=g)
    polls, notes, ran = [], [], []

    def sleep(s):
        polls.append(s)
        if len(polls) == 3:
            H.gate_release("h7", path=g)                       # 整合者放鎖
    rc = H.run(["x"], "heavy", "h9", qdir=q, runner=lambda c, e, f: ran.append(e) or 0, sleep=sleep, note=notes.append)
    assert rc == 0 and len(polls) == 3 and ran, "鎖在 ⇒ 等；放鎖後自動開跑"
    assert any("閘門鎖：h7" in n for n in notes), notes
    assert H.GATE_TOKEN_ENV not in ran[0], "非閘門的票不拿 token"
    assert not list(q.glob("*.json")), "等待期間／結束後票根都收乾淨"


def test_gate_lock_does_not_block_the_gate_the_owner_or_light_and_passes_the_token(tmp_path):
    q = tmp_path / "ci" / "queue"
    g = tmp_path / "ci" / H.GATE_FILE
    _ok, lock = H.gate_acquire("h7", "T82", 3600, path=g)
    envs = []
    for cls, win in (("official", "h8"), ("heavy", "h7"), ("e2e", "h7")):
        assert H.run(["x"], cls, win, qdir=q, runner=lambda c, e, f: envs.append(e) or 0, sleep=lambda s: (_ for _ in ()).throw(AssertionError("不該等")), note=lambda *_: None) == 0
    assert all(e.get(H.GATE_TOKEN_ENV) == lock["token"] for e in envs), "放行的票把 token 帶進子行程（conftest 的直接跑檢查認它）"
    assert H.run(["x"], "light", "h9", qdir=q, runner=lambda c, e, f: 0, sleep=lambda s: (_ for _ in ()).throw(AssertionError("light 不受閘門鎖影響")), note=lambda *_: None) == 0
    rc = H.run(["x"], "heavy", "h9", qdir=q, runner=lambda c, e, f: 0, sleep=lambda s: None, note=lambda *_: None, max_wait=-1)
    assert rc == 75, "非閘門的 heavy ⇒ 受 --max-wait 管（逾時 75、不跑）"


def test_direct_run_verdict_refuses_during_gate_lock_and_only_warns_otherwise():
    lock = {"window": "h7", "token": "abc", "note": "T82", "since": NOW, "expires": NOW + 7200}
    v = H.direct_run_verdict
    assert v({}, None)[0] == "warn" and "heavy_run" in v({}, None)[1], "沒有閘門鎖：只警告"
    assert v({"MOTRIX_REQUIRE_QUEUE": "1"}, None)[0] == "refuse"
    assert v({"MOTRIX_QUEUE_GUARD": "0"}, lock)[0] == "ok" and v({"MOTRIX_QUEUE_GUARD": "0", "MOTRIX_REQUIRE_QUEUE": "1"}, None)[0] == "ok", "關閉開關"
    assert v({H.CI_TICKET_ENV: "x.json"}, None)[0] == "ok", "有票根＝排過隊"
    assert v({"MOTRIX_PYTEST_BUILD_CHILD": "123"}, lock)[0] == "ok" and v({"MOTRIX_PYTEST_EXCLUSIVE_OWNER": "123"}, lock)[0] == "ok", "建包的子行程不被擋（它有自己的獨佔登記）"
    lvl, msg = v({}, lock)
    assert lvl == "refuse" and "h7" in msg and "heavy_run" in msg, "閘門鎖持有中、沒排隊、不是持有者 ⇒ 拒絕"
    assert v({H.GATE_TOKEN_ENV: "abc"}, lock)[0] == "ok" and v({H.GATE_TOKEN_ENV: "nope"}, lock)[0] == "refuse"
    assert v({H.CI_TICKET_ENV: "x.json"}, lock)[0] == "ok", "heavy_run 放行才會有票根；放行判斷在 heavy_run 那一側"


def test_gate_lock_cli_roundtrip_and_status_line_shows_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    assert H.main(["--gate-lock", "status"]) == 0 and "閘門鎖：無" in capsys.readouterr().out
    assert H.main(["--gate-lock", "renew", "--window", "h7"]) == 1, "沒持有就不能續"
    capsys.readouterr()
    assert H.main(["--gate-lock", "acquire", "--window", "h7", "--note", "T82 閘門"]) == 0
    out = capsys.readouterr().out
    assert "token=" in out and "h7" in out
    assert H.main(["--gate-lock", "acquire", "--window", "h9"]) == 1 and "取不到" in capsys.readouterr().out
    assert H.main(["--status"]) == 0
    assert "閘門鎖：h7 持有「T82 閘門」" in capsys.readouterr().out
    assert H.main(["--gate-lock", "renew", "--window", "h7", "--ttl-hours", "1"]) == 0
    assert H.main(["--gate-lock", "release", "--window", "h9"]) == 1, "別人不能放"
    assert H.main(["--gate-lock", "release", "--window", "h9", "--force"]) == 0
    assert H.read_gate() is None


def _guard_env(monkeypatch, tmp_path):
    for k in (H.CI_TICKET_ENV, H.GATE_TOKEN_ENV, "MOTRIX_PYTEST_BUILD_CHILD", "MOTRIX_PYTEST_EXCLUSIVE_OWNER", "MOTRIX_QUEUE_GUARD", "MOTRIX_REQUIRE_QUEUE", "MOTRIX_WINDOW"):
        monkeypatch.delenv(k, raising=False)                  # 這輪測試自己可能就是被 heavy_run 包著跑的
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    if str(REPO / "backend") not in sys.path:
        sys.path.insert(0, str(REPO / "backend"))
    import conftest as cf
    return cf


class _Cfg:
    def __init__(self, collectonly=False):
        self.option = type("O", (), {"collectonly": collectonly})()


def test_conftest_queue_guard_refuses_during_gate_lock_warns_otherwise_and_fails_open(tmp_path, monkeypatch, capsys):
    cf = _guard_env(monkeypatch, tmp_path)
    cf._queue_guard(_Cfg())
    assert "heavy_run" in capsys.readouterr().out, "沒有閘門鎖：重型直接跑只警告、不擋"
    _ok, lock = H.gate_acquire("h7", "T82", 3600, path=tmp_path / "ci" / H.GATE_FILE)
    with pytest.raises(pytest.UsageError) as e:
        cf._queue_guard(_Cfg())
    assert "h7" in str(e.value) and "heavy_run" in str(e.value)
    cf._queue_guard(_Cfg(collectonly=True))                   # --collect-only 不算重型
    monkeypatch.setenv(H.GATE_TOKEN_ENV, lock["token"])
    cf._queue_guard(_Cfg())                                    # 持有者的 token ⇒ 放行
    monkeypatch.delenv(H.GATE_TOKEN_ENV)
    monkeypatch.setenv(H.CI_TICKET_ENV, "x.json")
    cf._queue_guard(_Cfg())                                    # 經 heavy_run 排過隊 ⇒ 放行
    monkeypatch.delenv(H.CI_TICKET_ENV)
    monkeypatch.setenv("MOTRIX_QUEUE_GUARD", "0")
    cf._queue_guard(_Cfg())                                    # 關閉開關
    monkeypatch.delenv("MOTRIX_QUEUE_GUARD")
    (tmp_path / "ci" / H.GATE_FILE).write_text("{壞檔", encoding="utf-8")
    capsys.readouterr()
    cf._queue_guard(_Cfg())                                    # 鎖檔壞了 ⇒ 當沒鎖（只警告），不是擋住測試
    assert "heavy_run" in capsys.readouterr().out


def test_conftest_calls_the_queue_guard_only_for_heavy_runs():
    src = (REPO / "backend" / "conftest.py").read_text(encoding="utf-8")
    heavy = src.index("    if not _is_heavy_run(config):")
    guard = src.index("    _queue_guard(config)", heavy)
    assert src.index("return                       # 單檔臨時跑", heavy) < guard < src.index("slots = _lock_slots()", heavy), "單檔臨時跑先 return；重型才走佇列檢查，且在搶鎖之前"


def test_gated_waiter_queued_ahead_does_not_deadlock_the_lock_holder(tmp_path):
    """H1：別視窗在鎖期間先排了 heavy／e2e（它在放鎖前不會開跑），持有者之後排的票不能被它擋住（否則兩邊互等到 TTL）。"""
    q = tmp_path / "q"
    lock = {"window": "h7", "token": "tk", "expires": NOW + 7200}
    _t(q, "a-other-heavy.json", "heavy", window="h9", enq=NOW - 100)
    _t(q, "b-other-e2e.json", "e2e", window="h9", enq=NOW - 90)
    _t(q, "c-holder.json", "heavy", window="h7", enq=NOW)
    ts = _tickets(q)
    holder = _by(ts, "c-holder.json")
    assert H.can_start(holder, ts) is False, "（對照）沒給 gate 時，排前面的等待者仍擋著 ⇒ 這就是死結的來源"
    assert H.can_start(holder, ts, lock) is True, "給了 gate：被鎖擋住的等待者不算排在前面，持有者插隊"
    _t(q, "d-running.json", "heavy", window="h9", started=NOW - 5, enq=NOW - 300)      # 已經在跑的別人仍然算（鎖擋新開跑，不殺舊的）
    ts = _tickets(q)
    assert H.can_start(_by(ts, "c-holder.json"), ts, lock) is False


def test_run_by_the_holder_goes_even_with_a_gated_waiter_ahead_of_it_in_the_queue(tmp_path):
    q = tmp_path / "ci" / "queue"
    H.gate_acquire("h7", "T82", 3600, path=tmp_path / "ci" / H.GATE_FILE)
    _t(q, "0000-other.json", "heavy", window="h9", enq=time.time() - 100, pid=os.getpid())     # 活的行程、還在等（被鎖擋住）
    ran = []
    rc = H.run(["x"], "heavy", "h7", qdir=q, runner=lambda c, e, f: ran.append(1) or 0, sleep=lambda s: (_ for _ in ()).throw(AssertionError("持有者不該等")), note=lambda *_: None)
    assert rc == 0 and ran


def test_holder_window_via_motrix_window_passes_the_direct_run_check_and_expiry_warns():
    lock = {"window": "h7", "token": "abc", "note": "T82", "since": NOW, "expires": NOW + 7200}
    assert H.direct_run_verdict({"MOTRIX_WINDOW": "h7"}, lock)[0] == "ok", "持有者的 shell（MOTRIX_WINDOW）直接跑重型不被擋"
    assert H.direct_run_verdict({"MOTRIX_WINDOW": "h9"}, lock)[0] == "refuse"
    assert "即將過期" not in H.gate_line(lock, NOW)
    assert "即將過期" in H.gate_line(dict(lock, expires=NOW + 600), NOW), "剩不到 30 分鐘要警告"


def test_run_stage_the_gate_itself_exports_the_gate_token_when_a_lock_is_held(tmp_path, monkeypatch):
    """M-A：run_stage 就是閘門，持有者起它時自動帶 token（不靠人記得 export）。"""
    sys.path.insert(0, str(REPO / "backend" / "tools"))
    import build_test_reuse as BT
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    monkeypatch.delenv(H.GATE_TOKEN_ENV, raising=False)
    seen = []
    ok, lock = H.gate_acquire("h7", "T82", 3600)
    assert ok
    BT.run_stage(REPO, "not_e2e", [], python=sys.executable, runner=lambda cmd, cwd, env: seen.append(env.get(H.GATE_TOKEN_ENV)) or 0, note=lambda *_: None)
    assert seen == [lock["token"]]
    H.gate_release("h7")
    seen.clear()
    BT.run_stage(REPO, "not_e2e", [], python=sys.executable, runner=lambda cmd, cwd, env: seen.append(env.get(H.GATE_TOKEN_ENV)) or 0, note=lambda *_: None)
    assert seen == [None], "沒有鎖就不帶"
