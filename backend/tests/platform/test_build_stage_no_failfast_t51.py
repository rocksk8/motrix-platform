# -*- coding: utf-8 -*-
"""run-stage --no-failfast（SPEEDUP-PIPELINE-T50 步驟 1）：只關 failfast、其餘同正式指令；紅的段記 reds 清單；全綠仍可被沿用、有紅不沿用。
自造 git 小 repo＋注入的 runner（不真的跑 pytest）。"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "backend" / "tools"
if not (TOOLS / "build_test_reuse.py").is_file():
    pytest.skip("build_test_reuse.py 不在這個安裝包", allow_module_level=True)
sys.path.insert(0, str(TOOLS))
import build_test_reuse as btr  # noqa: E402

ENV1 = {"python": "3.12.0", "pip_freeze": "pytest==9", "playwright": "1.0", "browsers": ["chromium-1"], "motrix_env": {}}


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
    (r / "backend").mkdir()
    (r / "backend" / "keep.txt").write_text("k", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "c1")
    monkeypatch.setattr(btr, "current_env", lambda: dict(ENV1))
    # 正式閘門／run-stage 的子行程會帶著 MOTRIX_FAIL_STREAM_*／MOTRIX_FAILFAST*；本檔的假 runner 會讀這些並寫檔，
    # 不清掉就會讀到外層閘門的值（斷言失敗），且把假紅題 t::a 寫進外層閘門的 fail_stream
    for k in [k for k in os.environ if k.startswith(("MOTRIX_FAIL_STREAM", "MOTRIX_FAILFAST", "MOTRIX_FAILFIRST"))]:
        monkeypatch.delenv(k, raising=False)
    return r


def _runner(code, reds=(), seen=None):
    """假 runner：記下收到的環境；若有 reds，就像 fail_stream 一樣把它們寫進 MOTRIX_FAIL_STREAM_DIR。"""
    def run(cmd, cwd, env):
        if seen is not None:
            seen.update(env)
        d = env.get("MOTRIX_FAIL_STREAM_DIR")
        if d and reds:
            Path(d).mkdir(parents=True, exist_ok=True)
            lines = [json.dumps({"type": "fail", "nodeid": n, "seq": i}) for i, n in enumerate(reds)]
            lines += [json.dumps({"type": "fail", "nodeid": reds[0]}), json.dumps({"type": "summary"}), "not json"]
            (Path(d) / "run.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return code
    return run


def test_default_run_stage_is_unchanged_failfast_on_no_reds_field(repo, tmp_path):
    rec, seen = tmp_path / "rec.jsonl", {}
    rc, wrote, why = btr.run_stage(repo, "not_e2e", rec, runner=_runner(1, ["t::a"], seen), note=lambda *_: None)
    assert rc == 1 and wrote and seen["MOTRIX_FAILFAST"] == "1" and seen["MOTRIX_FAIL_STREAM_DIR"].endswith("-failstream")
    line = json.loads(rec.read_text(encoding="utf-8").splitlines()[-1])
    assert "reds" not in line["stages"]["not_e2e"] and "failfast" not in line["stages"]["not_e2e"], "原行為：不多記欄位"
    assert "t::a" in why and "failfast 提早停" in why and "-failstream" in why, "failfast 停下也要印出紅題與明細位置：%s" % why


def test_no_failfast_turns_only_failfast_off_and_lists_every_red_once(repo, tmp_path):
    rec, seen = tmp_path / "rec.jsonl", {}
    rc, wrote, why = btr.run_stage(repo, "not_e2e", rec, runner=_runner(1, ["t::a", "t::b", "t::c"], seen), note=lambda *_: None, no_failfast=True)
    assert rc == 1 and wrote
    assert seen["MOTRIX_FAILFAST"] == "0" and seen["MOTRIX_FAILFIRST"] == "1" and seen["MOTRIX_FAIL_STREAM_STAGE"] == "not_e2e", "其餘開關與正式指令相同"
    e = json.loads(rec.read_text(encoding="utf-8").splitlines()[-1])["stages"]["not_e2e"]
    assert e["green"] is False and e["reds"] == ["t::a", "t::b", "t::c"] and e["failfast"] is False, e
    assert "t::a" in why and "3 題" in why and "全部列出" in why


def test_red_no_failfast_stage_is_not_reusable_green_one_is(repo, tmp_path):
    rec = tmp_path / "rec.jsonl"
    btr.run_stage(repo, "not_e2e", rec, runner=_runner(1, ["t::a"]), note=lambda *_: None, no_failfast=True)
    fp = btr.fingerprint(repo)
    records = [json.loads(l) for l in rec.read_text(encoding="utf-8").splitlines()]
    assert btr.find_reusable_stage(records, fp, "not_e2e", datetime.now()) is None, "紅的段不沿用"
    btr.run_stage(repo, "not_e2e", rec, runner=_runner(0), note=lambda *_: None, no_failfast=True)       # 同一份 tree 再跑一次，這次全綠
    records = [json.loads(l) for l in rec.read_text(encoding="utf-8").splitlines()]
    got = btr.find_reusable_stage(records, fp, "not_e2e", datetime.now())
    assert got and got["green"] is True, "無 failfast 的全綠與有 failfast 的全綠同一份證據 ⇒ 可沿用"


def test_collect_reds_reads_only_fail_records_and_dedups(tmp_path):
    d = tmp_path / "fs"
    d.mkdir()
    (d / "x.jsonl").write_text("\n".join([json.dumps({"type": "fail", "nodeid": "a"}), json.dumps({"type": "node_down", "nodeid": "b"}),
                                           json.dumps({"type": "aborted", "nodeid": "c"}), json.dumps({"type": "fail", "nodeid": "a"}), "{bad"]), encoding="utf-8")
    assert btr.collect_reds(d) == ["a", "b"]
    assert btr.collect_reds(tmp_path / "nope") == []
    assert btr.collect_reds(d, limit=1) == ["a"]


def test_cli_flag_is_wired():
    src = (TOOLS / "build_test_reuse.py").read_text(encoding="utf-8")
    assert '"--no-failfast"' in src and "no_failfast=a.no_failfast" in src
