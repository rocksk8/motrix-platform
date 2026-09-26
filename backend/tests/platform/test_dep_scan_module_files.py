"""「模組裡有哪些檔」只有一份定義：`core.source_tree.module_files`（主持裁示 2026-09-26）。

外包工班依 CORE-SPEC §3 把三支 router 放在 `modules/subcontract/api/`；dep_scan 原本只掃模組第一層（`d.glob("*.py")`）、
source_tree 只認 `api.py`／`api/` ⇒ 兩份清單各走各的，任一種放法都有一道守門看不到。
① 一致性：dep_scan 掃到的每個模組檔集合＝source_tree 的集合（真實 repo，逐模組比，不綁特定模組）
  〔更正（2026-09-26，稽核 D AUDIT-D-B-G1 G-M1）：原本寫「不綁特定模組」，卻用 `assert dirs` 要求真實 repo 至少一個模組 ⇒
   core-only 反向控制（拿掉全部 L2）必紅。正對照改在合成樹上做（①b），真實 repo 有幾個模組就比幾個，0 個也成立〕
①b 正對照：dep_scan 合成樹（`SYNTHETIC_FILES`，含子目錄 service/ 與 tests/）上同一個比對成立，而且比到的檔不是空的
② 正對照：子目錄裡的檔與它的跨組 import 抓得到、tests/ 不算（dep_scan 合成樹 `_synthetic_checks`）
③ 突變：dep_scan 改回 `glob("*.py")` ⇒ ①②紅
④ modtest 的 `test_map.unit_name(改動檔)` 與 dep_scan 單位同名（B：否則改到 api/ 底下的檔選不到題而且不報錯）
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402
import test_map  # noqa: E402

from core import source_tree  # noqa: E402


def _agree(units, dirs, rel):
    """每個模組資料夾：dep_scan 的單位檔集合＝source_tree.module_files；單位名稱＝test_map.unit_name。回比過的檔數。"""
    n = 0
    for d in dirs:
        expected = {rel(p) for p in source_tree.module_files(d)
                    if not (p.name == "__init__.py" and dep_scan._docstring_only(p))}
        got = {u["path"] for u in units.values() if u.get("module_key") == d.name}
        assert got == expected, (d.name, sorted(expected - got), sorted(got - expected))
        # B 的交會點：modtest 用 test_map.unit_name(改動檔) 找單位；名稱要與 dep_scan／dep_graph 的單位一致，
        # 否則改到 api/ 底下的檔會選不到任何題而且不報錯
        for name, u in units.items():
            if u.get("module_key") == d.name:
                assert test_map.unit_name(u["path"]) == name, (u["path"], test_map.unit_name(u["path"]), name)
        n += len(expected)
    return n


def test_dep_scan_and_source_tree_agree_on_module_files():
    """真實 repo：裝了幾個模組就比幾個（core-only 反向控制時 0 個，不算紅；正對照在下一題的合成樹）。"""
    _agree(dep_scan.backend_units(), source_tree.module_dirs(), lambda p: "backend/" + source_tree.rel(p))


def test_dep_scan_and_source_tree_agree_on_the_synthetic_tree(tmp_path):
    """正對照不綁真實 L2（稽核 D G-M1）：合成樹的 zz_mod 有第一層、子目錄（service/）與 tests/ ⇒ 比對成立且比到了子目錄的檔。"""
    dep_scan.build_synthetic(tmp_path)
    with dep_scan.use_root(tmp_path):
        units = dep_scan.backend_units()
    d = tmp_path / "backend" / "modules" / "zz_mod"
    n = _agree(units, [d], lambda p: "backend/" + p.relative_to(tmp_path / "backend").as_posix())
    assert n >= 5, n                                                    # __init__、api、work、util、service/calc
    assert "backend/modules/zz_mod/service/calc.py" in {u["path"] for u in units.values()}


def test_nested_module_files_are_scanned_in_the_synthetic_tree():
    assert dep_scan.positive_controls() == []


def test_module_unit_names():
    d = Path("/x/modules/zz_k")
    assert dep_scan.mod_unit(d, d / "api.py") == "mod:zz_k/api"                        # 第一層：名稱不變
    assert dep_scan.mod_unit(d, d / "api" / "orders.py") == "mod:zz_k/api/orders"
