# -*- coding: utf-8 -*-
"""tools/platform/preflight_guards.py（T82 整合守門題組）：題組清單完整、每個檔都在、報告依守門種類分組並指出肇因合併、結束碼語意。

不跑真的 pytest 子行程（用注入的 runner）；只有 _make_runner 那題起一個 `python -c` 驗環境變數。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import preflight_guards as P  # noqa: E402

BACKEND = REPO / "backend"


def _cfg():
    return P.load_config()


def _files():
    cfg = _cfg()
    targets, fg, missing = P.expand_groups(BACKEND, cfg, None, with_e2e=True)
    return cfg, targets, fg, missing


def test_every_pattern_in_the_guard_list_resolves_to_a_file():
    """守門的對象被搬走＝悄悄少跑：題組裡每一個 pattern 都要在這棵樹找得到至少一個檔。"""
    _cfg_, targets, _fg, missing = _files()
    assert targets and not missing, "找不到守門檔（改名或刪除了？更新 tools/platform/preflight_guards.json）：%s" % missing


def test_the_list_covers_every_guard_class_named_in_the_t82_ticket():
    cfg, _t, fg, _m = _files()
    names = {Path(f).name for f in fg}
    assert fg["tests/test_e2e_no_bad_requests_on_load_2026_11_13.py"] == "e2e_goldens"
    wanted = [
        "test_module_changelog_follows_code.py",            # CHANGELOG 跟著程式
        "test_version_slots.py", "test_version_manifest_2026_09_22.py", "test_version_manifest_no_future_stamps_2026_10_07.py",
        "test_spec_coverage_2026_09_21.py", "test_page_paths_centralized.py", "test_no_direct_js_enumeration_2026_11_08.py",
        "test_route_ownership.py",                           # modules.json 歸屬
        "test_l1_interface_snapshot.py", "test_route_inventory.py", "test_response_keys_baseline.py", "test_write_golden.py",
        "test_unscoped_reads_ratchet.py", "test_u0a_sinks.py", "test_view_filter_marking_2026_09_25.py", "test_mail_registry.py",
        "test_recyclebin_guards_t53.py", "test_generated_maps.py", "test_route_table_golden_2026_10_05.py",
        "test_apply_plan_2026_09_28.py",                     # AH-O7 套用腳本版本
        "test_form_version_bumped_2026_09_24.py", "test_expense_wording_2026_10_06.py", "test_module_no_admin_bypass_2026_09_14.py",
        "test_quote_alt_write_paths_2026_10_13.py",
        # 17788142e：外網登入強化後超管登入全紅的 8 支（7 支非 e2e 在 superadmin_login 組，e2e 那支在 --with-e2e-goldens）
        "test_backup_retention_visible_2026_09_22.py", "test_geocode_miss_message_2026_09_23.py", "test_geocode_shortcircuit_2026_09_22.py",
        "test_google_quota_2026_09_22.py", "test_location_fallback_rules_2026_09_23.py", "test_location_identity_roundtrip_2026_09_23.py",
        "test_quote_location_2026_09_22.py", "test_e2e_no_bad_requests_on_load_2026_11_13.py",
    ]
    assert [w for w in wanted if w not in names] == []
    # T76／T81 整合閘門 14 輪實際紅過、屬守門類（不是功能題）的檔，全部要在題組裡
    red_in_gate_logs = ["test_prod_status_snapshot_2026_09_30.py", "test_response_keys_baseline.py", "test_e2e_font_zoom_fits_viewport_2026_09_24.py",
                        "test_quote_alt_write_paths_2026_10_13.py", "test_spec_coverage_2026_09_21.py", "test_module_changelog_follows_code.py",
                        "test_form_version_bumped_2026_09_24.py", "test_version_manifest_no_future_stamps_2026_10_07.py", "test_expense_wording_2026_10_06.py",
                        "test_route_table_golden_2026_10_05.py", "test_recycle_adapter_t53.py", "test_module_no_admin_bypass_2026_09_14.py"]
    assert [w for w in red_in_gate_logs if w not in names] == []
    assert any(g["id"] == "recent_interplay" and g.get("required") is False for g in cfg["groups"]), "功能題組標成選用（找不到不擋）"


def test_group_ids_are_unique_and_each_group_has_a_fix_and_watch():
    cfg = _cfg()
    ids = [g["id"] for g in cfg["groups"]]
    assert len(ids) == len(set(ids))
    for g in cfg["groups"]:
        assert g.get("fix") and g.get("watch"), "每組要有出紅標準修法與 watch：%s" % g["id"]


def test_load_config_rejects_duplicate_ids_and_empty_groups(tmp_path):
    bad = tmp_path / "c.json"
    bad.write_text(json.dumps({"groups": [{"id": "a", "label": "x", "paths": ["p"]}, {"id": "a", "label": "y", "paths": ["q"]}], "e2e_goldens": {"paths": []}}), encoding="utf-8")
    with pytest.raises(ValueError):
        P.load_config(bad)
    bad.write_text(json.dumps({"groups": [{"id": "a", "label": "x", "paths": []}], "e2e_goldens": {"paths": []}}), encoding="utf-8")
    with pytest.raises(ValueError):
        P.load_config(bad)


def test_expand_groups_only_filter_missing_required_and_nodeid_passthrough(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    cfg = {"groups": [{"id": "a", "label": "A", "paths": ["tests/test_a.py::test_x"]},
                      {"id": "b", "label": "B", "paths": ["tests/test_gone.py"]},
                      {"id": "c", "label": "C", "paths": ["tests/test_none*.py"], "required": False}], "e2e_goldens": {"paths": []}}
    targets, fg, missing = P.expand_groups(tmp_path, cfg)
    assert targets == ["tests/test_a.py::test_x"] and fg == {"tests/test_a.py": "a"}
    assert missing == [("b", "tests/test_gone.py", True), ("c", "tests/test_none*.py", False)]
    t2, _fg2, m2 = P.expand_groups(tmp_path, cfg, only={"a"})
    assert t2 == targets and m2 == []


def test_group_failures_by_kind_and_unknown_goes_to_other():
    fg = {"tests/test_a.py": "ga", "modules/case/tests/test_b.py": "gb"}
    fails = [{"nodeid": "tests/test_a.py::t1", "kind": "FAILED", "msg": ""}, {"nodeid": "backend/modules/case/tests/test_b.py::t2", "kind": "FAILED", "msg": ""},
             {"nodeid": "tests/test_zzz.py::t3", "kind": "ERROR", "msg": ""}, {"nodeid": "tests\\test_a.py::t4", "kind": "FAILED", "msg": ""}]
    g = P.group_failures(fails, fg)
    assert [f["nodeid"] for f in g["ga"]] == ["tests/test_a.py::t1", "tests\\test_a.py::t4"] and len(g["gb"]) == 1 and len(g["other"]) == 1


MERGES = [
    {"sha": "a" * 40, "subject": "merge: 無關分支", "files": ["frontend/static/x.js"]},
    {"sha": "b" * 40, "subject": "merge: 動到同一支測試", "files": ["backend/tests/test_version_manifest_2026_09_22.py", "docs/x.md"]},
    {"sha": "c" * 40, "subject": "merge: 動到同模組", "files": ["backend/modules/case/api/q.py"]},
    {"sha": "d" * 40, "subject": "merge: 只動 watch", "files": ["backend/version_manifest.json"]},
]


def test_attribute_ranks_test_file_over_owner_over_watch_and_returns_nothing_when_unrelated():
    got = P.attribute(["tests/test_version_manifest_2026_09_22.py::t"], ["backend/version_manifest.json"], MERGES)
    assert [g["sha"] for g in got] == ["bbbbbbbb", "dddddddd"], "動到那支測試 3 分 > 只動 watch 1 分；無關的不列"
    assert got[0]["files"] == ["backend/tests/test_version_manifest_2026_09_22.py"]
    got2 = P.attribute(["modules/case/tests/test_q.py::t"], [], MERGES)
    assert [g["sha"] for g in got2] == ["cccccccc"], "模組歸屬 +2"
    assert P.attribute(["tests/test_zzz.py::t"], ["docs/none/**"], MERGES) == [], "都不沾邊 ⇒ 空（不亂指）"
    assert len(P.attribute(["tests/test_version_manifest_2026_09_22.py::t"], ["backend/**", "frontend/**", "docs/**"], MERGES, top=2)) == 2


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a], capture_output=True, text=True, check=True).stdout


def test_recent_merges_lists_first_parent_merges_with_files_against_first_parent(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("1", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    for name, fn in (("fx", "x.txt"), ("fy", "dir/y.txt")):
        _git(r, "checkout", "-qb", name)
        (r / "dir").mkdir(exist_ok=True)
        (r / fn).write_text(name, encoding="utf-8")
        _git(r, "add", "-A")
        _git(r, "commit", "-qm", "work " + name)
        _git(r, "checkout", "-q", "main")
        _git(r, "merge", "-q", "--no-ff", "-m", "merge: " + name, name)
    got = P.recent_merges(r, None, 10)
    assert [m["subject"] for m in got] == ["merge: fy", "merge: fx"], "新的在前"
    assert got[0]["files"] == ["dir/y.txt"] and got[1]["files"] == ["x.txt"], "檔＝相對第一親的變動，不含另一支的"
    assert [m["subject"] for m in P.recent_merges(r, "HEAD~1", 10)] == ["merge: fy"], "since 縮小範圍"
    assert len(P.recent_merges(r, "no-such-rev", 1)) == 1, "since 不存在 ⇒ 退回最近 n 個，不報錯"


def _cfg_two(tmp_path):
    (tmp_path / "backend" / "tests").mkdir(parents=True, exist_ok=True)
    for n in ("test_a.py", "test_b.py"):
        (tmp_path / "backend" / "tests" / n).write_text("def test_x():\n    pass\n", encoding="utf-8")
    return {"groups": [{"id": "ga", "label": "A 類守門", "paths": ["tests/test_a.py"], "watch": ["backend/a/**"], "fix": "修 A"},
                       {"id": "gb", "label": "B 類守門", "paths": ["tests/test_b.py"], "watch": ["backend/b/**"], "fix": "修 B"}], "e2e_goldens": {"paths": []}}


def _junit(**per_class):
    """per_class: classname=(passed, skipped, failed) ⇒ junit xml 文字（類別名裡的 __ 代表 .）。"""
    cases = []
    for cn, (p_, s_, f_) in per_class.items():
        cn = cn.replace("__", ".")
        cases += ['<testcase classname="%s" name="t%d"/>' % (cn, i) for i in range(p_)]
        cases += ['<testcase classname="%s" name="s%d"><skipped message="x"/></testcase>' % (cn, i) for i in range(s_)]
        cases += ['<testcase classname="%s" name="f%d"><failure message="x"/></testcase>' % (cn, i) for i in range(f_)]
    return "<testsuites><testsuite>%s</testsuite></testsuites>" % "".join(cases)


GREEN_XML = _junit(tests__test_a=(2, 0, 0), tests__test_b=(2, 0, 0))
KW = dict(window="h7", base_exists=lambda r: True, run_static=False)


def _pf(tmp_path, out, rc, xml=GREEN_XML, **kw):
    cfg = _cfg_two(tmp_path)
    merges = [{"sha": "e" * 40, "subject": "merge: 動到 A 的合併", "files": ["backend/tests/test_a.py"]}]
    return P.preflight(tmp_path, config=cfg, merges_fn=lambda *a: merges, runner=lambda repo, ts, marker: (rc, out, 12.0, xml), **dict(KW, **kw))


def test_preflight_green_exit0_and_red_exit1_groups_by_kind_with_cause_and_fix(tmp_path):
    code, text, data = _pf(tmp_path, "....\n2 passed in 1s\n", 0)
    assert code == 0 and "題組全綠" in text and "題組綠 ≠ 閘門綠" in text
    out = "FAILED tests/test_a.py::test_x - AssertionError: no\nERROR tests/test_b.py::test_y\n1 failed, 1 error, 3 passed in 4s\n"
    code, text, data = _pf(tmp_path, out, 1, xml=_junit(tests__test_a=(1, 0, 1), tests__test_b=(1, 0, 1)))
    assert code == 1
    assert "紅 2 題，依守門種類（2 類）" in text and "■ [A 類守門] 1 紅" in text and "■ [B 類守門] 1 紅" in text
    assert "e" * 8 in text and "merge: 動到 A 的合併" in text, "A 組點名肇因合併"
    assert "修法：修 A" in text and "修法：修 B" in text
    assert "--only ga,gb" in text, "修完只重跑出紅的組"
    assert data["grouped"] == {"ga": ["tests/test_a.py::test_x"], "gb": ["tests/test_b.py::test_y"]}
    assert "最近 1 次合併裡沒有動到相關檔" in text, "B 組沒有肇因時要明說，不是空白"


def test_preflight_incomplete_is_exit3_and_never_reads_as_green(tmp_path):
    code, text, _d = _pf(tmp_path, "FAILED tests/test_a.py::test_x\n", P.INCOMPLETE_RC, xml=None)
    assert code == 3 and "未完成" in text and "不能當作綠" in text


def test_preflight_missing_required_group_file_is_exit2_even_when_the_rest_is_green(tmp_path):
    cfg = _cfg_two(tmp_path)
    cfg["groups"].append({"id": "gc", "label": "C", "paths": ["tests/test_renamed.py"], "watch": ["x"], "fix": "y"})
    code, text, _d = P.preflight(tmp_path, config=cfg, runner=lambda repo, ts, marker: (0, "2 passed in 1s\n", 1.0, GREEN_XML), **KW)
    assert code == 2 and "找不到守門檔" in text and "test_renamed.py" in text
    cfg["groups"][-1]["required"] = False
    code, text, _d = P.preflight(tmp_path, config=cfg, runner=lambda repo, ts, marker: (0, "2 passed in 1s\n", 1.0, GREEN_XML), **KW)
    assert code == 0 and "⚠ 找不到守門檔" in text, "選用組找不到：警告但不擋"


def test_preflight_unknown_only_id_and_queue_timeout(tmp_path):
    cfg = _cfg_two(tmp_path)
    code, text, _d = P.preflight(tmp_path, only=["nope"], config=cfg, **KW)
    assert code == 2 and "未知的題組 id" in text
    code, text, _d = P.preflight(tmp_path, config=cfg, runner=lambda repo, ts, marker: (75, "", 0.0, None), **KW)
    assert code == 75 and "排隊" in text


def test_preflight_only_runs_the_selected_groups(tmp_path):
    seen = []
    cfg = _cfg_two(tmp_path)
    P.preflight(tmp_path, only=["gb"], config=cfg, runner=lambda repo, ts, marker: seen.append((ts, marker)) or (0, "1 passed\n", 1.0, _junit(tests__test_b=(2, 0, 0))), **KW)
    assert seen == [(["tests/test_b.py"], "not e2e")]


def test_build_cmd_is_train_mode_non_failfast_and_uses_xdist_only_for_two_or_more_workers():
    c = P.build_cmd("py", ["tests/a.py"], 3, "bt")
    assert c[:3] == ["py", "-m", "pytest"] and "-n" in c and c[c.index("-n") + 1] == "3" and "not e2e" in c
    assert not any("failfast" in x or "-x" == x or x.startswith("--maxfail") for x in c), "不 fail-fast：要一次看到全部的紅"
    c1 = P.build_cmd("py", ["tests/a.py"], 1, "bt")
    assert "-n" not in c1 and "no:xdist" in c1


def test_make_runner_sets_train_mode_env_and_captures_output(tmp_path):
    holder = {}
    rc = P._make_runner(tmp_path, holder, None, tee=False)([sys.executable, "-c", "import os,sys;print('T=' + os.environ['MOTRIX_TRAIN']);sys.exit(4)"], {"PATH": "x"}, 0)
    assert rc == 4 and "T=1" in holder["out"], "MOTRIX_TRAIN=1 一定帶進去（不靠呼叫端的環境）"


def test_dry_run_prints_command_and_estimate_without_running(tmp_path):
    cfg = _cfg_two(tmp_path)
    code, text, _d = P.preflight(tmp_path, dry_run=True, config=cfg, runner=lambda *a: (_ for _ in ()).throw(AssertionError("dry-run 不該跑")), window="h7", base_exists=lambda r: True)
    assert code == 0 and "[dry-run] 2 組、2 個測試檔" in text and "pytest tests/test_a.py tests/test_b.py" in text


def test_queue_path_goes_through_heavy_run_with_the_given_window_and_class(tmp_path, monkeypatch):
    calls = []

    class HR:
        @staticmethod
        def run(cmd, cls, window, runner=None, max_wait=None, note=None):
            calls.append((cls, window, max_wait))
            return runner(cmd, {}, 0)
    (tmp_path / "backend").mkdir()
    rc, _out, _secs, _xml = P.run_pytest(tmp_path, ["tests/x.py"], 3, "h7", hr=HR, budget_min=None, tee=False, max_wait=30)
    assert calls == [("heavy", "h7", 30)], "-n≥2 ⇒ heavy 排隊；視窗名原樣帶進去（閘門鎖持有者靠它放行）"
    calls.clear()
    P.run_pytest(tmp_path, ["tests/x.py"], 1, "h7", hr=HR, budget_min=None, tee=False)
    assert calls[0][0] == "light", "單 worker ⇒ light 不排隊"


def test_every_group_has_a_positive_min_tests_floor():
    """題數下限：glob 縮水／守門被刪 ⇒ 收集數低於下限（實收集數 2026-11-13 量過，下限＝80%，見 json _about）。"""
    cfg = _cfg()
    assert all(int(g.get("min_tests", 0)) >= 1 for g in cfg["groups"]), [g["id"] for g in cfg["groups"] if int(g.get("min_tests", 0)) < 1]


def test_parse_junit_maps_classnames_to_groups_and_counts_outcomes():
    fg = {"tests/platform/test_x.py": "g1", "modules/case/tests/test_y.py": "g2"}
    xml = _junit(tests__platform__test_x__TestCls=(2, 1, 1), modules__case__tests__test_y=(1, 0, 0), tests__other=(5, 0, 0))
    assert P.parse_junit(xml, fg) == {"g1": {"passed": 2, "skipped": 1, "failed": 1}, "g2": {"passed": 1, "skipped": 0, "failed": 0}}, "類別名逐段退回到檔；對不上的略過"
    assert P.parse_junit("<<壞", fg) is None and P.parse_junit(None, fg) is None


def test_judge_counts_collected_zero_all_skipped_below_floor_and_missing_file_are_unchecked():
    ok = {"passed": 5, "skipped": 0, "failed": 0}
    bad, skipped = P.judge_counts({"a"}, {"a": ok}, {"a": 5})
    assert bad == [] and skipped == []
    assert "收集 0 題" in P.judge_counts({"a"}, {}, {})[0][0], "整檔被 deselect／匯入失敗 ⇒ 收集 0"
    assert "全部略過" in P.judge_counts({"a"}, {"a": {"passed": 0, "skipped": 3, "failed": 0}}, {})[0][0]
    assert "低於下限" in P.judge_counts({"a"}, {"a": ok}, {"a": 9})[0][0], "glob 縮水"
    b2, s2 = P.judge_counts({"a"}, {"a": {"passed": 4, "skipped": 2, "failed": 0}}, {})
    assert b2 == [] and "略過 2 題" in s2[0], "有略過但有過：只列出來，不擋"
    assert "沒有拿到 junit" in P.judge_counts({"a"}, None, {})[0][0]
    assert P.judge_counts({"a"}, {"a": {"passed": 0, "skipped": 0, "failed": 2}}, {})[0] == [], "全紅不是沒跑（紅會另外報）"


def test_a_whole_file_skipped_or_missing_results_never_end_green(tmp_path):
    skipped_all = _junit(tests__test_a=(0, 4, 0), tests__test_b=(2, 0, 0))
    code, text, _d = _pf(tmp_path, "4 skipped, 2 passed in 1s\n", 0, xml=skipped_all)
    assert code == 1 and "未能檢查" in text and "全部略過" in text and "題組全綠" not in text
    code, text, _d = _pf(tmp_path, "2 passed in 1s\n", 0, xml=None)
    assert code == 1 and "沒有拿到 junit" in text, "沒有結果檔＝無法證明有跑 ⇒ 不是綠"
    code, text, _d = _pf(tmp_path, "2 passed\n", 0, xml=_junit(tests__test_b=(2, 0, 0)))
    assert code == 1 and "[ga] 收集 0 題" in text, "一整組沒收集到"
    cfg_floor = _cfg_two(tmp_path)
    cfg_floor["groups"][0]["min_tests"] = 10
    code, text, _d = P.preflight(tmp_path, config=cfg_floor, runner=lambda r, t, m: (0, "4 passed\n", 1.0, GREEN_XML), **KW)
    assert code == 1 and "低於下限 10" in text
    code, text, _d = _pf(tmp_path, "4 passed in 1s\n", 0)
    assert code == 0 and "跑了多少" in text and "ga 2/0/0" in text, "綠的報告列出每組過／略過／紅"


def test_window_is_required_and_missing_base_is_an_error_not_an_empty_result(tmp_path):
    cfg = _cfg_two(tmp_path)
    code, text, _d = P.preflight(tmp_path, window=None, config=cfg, base_exists=lambda r: True)
    assert code == 2 and "--window 必填" in text
    code, text, _d = P.preflight(tmp_path, window="h7", config=cfg, base_exists=lambda r: False, base="origin/zzz")
    assert code == 2 and "--base 找不到" in text and "origin/zzz" in text
    with pytest.raises(SystemExit):
        P.main(["--list"])                                    # argparse：--window 必填，沒有預設
    r = tmp_path / "gitrepo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "f").write_text("1", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "c")
    assert P.rev_exists(r, "main") is True and P.rev_exists(r, "origin/nope") is False and P.rev_exists(r, "") is False


def test_non_expected_pytest_exit_prints_the_output_tail(tmp_path):
    code, text, _d = _pf(tmp_path, "ERROR: not found: tests/test_a.py::test_renamed\n", 4)
    assert code == 1 and "非預期的結束碼 4" in text and "test_renamed" in text


def test_watchdog_kills_a_hung_silent_run_and_reports_incomplete(tmp_path):
    """卡住沒輸出（讀 stdout 永遠阻塞）也要在預算到時被停：回 INCOMPLETE_RC。"""
    import time
    holder = {}
    t0 = time.time()
    rc = P._make_runner(tmp_path, holder, 1.5, tee=False)([sys.executable, "-c", "import time; time.sleep(60)"], {"PATH": "x"}, 0)
    assert rc == P.INCOMPLETE_RC and time.time() - t0 < 30, "沒有輸出的卡死也被 watchdog 停掉"


def test_gated_preflight_by_a_non_holder_window_waits_at_most_120s(tmp_path):
    seen = {}

    class HR:
        @staticmethod
        def read_gate():
            return {"window": "h7", "token": "t", "expires": 9e12}

        @staticmethod
        def gate_exempt(cls, window, lock, env):
            return window == lock["window"]

        @staticmethod
        def run(cmd, cls, window, runner=None, max_wait=None, note=None):
            seen["max_wait"] = max_wait
            return 75
    cfg = _cfg_two(tmp_path)
    code, _t, _d = P.preflight(tmp_path, config=cfg, hr=HR, **dict(KW, window="h9"))
    assert code == 75 and seen["max_wait"] == P.GATED_MAX_WAIT == 120, "非持有者：最多 120 秒就放棄（不靜默等到鎖過期）"
    seen.clear()
    P.preflight(tmp_path, config=cfg, hr=HR, **dict(KW, window="h7"))
    assert seen["max_wait"] is None, "持有者自己不限"
