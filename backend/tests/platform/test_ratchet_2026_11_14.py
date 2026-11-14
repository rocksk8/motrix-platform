# -*- coding: utf-8 -*-
"""棘輪三道檢查的單元測試（tools/platform/ratchet.py；T87 A2，h11 審查 M2）。純函式＋暫時 git repo，不碰真實倉庫。

釘住的事：基線不能「悄悄變鬆」——(i) 基線高於現場（空位）要被抓、(ii) 基線比合併基準高要被抓（含改名、新檔、總數）、(iii) 抓不到基準要明說（no_base），不能當通過。
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import ratchet as R  # noqa: E402


def test_slack_flags_baseline_numbers_above_the_tree():
    assert R.slack({"a.py": 2}, {"a.py": 2, "b.py": 1}) == [("b.py", 0, 1)]           # b 已改乾淨但基線還留著 1 個空位
    assert R.slack({"a.py": 1}, {"a.py": 2}) == [("a.py", 1, 2)]
    assert R.slack({"a.py": 2, "new.py": 1}, {"a.py": 2}) == []                          # 現場比基線多是另一道檢查（over_baseline）的事


def test_vs_base_flags_increases_new_files_and_follows_renames():
    old = {"a.py": 2, "b.py": 1}
    assert R.vs_base({"a.py": 2, "b.py": 1}, old) == []
    assert R.vs_base({"a.py": 1}, old) == []
    assert R.vs_base({"a.py": 3}, old) == [("a.py", 3, 2)]
    assert R.vs_base({"c.py": 1}, old) == [("c.py", 1, 0)], "新檔的基準是 0"
    assert R.vs_base({"renamed.py": 1}, old, {"renamed.py": "b.py"}) == [], "改名後同數字＝沒有變鬆"
    assert R.vs_base({"renamed.py": 2}, old, {"renamed.py": "b.py"}) == [("renamed.py", 2, 1)], "改名不能順便多加命中"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def _repo(tmp_path, files):
    _git(tmp_path, "init", "-q", "-b", "master")
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")


def test_check_against_base_uses_the_merge_base_baseline_and_flags_a_loosened_one(tmp_path):
    rel = "base.json"
    _repo(tmp_path, {rel: json.dumps({"total": 3, "files": {"a.py": 2, "b.py": 1}})})
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    same = {"files": {"a.py": 2, "b.py": 1}}
    assert R.check_against_base(rel, same, tmp_path)["status"] == "ok"
    swap = {"files": {"a.py": 3, "b.py": 0}}                                              # 這個加、那個減，總數不變
    res = R.check_against_base(rel, swap, tmp_path)
    assert res["status"] == "violation" and ("a.py", 3, 2) in res["violations"]
    more = {"files": {"a.py": 2, "b.py": 1, "c.py": 1}}
    res = R.check_against_base(rel, more, tmp_path)
    assert res["status"] == "violation" and any(v[0] == "<總數>" for v in res["violations"])
    hat = {"files": {"a.py": 2, "b.py": 1}, "hatches": {"a.py": 1}}
    assert R.check_against_base(rel, hat, tmp_path)["status"] == "violation", "逃生口使用數也只准減少"


def test_check_against_base_reports_no_base_instead_of_passing(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "trunk")                                           # 沒有 master／main，也沒有 origin
    (tmp_path / "x").write_text("1", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "x")
    res = R.check_against_base("base.json", {"files": {"a.py": 99}}, tmp_path)
    assert res["status"] == "no_base" and res["note"], "抓不到基準必須明說，呼叫端要印成『未跑』"


def test_first_time_baseline_is_ok_with_an_explaining_note(tmp_path):
    _repo(tmp_path, {"x": "1"})
    res = R.check_against_base("not_yet.json", {"files": {"a.py": 5}}, tmp_path)
    assert res["status"] == "ok" and "第一次建立" in res["note"]


def test_env_base_overrides_and_a_missing_one_is_reported(tmp_path):
    _repo(tmp_path, {"base.json": json.dumps({"files": {"a.py": 1}})})
    assert R.merge_base(tmp_path, env_base="nonexistent-ref")[0] is None
    sha, why = R.merge_base(tmp_path, env_base="HEAD")
    assert sha and why == "env"
