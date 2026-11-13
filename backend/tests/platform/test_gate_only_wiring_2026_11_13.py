# -*- coding: utf-8 -*-
"""`gate_only`（升級演練只在正式閘門跑）的接線守門——2026-11-13 chore/test-prune，PM 轉達使用者裁示。

使用者要的是「兩組升級演練（約 100 秒）只在正式閘門跑，預跑／守門題組／各視窗自己跑全量都跳過，
而且正式閘門**絕對不能漏跑**」。這個機制有四個接點，任何一個斷掉都會變成「靜默漏跑」，所以逐個守：

1. 標記 `gate_only` 有註冊在 pytest.ini，而且兩個演練檔都帶（整檔 pytestmark）。
2. backend/conftest.py 的 `_skip_gate_only`：沒設 MOTRIX_GATE_OFFICIAL=1 ⇒ 帶標記的題 skip；設了 ⇒ 不動。
   ⚠️ 它掛在**既有**的 `pytest_collection_modifyitems` 上（同名 hook 會互相覆蓋）：本檔守「只有一個這個名字的 hook」。
3. 三條正式閘門路徑都會設 1：`heavy_run --class official` 的子行程、`run_stage` 的子行程、build_deploy_package.ps1 的兩段 pytest；
   非 official 的票不得設（也不得從外層環境繼承 1）。
4. modtest：沒設 1 ⇒ 全量結果記 gate_official=False，且**不寫建包沿用紀錄**（否則一輪跳過演練的綠燈會被建包當成已跑過）；
   該旗標不進建包指紋（_ENV_IGNORE），不然 official 與非 official 的紀錄永遠對不上。
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(BACKEND / "tools"))
import heavy_run as H  # noqa: E402
import modtest as M  # noqa: E402

DRILLS = ["tests/test_upgrade_drill_2026_09_25.py", "tests/platform/test_stepfile_drill_2026_09_30.py"]
ENV = "MOTRIX_GATE_OFFICIAL"


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def test_marker_is_registered_and_both_drill_files_carry_it():
    assert re.search(r"^\s+gate_only:", _read(BACKEND / "pytest.ini"), re.M), "gate_only 沒註冊（打錯字的 mark 只會噴 warning、靜默不生效）"
    for rel in DRILLS:
        tree = ast.parse(_read(BACKEND / rel))
        marks = []
        for n in tree.body:
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets):
                marks.append(ast.get_source_segment(_read(BACKEND / rel), n.value))
        assert marks and "pytest.mark.gate_only" in marks[0], "%s 沒有整檔 pytestmark = gate_only" % rel


def _conftest_skip():
    src = _read(BACKEND / "conftest.py")
    tree = ast.parse(src)
    hooks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pytest_collection_modifyitems"]
    assert len(hooks) == 1, "pytest_collection_modifyitems 只能有一個（同名 hook 會互相覆蓋）：%d" % len(hooks)
    assert "_skip_gate_only(items)" in ast.get_source_segment(src, hooks[0]), "既有 hook 沒呼叫 _skip_gate_only"
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_skip_gate_only")
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("GATE_ONLY", "GATE_OFFICIAL_ENV"):
            consts[n.targets[0].id] = ast.literal_eval(n.value)
    assert consts == {"GATE_ONLY": "gate_only", "GATE_OFFICIAL_ENV": ENV}, consts
    ns = {"os": os, "pytest": pytest, **consts}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "conftest._skip_gate_only", "exec"), ns)
    return ns["_skip_gate_only"]


class _Item:
    def __init__(self, marked):
        self.marked, self.added = marked, []

    def get_closest_marker(self, name):
        return object() if (self.marked and name == "gate_only") else None

    def add_marker(self, m):
        self.added.append(m)


@pytest.mark.parametrize("val,skipped", [(None, True), ("", True), ("0", True), ("true", True), ("1", False), (" 1 ", False)])
def test_skip_fires_unless_env_is_exactly_one(monkeypatch, val, skipped):
    skip = _conftest_skip()
    if val is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, val)
    drill, other = _Item(True), _Item(False)
    skip([drill, other])
    assert bool(drill.added) is skipped, "gate_only 題 %s" % ("應該 skip" if skipped else "正式閘門不能被 skip")
    assert not other.added, "沒帶 gate_only 的題不能被動到"


def test_official_ticket_sets_the_env_and_other_classes_clear_it(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "1")                       # 外層（例如正式閘門內再開的一般票）不得把 1 傳下去
    seen = {}

    def runner(cmd, env, flags):
        seen["v"] = env.get(ENV)
        return 0
    H.run(["gate"], "official", "b7", qdir=tmp_path / "q", gate_file=tmp_path / "gate.lock", runner=runner, note=lambda *_: None)
    assert seen["v"] == "1", "heavy_run --class official 沒把 %s=1 帶進子行程 ⇒ 升級演練會被漏跑" % ENV
    for cls in ("heavy", "e2e", "watcher", "light"):
        seen.clear()
        H.run(["x"], cls, "ab", qdir=tmp_path / ("q" + cls), gate_file=tmp_path / "gate.lock", runner=runner, note=lambda *_: None)
        assert seen["v"] == "", "%s 票不得繼承／帶出 %s=1" % (cls, ENV)


def test_run_stage_sets_the_env_for_the_pytest_child(tmp_path, monkeypatch):
    import build_test_reuse as btr
    r = tmp_path / "r"
    (r / "backend").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@x"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    (r / "backend" / "k.txt").write_text("k", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True, capture_output=True)
    monkeypatch.delenv(ENV, raising=False)
    monkeypatch.setattr(btr, "current_env", lambda: {"python": "3", "pip_freeze": "", "playwright": "", "browsers": [], "motrix_env": {}})
    seen = {}

    def runner(cmd, cwd, env):
        seen["v"] = env.get(ENV)
        return 0
    btr.run_stage(r, "not_e2e", tmp_path / "rec.jsonl", runner=runner, note=lambda *_: None)
    assert seen["v"] == "1", "建包 run-stage 沒把 %s=1 帶進 pytest 子行程 ⇒ 升級演練會被漏跑" % ENV
    assert ENV in btr._ENV_IGNORE, "%s 不能進建包指紋（official 與非 official 的紀錄會永遠對不上）" % ENV


def test_modtest_reads_the_flag_and_only_records_for_build_when_official():
    assert M.gate_official({ENV: "1"}) and not M.gate_official({}) and not M.gate_official({ENV: "0"}) and not M.gate_official({ENV: ""})
    src = _read(REPO / "tools" / "platform" / "modtest.py")
    m = re.search(r'if not result\["gate_official"\]:[^\n]*\n\s+done, why = False,[^\n]*\n\s+else:\n\s+done, why = record_for_build\(', src)
    assert m, "modtest 沒有「非正式閘門就不寫建包沿用紀錄」的分支（跳過演練的綠燈會被建包當成已跑過）"
    assert 'result["gate_official"] = gate_official()' in src, "全量結果沒記 gate_official"




def test_build_script_sets_the_flag_before_both_pytest_runs_and_clears_it():
    """第三條正式閘門路徑：build_deploy_package.ps1 自己跑的 pytest（非 e2e／e2e 兩段）。沒設 ⇒ 建包把演練靜靜 skip 還記成綠。"""
    ps1 = _read(BACKEND / "tools" / "build_deploy_package.ps1")
    setat = ps1.index('$env:%s = "1"' % ENV)
    runs = [m.start() for m in re.finditer(r'& \$pyExe -m pytest -q [^\n]*-m "(?:not e2e|e2e)"', ps1)]
    assert len(runs) == 2, "建包的兩段 pytest 呼叫找不到（腳本改寫了？）%s" % runs
    assert setat < min(runs), "%s=1 必須在兩段 pytest 之前設" % ENV
    assert "Env:\\%s" % ENV in ps1, "建包結束／釋放鎖時要清掉 %s" % ENV


def test_dashboard_gate_rejects_a_non_official_green(tmp_path):
    import deploy_insights as di
    sha = "a" * 40
    p = tmp_path / (sha + ".json")
    p.write_text('{"commit": "%s", "ok": true, "dirty": false, "gate_official": false}' % sha, encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "not_official"
    p.write_text('{"commit": "%s", "ok": true, "dirty": false}' % sha, encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "ok", "缺欄位＝舊結果，不可誤擋"
