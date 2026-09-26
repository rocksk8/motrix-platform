"""core-only 反向控制工具（tools/platform/core_only_rc.py）的判定邏輯：junit 解析與允許清單分類。

實際「拿掉全部模組跑 tests/platform」由列車執行（PLAYBOOK §G3），這裡只驗判定——判定錯了，
那一輪的綠是假的（例：收集錯誤沒被算成失敗 ⇒ import 不到的整檔看起來像「沒有紅」）。
"""
import sys

import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import core_only_rc as C  # noqa: E402

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="tests.platform.test_a" name="test_ok"/>
  <testcase classname="tests.platform.test_a" name="test_bad"><failure message="x"/></testcase>
  <testcase classname="tests.platform.test_b.TestK" name="test_m[p1]"><error message="y"/></testcase>
  <testcase classname="" name="tests.platform.test_gone"><error message="collection failure"/></testcase>
  <testcase classname="tests.platform.test_unit_cards" name="test_unit_index_is_current"><failure message="z"/></testcase>
  <testcase classname="tests.platform.test_a" name="test_skip"><skipped message="s"/></testcase>
</testsuite></testsuites>
"""


def test_failed_ids_cover_failures_errors_and_collection_errors(tmp_path):
    j = tmp_path / "j.xml"
    j.write_text(JUNIT, encoding="utf-8")
    assert C.failed_ids(j) == {
        "tests/platform/test_a.py::test_bad",
        "tests/platform/test_b.py::TestK::test_m[p1]",
        "tests/platform/test_gone.py",                                   # 收集錯誤也算不過
        "tests/platform/test_unit_cards.py::test_unit_index_is_current",
    }


def test_classify_splits_allowed_from_unexpected():
    hit, unexpected = C.classify({"tests/platform/test_unit_cards.py::test_unit_index_is_current",
                                  "tests/platform/test_a.py::test_bad"})
    assert hit == ["tests/platform/test_unit_cards.py::test_unit_index_is_current"]
    assert unexpected == ["tests/platform/test_a.py::test_bad"]


def test_allowed_is_exactly_the_playbook_b11_list():
    """允許清單＝§B-11 那兩題＋產生檔一致性三題（BM-M2）；加一題要先改 PLAYBOOK §B-11（本題與它一起改）。"""
    assert C.ALLOWED == {
        "tests/platform/test_module_boundaries.py::test_modules_json_lists_only_existing_units",
        "tests/platform/test_unit_cards.py::test_unit_index_is_current",
        "tests/platform/test_generated_maps.py::test_dep_graph_json_is_current",
        "tests/platform/test_generated_maps.py::test_test_map_json_is_current",
        "tests/platform/test_generated_maps.py::test_modules_json_has_no_ownership_errors",
    }
    playbook = (REPO / "docs" / "platform" / "PLAYBOOK.md").read_text(encoding="utf-8")
    assert "test_unit_index_is_current" in playbook and "modules.json 列了但掃描不到" in playbook


def test_module_dirs_only_counts_folders_with_module_json(tmp_path):
    m = tmp_path / "backend" / "modules"
    (m / "a").mkdir(parents=True)
    (m / "a" / "module.json").write_text("{}", encoding="utf-8")
    (m / "b").mkdir()                                      # 沒有 module.json ⇒ 不是模組
    (m / "__init__.py").write_text("", encoding="utf-8")
    assert [d.name for d in C.module_dirs(tmp_path / "backend")] == ["a"]


# ── 已知紅清單（AUDIT-D-B-G1 G-M1）與判定 ─────────────────────────────────────

def test_judge_known_red_is_tolerated_unexpected_is_not():
    known = {"tests/platform/test_a.py::test_k"}
    ok = C.judge({"tests/platform/test_a.py::test_k"} | C.ALLOWED, 100, 1, known)
    assert ok["ok"] and ok["known_hit"] == ["tests/platform/test_a.py::test_k"], ok
    bad = C.judge({"tests/platform/test_a.py::test_new"}, 100, 1, known)
    assert not bad["ok"] and bad["unexpected"] == ["tests/platform/test_a.py::test_new"], bad


def test_judge_known_red_that_turned_green_fails():
    """清單上的題已經綠了還留著 ⇒ 不算過（避免退化成「全寫進清單就變綠」）。"""
    res = C.judge(set(), 100, 0, {"tests/platform/test_a.py::test_k"})
    assert not res["ok"] and res["stale_known"] == ["tests/platform/test_a.py::test_k"], res


@pytest.mark.parametrize("total,exit_code", [(0, 0), (0, 5), (12, 5)])
def test_judge_no_tests_ran_is_not_a_pass(total, exit_code):
    """G-S1：一題都沒跑（exit 5 或 0 題）⇒ ok=False；「沒有紅」不等於「驗過了」。"""
    assert not C.judge(set(), total, exit_code, set())["ok"]


def test_real_known_red_list_is_valid():
    """清單每一筆：欄位齊、題存在、RUN-PLAN 有一行同時寫著裁示錨點與題名（新增要先有主持裁示）。"""
    import json
    entries = json.loads((REPO / C.KNOWN_RED_REL).read_text(encoding="utf-8"))["entries"]
    runplan = (REPO / "docs" / "platform" / "RUN-PLAN.md").read_text(encoding="utf-8")
    assert C.validate_known(entries, runplan, REPO / "backend") == []


def test_rc_known_red_entry_without_a_ruling_or_a_real_test_is_refused(tmp_path):
    """反向控制（合成）：沒有裁示行的、題不存在的、缺欄位的、重複的 ⇒ 都報；有裁示且題存在的 ⇒ 不報。"""
    b = tmp_path / "backend"
    (b / "tests" / "platform").mkdir(parents=True)
    (b / "tests" / "platform" / "test_x.py").write_text("def test_real():\n    pass\n", encoding="utf-8")
    good = {"test": "tests/platform/test_x.py::test_real", "owner": "C", "fix_branch": "wip/c-x",
            "registered_at": "2026-09-26", "ruling": "CORE-ONLY-KR-9"}
    runplan = "- `CORE-ONLY-KR-9` test_real：擁有者 C\n"
    assert C.validate_known([good], runplan, b) == []
    assert C.validate_known([good], "- 沒有裁示\n", b)                                   # 沒有主持裁示 ⇒ 不准加
    assert C.validate_known([dict(good, test="tests/platform/test_x.py::test_gone")],
                            "- `CORE-ONLY-KR-9` test_gone\n", b)                       # 題不存在
    assert C.validate_known([dict(good, owner="")], runplan, b)                         # 缺欄位
    assert C.validate_known([good, good], runplan, b)                                   # 重複


def test_known_red_list_only_shrinks_against_origin():
    """只准縮短：比 origin/platform 那一版多出來的每一筆，都必須在本分支的 RUN-PLAN 有裁示行（由上一題的驗證涵蓋）；
    這裡另驗「多出來的」確實都帶了錨點——合回之後 origin 那一版就是新的基準。"""
    import json
    import subprocess
    cur = json.loads((REPO / C.KNOWN_RED_REL).read_text(encoding="utf-8"))["entries"]
    r = subprocess.run(["git", "-C", str(REPO), "show", "origin/platform:" + C.KNOWN_RED_REL],
                       capture_output=True, text=True, encoding="utf-8")
    base = {e["test"] for e in json.loads(r.stdout)["entries"]} if r.returncode == 0 else set()
    added = [e for e in cur if e["test"] not in base]
    runplan = (REPO / "docs" / "platform" / "RUN-PLAN.md").read_text(encoding="utf-8")
    assert C.validate_known(added, runplan, REPO / "backend") == []


@pytest.mark.parametrize("exit_code", [2, 3, 4])
def test_judge_abnormal_pytest_exit_is_not_a_pass(exit_code):
    """稽核 G-O3：中斷／內部錯誤／用法錯誤 ⇒ junit 可能只有部分結果 ⇒ 不算過（即使紅燈 ⊆ 允許）。"""
    res = C.judge(set(C.ALLOWED), 500, exit_code, set())
    assert not res["ok"] and any("異常結束" in r for r in res["reasons"]), res


def test_judge_normal_exit_codes_still_pass():
    assert C.judge(set(), 500, 0, set())["ok"] and C.judge(set(C.ALLOWED), 500, 1, set())["ok"]


def test_queue_line_names_the_holder_and_the_wait():
    """稽核 G-O4：conftest 的排隊訊息 ⇒ 「排隊中：等 <持鎖者>，已等 N 分」。"""
    line = "[測試鎖] 全機名額已滿（pid=4711、C:\T\motrix-pytest-x-full、已跑 12 分鐘）—— 排隊中，最多再等 80 分鐘"
    assert C.queue_line(line, 185) == "排隊中：等 pid=4711 C:\T\motrix-pytest-x-full，已等 3 分"
    assert C.queue_line("collected 12 items", 185) is None


def test_streaming_prints_a_heartbeat_when_silent(monkeypatch, capsys, tmp_path):
    """沒有輸出超過心跳間隔 ⇒ 印「執行中：…沒有輸出」；子行程的輸出即時轉印；排隊訊息另印一行。"""
    import sys as _sys
    monkeypatch.setattr(C, "HEARTBEAT_SECONDS", 1)
    code_src = ("import time\n"
                "print('[測試鎖] 滿（pid=9、C:/x-full、已跑 1 分鐘）—— 排隊中，最多再等 9 分鐘', flush=True)\n"
                "time.sleep(2.5)\nprint('done', flush=True)\n")
    code, lines = C._run_streaming([_sys.executable, "-X", "utf8", "-c", code_src], tmp_path)
    out = capsys.readouterr().out
    assert code == 0 and lines[-1] == "done"
    assert "排隊中：等 pid=9 C:/x-full，已等 0 分" in out, out
    assert "執行中：" in out and "沒有輸出" in out, out
