# -*- coding: utf-8 -*-
"""modtest 分批執行的結果彙總（wip/b-modtest-batch，主持派工）。

第十班列車：差異題 644 檔分兩批跑，畫面最後一行是第 2 批的摘要「1993 過 0 紅」，第 1 批的 2 紅
（test_cm12_p3_prep）沒有人看到——modtest 的 exit 其實是 1（modtest_stats.jsonl 21:29 那一筆）。
這裡驗：①任一批紅 ⇒ 總結果紅，而且最後一行（總摘要）是各批合計；②選到的檔沒有任何結果 ⇒ 紅
（〈守門要驗有沒有人做過決定〉）；③每一批都要有結果。
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_modtest_batches", REPO / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MT)

_OK = "def test_ok():\n    assert True\n"
_RED = "def test_red():\n    assert False\n"


def _child_env(monkeypatch):
    """子 pytest 不繼承外層這一次執行的狀態（xdist worker 等）——比照 tests/_subproc.utf8_env。"""
    from tests._subproc import utf8_env
    env = utf8_env()
    for k in list(os.environ):
        if k not in env:
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def _sandbox(tmp_path, monkeypatch, files):
    """合成 backend/tests/<檔>；run_pytest 在那裡跑，每檔一批。"""
    backend = tmp_path / "backend"
    (backend / "tests").mkdir(parents=True)
    for name, body in files.items():
        (backend / "tests" / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(MT, "BACKEND", backend)
    monkeypatch.setattr(MT, "PYEXE", sys.executable)
    monkeypatch.setattr(MT, "_batches_by_length", lambda rel, budget=None: [[r] for r in rel])
    _child_env(monkeypatch)
    return ["backend/tests/%s" % n for n in files]


def test_a_red_in_the_first_batch_makes_the_whole_run_red(tmp_path, monkeypatch, capsys):
    """反向控制（主持指定）：第 1 批放一題紅、第 2 批全綠 ⇒ exit 非 0；最後一行是合計（1 failed, 1 passed）。"""
    targets = _sandbox(tmp_path, monkeypatch, {"test_a_red.py": _RED, "test_b_ok.py": _OK})
    code, out = MT.run_pytest(targets, [], "bmtb", full=False)
    assert code == 1, out[-1500:]
    last = out.strip().splitlines()[-1]
    assert MT.parse_summary(last) == {"passed": 1, "failed": 1, "errors": 0, "skipped": 0, "xfailed": 0}, last
    assert MT.parse_summary(out)["failed"] == 1, "parse_summary(整份輸出) 要讀到合計，不是最後一批"
    shown = capsys.readouterr().out
    assert "第 1 批" in shown and "tests.test_a_red::test_red" in shown, shown[-1500:]


def test_a_picked_file_without_any_result_is_red(tmp_path, monkeypatch):
    """反向控制（主持指定）：選到的檔一題都沒有結果（檔裡沒有題）⇒ 紅，並列出檔名。"""
    targets = _sandbox(tmp_path, monkeypatch, {"test_a_ok.py": _OK, "test_b_empty.py": "X = 1\n"})
    code, out = MT.run_pytest(targets, [], "bmtb", full=False)
    assert code == 1, out[-1500:]
    assert "選到而沒有任何結果的檔 1：tests/test_b_empty.py" in out.replace("\\", "/"), out[-1500:]


def test_all_green_batches_stay_green_and_sum_up(tmp_path, monkeypatch):
    """正對照：兩批都綠 ⇒ exit 0，合計 2 passed；模組層級 skip 算「有結果」（不是缺）。"""
    skip_mod = "import pytest\npytest.skip('module absent', allow_module_level=True)\n"
    targets = _sandbox(tmp_path, monkeypatch, {"test_a_ok.py": _OK, "test_b_ok.py": _OK, "test_c_skip.py": skip_mod})
    # 整批只有一個整檔 skip 的檔 ⇒ pytest exit 5（沒有題跑）——那是既有語意；這裡把它跟一個綠檔放同一批
    monkeypatch.setattr(MT, "_batches_by_length", lambda rel, budget=None: [[rel[0], rel[2]], [rel[1]]])
    code, out = MT.run_pytest(targets, [], "bmtb", full=False)
    assert code == 0, out[-1500:]
    got = MT.parse_summary(out.strip().splitlines()[-1])
    assert got["passed"] == 2 and got["failed"] == 0 and got["skipped"] == 1, got


def test_narrowing_args_skip_the_coverage_check(tmp_path, monkeypatch, capsys):
    """帶 -k 時刻意不跑的檔不算缺（印出說明）；紅照樣紅。"""
    targets = _sandbox(tmp_path, monkeypatch, {"test_a_ok.py": _OK, "test_b_ok.py": _OK})
    code, _out = MT.run_pytest(targets, ["-k", "nothing_matches_this"], "bmtb", full=False)
    assert code == 5
    assert "不檢查「每個選到的檔都有結果」" in capsys.readouterr().out


def test_merge_batches_rules():
    """純函式：無摘要的批 ⇒ 紅；junit 讀不到 ⇒ 紅；5（沒有題）不蓋過 1；classname 前綴與模組層級結果都算有結果。"""
    ok = {"code": 0, "tail": "== 1 passed in 0.1s ==", "cases": [("tests.test_a", "test_x", "passed")]}
    red = {"code": 1, "tail": "== 1 failed in 0.1s ==", "cases": [("tests.test_b.TestC", "test_y", "failed")]}
    code, total, _ = MT.merge_batches([red, ok], ["tests/test_b.py", "tests/test_a.py"])
    assert code == 1 and total["failed"] == 1 and total["passed"] == 1
    code, _, lines = MT.merge_batches([ok, {"code": 0, "tail": "boom", "cases": []}], ["tests/test_a.py"])
    assert code == 1 and any("第 2 批沒有結果" in ln for ln in lines), lines
    code, _, _ = MT.merge_batches([ok, {"code": 0, "tail": "== 0 passed in 0.1s ==", "cases": None}], ["tests/test_a.py"])
    assert code == 1, "junit 讀不到 ⇒ 那一批沒有結果"
    code, _, _ = MT.merge_batches([{"code": 5, "tail": "no tests ran in 0.1s", "cases": []}, red], ["tests/test_b.py"])
    assert code == 1
    assert MT.files_without_results(["tests/test_m.py", "modules/a/tests/test_n.py"],
                                    [("", "tests.test_m", "skipped"), ("modules.a.tests.test_n", "t", "passed")]) == []
    assert MT.files_without_results(["tests/test_m.py"], [("tests.test_mx", "t", "passed")]) == ["tests/test_m.py"], \
        "前綴要到模組邊界（test_m 不可以被 test_mx 算成有結果）"
