# -*- coding: utf-8 -*-
"""建包優化 2 項 2（backend/tools/build_test_reuse.py 的 explain／run-stage）：獨立跑一段也算數、不重跑第二次，而且**不放水**。

自造 git 小 repo＋注入的 runner（不真的跑 pytest）；環境用固定 dict 注入（pip freeze 不進這裡）。反向控制：
紅的段不被沿用（同指紋較早的綠也不行）、跑到一半指紋變了不記、工作樹不乾淨不記、fail-fast 停掉的段（exit 1）記紅、指令與建包腳本逐項對照（防漂移）。
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "backend" / "tools"
if not (TOOLS / "build_test_reuse.py").is_file():
    pytest.skip("build_test_reuse.py 不在這個安裝包", allow_module_level=True)
sys.path.insert(0, str(TOOLS))
import build_test_reuse as btr  # noqa: E402

ENV1 = {"python": "3.12.0", "pip_freeze": "pytest==9", "playwright": "1.0", "browsers": ["chromium-1"], "motrix_env": {}}
ENV2 = dict(ENV1, python="3.13.1")


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@x")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("1", encoding="utf-8")
    (r / "b.txt").write_text("1", encoding="utf-8")
    (r / "backend").mkdir()
    (r / "backend" / "keep.txt").write_text("k", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "c1")
    monkeypatch.setattr(btr, "current_env", lambda: dict(ENV1))
    return r


def commit_change(repo, name="b.txt", text="2"):
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c-" + name)


def fake_runner(code, side_effect=None):
    def run(cmd, cwd, env):
        if side_effect:
            side_effect()
        return code
    return run


# ── run-stage：獨立跑也算數 ────────────────────────────────────────────────────

def test_a_green_standalone_stage_is_recorded_and_the_build_would_reuse_it(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    rc, wrote, why = btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    assert (rc, wrote) == (0, True), why
    fp = btr.fingerprint(repo)
    hit = btr.lookup_stage(rec, fp, "e2e")
    assert hit and hit["green"] is True and hit["source"] == "standalone"                 # 建包查得到 ⇒ 沿用，不再跑 e2e
    assert btr.lookup_stage(rec, fp, "not_e2e") is None                                     # 另一段不受影響（只沿用跑過的那一段）


def test_a_red_standalone_stage_is_recorded_red_and_blocks_an_earlier_green(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "not_e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    fp = btr.fingerprint(repo)
    assert btr.lookup_stage(rec, fp, "not_e2e")
    rc, wrote, _ = btr.run_stage(repo, "not_e2e", rec, runner=fake_runner(1), note=lambda *_: None)   # 同一份 tree 再跑，這次紅（含 fail-fast 提前停止＝exit 1）
    assert (rc, wrote) == (1, True)
    assert btr.lookup_stage(rec, fp, "not_e2e") is None, "同指紋最新一筆是紅 ⇒ 較早的綠不可再被沿用（與建包同一條規則）"


def test_nothing_is_recorded_when_the_tree_changes_during_the_run_or_is_dirty_at_start(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    rc, wrote, why = btr.run_stage(repo, "e2e", rec, runner=fake_runner(0, lambda: commit_change(repo)), note=lambda *_: None)
    assert (rc, wrote) == (0, False) and "指紋變了" in why and not rec.exists()           # 跑的是舊 tree，不可以把綠記到新 tree 上
    (repo / "untracked.txt").write_text("x", encoding="utf-8")
    rc, wrote, why = btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    assert (rc, wrote) == (0, False) and "不乾淨" in why and not rec.exists()


def test_environment_change_between_runs_makes_the_recorded_green_unusable(repo, tmp_path, monkeypatch):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    fp1 = btr.fingerprint(repo)
    monkeypatch.setattr(btr, "current_env", lambda: dict(ENV2))
    fp2 = btr.fingerprint(repo)
    assert fp1 != fp2 and btr.lookup_stage(rec, fp1, "e2e") and btr.lookup_stage(rec, fp2, "e2e") is None


def test_the_reuse_window_still_applies_to_standalone_records(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    fp = btr.fingerprint(repo)
    late = datetime.now() + timedelta(hours=btr.MAX_HOURS + 1)
    assert btr.lookup_stage(rec, fp, "e2e", now=late) is None                               # 超過 12 小時不沿用（沿用規則沒有被放寬）


# ── explain：為什麼沒被沿用 ───────────────────────────────────────────────────

def test_explain_names_the_files_that_made_the_fingerprint_differ(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    commit_change(repo, "b.txt", "2")
    res = btr.explain(rec, repo)
    assert res["dirty"] == [] and res["stages"]["e2e"]["reuse"] is False
    assert "沒有任何同指紋" in res["stages"]["e2e"]["reason"]
    row = res["rows"][-1]
    assert row["fp_match"] is False and "tree 不同" in row["why"] and "b.txt" in row["why"] and row["changed_files"] == 1, row


def test_explain_says_environment_when_the_tree_is_identical(repo, tmp_path, monkeypatch):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    btr.remember_parts(rec, btr.fingerprint(repo), btr.components(repo))                    # 之前算指紋時留下的旁表
    monkeypatch.setattr(btr, "current_env", lambda: dict(ENV2))                             # 同一份 tree，換了直譯器
    res = btr.explain(rec, repo)
    row = res["rows"][-1]
    assert "tree 相同" in row["why"] and row["env_diff"] == ["python"], row


def test_explain_reports_why_a_matching_record_is_not_reusable_and_when_it_is(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(1), note=lambda *_: None)
    assert "紅" in btr.explain(rec, repo)["stages"]["e2e"]["reason"]
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(0), note=lambda *_: None)
    ok = btr.explain(rec, repo)["stages"]["e2e"]
    assert ok["reuse"] is True and "standalone" in ok["reason"]
    assert "可沿用" in btr.render_explain(btr.explain(rec, repo))


def test_explain_on_a_dirty_tree_lists_the_dirty_files(repo, tmp_path):
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    res = btr.explain(tmp_path / "none.jsonl", repo)
    assert res["fingerprint"] is None and any("stray.txt" in d for d in res["dirty"])
    assert all(not v["reuse"] for v in res["stages"].values())


# ── 防漂移：指令與建包腳本逐項對照 ─────────────────────────────────────────────

def test_stage_commands_match_the_build_script_text():
    ps1 = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    lines = {"not_e2e": next(l for l in ps1.splitlines() if '-m "not e2e"' in l and "pytest" in l),
             "e2e": next(l for l in ps1.splitlines() if '-m "e2e"' in l and "pytest" in l)}
    for stage, args in btr.STAGE_PYTEST.items():
        for a in args:
            needle = ('"%s"' % a) if " " in a else a
            assert needle in lines[stage], "run-stage 的參數 %r 不在建包腳本的 %s 指令裡（兩邊漂移了）：%s" % (a, stage, lines[stage])
    assert btr.default_workers("e2e") == 4 and 2 <= btr.default_workers("not_e2e") <= 4
    assert "$e2eWorkers = 4" in ps1 and "[Math]::Min($physCores, 4)" in ps1


def test_reverse_control_a_mutated_recorder_that_writes_red_as_green_is_caught(repo, tmp_path, monkeypatch):
    real = btr.stage_entry
    monkeypatch.setattr(btr, "stage_entry", lambda green, *a, **k: real(True, *a, **k))      # 突變：紅也記成綠
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "e2e", rec, runner=fake_runner(1), note=lambda *_: None)
    fp = btr.fingerprint(repo)
    assert btr.lookup_stage(rec, fp, "e2e"), "（這個斷言在突變下成立＝突變存在）"
    # 守門題 test_a_red_standalone_stage_... 在同樣的突變下會紅：下面直接驗證那條斷言的反面
    monkeypatch.setattr(btr, "stage_entry", real)
    rec2 = tmp_path / "rec2.jsonl"
    btr.run_stage(repo, "e2e", rec2, runner=fake_runner(1), note=lambda *_: None)
    assert btr.lookup_stage(rec2, btr.fingerprint(repo), "e2e") is None


def test_cli_explain_runs_and_prints_utf8(repo, tmp_path):
    r = subprocess.run([sys.executable, str(TOOLS / "build_test_reuse.py"), "explain", "--records", str(tmp_path / "x.jsonl"), "--last", "3"],
                       cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0 and ("指紋" in r.stdout or "不沿用" in r.stdout), r.stdout[-300:] + r.stderr[-300:]
