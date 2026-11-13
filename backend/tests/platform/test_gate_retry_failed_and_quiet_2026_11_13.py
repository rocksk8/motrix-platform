# -*- coding: utf-8 -*-
"""T82 閘門三個卡點的後兩個（2026-11-13，使用者：「一個太忙就要整段重跑，這個不能有重複機制嗎？」）。

① run-stage「只重試失敗題」：一段跑完、紅的題數 ≤ N ⇒ 只把紅的題在安靜環境（單程序、無 failfast）重跑一次。
   全過 ⇒ 這一段記「綠（重試 k 題）」（建包可沿用；原始紅與重試結果寫進紀錄與 retry_log.jsonl）；仍紅 ⇒ 記紅；
   紅超過 N／被中斷／failfast 提早停／collect 紅／沒有 summary ⇒ 不重試（沒跑到的題不能靠重試補）。這不是 flake 登記（known_flakes 不動）。
② 閘門期間全機安靜：閘門鎖被持有 ⇒ 非持有者的 pytest（含單檔）在 conftest 拒絕；run-stage 自己跑的時候自己持有閘門鎖（綁行程）。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._subproc import run_python, utf8_env

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(BACKEND / "tools"))
import build_test_reuse as btr  # noqa: E402
import heavy_run as H  # noqa: E402

TARGET = os.path.join("tests", "test_version_manifest_unique_version_2026_09_25.py")
R1, R2, R3 = "tests/test_a.py::test_one", "tests/test_b.py::test_two", "tests/test_c.py::test_three"


@pytest.fixture
def tiny_repo(tmp_path):
    r = tmp_path / "r"
    (r / "backend").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@x"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    (r / "backend" / "k.txt").write_text("k", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True, capture_output=True)
    return r


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in [k for k in os.environ if k.startswith("MOTRIX_")] + ["PYTEST_ADDOPTS"]:
        monkeypatch.delenv(k, raising=False)
    real_run = subprocess.run

    def run(cmd, *a, **k):                           # pip freeze 很慢且與這裡要驗的無關；其餘（git）照舊
        if isinstance(cmd, list) and cmd[1:4] == ["-m", "pip", "freeze"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="pkg==1" + chr(10), stderr="")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(btr.subprocess, "run", run)


def _write_stream(d, reds, passed=100, skipped=0, exitstatus=1, aborted=False, aborted_by="", when="call", failed=None, errors=0, summary=True):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "fail", "nodeid": n, "when": when, "summary": "AssertionError: " + n}) for n in reds]
    if summary:
        lines.append(json.dumps({"type": "summary", "exitstatus": exitstatus, "passed": passed, "skipped": skipped,
                                 "failed": len(reds) if failed is None else failed, "errors": errors,
                                 "aborted": aborted, "aborted_by": aborted_by}))
    with open(d / "x.jsonl", "a", encoding="utf-8") as fh:
        fh.write(chr(10).join(lines) + chr(10))


class Runner:
    """第一次呼叫＝整段（寫紅）；之後的呼叫＝重試（-n 0）：still 裡的題仍紅，其餘通過。"""

    def __init__(self, first_reds, first_rc=1, still=(), retry_rc=None, **first_kw):
        self.first_reds, self.first_rc, self.still, self.retry_rc, self.first_kw = list(first_reds), first_rc, list(still), retry_rc, first_kw
        self.calls = []

    def __call__(self, cmd, cwd, env):
        self.calls.append((list(cmd), dict(env)))
        d = env["MOTRIX_FAIL_STREAM_DIR"]
        if len(self.calls) == 1:
            _write_stream(d, self.first_reds, **self.first_kw)
            return self.first_rc
        ids = [a for a in cmd if "::" in a]
        _write_stream(d, [n for n in ids if n in self.still], passed=len(ids) - len(self.still))
        return self.retry_rc if self.retry_rc is not None else (1 if self.still else 0)


def _run(repo, tmp_path, runner, stage="not_e2e", **kw):
    recs = tmp_path / "rec.jsonl"
    rc, wrote, why = btr.run_stage(repo, stage, recs, runner=runner, note=lambda *_: None, **kw)
    last = json.loads(recs.read_text(encoding="utf-8").splitlines()[-1]) if recs.exists() else None
    return rc, wrote, why, last, recs


# ── ① 只重試失敗題 ──────────────────────────────────────────────────────────────────────────


def test_retry_all_green_records_green_with_evidence_and_the_build_can_reuse_it(tiny_repo, tmp_path):
    rn = Runner([R1, R2])
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert (rc, wrote) == (0, True), why
    assert len(rn.calls) == 2 and "綠（重試 2 題）" in why, why
    ent = rec["stages"]["not_e2e"]
    assert ent["green"] is True and ent["retry"]["retried_green"] is True and ent["retry"]["original_reds"] == [R1, R2] and ent["retry"]["still_red"] == []
    # 建包可沿用：同指紋、窗口內
    got = btr.find_reusable_stage(btr._read(recs), rec["fingerprint"], "not_e2e", __import__("datetime").datetime.now())
    assert got and got["green"] is True
    # 證據：retry_log 每題一行（原始紅摘要＋結果）
    rows = [json.loads(x) for x in btr.retry_log_path(recs).read_text(encoding="utf-8").splitlines()]
    assert [r["nodeid"] for r in rows] == [R1, R2] and all(r["result"] == "pass" and r["original"]["summary"].startswith("AssertionError") for r in rows)
    # known_flakes 不動（這不是 flake 登記）
    assert not (tiny_repo / "tools" / "platform" / "known_flakes.json").exists()


def test_retry_still_red_records_red(tiny_repo, tmp_path):
    rn = Runner([R1, R2], still=[R2])
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert (rc, wrote) == (1, True), why
    ent = rec["stages"]["not_e2e"]
    assert ent["green"] is False and ent["retry"]["retried_green"] is False and ent["retry"]["still_red"] == [R2], ent
    assert btr.find_reusable_stage(btr._read(recs), rec["fingerprint"], "not_e2e", __import__("datetime").datetime.now()) is None
    rows = {json.loads(x)["nodeid"]: json.loads(x)["result"] for x in btr.retry_log_path(recs).read_text(encoding="utf-8").splitlines()}
    assert rows == {R1: "pass", R2: "fail"}


def test_more_reds_than_the_limit_are_not_retried(tiny_repo, tmp_path):
    reds = ["tests/t.py::t%d" % i for i in range(6)]
    rn = Runner(reds)
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert (rc, wrote) == (1, True) and len(rn.calls) == 1, "紅超過上限卻重試了"
    assert "retry" not in rec["stages"]["not_e2e"] and "6 題 > 5" in why, why
    assert not btr.retry_log_path(recs).exists()


@pytest.mark.parametrize("kw,reason", [
    (dict(aborted_by="failfast"), "提早停止"),                      # failfast 停了＝後面的題沒跑
    (dict(aborted=True), "中斷"),
    (dict(when="collect"), "collect"),                              # 檔案載入失敗＝那檔的題根本沒跑
    (dict(summary=False), "summary"),                               # 沒有 summary ＝無法確認跑完
    (dict(failed=3), "少"),                                         # summary 說 3 個失敗、只抓到 2 個
])
def test_incomplete_or_unsafe_runs_are_never_retried(tiny_repo, tmp_path, kw, reason):
    rn = Runner([R1, R2], **kw)
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert rc == 1 and len(rn.calls) == 1 and "retry" not in rec["stages"]["not_e2e"], (kw, why)
    assert reason in why, why


def test_a_non_test_failure_exit_code_is_never_retried(tiny_repo, tmp_path):
    rn = Runner([R1], first_rc=2)                                   # 2＝中斷；3＝內部錯誤；4＝用法
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert rc == 2 and len(rn.calls) == 1


def test_retry_needs_explicit_proof_every_test_passed(tiny_repo, tmp_path):
    """重試 exit 0 但沒有「每題都跑過且通過」的證據（summary 缺）⇒ 不算綠。"""
    class NoSummary(Runner):
        def __call__(self, cmd, cwd, env):
            if len(self.calls) == 0:
                return super().__call__(cmd, cwd, env)
            self.calls.append((list(cmd), dict(env)))
            return 0                                                # 沒寫 fail_stream
    rn = NoSummary([R1])
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn)
    assert rc == 1 and rec["stages"]["not_e2e"]["green"] is False and rec["stages"]["not_e2e"]["retry"]["retried_green"] is False


def test_retry_command_is_serial_scoped_and_quiet(tiny_repo, tmp_path):
    rn = Runner([R1, R2])
    _run(tiny_repo, tmp_path, rn)
    (cmd1, env1), (cmd2, env2) = rn.calls
    assert env1["MOTRIX_FAILFAST"] == "1" and env1["MOTRIX_FAILFAST_N"] == "6" and env1["MOTRIX_FAILFAST_QUIET_MIN"] == "0", "第一輪 failfast 要讓『紅≤上限』的一輪跑完"
    assert cmd2[cmd2.index("-n") + 1] == "0", "重試必須單程序"
    assert R1 in cmd2 and R2 in cmd2 and "-m" in cmd2 and cmd2[cmd2.index("-m") + 1] == "not e2e"
    assert not any(a.startswith("--durations") for a in cmd2) and "failfast" not in cmd2 and "fail_stream" in cmd2
    assert env2["MOTRIX_FAILFAST"] == "0" and env2["MOTRIX_FAILFIRST"] == "0"
    assert env2["MOTRIX_FAIL_STREAM_DIR"] != env1["MOTRIX_FAIL_STREAM_DIR"], "重試的明細要在自己的目錄"
    rn_e2e = Runner([R1])
    _run(tiny_repo, tmp_path, rn_e2e, stage="e2e")
    c = rn_e2e.calls[1][0]
    assert c[c.index("-m") + 1] == "e2e"


def test_no_retry_keeps_the_old_failfast_and_never_retries(tiny_repo, tmp_path):
    rn = Runner([R1])
    rc, wrote, why, rec, recs = _run(tiny_repo, tmp_path, rn, retry_failed=0)
    env1 = rn.calls[0][1]
    assert rc == 1 and len(rn.calls) == 1 and env1["MOTRIX_FAILFAST_N"] == "10" and env1["MOTRIX_FAILFAST_QUIET_MIN"] == "3"
    assert "retry" not in rec["stages"]["not_e2e"]


def test_retry_counts_accumulate_per_test_across_runs(tiny_repo, tmp_path):
    recs = tmp_path / "rec.jsonl"
    for _ in range(2):
        btr.run_stage(tiny_repo, "not_e2e", recs, runner=Runner([R1, R2]), note=lambda *_: None)
    _, _, why, rec, _ = _run(tiny_repo, tmp_path, Runner([R1], still=[R1]))
    c = btr.retry_counts(recs)
    assert c[R1]["retries"] == 3 and c[R1]["passed"] == 2 and c[R1]["failed"] == 1 and c[R2]["retries"] == 2, c
    assert "%s×3" % R1 in why, "結束訊息要說這題累計重試了幾次：%s" % why


# ── ② 閘門期間全機安靜 ─────────────────────────────────────────────────────────────────────────


LOCK = {"window": "h7", "token": "tok-1", "expires": time.time() + 3600, "since": time.time(), "note": "T82"}


def test_light_run_verdict_rules():
    v = H.light_run_verdict
    assert v({}, None)[0] == "ok", "沒有閘門鎖也擋"
    assert v({}, LOCK)[0] == "refuse", "閘門期間別人的單檔沒被擋"
    assert v({}, LOCK, collect_only=True)[0] == "ok", "collect-only 被擋"
    assert v({"MOTRIX_GATE_TOKEN": "tok-1"}, LOCK)[0] == "ok" and v({"MOTRIX_GATE_TOKEN": "wrong"}, LOCK)[0] == "refuse"
    assert v({"MOTRIX_WINDOW": "h7"}, LOCK)[0] == "ok" and v({"MOTRIX_WINDOW": "h2"}, LOCK)[0] == "refuse"
    assert v({"MOTRIX_CI_TICKET": "x"}, LOCK)[0] == "ok" and v({"MOTRIX_PYTEST_BUILD_CHILD": "1"}, LOCK)[0] == "ok"
    assert v({"PYTEST_CURRENT_TEST": "a::b (call)"}, LOCK)[0] == "ok", "題目自己起的巢狀 pytest 被擋"
    assert v({"MOTRIX_QUEUE_GUARD": "0"}, LOCK)[0] == "ok", "總開關關不掉"
    level, msg = v({}, LOCK)
    assert "h7" in msg and "MOTRIX_WINDOW" in msg and "MOTRIX_QUEUE_GUARD=0" in msg, msg


def _light(tmp_path, **env):
    extra = {"MOTRIX_CI_DIR": str(tmp_path / "ci"), "MOTRIX_PYTEST_LOCK": str(tmp_path / "lock"), "MOTRIX_PYTEST_BUILD_CHILD": None,
             "MOTRIX_PYTEST_BUILD_GUARD": None, "MOTRIX_WINDOW": None, "MOTRIX_GATE_TOKEN": None, "MOTRIX_CI_TICKET": None,
             "MOTRIX_QUEUE_GUARD": None}
    extra.update(env)
    return run_python(["-m", "pytest", TARGET, "-q", "-p", "no:cacheprovider", "-k", "zz_no_such_test_zz",
                       "--basetemp=%s" % (tmp_path / "bt-adhoc")], cwd=BACKEND, env=utf8_env(**extra), timeout=180)


def test_a_single_file_pytest_is_refused_while_the_gate_lock_is_held(tmp_path):
    """行為題（真的子 pytest）：閘門鎖持有 ⇒ 非持有者 exit 4＋說明；持有者（window／token）、MOTRIX_QUEUE_GUARD=0 ⇒ 照跑（沒選到題 exit 5）；放鎖後照跑。"""
    ok, lock = H.gate_acquire("h7", note="T82", path=tmp_path / "ci" / "gate.lock")
    assert ok
    p = _light(tmp_path)
    assert p.returncode == 4 and "閘門期間" in (p.stdout + p.stderr), (p.returncode, (p.stdout + p.stderr)[-800:])
    assert _light(tmp_path, MOTRIX_WINDOW="h7").returncode == 5, "持有者視窗被擋"
    assert _light(tmp_path, MOTRIX_GATE_TOKEN=lock["token"]).returncode == 5, "帶對 token 的被擋"
    assert _light(tmp_path, MOTRIX_QUEUE_GUARD="0").returncode == 5, "總開關關不掉"
    assert _light(tmp_path, MOTRIX_WINDOW="h2").returncode == 4
    assert H.gate_release("h7", path=tmp_path / "ci" / "gate.lock")
    assert _light(tmp_path).returncode == 5, "放鎖後還被擋"


def test_conftest_calls_the_gate_check_on_the_light_path_before_returning():
    src = (BACKEND / "conftest.py").read_text(encoding="utf-8")
    i = src.index("if not _is_heavy_run(config):")
    block = src[i:src.index("_queue_guard(config)", i)]
    assert "_refuse_light_run_during_build(config)" in block and "_refuse_light_run_during_gate(config)" in block
    assert block.index("_refuse_light_run_during_gate(config)") < block.index("return"), "閘門檢查在 return 之後＝永遠不跑"


def test_a_gate_lock_bound_to_a_dead_process_is_not_a_lock(tmp_path):
    path = tmp_path / "gate.lock"
    ok, lock = H.gate_acquire("run-stage", path=path, holder_pid=os.getpid())
    assert ok and H.read_gate(path)["token"] == lock["token"]
    d = json.loads(path.read_text(encoding="utf-8"))
    d["holder_pid"] = 2147483000                                     # 不存在的行程（被殺／當機）
    path.write_text(json.dumps(d), encoding="utf-8")
    assert H.read_gate(path) is None, "持有者已死的鎖還擋著全機（要等 TTL）"
    # 反向控制：整合者顯式取的鎖不帶 holder_pid，照舊只看 TTL
    ok, lock2 = H.gate_acquire("h7", path=tmp_path / "g2.lock")
    assert ok and "holder_pid" not in lock2 and H.read_gate(tmp_path / "g2.lock")


def test_gate_hold_takes_a_free_gate_and_releases_it_but_never_touches_anothers(tmp_path, monkeypatch):
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    gp = H.gate_path()
    rel = btr.gate_hold(REPO, "not_e2e", note=lambda *_: None)
    got = H.read_gate(gp)
    assert got and got["window"] == "run-stage" and got["holder_pid"] == os.getpid() and "run-stage" in got["note"]
    rel()
    assert H.read_gate(gp) is None and not gp.exists(), "跑完沒放鎖"
    # 別人（整合者）已持有 ⇒ 不動、release 也不放
    ok, lock = H.gate_acquire("h7", note="T82", path=gp)
    rel2 = btr.gate_hold(REPO, "not_e2e", note=lambda *_: None)
    rel2()
    assert H.read_gate(gp)["token"] == lock["token"] and H.read_gate(gp)["window"] == "h7", "動了別人的閘門鎖"


def test_run_stage_holds_the_gate_only_for_a_real_run_and_children_carry_the_token(tiny_repo, tmp_path, monkeypatch):
    """真的跑（沒注入 runner）才取鎖；子行程環境帶這把鎖的 token（conftest 認 token ⇒ 自己不被自己擋）。注入 runner 時不碰真的閘門鎖。"""
    monkeypatch.setenv("MOTRIX_CI_DIR", str(tmp_path / "ci"))
    shutil_src = REPO / "tools" / "platform"
    (tiny_repo / "tools").mkdir(exist_ok=True)
    import shutil
    shutil.copytree(shutil_src, tiny_repo / "tools" / "platform", ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    subprocess.run(["git", "-C", str(tiny_repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tiny_repo), "commit", "-qm", "tools"], check=True, capture_output=True)
    seen = {}
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if isinstance(cmd, list) and "pytest" in cmd:
            g = H.read_gate()
            seen["gate"] = g
            seen["token"] = (k.get("env") or {}).get("MOTRIX_GATE_TOKEN")
            _write_stream(k["env"]["MOTRIX_FAIL_STREAM_DIR"], [])
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(btr.subprocess, "run", fake_run)
    rc, wrote, why = btr.run_stage(tiny_repo, "not_e2e", tmp_path / "rec.jsonl", note=lambda *_: None)
    assert rc == 0 and seen["gate"] and seen["gate"]["note"].startswith("run-stage") and seen["token"] == seen["gate"]["token"], seen
    assert H.read_gate() is None, "run-stage 跑完沒放閘門鎖"
