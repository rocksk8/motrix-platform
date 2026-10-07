# -*- coding: utf-8 -*-
"""全閘門優化 第 45 班 O1（切片＋fail-fast）／O4（偶發分流）／O6（worksteal）的守門與反向控制。

不跑真的 pytest 全量：run_pytest 換成假的，驗「順序、環境、不漏守門、紅了就停、政策不放寬」。
（slice0 ∪ rest ＝ 全部題 的真實 nodeid 集合比對：`python tools/platform/gate_slices.py --check`，要收集全庫，列車／全閘門前跑。）
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))


def _load(name):
    spec = importlib.util.spec_from_file_location("_gs_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MT = _load("modtest")
GS = _load("gate_slices")
PT = _load("pre_train_check")

OLD_GUARDS = [  # 第 45 班之前 pre_train_check.GUARDS 的 10 項（全部必須還在，不可因搬進 json 而少）
    "tests/test_spec_coverage_2026_09_21.py", "tests/test_alpine_double_init_2026_09_23.py",
    "tests/test_company_setup_output_points_2026_09_28.py", "tests/test_system_audit_2026_09_14.py",
    "tests/test_e2e_font_zoom_fits_viewport_2026_09_24.py::test_fz_no_raw_vh_is_left_in_the_frontend",
    "modules/*/tests/test_approval_providers*.py", "tests/test_page_shell_scripts_2026_09_30.py",
    "tests/test_module_keys_consistency_2026_09_13.py", "tests/test_no_credentials_in_query_2026_09_22.py",
    "tests/test_wording_guards_2026_09_23.py"]
SUMMARY = "== 5 passed in 1.0s =="


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (MT.FULL_ENV, MT.PARTIAL_ENV, MT.E2E_ENV, "MOTRIX_GATE_SLICES", "MOTRIX_GATE_DIST", "MOTRIX_FULL_FLAKY_RETRY",
              "MOTRIX_FAILFAST", "MOTRIX_FAILFAST_N", "MOTRIX_GATE_WORKERS", "MOTRIX_FAILFAST_QUIET_MIN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(MT, "tree_state", lambda repo=None: ("a" * 40, ""))
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: Path("x"))
    monkeypatch.setattr(MT, "dist_args", lambda: ["--dist", "worksteal"])
    monkeypatch.setattr(MT, "record_for_build", lambda *a, **k: (False, "test"))


def _run(monkeypatch, codes_by_window, capture):
    """假 run_pytest：依 window 後綴回 exit code；capture 收 (window, targets, args, env_extra)。"""
    def fake(targets, args, window, full, collect_only=False, env_extra=None):
        capture.append((window, list(targets), list(args), dict(env_extra or {})))
        return codes_by_window.get(window, 0), SUMMARY
    monkeypatch.setattr(MT, "run_pytest", fake)
    return MT.run_full([], types.SimpleNamespace(workers=4, e2e_workers=2, window="w"))


# ── O1：清單單一來源 ─────────────────────────────────────────────────────────────

def test_slices_file_loads_and_every_slice0_path_resolves():
    data = GS.load()
    assert data is not None
    targets, missing = GS.expand(data, REPO / "backend")
    assert missing == [], "slice0 的守門被改名或刪掉（請同步 gate_slices.json）：%s" % missing
    assert "tests/platform" in targets


def test_pre_train_guards_and_slice0_are_one_list_and_keep_the_old_ten():
    """不放寬：舊 10 項守門一項不少；pre_train_check 與全閘門 slice0 讀同一份（兩邊不會悄悄分岔）。"""
    paths = [p for _, p in PT.GUARDS]
    for old in OLD_GUARDS:
        assert old in paths, "守門被拿掉了：" + old
    assert PT.GUARDS == GS.guards()
    assert "tests/platform" not in paths                      # tests/platform 另外整個跑，不重複列在 GUARDS


def test_slice0_covers_the_ten_reds_of_train43_round1():
    """第 43 班第 1 輪 10 個整合紅都是靜態／產生檔守門：它們所在的檔必須在 slice0。"""
    paths = " ".join(p["path"] for p in GS.load()["slice0"]["paths"])
    for need in ("tests/platform",                           # dep_graph／test_map／UNIT-INDEX 是否最新、module_keys…
                 "test_ac1_write_actions", "test_cm12_p3_prep", "test_alpine_double_init", "test_begin_only_via_begin_write",
                 "test_module_keys_consistency"):
        assert need in paths, need


def test_unreadable_slices_file_gives_none_not_an_empty_gate(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text("{not json", encoding="utf-8")
    assert GS.load(bad) is None
    bad.write_text('{"slice0": {"paths": []}}', encoding="utf-8")
    assert GS.load(bad) is None


def test_rest_args_ignore_files_but_only_deselect_node_ids():
    assert GS.rest_args(["tests/platform", "tests/a.py", "tests/b.py::test_x"]) == [
        "--ignore=tests/platform", "--ignore=tests/a.py", "--deselect=tests/b.py::test_x"]


def test_judge_sets_catches_lost_extra_and_overlapping_tests():
    assert GS.judge_sets({"a", "b", "c"}, {"a"}, {"b", "c"})[0] is True
    ok, why = GS.judge_sets({"a", "b", "c"}, {"a"}, {"b"})                 # 漏 c
    assert not ok and "漏 1" in why[0]
    assert not GS.judge_sets({"a", "b"}, {"a", "b"}, {"b"})[0]              # 重疊
    assert not GS.judge_sets({"a"}, set(), {"a"})[0]                        # slice0 空＝守門沒收集到
    assert GS.judge_counts(10, 10)[0] and not GS.judge_counts(10, 9)[0] and not GS.judge_counts(None, 9)[0]
    assert GS.nodeid_sha(["b", "a"]) == GS.nodeid_sha(["a", "b", "a"])


# ── O1：run_full 的順序、環境、停止 ──────────────────────────────────────────────

def test_full_gate_runs_slice0_then_rest_then_e2e_with_failfast_on(monkeypatch):
    cap = []
    assert _run(monkeypatch, {}, cap) == 0
    assert [c[0] for c in cap] == ["ws0", "w", "we2e"]
    s0, rest, e2e = cap
    assert s0[1] == GS.expand()[0] and rest[1] == MT.TEST_ROOTS
    assert all(c[3].get("MOTRIX_FAILFAST") == "1" and c[3].get("MOTRIX_FAILFIRST") == "1" for c in cap)
    assert all("-p" in c[2] and "failfast" in c[2] for c in cap)
    assert "not e2e" in s0[2] and "not e2e" in rest[2] and "e2e" in e2e[2]
    # 不漏：slice0 的每個目標在第二片都被排除（檔 ⇒ --ignore，帶 nodeid ⇒ --deselect），沒有多排別的
    ex = [a for a in rest[2] if a.startswith(("--ignore=", "--deselect="))]
    assert ex == GS.rest_args(s0[1])


def test_red_slice0_stops_everything_and_is_not_green(monkeypatch):
    """反向控制：第一片紅 ⇒ 不開第二片、不跑 e2e、結果不是 ok、exit≠0（不能把「沒跑」當綠）。"""
    cap, written = [], []
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: written.append(dict(r)) or Path("x"))
    rc = _run(monkeypatch, {"ws0": 1}, cap)
    assert [c[0] for c in cap] == ["ws0"]
    assert rc != 0 and written[-1]["ok"] is False and written[-1]["slice_stopped"] == "slice0"


def test_red_rest_still_runs_e2e_like_before_and_is_red(monkeypatch):
    cap = []
    rc = _run(monkeypatch, {"w": 1}, cap)
    assert [c[0] for c in cap] == ["ws0", "w", "we2e"] and rc != 0


def test_counts_of_both_slices_are_added(monkeypatch):
    written = []
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: written.append(dict(r)) or Path("x"))
    _run(monkeypatch, {}, [])
    assert written[-1]["passed"] == 10 and written[-1]["ok"] is True       # 5＋5


def test_slices_off_goes_back_to_one_main_stage(monkeypatch):
    monkeypatch.setenv("MOTRIX_GATE_SLICES", "0")
    cap = []
    assert _run(monkeypatch, {}, cap) == 0
    assert [c[0] for c in cap] == ["w", "we2e"]
    assert not any(a.startswith("--ignore=") for a in cap[0][2])


def test_missing_slice0_file_does_not_silently_drop_a_guard(monkeypatch, capsys):
    """slice0 的檔被改名 ⇒ 不切片、全跑（守門仍都在第二段）並說出來；不是少跑。"""
    monkeypatch.setattr(GS, "expand", lambda data=None, backend=None: (["tests/platform"], ["某守門（tests/x.py）"]))
    monkeypatch.setitem(sys.modules, "gate_slices", GS)
    cap = []
    assert _run(monkeypatch, {}, cap) == 0
    assert [c[0] for c in cap] == ["w", "we2e"] and cap[0][1] == MT.TEST_ROOTS
    assert "找不到" in capsys.readouterr().out


def test_user_set_env_wins_over_gate_defaults(monkeypatch):
    monkeypatch.setenv("MOTRIX_FAILFAST", "0")
    monkeypatch.setenv("MOTRIX_FAILFAST_N", "3")
    cap = []
    _run(monkeypatch, {}, cap)
    assert cap[0][3]["MOTRIX_FAILFAST"] == "0" and cap[0][3]["MOTRIX_FAILFAST_N"] == "3"


def test_evidence_windows_cover_both_slices(monkeypatch):
    """沿用紀錄的證據要涵蓋兩片：main 的 windows 是 [slice0, 其餘]。"""
    seen = {}
    monkeypatch.setattr(MT, "stream_evidence", lambda run, windows, stream_dir=None: seen.update(windows) or {})
    _run(monkeypatch, {}, [])
    assert seen["main"] == ["ws0", "w"] and seen["e2e"] == "we2e"


def test_stream_evidence_accepts_a_list_of_windows(tmp_path):
    import json
    (tmp_path / "R.jsonl").write_text("\n".join(json.dumps({"type": "summary", "stage": s, "exitstatus": x})
                                                for s, x in (("ws0", 0), ("w", 1), ("we2e", 0))), encoding="utf-8")
    got = MT.stream_evidence("R", {"main": ["ws0", "w"], "e2e": "we2e"}, stream_dir=tmp_path)
    assert got == {"main": [0, 1], "e2e": [0]}


# ── O6：尾端平衡 ────────────────────────────────────────────────────────────────

def test_worksteal_is_in_every_stage_args(monkeypatch):
    cap = []
    _run(monkeypatch, {}, cap)
    assert all(c[2][c[2].index("--dist") + 1] == "worksteal" for c in cap)


def test_dist_args_falls_back_quietly_when_off_or_unsupported(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("MOTRIX_GATE_DIST", "load")
    assert MT.dist_args() == []
    monkeypatch.setenv("MOTRIX_GATE_DIST", "worksteal")
    monkeypatch.setattr(MT.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="3.1.0", returncode=0))
    assert MT.dist_args() == []                                    # 3.2 以前不支援
    monkeypatch.setattr(MT.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="3.8.0", returncode=0))
    assert MT.dist_args() == ["--dist", "worksteal"]
    monkeypatch.setattr(MT.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert MT.dist_args() == []


# ── O4：偶發分流（政策不放寬）────────────────────────────────────────────────────

def _fake_retry(monkeypatch, rc, res):
    import json
    import flaky_retry

    def main(argv):
        Path(argv[argv.index("--result-out") + 1]).write_text(json.dumps(res), encoding="utf-8")
        return rc
    monkeypatch.setattr(flaky_retry, "main", main)
    monkeypatch.setattr(MT, "_FAIL_STREAM_RUN", "RUN")


def test_unregistered_flake_stays_red_and_is_diagnosed(monkeypatch, capsys):
    _fake_retry(monkeypatch, 1, {"ok": False, "flaky_retried": [], "results": [{"nodeid": "t.py::a", "passed": True, "attempts": [0]}]})
    result = {}
    assert MT.flaky_gate(1, "", "w", result) == 1                              # 未登記 ⇒ 仍擋
    assert "flaky_retried" not in result
    assert "疑似負載偶發" in capsys.readouterr().out


def test_registered_flake_passes_and_is_recorded(monkeypatch):
    _fake_retry(monkeypatch, 0, {"ok": True, "flaky_retried": [{"nodeid": "t.py::a"}], "results": [{"nodeid": "t.py::a", "passed": True}]})
    result = {}
    assert MT.flaky_gate(1, "", "w", result) == 0 and result["flaky_retried"] == ["t.py::a"]


def test_real_red_is_reported_as_real_red(monkeypatch, capsys):
    _fake_retry(monkeypatch, 1, {"ok": False, "flaky_retried": [], "results": [{"nodeid": "t.py::a", "passed": False}]})
    assert MT.flaky_gate(1, "", "w", {}) == 1
    assert "真紅" in capsys.readouterr().out


@pytest.mark.parametrize("code", [0, 2, 3, 5])
def test_only_exit_1_is_retried(monkeypatch, code):
    import flaky_retry
    monkeypatch.setattr(MT, "_FAIL_STREAM_RUN", "RUN")
    monkeypatch.setattr(flaky_retry, "main", lambda argv: pytest.fail("不該重跑"))
    assert MT.flaky_gate(code, "", "w", {}) == code


def test_retry_switch_off_and_tool_errors_never_turn_red_into_green(monkeypatch):
    import flaky_retry
    monkeypatch.setattr(MT, "_FAIL_STREAM_RUN", "RUN")
    monkeypatch.setattr(flaky_retry, "main", lambda argv: (_ for _ in ()).throw(RuntimeError("boom")))
    assert MT.flaky_gate(1, "", "w", {}) == 1                                  # 工具出錯 ⇒ 照原碼擋
    monkeypatch.setenv("MOTRIX_FULL_FLAKY_RETRY", "0")
    monkeypatch.setattr(flaky_retry, "main", lambda argv: pytest.fail("開關關了不該重跑"))
    assert MT.flaky_gate(1, "", "w", {}) == 1


def test_run_full_uses_the_flaky_verdict_per_stage(monkeypatch):
    """整合：e2e 段紅但已登記偶發 ⇒ 該段記 0、flaky_retried 寫進結果；未登記 ⇒ 結果仍紅。"""
    written = []
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: written.append(dict(r)) or Path("x"))
    monkeypatch.setattr(MT, "flaky_gate", lambda code, out, window, result: (result.setdefault("flaky_retried", []).append("t::x") or 0) if window == "we2e" and code else code)
    _run(monkeypatch, {"we2e": 1}, [])
    assert written[-1]["ok"] is True and written[-1]["flaky_retried"] == ["t::x"]


# ── O6：LPT（慢檔先派）只改順序 ─────────────────────────────────────────────────

FF = _load("failfast")


class _It:
    def __init__(self, nodeid):
        self.nodeid = nodeid


def test_lpt_puts_slow_files_first_within_a_group_keeps_in_file_order_and_the_set():
    items = [_It(n) for n in ("tests/a.py::t1", "tests/b.py::t1", "tests/b.py::t2", "tests/c.py::t1", "tests/platform/p.py::t1")]
    before = sorted(i.nodeid for i in items)
    prio = {"ids": [], "files": [], "secs": {"tests/a.py": 1, "tests/b.py": 50, "tests/c.py": 10, "tests/platform/p.py": 5}}
    assert FF.reorder(items, prio) is True
    got = [i.nodeid for i in items]
    assert got == ["tests/platform/p.py::t1", "tests/b.py::t1", "tests/b.py::t2", "tests/c.py::t1", "tests/a.py::t1"]   # 守門群組仍先；其後慢→快；同檔原序
    assert sorted(got) == before                                                      # 題集合不變


def test_lpt_off_or_no_data_keeps_the_original_order():
    names = ["tests/a.py::t1", "tests/b.py::t1", "tests/c.py::t1"]
    items = [_It(n) for n in names]
    FF.reorder(items, {"ids": [], "files": [], "secs": {}})
    assert [i.nodeid for i in items] == names


def test_a_red_or_changed_file_still_beats_a_slow_file():
    items = [_It(n) for n in ("tests/slow.py::t", "tests/changed.py::t", "tests/red.py::t")]
    FF.reorder(items, {"ids": ["tests/red.py::t"], "files": ["tests/changed.py"], "secs": {"tests/slow.py": 999}})
    assert [i.nodeid for i in items] == ["tests/red.py::t", "tests/changed.py::t", "tests/slow.py::t"]


def test_seed_seconds_files_exist_and_unreadable_data_is_empty(tmp_path):
    secs = FF.file_seconds(local=tmp_path / "none.json")
    assert secs and all((REPO / "backend" / k).is_file() for k in secs), "種子裡的檔被改名了：請更新 gate_file_seconds.json"
    (tmp_path / "bad.json").write_text("{x", encoding="utf-8")
    assert FF.file_seconds(seed=tmp_path / "bad.json", local=tmp_path / "bad.json") == {}


def test_merge_seconds_smooths_and_keeps_unseen_files():
    assert FF.merge_seconds({"a": 100.0, "b": 7.0}, {"a": 0.0, "c": 3.0}) == {"a": 50.0, "b": 7.0, "c": 3.0}


def test_worker_cap_env_overrides_workers(monkeypatch):
    monkeypatch.setenv("MOTRIX_GATE_WORKERS", "2")
    cap = []
    _run(monkeypatch, {}, cap)
    assert all(c[2][c[2].index("-n") + 1] == "2" for c in cap[:2])
