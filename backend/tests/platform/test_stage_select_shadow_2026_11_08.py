# -*- coding: utf-8 -*-
"""tools/platform/stage_select_shadow.py（stage_select 影子模式紀錄器）的測試台。

不跑任何真測試、不碰主工作樹的紀錄檔：全部用 tmp 的假 fail_stream／假 test_results／自造的小 git repo，
選題計畫用 `plan_fn` 注入（stage_select 自己的選題邏輯由 test_stage_select_2026_10_02 守）。

守的是這份紀錄的四個承諾：
  ① 「漏抓」判定正確（紅檔不在 selected∪floor∪red_reselect ⇒ no_escape=miss；強制全量時 policy 不會漏）；
  ② 全量的紅只取該段（`<stage>-retry` 不算）、偶發放行（段最後判綠）不算該抓的失敗、沒跑完的段單列；
  ③ 基準只取同段『跑完』且 commit ≠ head 的最近一筆；
  ④ 永不影響建包：record 任何內部錯誤 ⇒ exit 0＋寫 error 行；同一（run,段）不重複記。
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[3] / "tools" / "platform"
if not (TOOLS / "stage_select_shadow.py").is_file():
    pytest.skip("tools/platform/stage_select_shadow.py 不在這個安裝包", allow_module_level=True)
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import stage_select_shadow as SH  # noqa: E402

F_A = "backend/tests/test_a.py"
F_B = "backend/tests/test_b.py"
F_C = "backend/tests/test_c.py"


def _fail(stage, nodeid, typ="fail"):
    return {"type": typ, "stage": stage, "nodeid": nodeid, "run": "r1"}


def _summary(stage, aborted_by="", t="2026-11-08T05:58:05.874", failed=0):
    return {"type": "summary", "stage": stage, "t": t, "exitstatus": 0, "duration_s": 12.5, "passed": 10, "failed": failed,
            "aborted": bool(aborted_by), "aborted_by": aborted_by}


def _plan(mode="incremental", selected=(), floor=(), red_reselect=(), to_run=None, base="b" * 40, plan_error=None):
    sel = list(selected)
    return {"mode": mode, "base_commit": base, "plan_error": plan_error, "selected_files": sel, "floor_files": list(floor),
            "red_reselect": list(red_reselect), "to_run": list(to_run if to_run is not None else set(sel) | set(floor) | set(red_reselect))}


# ── ② 全量的實際結果 ───────────────────────────────────────────────────────────────

def test_full_result_takes_only_this_stage_not_the_retry_stage():
    recs = [_fail("not_e2e", "tests/test_a.py::test_x"), _fail("not_e2e-retry", "tests/test_b.py::test_y"),
            _fail("e2e", "tests/test_c.py::test_z"), _summary("not_e2e", failed=1)]
    f = SH.full_result(recs, "not_e2e", False)
    assert f["reds_files"] == [F_A] and f["reds_raw_files"] == [F_A]
    assert f["evidence"] == "fail_stream" and f["complete"] is True


def test_green_stage_means_flaky_absorbed_reds_not_counted_but_kept_raw():
    recs = [_fail("not_e2e", "tests/test_a.py::test_x"), _summary("not_e2e", failed=1)]
    f = SH.full_result(recs, "not_e2e", True)
    assert f["reds_files"] == [] and f["reds_raw_files"] == [F_A]


def test_aborted_run_is_not_complete_and_non_file_nodeids_go_to_unmapped():
    recs = [_fail("not_e2e", "tests/test_a.py::test_x"), _fail("not_e2e", "gw2", "node_down"),
            _summary("not_e2e", aborted_by="failfast")]
    f = SH.full_result(recs, "not_e2e", False)
    assert f["complete"] is False and f["aborted_by"] == "failfast"
    assert f["reds_files"] == [F_A] and f["reds_unmapped"] == ["gw2"]


def test_no_summary_means_no_evidence():
    f = SH.full_result([_fail("not_e2e", "tests/test_a.py::t")], "not_e2e", False)
    assert f["evidence"] == "none"
    assert SH.judge(f, _plan())["policy"] == "unknown"


# ── ① 判定 ────────────────────────────────────────────────────────────────────────

def _full(reds, complete=True, green=False):
    return {"evidence": "fail_stream", "green": green, "complete": complete, "reds_files": list(reds), "reds_unmapped": []}


def test_miss_when_red_file_is_not_covered_by_the_plan():
    v = SH.judge(_full([F_A, F_B]), _plan(selected=[F_A]))
    assert v["policy"] == "miss" and v["no_escape"] == "miss"
    assert v["missed_files"] == [F_B] and v["missed_files_no_escape"] == [F_B]


def test_covered_by_selected_floor_or_red_reselect():
    v = SH.judge(_full([F_A, F_B, F_C]), _plan(selected=[F_A], floor=[F_B], red_reselect=[F_C]))
    assert v["policy"] == "covered" and v["no_escape"] == "covered" and v["missed_files"] == []


def test_forced_full_never_misses_by_policy_but_selection_recall_is_still_judged():
    v = SH.judge(_full([F_B]), _plan(mode="full", selected=[F_A], to_run=[F_A, F_B]))
    assert v["policy"] == "covered", "強制全量 ⇒ 全跑 ⇒ 不會漏"
    assert v["no_escape"] == "miss" and v["missed_files_no_escape"] == [F_B], "選題本身沒蓋到，要看得見"


def test_no_base_or_plan_error_cannot_judge_selection():
    for p in (_plan(mode="full", base=None), _plan(mode="full", plan_error="計算失敗")):
        v = SH.judge(_full([F_A]), p)
        assert v["policy"] == "covered" and v["no_escape"] == "unknown"


def test_no_reds_and_green_unknown():
    assert SH.judge(_full([], green=True), _plan())["policy"] == "no_reds"
    f = _full([F_A])
    f["green"] = None
    assert SH.judge(f, _plan())["policy"] == "unknown"


# ── ③ 基準 ────────────────────────────────────────────────────────────────────────

def _shadow(run, stage, commit, complete=True, evidence="fail_stream", fin="2026-11-08T03:00:00", reds=()):
    return {"type": "shadow", "run_id": run, "stage": stage, "commit": commit, "recorded_at": "2026-11-08 03:00:00",
            "full": {"evidence": evidence, "complete": complete, "finished_at": fin, "reds_raw_files": list(reds)}}


def test_pick_base_same_stage_complete_and_not_head():
    now = datetime(2026, 11, 8, 4, 0, 0)
    entries = [_shadow("r1", "not_e2e", "c1" * 20), _shadow("r2", "e2e", "c2" * 20), _shadow("r3", "not_e2e", "c3" * 20, complete=False),
               _shadow("r4", "not_e2e", "c4" * 20, evidence="none"), _shadow("r5", "not_e2e", "c5" * 20, reds=[F_A])]
    b = SH.pick_base(entries, "not_e2e", "c9" * 20, now)
    assert b["commit"] == "c5" * 20 and b["red_files"] == [F_A] and abs(b["age_hours"] - 1.0) < 1e-6
    assert SH.pick_base(entries, "not_e2e", "c5" * 20, now)["commit"] == "c1" * 20, "同 commit 不當基準（重建同一棵 tree 走既有沿用）"
    assert SH.pick_base([], "not_e2e", "c9" * 20, now) is None
    assert SH.pick_base(entries, "e2e", "c2" * 20, now) is None


# ── 配對（backfill）───────────────────────────────────────────────────────────────

def test_join_commits_pairs_by_stage_and_time_once(tmp_path):
    sd = tmp_path / "fs"
    sd.mkdir()
    (sd / "build_20261108_050000_1.jsonl").write_text(json.dumps(_summary("not_e2e", t="2026-11-08T05:10:00.000")) + "\n", encoding="utf-8")
    (sd / "build_20261108_052000_2.jsonl").write_text(json.dumps(_summary("not_e2e", t="2026-11-08T05:30:00.000")) + "\n", encoding="utf-8")
    results = [{"commit": "aaa", "source": "build", "stages": {"not_e2e": {"green": True, "tested_at": "2026-11-08 05:10:09"}}},
               {"commit": "bbb", "source": "build", "stages": {"not_e2e": {"green": False, "tested_at": "2026-11-08 05:30:02"}}},
               {"commit": "zzz", "source": "modtest", "stages": {"not_e2e": {"green": True, "tested_at": "2026-11-08 05:10:01"}}}]
    got = SH.join_commits(sorted(sd.glob("build_*.jsonl")), results)
    assert [(g[0], g[3], g[4]) for g in got] == [("build_20261108_050000_1", "aaa", True), ("build_20261108_052000_2", "bbb", False)]


# ── ④ record 的端到端（自造 git repo＋注入計畫）──────────────────────────────────────

@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*a):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q")
    (repo / "a.txt").write_text("1", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "c1")
    c1 = git("rev-parse", "HEAD")
    (repo / "a.txt").write_text("2", encoding="utf-8")
    git("commit", "-qam", "c2")
    c2 = git("rev-parse", "HEAD")
    sd = tmp_path / "fs"
    sd.mkdir()
    return {"repo": repo, "c1": c1, "c2": c2, "sd": sd, "log": tmp_path / "shadow.jsonl"}


def _run(env, run, stage, green, plan_fn, head=None):
    recs = read = None
    f = env["sd"] / (run + ".jsonl")
    recs = SH.read_jsonl(f)
    return SH.build_entry(env["repo"], run, stage, head or env["c2"], green, recs, SH.read_jsonl(env["log"]), plan_fn=plan_fn)


def _fake_plan_fn(selected=(), floor=(), mode="incremental"):
    def fn(stage, base, head, repo, red_files=None, base_info=None, **kw):
        return {"stage": stage, "base": base, "head": head, "mode": "full" if not base else mode,
                "forced_full": [] if base else ["基準不存在或缺失（None）"], "changed_files": ["x"], "collected": [F_A, F_B, F_C],
                "selected": {f: ["理由"] for f in selected}, "floor": {f: ["F0"] for f in floor},
                "red_reselect": sorted(red_files or []), "to_run": sorted(set(selected) | set(floor) | set(red_files or [])),
                "to_run_all": not base, "invariant": {"ok": True}, "scope_gate_mode": "scoped", "soft_bottom": [], "notes": []}
    return fn


def test_entry_chain_first_has_no_base_then_second_uses_first_and_reports_a_miss(env):
    (env["sd"] / "r1.jsonl").write_text(json.dumps(_summary("not_e2e")) + "\n", encoding="utf-8")
    e1 = _run(env, "r1", "not_e2e", True, _fake_plan_fn(), head=env["c1"])
    assert e1["base"] is None and e1["plan"]["mode"] == "full" and e1["verdict"]["policy"] == "no_reds"
    SH.append_line(env["log"], e1)
    (env["sd"] / "r2.jsonl").write_text("\n".join(json.dumps(r) for r in [_fail("not_e2e", "tests/test_b.py::t"), _summary("not_e2e", failed=1)]) + "\n", encoding="utf-8")
    e2 = _run(env, "r2", "not_e2e", False, _fake_plan_fn(selected=[F_A]))
    assert e2["base"]["commit"] == env["c1"] and e2["plan"]["mode"] == "incremental"
    assert e2["verdict"]["policy"] == "miss" and e2["verdict"]["missed_files"] == [F_B]
    assert "selected_files" not in e2["plan"] and "to_run" not in e2["plan"], "清單不整份寫進紀錄"
    json.dumps(e2)


def test_record_cli_is_idempotent_and_never_fails_the_build(env, monkeypatch):
    (env["sd"] / "r1.jsonl").write_text(json.dumps(_summary("not_e2e")) + "\n", encoding="utf-8")
    monkeypatch.setattr(SH.SS, "plan_stage", _fake_plan_fn())
    args = ["--repo", str(env["repo"]), "--log", str(env["log"]), "--stream-dir", str(env["sd"]), "record", "--run-id", "r1",
            "--stage", "not_e2e", "--green", "1", "--head", env["c2"]]
    assert SH.main(args) == 0 and SH.main(args) == 0
    lines = SH.read_jsonl(env["log"])
    assert [e["type"] for e in lines] == ["shadow"], "同一（run,段）只記一次"
    bad = ["--repo", str(env["repo"]), "--log", str(env["log"]), "--stream-dir", str(env["sd"]), "record", "--run-id", "r9",
           "--stage", "e2e", "--green", "0", "--head", "no-such-commit"]
    assert SH.main(bad) == 0, "壞輸入也不能讓呼叫端失敗"
    last = SH.read_jsonl(env["log"])[-1]
    assert last["type"] == "error" and last["run_id"] == "r9" and "no-such-commit" in last["error"]


# ── 必修 1：紅卻歸不到檔 ⇒ 不是『沒有紅』───────────────────────────────────────────

def test_red_stage_without_attributable_file_is_unattributed_not_no_reds():
    only_node_down = SH.full_result([_fail("not_e2e", "gw2", "node_down"), _summary("not_e2e", failed=0)], "not_e2e", False)
    v = SH.judge(only_node_down, _plan())
    assert v["policy"] == "unattributed" and v["no_escape"] == "unattributed" and v["reds_n"] == 0
    failed_no_lines = SH.full_result([_summary("not_e2e", failed=3)], "not_e2e", False)
    v = SH.judge(failed_no_lines, _plan())
    assert v["policy"] == "unattributed" and v["no_escape"] == "unattributed"
    # 綠（偶發放行）才是真的 no_reds
    assert SH.judge(SH.full_result([_fail("not_e2e", "gw2", "node_down"), _summary("not_e2e")], "not_e2e", True), _plan())["policy"] == "no_reds"


# ── 建議 a／b／g ──────────────────────────────────────────────────────────────────

def test_pick_base_takes_latest_finished_not_last_in_file_order():
    """backfill 補錄的較舊 run 會排在檔案後面：基準仍要是『跑完時間』最近的那筆。"""
    now = datetime(2026, 11, 8, 6, 0, 0)
    entries = [_shadow("newer", "not_e2e", "c1" * 20, fin="2026-11-08T05:00:00"), _shadow("older", "not_e2e", "c2" * 20, fin="2026-11-08T03:00:00")]
    assert SH.pick_base(entries, "not_e2e", "c9" * 20, now)["run_id"] == "newer"
    assert SH.pick_base(list(reversed(entries)), "not_e2e", "c9" * 20, now)["run_id"] == "newer"


def test_timeout_env_garbage_falls_back_and_never_raises(monkeypatch):
    assert SH._timeout_s("abc") == 120 and SH._timeout_s("0") == 120 and SH._timeout_s("-3") == 120 and SH._timeout_s("7") == 7
    monkeypatch.setenv("MOTRIX_STAGE_SHADOW_TIMEOUT_S", "abc")
    assert SH._timeout_s() == 120


def test_dirty_check_uses_no_optional_locks(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(SH.subprocess, "run", fake_run)
    assert SH._is_dirty("x") is False
    assert "--no-optional-locks" in seen["cmd"], "共用樹上別搶 index.lock"


def test_pick_base_skips_rows_from_the_future_for_backfill():
    now = datetime(2026, 11, 8, 5, 0, 0)
    entries = [_shadow("r1", "not_e2e", "c1" * 20, fin="2026-11-08T03:00:00"), _shadow("r2", "not_e2e", "c2" * 20, fin="2026-11-08T09:00:00")]
    b = SH.pick_base(entries, "not_e2e", "c9" * 20, now)
    assert b["commit"] == "c1" * 20 and b["age_hours"] > 0


def test_covered_by_is_split_by_source_and_selection_only_excludes_red_reselect():
    v = SH.judge(_full([F_A, F_B, F_C]), _plan(selected=[F_A], floor=[F_B], red_reselect=[F_C]))
    assert v["covered_by"] == {F_A: "selected", F_B: "floor", F_C: "red_reselect"}
    assert v["missed_files_selection_only"] == [F_C], "red_reselect 蓋住的是前一次就知道的紅，不算選題召回"


def test_no_evidence_is_not_counted_as_unfinished_full_run():
    f = SH.full_result([], "not_e2e", False)
    assert f["evidence"] == "none" and f["complete"] is None
    s = SH.summarize([{"type": "shadow", "stage": "not_e2e", "run_id": "x", "commit": "c" * 40, "plan": {"mode": "full", "forced_full": []},
                       "full": f, "verdict": SH.judge(f, _plan())}])
    d = s["by_stage"]["not_e2e"]
    assert d["incomplete_full_runs"] == 0 and d["no_evidence"] == 1


# ── 彙總（必修 2：分母只算已評估；無法評估要單列）─────────────────────────────────────

def _ent(run, mode, verdict, complete=True, share=0.3, evidence="fail_stream"):
    return {"type": "shadow", "stage": "not_e2e", "run_id": run, "commit": "c" * 40,
            "plan": {"mode": mode, "forced_full": ["基準年齡 7 小時 > 6.0"] if mode == "full" else [], "to_run_share_tests": share, "to_run_share_files": share},
            "full": {"complete": complete, "evidence": evidence}, "verdict": verdict}


def test_summarize_unknown_is_not_reported_as_zero_misses_and_denominator_is_evaluated_only():
    ok = SH.judge(_full([F_A]), _plan(selected=[F_A]))                               # 已評估、蓋住
    miss = SH.judge(_full([F_B, F_C]), _plan(selected=[F_A]))                        # 已評估、漏 2 檔
    nobase = SH.judge(_full([F_A]), _plan(mode="full", base=None))                   # 有紅但沒基準 ⇒ no_escape=unknown
    unattr = SH.judge(SH.full_result([_summary("not_e2e", failed=2)], "not_e2e", False), _plan())
    s = SH.summarize([_ent("a", "incremental", ok), _ent("b", "incremental", miss), _ent("c", "full", nobase, complete=False),
                      _ent("d", "full", unattr), {"type": "error"}])
    d = s["by_stage"]["not_e2e"]
    a, inc = d["all"], d["incremental"]
    assert s["entries"] == 4 and s["errors"] == 1
    assert (a["evaluated"], a["no_escape_covered"], a["no_escape_miss"]) == (2, 1, 1)
    assert a["reds_evaluated"] == 3 and a["reds_missed_no_escape"] == 2, "分母是已評估列的紅檔，不含沒基準那筆"
    assert a["no_escape_unknown"] == 1 and a["unattributed"] == 1
    assert (inc["rows"], inc["evaluated"], inc["no_escape_miss"]) == (2, 2, 1), "增量列另計"
    assert (d["incremental_n"], d["forced_full_n"], d["incomplete_full_runs"]) == (2, 2, 1)
    assert d["mean_to_run_share_tests_incremental"] == 0.3
    txt = SH.format_summary(s)
    assert "無基準或計畫壞 1" in txt and "歸不到檔 1" in txt and "增量列" in txt


# ── 反向控制（突變）：判定被改鬆，守門題必須紅 ─────────────────────────────────────────

def _mutant(tmp_path, old, new):
    src = (TOOLS / "stage_select_shadow.py").read_text(encoding="utf-8")
    assert old in src, "突變錨點不見了：" + old
    p = tmp_path / "stage_select_shadow_mut.py"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("stage_select_shadow_mut", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_mutation_ignoring_floor_in_coverage_is_detected(tmp_path):
    m = _mutant(tmp_path, "cover = sel | flo | rr", "cover = sel | rr")
    v = m.judge(_full([F_B]), _plan(floor=[F_B]))
    assert v["no_escape"] == "miss", "（突變版把底板拿掉 ⇒ 會假報漏抓）"
    assert SH.judge(_full([F_B]), _plan(floor=[F_B]))["no_escape"] == "covered"


def test_mutation_counting_retry_stage_reds_is_detected(tmp_path):
    m = _mutant(tmp_path, 'r.get("stage") == stage]', 'str(r.get("stage")).startswith(stage)]')
    recs = [_fail("not_e2e-retry", "tests/test_b.py::t"), _summary("not_e2e", failed=0)]
    assert m.full_result(recs, "not_e2e", False)["reds_files"] == [F_B]
    assert SH.full_result(recs, "not_e2e", False)["reds_files"] == []


def test_mutation_dropping_unattributed_rule_is_detected(tmp_path):
    m = _mutant(tmp_path, 'if not reds and full.get("green") is False:', "if False:")
    f = SH.full_result([_summary("not_e2e", failed=3)], "not_e2e", False)
    assert m.judge(f, _plan())["policy"] == "no_reds", "（突變版把紅的建包判成沒有紅）"
    assert SH.judge(f, _plan())["policy"] == "unattributed"


def test_watchdog_kills_a_stuck_background_record_and_leaves_an_error_line(env):
    import os
    prog = "\n".join([
        "import sys, time",
        "sys.path.insert(0, %r)" % str(TOOLS),
        "import stage_select_shadow as SH",
        "SH.SS.plan_stage = lambda *a, **k: time.sleep(60)",
        "SH.main(['--repo', %r, '--log', %r, '--stream-dir', %r, 'record', '--run-id', 'rw', '--stage', 'not_e2e', '--green', '1', '--head', %r])"
        % (str(env["repo"]), str(env["log"]), str(env["sd"]), env["c2"]),
    ])
    (env["sd"] / "rw.jsonl").write_text(json.dumps(_summary("not_e2e")) + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", prog], env=dict(os.environ, MOTRIX_STAGE_SHADOW_TIMEOUT_S="1"), timeout=45, capture_output=True)
    assert r.returncode == 0
    last = SH.read_jsonl(env["log"])[-1]
    assert last["type"] == "error" and "timeout" in last["error"] and last["run_id"] == "rw"

