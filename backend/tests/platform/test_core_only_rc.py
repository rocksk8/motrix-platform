"""core-only 反向控制工具（tools/platform/core_only_rc.py）的判定邏輯：junit 解析與允許清單分類。

實際「拿掉全部模組跑 tests/platform」由列車執行（PLAYBOOK §G3），這裡只驗判定——判定錯了，
那一輪的綠是假的（例：收集錯誤沒被算成失敗 ⇒ import 不到的整檔看起來像「沒有紅」）。
"""
import sys
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
    """允許清單只有 §B-11 那兩題；加一題要先改 PLAYBOOK（本題與它一起改）。"""
    assert C.ALLOWED == {
        "tests/platform/test_module_boundaries.py::test_modules_json_lists_only_existing_units",
        "tests/platform/test_unit_cards.py::test_unit_index_is_current",
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
