# -*- coding: utf-8 -*-
"""建包優化（2026-09-30 使用者「安排建包的優化方式，避免非正常情況的失敗」；PLAYBOOK §D-建包）。

五條規則各有題、各附反向控制（突變清單見 PLAYBOOK §D-建包「守門」）：
① 跨工具沿用：modtest --full 的綠寫進建包的沿用紀錄；分段沿用（非 e2e 綠、只有 e2e 紅 ⇒ 重建只跑 e2e）。
② 偶發政策：紅的題隔離重跑，通過**且已登記**才放行；未登記、每次都紅、登記過期 ⇒ 擋。
③ 建包獨佔：臨時 pytest 在建包登記存活時拒絕開始；建包自己的子行程（BUILD_CHILD）照跑。
④ 孤兒偵測：鎖持有者父行程不在、或祖先鏈沒有 Claude／殼 ⇒ 報告（不結束）。
⑤ 功能關掉 ⇒ 舊行為（ps1 開關、conftest MOTRIX_PYTEST_BUILD_GUARD=0）。
"""
import importlib.util
import json
import os
import sys
import time
import types
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tests._subproc import run_python, utf8_env
from tools import build_test_reuse as tr

REPO = Path(__file__).resolve().parents[3]
PLAT = REPO / "tools" / "platform"
BACKEND = REPO / "backend"
if str(PLAT) not in sys.path:
    sys.path.insert(0, str(PLAT))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KF = _load("_known_flakes_t", PLAT / "known_flakes.py")
FR = _load("_flaky_retry_t", PLAT / "flaky_retry.py")
PF = _load("_build_preflight_t", PLAT / "build_preflight.py")
MT = _load("_modtest_bo_t", PLAT / "modtest.py")
PS1 = (BACKEND / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")

NOW = datetime(2026, 9, 30, 15, 0, 0)
TS = "%Y-%m-%d %H:%M:%S"


def _t(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime(TS)


def _stage_row(fp, stage, green, hours_ago=1, flaky=None, source="build"):
    e = {"green": green, "tested_at": _t(hours_ago)}
    if flaky:
        e["flaky_retried"] = flaky
    return {"fingerprint": fp, "tested_at": _t(hours_ago), "green": False, "commit": "c", "source": source,
            "stages": {stage: e}}


# ── ① 分段沿用 ────────────────────────────────────────────────────────────────

def test_only_e2e_failed_means_a_rebuild_reuses_the_non_e2e_stage():
    """使用者指定：非 e2e 綠、只有 e2e 紅 ⇒ 重建只跑 e2e。反向控制：e2e 那一段不可以被沿用。"""
    rows = [_stage_row("F", "not_e2e", True, 2), _stage_row("F", "e2e", False, 1)]
    got = tr.find_reusable_stage(rows, "F", "not_e2e", NOW)
    assert got and got["green"] is True and got["tested_at"] == _t(2)
    assert tr.find_reusable_stage(rows, "F", "e2e", NOW) is None, "紅的 e2e 被沿用"
    assert tr.find_reusable(rows, "F", NOW) is None, "舊的完整沿用把分段紀錄當成全綠"


def test_a_newer_red_of_the_same_stage_blocks_an_older_green():
    rows = [_stage_row("F", "not_e2e", True, 3), _stage_row("F", "not_e2e", False, 1)]
    assert tr.find_reusable_stage(rows, "F", "not_e2e", NOW) is None


def test_a_row_without_that_stage_does_not_decide_it():
    """只跑完非 e2e 就中斷的那一行（沒有 e2e）⇒ e2e 看更早的一筆。"""
    rows = [_stage_row("F", "e2e", True, 3), _stage_row("F", "not_e2e", True, 1)]
    assert tr.find_reusable_stage(rows, "F", "e2e", NOW)["tested_at"] == _t(3)


def test_stage_window_counts_from_when_it_really_ran():
    """沿用後再記錄帶原時間 ⇒ 12 小時從實跑那一刻算，不會一路延長。"""
    row = _stage_row("F", "not_e2e", True, 1)
    row["stages"]["not_e2e"]["tested_at"] = _t(13)
    assert tr.find_reusable_stage([row], "F", "not_e2e", NOW) is None
    assert tr.find_reusable_stage([_stage_row("F", "not_e2e", True, 11)], "F", "not_e2e", NOW) is not None
    cross_day = _stage_row("F", "not_e2e", True, 1)
    cross_day["stages"]["not_e2e"]["tested_at"] = "2026-09-29 23:59:00"
    assert tr.find_reusable_stage([cross_day], "F", "not_e2e", NOW) is None, "跨日也沿用"
    assert tr.find_reusable_stage([_stage_row("G", "not_e2e", True)], "F", "not_e2e", NOW) is None, "指紋不同也沿用"
    assert tr.find_reusable_stage([_stage_row("F", "not_e2e", True)], None, "not_e2e", NOW) is None


def test_legacy_rows_count_for_both_stages():
    legacy = {"fingerprint": "F", "tested_at": _t(1), "green": True, "commit": "c"}
    assert tr.find_reusable_stage([legacy], "F", "e2e", NOW) is not None
    assert tr.find_reusable_stage([dict(legacy, green=False)], "F", "not_e2e", NOW) is None, "舊格式紅的一行被當綠"


def test_flaky_list_travels_with_the_reused_stage():
    rows = [_stage_row("F", "e2e", True, 1, flaky=["m/t.py::x"])]
    assert tr.find_reusable_stage(rows, "F", "e2e", NOW)["flaky_retried"] == ["m/t.py::x"]


def test_record_stage_cli_round_trip(tmp_path):
    rec = tmp_path / "r.jsonl"
    tr.main(["record-stage", "--records", str(rec), "--fp", "F", "--stage", "not_e2e", "--green", "1", "--commit", "c"])
    tr.main(["record-stage", "--records", str(rec), "--fp", "F", "--stage", "e2e", "--green", "0", "--commit", "c"])
    assert tr.lookup_stage(rec, "F", "not_e2e") is not None
    assert tr.lookup_stage(rec, "F", "e2e") is None
    assert tr.lookup(rec, "F") is None, "分段紀錄的頂層 green 必須是 False（舊版建包不可誤沿用）"
    res = tmp_path / "retry.json"
    res.write_text(json.dumps({"flaky_retried": [{"nodeid": "m/t.py::x"}]}), encoding="utf-8")
    tr.main(["record-stage", "--records", str(rec), "--fp", "F", "--stage", "e2e", "--green", "1", "--flaky-from", str(res)])
    assert tr.lookup_stage(rec, "F", "e2e")["flaky_retried"] == ["m/t.py::x"]


def test_record_full_run_rules(tmp_path):
    rec = tmp_path / "r.jsonl"
    ok, _ = tr.record_full_run(rec, "F", "F", "c", {"main": 0, "e2e": 0}, ["-q"])
    assert ok and tr.lookup(rec, "F") is not None, "兩段都綠的 modtest --full 沒有寫成完整全綠"
    assert tr.lookup_stage(rec, "F", "e2e")["source"] == "modtest --full"
    # 反向控制：指紋前後不同／算不出來、縮小範圍的參數 ⇒ 不寫
    for args in (("F", "G", {"main": 0, "e2e": 0}, []), (None, None, {"main": 0, "e2e": 0}, []),
                 ("F", "F", {"main": 0, "e2e": 0}, ["-k", "x"]), ("F", "F", {"main": 0, "e2e": 0}, ["tests/x.py"]),
                 ("F", "F", {"main": 0, "e2e": 0}, ["--deselect", "a::b"]), ("F", "F", {"main": 0, "e2e": 0}, ["-x"])):
        assert tr.record_full_run(tmp_path / "no.jsonl", *args[:2], "c", args[2], args[3])[0] is False, args
    # e2e 中斷 ⇒ 只記非 e2e；紅照記
    tr.record_full_run(rec, "H", "H", "c", {"main": 0, "e2e": 1}, [], interrupted=True)
    assert tr.lookup_stage(rec, "H", "not_e2e") and tr.lookup_stage(rec, "H", "e2e") is None
    tr.record_full_run(rec, "F", "F", "c", {"main": 0, "e2e": 1}, [])
    assert tr.lookup_stage(rec, "F", "e2e") is None, "紅的 --full 沒有擋掉同指紋先前的綠"
    assert tr.lookup_stage(rec, "F", "not_e2e") is not None


def test_registering_a_flake_does_not_invalidate_the_reuse_fingerprint(tmp_path):
    """「e2e 紅 → 登記偶發 → commit → 重建」：登記簿不改變任何題目過或不過 ⇒ 指紋不變，重建只跑 e2e。
    反向控制：同一目錄的別的檔改了 ⇒ 指紋要變（排除的只有那一個檔）。"""
    import subprocess as sp

    def git(*a):
        sp.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    r = tmp_path / "repo"
    (r / "tools" / "platform").mkdir(parents=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (r / "tools" / "platform" / "known_flakes.json").write_text('{"flakes": []}', encoding="utf-8")
    (r / "tools" / "platform" / "other.json").write_text("{}", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "a")
    env = {"python": "x", "pip_freeze": "", "playwright": None, "browsers": [], "motrix_env": {}}
    before = tr.fingerprint(r, env=env)
    (r / "tools" / "platform" / "known_flakes.json").write_text('{"flakes": [1]}', encoding="utf-8")
    git("commit", "-q", "-am", "b")
    assert tr.fingerprint(r, env=env) == before, "登記偶發改變了指紋 ⇒ 重建整套重跑"
    (r / "tools" / "platform" / "other.json").write_text('{"x": 1}', encoding="utf-8")
    git("commit", "-q", "-am", "c")
    assert tr.fingerprint(r, env=env) != before


def test_worker_caps_and_stream_ids_are_not_part_of_the_fingerprint(monkeypatch):
    """建包與 modtest 各自會有的環境變數（worker 上限、fail_stream、建包守門）不可以讓兩邊指紋不同。"""
    for k in ("MOTRIX_E2E_MAX_WORKERS", "MOTRIX_FULL_MAX_WORKERS", "MOTRIX_FAIL_STREAM_RUN", "MOTRIX_PYTEST_BUILD_CHILD"):
        monkeypatch.setenv(k, "3")
    monkeypatch.setenv("MOTRIX_EDGE_PDF_TIMEOUT", "40")
    env = tr.current_env()["motrix_env"]
    assert "MOTRIX_EDGE_PDF_TIMEOUT" in env, "影響結果的 MOTRIX_* 被排除了"
    assert not {"MOTRIX_E2E_MAX_WORKERS", "MOTRIX_FULL_MAX_WORKERS", "MOTRIX_FAIL_STREAM_RUN",
                "MOTRIX_PYTEST_BUILD_CHILD"} & set(env)


class _FakeTool:
    def __init__(self):
        self.calls = []

    def fingerprint_via(self, py):
        return "FP"

    def default_records(self, repo):
        return "R"

    def record_full_run(self, *a):
        self.calls.append(a)
        return True, "ok"


def test_modtest_records_only_with_real_run_evidence():
    """🔴 run_pytest 被換掉的題目（或 plugin 沒載入）不可以寫出「綠」——否則題目會替真的 tree 造出假綠，建包跳過測試。"""
    t = _FakeTool()
    assert MT.record_for_build("c", {"main": 0, "e2e": 0}, [], False, False, {}, tool=t)[0] is False
    assert MT.record_for_build("c", {"main": 0, "e2e": 0}, [], False, False, {"main": [0]}, tool=t)[0] is False
    assert MT.record_for_build("c", {"main": 0, "e2e": 0}, [], False, False, {"main": [0], "e2e": [1]}, tool=t)[0] is False
    assert MT.record_for_build("c", {"main": 0, "e2e": 0}, [], False, True, {"main": [0], "e2e": [0]}, tool=t)[0] is False, "dirty 也寫"
    assert t.calls == []
    assert MT.record_for_build("c", {"main": 0, "e2e": 0}, [], False, False, {"main": [0, 0], "e2e": [0]}, tool=t)[0] is True
    assert MT.record_for_build("c", {"main": 1, "e2e": 0}, [], False, False, {"main": [0, 1], "e2e": [0]}, tool=t)[0] is True
    assert len(t.calls) == 2 and t.calls[0][1:3] == ("FP", "FP")


def test_stream_evidence_reads_only_this_runs_summaries(tmp_path):
    (tmp_path / "RUN.jsonl").write_text("\n".join(json.dumps(r) for r in (
        {"type": "summary", "stage": "w", "exitstatus": 0}, {"type": "fail", "stage": "w"},
        {"type": "summary", "stage": "we2e", "exitstatus": 1}, {"type": "summary", "stage": "other", "exitstatus": 0})),
        encoding="utf-8")
    assert MT.stream_evidence("RUN", {"main": "w", "e2e": "we2e"}, stream_dir=tmp_path) == {"main": [0], "e2e": [1]}
    assert MT.stream_evidence(None, {"main": "w"}, stream_dir=tmp_path) == {}
    assert MT.stream_evidence("NOPE", {"main": "w"}, stream_dir=tmp_path) == {}


def test_run_full_with_faked_pytest_writes_no_reuse_record(monkeypatch, tmp_path):
    """行為題：既有題目以假 run_pytest 呼叫 run_full ⇒ 不可以寫進（真的）沿用紀錄。"""
    t = _FakeTool()
    monkeypatch.setattr(MT, "_reuse_tool", lambda: t)
    monkeypatch.setattr(MT, "tree_state", lambda repo=None: ("a" * 40, ""))
    monkeypatch.setattr(MT, "run_pytest", lambda *a, **k: (0, "== 5 passed in 1.0s =="))
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: Path("x"))
    monkeypatch.setenv("MOTRIX_FAIL_STREAM_DIR", str(tmp_path))
    MT.run_full([], types.SimpleNamespace(workers=2, e2e_workers=2, window="t"))
    assert t.calls == []


# ── ② 偶發政策 ────────────────────────────────────────────────────────────────

NID = "modules/x/tests/test_y.py::test_z"
TODAY = date(2026, 9, 30)


def _entry(nodeid=NID, expires="2026-10-10"):
    return {"nodeid": nodeid, "first_seen": "2026-09-26", "owner": "H", "ticket": "RUN-PLAN O7", "expires": expires}


def test_registered_flake_that_passes_on_retry_is_allowed_and_listed():
    ok, flaky, msgs = KF.decide([{"nodeid": NID, "attempts": [1, 0], "passed": True}], [_entry()], TODAY)
    assert ok and [f["nodeid"] for f in flaky] == [NID] and flaky[0]["ticket"] == "RUN-PLAN O7" and not msgs


def test_unregistered_flake_still_blocks_and_prints_the_register_command():
    ok, flaky, msgs = KF.decide([{"nodeid": NID, "attempts": [0], "passed": True}], [], TODAY)
    assert not ok and flaky == []
    assert any("known_flakes.py add" in m and NID in m for m in msgs), msgs


def test_failing_every_attempt_blocks_even_when_registered():
    ok, _, msgs = KF.decide([{"nodeid": NID, "attempts": [1, 1], "passed": False}], [_entry()], TODAY)
    assert not ok and any("每次都紅" in m for m in msgs)


def test_expired_entries_block_and_fail_the_registry_check():
    old = _entry(expires="2026-09-29")
    ok, _, msgs = KF.decide([{"nodeid": NID, "attempts": [0], "passed": True}], [old], TODAY)
    assert not ok and any("過期" in m for m in msgs)
    assert KF.check_messages([old], [], TODAY), "過期條目沒有讓檢查失敗"
    assert not KF.check_messages([_entry(expires="2026-09-30")], [], TODAY), "到期日當天就判過期"


def test_no_identified_failures_blocks():
    assert KF.decide([], [_entry()], TODAY)[0] is False


def test_registry_file_is_well_formed_and_cli_round_trip(tmp_path):
    entries, problems = KF.load()
    assert problems == [], problems
    assert all(e["expires"] for e in entries)
    reg = tmp_path / "kf.json"
    assert KF.main(["--path", str(reg), "--today", "2026-09-30", "add", "--nodeid", NID, "--owner", "H", "--ticket", "T", "--days", "45"]) == 2, \
        "超過 30 天的登記被接受（登記是限期查根因）"
    assert KF.main(["--path", str(reg), "--today", "2026-09-30", "add", "--nodeid", NID, "--owner", "H", "--ticket", "T", "--days", "7"]) == 0
    assert KF.main(["--path", str(reg), "--today", "2026-10-06", "check"]) == 0
    assert KF.main(["--path", str(reg), "--today", "2026-10-08", "check"]) == 1, "過期後 check 仍通過"
    assert KF.main(["--path", str(reg), "--today", "2026-10-08", "add", "--nodeid", NID, "--owner", "H", "--ticket", "T", "--days", "7",
                    "--reason", "還在查"]) == 0
    assert KF.load(reg)[0][0]["first_seen"] == "2026-09-30", "延期改掉了首次出現日"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"flakes": [{"nodeid": NID}]}), encoding="utf-8")
    assert KF.load(bad)[1], "缺欄位的條目沒有被判成問題"


def test_the_committed_registry_is_empty_after_o7_was_fixed():
    """主持裁示（W3 修掉 O7 根因）：登記簿維持空；O7 留在 removed（延期紀錄不因移除而歸零）。"""
    entries, problems = KF.load()
    assert problems == [] and entries == []
    assert any("test_layout_editor_role_override_and_restore" in r["nodeid"] for r in KF._removed())


def test_extension_rules():
    """稽核 W4：延期每次 ≤14 天、要原因；第 2 次要換原因＋根因連結；第 3 次一律拒絕。"""
    f = KF.extension_decision
    assert f(None, 30, "", "", TODAY)[0] is True, "首次登記被當成延期"
    h0 = _entry()
    assert f(h0, 15, "還在查", "", TODAY)[0] is False, "延期超過 14 天被接受"
    assert f(h0, 14, "", "", TODAY)[0] is False, "延期沒寫原因被接受"
    ok, _, exts = f(h0, 14, "還在查", "", TODAY)
    assert ok and len(exts) == 1
    h1 = dict(h0, extensions=exts)
    assert f(h1, 14, "還在查", "https://x/1", TODAY)[0] is False, "第 2 次延期沿用同一個原因被接受"
    assert f(h1, 14, "換了原因", "", TODAY)[0] is False, "第 2 次延期沒附根因連結被接受"
    ok, _, exts2 = f(h1, 14, "換了原因", "https://x/1", TODAY)
    assert ok and exts2[-1]["root_cause_link"] == "https://x/1"
    assert f(dict(h0, extensions=exts2), 7, "第三個原因", "https://x/2", TODAY)[0] is False, "第 3 次延期被接受"


def test_remove_then_readd_does_not_reset_the_extension_count(tmp_path):
    reg = tmp_path / "kf.json"
    base = ["--path", str(reg), "--today", "2026-09-30"]
    add = ["add", "--nodeid", NID, "--owner", "H", "--ticket", "T", "--days", "7"]
    assert KF.main(base + add) == 0
    assert KF.main(base + add + ["--reason", "a"]) == 0
    assert KF.main(base + ["remove", "--nodeid", NID]) == 0
    assert KF.main(base + add + ["--reason", "a"]) == 2, "刪掉再登記把延期次數歸零（第 2 次延期沒換原因、沒附連結也過）"
    assert KF.main(base + add + ["--reason", "b", "--root-cause-link", "RUN-PLAN O99"]) == 0
    assert KF.main(base + add + ["--reason", "c", "--root-cause-link", "x"]) == 2


def test_pytest_addopts_is_part_of_the_fingerprint(monkeypatch):
    """稽核 W4：PYTEST_ADDOPTS（可含 -k／-m 縮小範圍）要進指紋；沒設時不加鍵（既有紀錄照樣可沿用）。"""
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    assert "pytest_addopts" not in tr.current_env()
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k smoke")
    assert tr.current_env().get("pytest_addopts") == "-k smoke", "PYTEST_ADDOPTS 沒進指紋 ⇒ 縮小範圍的綠會被建包沿用"


def test_failed_nodeids_from_stream_and_output():
    recs = [{"type": "fail", "when": "call", "nodeid": "a.py::t1"}, {"type": "node_down", "nodeid": "(worker gw1)"},
            {"type": "fail", "when": "setup", "nodeid": "a.py::t2"}]
    ids, blockers = FR.failed_nodeids(recs, "FAILED a.py::t1 - AssertionError\nFAILED b.py::t3 - Timeout\nnoise")
    assert ids == ["a.py::t1", "a.py::t2", "b.py::t3"] and blockers == []
    _, blockers = FR.failed_nodeids([{"type": "fail", "when": "collect", "nodeid": "c.py"}], "ERROR d.py - ImportError")
    assert len(blockers) == 2, "收集錯誤沒有擋下"


def test_precheck_refuses_non_flake_shapes():
    assert FR.precheck(1, ["a::b"], [], 5) == []
    assert FR.precheck(2, ["a::b"], [], 5), "中斷（exit 2）也重跑"
    assert FR.precheck(1, ["x::%d" % i for i in range(6)], [], 5), "一次紅 6 題也當偶發重跑"
    assert FR.precheck(1, [], [], 5), "認不出哪一題也放行"
    assert FR.precheck(1, ["a::b"], ["收集錯誤：c.py"], 5)


def test_retry_all_stops_at_first_pass_and_caps_attempts():
    seq = {"a": [1, 0], "b": [1, 1, 0], "c": [0, 1]}
    res = FR.retry_all(["a", "b", "c"], 2, lambda nid, k: seq[nid][k - 1])
    assert res == [{"nodeid": "a", "attempts": [1, 0], "passed": True}, {"nodeid": "b", "attempts": [1, 1], "passed": False},
                   {"nodeid": "c", "attempts": [0], "passed": True}]


def _run_retry_main(tmp_path, monkeypatch, registry_entries, runner_codes, exit_code=1):
    monkeypatch.setenv("MOTRIX_FAIL_STREAM_DIR", str(tmp_path / "fs"))
    (tmp_path / "fs").mkdir(exist_ok=True)
    (tmp_path / "fs" / "RUN.jsonl").write_text(json.dumps({"type": "fail", "when": "call", "stage": "e2e", "nodeid": NID}) + "\n",
                                               encoding="utf-8")
    reg = tmp_path / "kf.json"
    reg.write_text(json.dumps({"flakes": registry_entries}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(FR, "make_runner", lambda *a, **k: (lambda nid, n: calls.append((nid, n)) or runner_codes[n - 1]))
    out = tmp_path / "res.json"
    code = FR.main(["--run-id", "RUN", "--stage", "e2e", "--exit-code", str(exit_code), "--basetemp-prefix", str(tmp_path / "bt"),
                    "--result-out", str(out), "--registry", str(reg)])
    stream = [json.loads(l) for l in (tmp_path / "fs" / "RUN.jsonl").read_text(encoding="utf-8").splitlines()]
    return code, json.loads(out.read_text(encoding="utf-8")), stream, calls


def test_retry_main_allows_a_registered_flake_and_writes_fail_stream(tmp_path, monkeypatch):
    far = (date.today() + timedelta(days=5)).isoformat()
    code, res, stream, calls = _run_retry_main(tmp_path, monkeypatch, [_entry(expires=far)], [1, 0])
    assert code == 0 and res["ok"] is True and [f["nodeid"] for f in res["flaky_retried"]] == [NID]
    assert calls == [(NID, 1), (NID, 2)]
    assert stream[-1]["type"] == "flaky_retried" and stream[0]["type"] == "fail", "原本的紅被改掉或沒記 flaky_retried"


def test_retry_main_blocks_an_unregistered_flake(tmp_path, monkeypatch):
    code, res, stream, _ = _run_retry_main(tmp_path, monkeypatch, [], [0])
    assert code == 1 and res["ok"] is False and stream[-1]["type"] == "flaky_blocked"


def test_retry_main_does_not_rerun_an_interrupted_stage(tmp_path, monkeypatch):
    code, res, _, calls = _run_retry_main(tmp_path, monkeypatch, [_entry()], [0], exit_code=2)
    assert code == 1 and calls == [], "中斷的那一段也被重跑"


# ── ③ 建包獨佔：臨時 pytest 拒絕開始 ─────────────────────────────────────────────

import conftest as _cf  # noqa: E402


def test_light_run_block_reason_rules():
    reg = {"pid": 4711, "started_at": time.time()}
    f = _cf.light_run_block_reason
    assert f(reg, True, {}, 1, False) == "4711", "建包登記存活時臨時 pytest 沒被擋"
    assert f(reg, True, {_cf.BUILD_CHILD_ENV: "4711"}, 1, False) is None, "建包自己的子行程被擋"
    assert f(reg, True, {"MOTRIX_PYTEST_EXCLUSIVE_OWNER": "4711"}, 1, False) is None
    assert f(reg, True, {}, 4711, False) is None
    assert f(reg, True, {_cf.BUILD_CHILD_ENV: "999"}, 1, False) == "4711", "別的建包的子行程被放行"
    assert f(reg, True, {_cf.BUILD_GUARD_ENV: "0"}, 1, False) is None, "關掉守門仍擋（功能關掉要回舊行為）"
    assert f(reg, True, {}, 1, True) is None, "collect-only 被擋（modtest 選題與鎖守門題靠它）"
    assert f(reg, False, {}, 1, False) is None, "持有者已死仍擋"
    assert f(None, True, {}, 1, False) is None


TARGET = os.path.join("tests", "test_version_manifest_unique_version_2026_09_25.py")


def _light(tmp_path, **env):
    extra = {"MOTRIX_PYTEST_LOCK": str(tmp_path / "lock"), _cf.BUILD_CHILD_ENV: None, _cf.BUILD_GUARD_ENV: None}
    extra.update(env)
    e = utf8_env(**extra)
    return run_python(["-m", "pytest", TARGET, "-q", "-p", "no:cacheprovider", "-k", "zz_no_such_test_zz",
                       "--basetemp=%s" % (tmp_path / "bt-adhoc")], cwd=BACKEND, env=e, timeout=180)


def test_adhoc_pytest_refuses_to_start_while_a_build_holds_the_exclusive_lock(tmp_path):
    """行為題（真的子 pytest）：登記存活 ⇒ exit 4＋說明；帶 BUILD_CHILD＝登記 pid ⇒ 照跑（沒選到題 exit 5）；守門關掉 ⇒ 照跑。"""
    (tmp_path / "lock.exclusive").write_text(json.dumps({"pid": os.getpid(), "started_at": time.time(),
                                                         "basetemp": "build_deploy_package"}), encoding="utf-8")
    p = _light(tmp_path)
    assert p.returncode == 4 and "建包獨佔中" in (p.stdout + p.stderr), (p.returncode, (p.stdout + p.stderr)[-800:])
    assert (tmp_path / "lock.exclusive").exists(), "被擋的一輪動了建包的登記"
    p = _light(tmp_path, **{_cf.BUILD_CHILD_ENV: str(os.getpid())})
    assert p.returncode == 5, (p.returncode, (p.stdout + p.stderr)[-800:])
    p = _light(tmp_path, **{_cf.BUILD_GUARD_ENV: "0"})
    assert p.returncode == 5, (p.returncode, (p.stdout + p.stderr)[-800:])
    (tmp_path / "lock.exclusive").unlink()
    p = _light(tmp_path)
    assert p.returncode == 5, "沒有登記也被擋：%s" % (p.stdout + p.stderr)[-600:]


def test_an_exclusive_session_marks_its_own_children(tmp_path):
    """不經建包腳本、直接以獨佔身分跑的一輪：它起的子 pytest 要認得登記（BUILD_CHILD＝登記 pid），否則會被自己的守門擋。"""
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "bcprobe.py").write_text(
        "import os\n"
        "def pytest_collection_finish(session):\n"
        "    print('BUILDCHILD=%s ME=%s' % (os.environ.get('MOTRIX_PYTEST_BUILD_CHILD'), os.getpid()))\n", encoding="utf-8")
    e = utf8_env(MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"), MOTRIX_PYTEST_LOCK_WAIT=0, MOTRIX_PYTEST_SLOTS=2,
                 MOTRIX_PYTEST_EXCLUSIVE="1", PYTHONPATH=str(probe), **{_cf.BUILD_CHILD_ENV: None})
    p = run_python(["-m", "pytest", TARGET, "--collect-only", "-q", "-p", "bcprobe", "--basetemp=%s" % (tmp_path / "x-full")],
                   cwd=BACKEND, env=e, timeout=180)
    line = [l for l in p.stdout.splitlines() if l.startswith("BUILDCHILD=")]
    assert line, (p.stdout + p.stderr)[-800:]
    child, me = line[0][len("BUILDCHILD="):].split(" ME=")
    assert child == me, line[0]


# ── ④ 孤兒偵測（只報告）──────────────────────────────────────────────────────────

def _procs(*rows):
    return [{"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "created": created} for pid, ppid, name, cmd, created in rows]


PY_PYTEST = "python.exe -m pytest -q --basetemp=C:\\T\\motrix-pytest-a-full"


def test_orphan_when_the_parent_is_gone():
    idx = PF.index(_procs((100, 99, "python.exe", PY_PYTEST, 50)))
    c = PF.classify(100, idx)
    assert c["orphan"] and c["parent_gone"] and not c["has_live_ancestor"]
    assert any("父行程已不存在" in r for r in c["reasons"]), c["reasons"]


def test_not_orphan_under_a_live_shell_or_claude():
    idx = PF.index(_procs((1, 0, "claude.exe", "claude", 1), (10, 1, "bash.exe", "bash", 2), (11, 10, "timeout.exe", "t", 3),
                          (100, 11, "python.exe", PY_PYTEST, 4)))
    c = PF.classify(100, idx)
    assert not c["orphan"] and c["chain"][-1] == "claude.exe(1)"


def test_orphan_when_no_live_claude_or_shell_in_the_chain():
    idx = PF.index(_procs((5, 0, "services.exe", "s", 1), (100, 5, "python.exe", PY_PYTEST, 4)))
    c = PF.classify(100, idx)
    assert c["orphan"] and not c["parent_gone"] and any("Claude" in r for r in c["reasons"])


def test_reused_parent_pid_counts_as_gone():
    """父行程的 pid 被別人重用（比子行程晚建立）⇒ 父行程已不存在。"""
    idx = PF.index(_procs((1, 0, "claude.exe", "claude", 1), (99, 1, "bash.exe", "bash", 900), (100, 99, "python.exe", PY_PYTEST, 50)))
    assert PF.classify(100, idx)["parent_gone"] is True


def test_other_pytests_exclude_the_builds_own_tree_and_xdist_workers():
    procs = _procs((1, 0, "powershell.exe", "ps", 1), (500, 1, "powershell.exe", "build", 2), (501, 500, "python.exe", PY_PYTEST, 3),
                   (502, 501, "python.exe", 'python -c "import sys;exec(eval(sys.stdin.readline()))"', 4),
                   (600, 1, "python.exe", "python.exe -m pytest tests\\x.py --basetemp=C:\\T\\motrix-pytest-b-adhoc", 5),
                   (601, 1, "python.exe", "python.exe tools\\platform\\modtest.py --full", 5),
                   (602, 1, "python.exe", "python.exe other.py --basetemp=C:\\pytest-of-me", 5))
    assert sorted(p["pid"] for p in PF.other_pytests(procs, 500)) == [600, 601]


def test_venv_launcher_and_real_interpreter_count_once():
    """實測（2026-09-30 建包中）：venv 的 python.exe 轉呼叫真正的直譯器，兩個行程參數相同 ⇒ 只算一輪。"""
    args = " -m pytest -q -rf -m e2e -n 4 --basetemp=C:\\T\\motrix-pytest-x_e2e"
    procs = _procs((1, 0, "bash.exe", "b", 1), (10, 1, "python.exe", '"D:\\v\\.venv312\\Scripts\\python.exe"' + args, 2),
                   (11, 10, "python.exe", '"C:\\Py312\\python.exe"' + args, 3))
    assert [p["pid"] for p in PF.other_pytests(procs, 999)] == [10]


def test_report_lists_orphan_holders_with_a_manual_command_and_never_waits_on_them(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTRIX_PYTEST_SLOTS", raising=False)
    lock = tmp_path / "lock"
    lock.write_text(json.dumps({"pid": 100, "started_at": time.time() - 600, "basetemp": "x-full"}), encoding="utf-8")
    (tmp_path / "lock.slot2").write_text(json.dumps({"pid": 200, "started_at": time.time(), "basetemp": "y-full"}), encoding="utf-8")
    procs = _procs((100, 99, "python.exe", PY_PYTEST, 50), (1, 0, "bash.exe", "bash", 1), (200, 1, "python.exe", PY_PYTEST, 60))
    lines, waiting = PF.report(procs, 4242, lock)
    text = "\n".join(lines)
    assert "疑似孤兒持有者" in text and "taskkill /PID 100 /T /F" in text and "不會自動結束" in text, text
    assert waiting == [200], "等待名單含孤兒（孤兒永遠不會結束）或漏了活的持有者"


def test_preflight_never_kills_and_never_fails(monkeypatch, capsys):
    src = (PLAT / "build_preflight.py").read_text(encoding="utf-8")
    assert "subprocess.run([\"taskkill\"" not in src and "TerminateProcess" not in src and "os.kill" not in src
    monkeypatch.setattr(PF, "snapshot", lambda timeout=60: None)
    assert PF.main(["--self-pid", "1"]) == 0
    seq = iter([_procs((600, 1, "python.exe", PY_PYTEST, 5), (1, 0, "bash.exe", "b", 1)), _procs((1, 0, "bash.exe", "b", 1))])
    monkeypatch.setattr(PF, "snapshot", lambda timeout=60: next(seq))
    monkeypatch.setattr(PF.time, "sleep", lambda s: None)
    assert PF.main(["--self-pid", "4242", "--wait-minutes", "5", "--poll", "0", "--lock", "Z:\\nope\\lock"]) == 0
    assert "等 1 個 pytest 結束" in capsys.readouterr().out


# ── ⑤ 建包腳本的接線（文字比對；行為在上面各工具的題）──────────────────────────────

def _test_section():
    return PS1[PS1.index("if ($reuse) {"):PS1.index("}   # end: if ($reuse) else")]


def test_build_switches_exist_and_default_on():
    for sw in ("[switch]$NoStageReuse", "[switch]$NoFlakeRetry", "[switch]$NoPreflight", "[int]$WaitForOtherTests = 0"):
        assert sw in PS1, sw


def test_build_retries_failed_tests_before_every_red_exit():
    sec = _test_section()
    assert sec.count('Invoke-FlakyRetry "not_e2e"') == 1 and sec.count('Invoke-FlakyRetry "e2e"') == 1
    assert sec.index('Invoke-FlakyRetry "not_e2e"') < sec.index('Fail "測試未全數通過')
    assert sec.index('Invoke-FlakyRetry "e2e"') < sec.index("Release-TestExclusive"), "偶發重跑要在釋放獨佔之前（否則重跑時別人插進來加負載）"
    assert "if ($NoFlakeRetry) { return @{ Ok = $false" in PS1, "-NoFlakeRetry 沒有回到「紅就擋」"


def test_build_records_each_stage_before_leaving_red():
    sec = _test_section()
    i = sec.index('Fail "測試未全數通過')
    assert 'Record-Stage "not_e2e" $false' in sec[sec.rfind("-m pytest", 0, i):i]
    j = sec.index('Fail "e2e 未全數通過')
    assert 'Record-Stage "e2e"' in sec[sec.rfind("-m pytest", 0, j):j]


def test_build_marks_its_children_and_checks_the_registry_first():
    acq = PS1.index("\nAcquire-TestExclusive\n")
    assert PS1.index('$env:MOTRIX_PYTEST_BUILD_CHILD = "$PID"') > acq
    assert "Env:\\MOTRIX_PYTEST_BUILD_CHILD" in PS1[PS1.index("function Release-TestExclusive"):]
    kf = PS1.index("known_flakes.py\"), \"check\")")
    assert kf < PS1.index("-m pytest -q -m \"not e2e\""), "登記簿過期檢查要在跑任何測試之前"
    assert PS1.index("build_preflight.py") < acq and "$preflightTool, \"--self-pid\"" in PS1
    # 2026-09-30 合併 scope-gate：manifest.verification 統一為 {mode, scoped, stages}；分段紀錄在 stages
    assert "verification         = [ordered]@{ mode = $VerificationMode; scoped = $ScopedVerification; stages = $BuildVerification }" in PS1


def test_fail_stream_is_loaded_only_when_flake_retry_is_on():
    sec = _test_section()
    guard = sec.index("if (-not $NoFlakeRetry) {")
    assert sec.index('$fsArgs = @("-p", "fail_stream")') > guard
    assert sec.count("@fsArgs") == 2


def test_log_lines_starting_with_error_are_not_collection_errors():
    """日誌行 `ERROR    logger:file.py:200 msg` 曾被當成收集錯誤而擋掉偶發重跑（第29班建包）。"""
    out = "\n".join([
        "ERROR    helpers.email_notify:email_notify.py:200 信件類型 'backup_error'：不寄",
        "ERROR    archive:archive.py:521 備份告警信寄不出去",
        "FAILED tests/test_e2e_x.py::test_smoke - TimeoutError",
    ])
    ids, blockers = FR.failed_nodeids([], out)
    assert ids == ["tests/test_e2e_x.py::test_smoke"] and blockers == []
    _, blockers = FR.failed_nodeids([], "ERROR tests/test_bad.py - ImportError")   # 真的收集錯誤仍擋下
    assert blockers == ["收集錯誤：tests/test_bad.py"]
