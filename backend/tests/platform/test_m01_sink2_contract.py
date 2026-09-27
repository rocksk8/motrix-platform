"""M01-PLAN §3-2（2026-09-26）：`norm_at` → L1 `helpers/dates`、`_steps_to_tiers` → L1 `helpers/tiered_approval.steps_to_tiers`。

① 舊位置（`modules.case.quotations`、`helpers` 套件）的名字是 L1 的同一個物件（不是複本）
② 兩支 L1 檔不 import M01（掃描器與正對照沿用 test_tax_calc_contract）
③ L1 `routers/system` 不再為了 `_steps_to_tiers` import `modules.case.quotations`
④ 行為
"""
from pathlib import Path

import pytest

from tests.platform.test_tax_calc_contract import m01_imports

HELPERS = Path(__file__).resolve().parents[2] / "helpers"
SYSTEM = Path(__file__).resolve().parents[2] / "routers" / "system.py"


@pytest.mark.parametrize("old, new", [
    ("modules.case.quotations:norm_at", "helpers.dates:norm_at"),
    ("helpers:norm_at", "helpers.dates:norm_at"),
    ("modules.case.quotations:_steps_to_tiers", "helpers.tiered_approval:steps_to_tiers"),
    # 〔更正（C，M01-PLAN §3-8 ① CA-O4）：~~("helpers:_steps_to_tiers", …)~~——`helpers` 套件不再再匯出 M01 的名稱，
    #  這個底線舊名只剩 M01 自己的 `modules.case.quotations._steps_to_tiers`（上一列）；見 test_helpers_package_no_longer_exports_m01_name〕
])
def test_old_names_are_aliases_of_the_l1_objects(old, new):
    import importlib

    def get(spec):
        mod, name = spec.split(":")
        return getattr(importlib.import_module(mod), name)
    assert get(old) is get(new), (old, new)


@pytest.mark.parametrize("f", ["dates.py", "tiered_approval.py"])
def test_l1_files_import_no_m01(f):
    assert m01_imports((HELPERS / f).read_text(encoding="utf-8")) == []


def test_system_does_not_import_helpers_quotations_for_steps():
    src = SYSTEM.read_text(encoding="utf-8")
    assert "from modules.case.quotations import _steps_to_tiers" not in src
    assert "from helpers.tiered_approval import steps_to_tiers" in src


def test_behaviour():
    from helpers.dates import norm_at
    from helpers.tiered_approval import steps_to_tiers
    assert norm_at("2026-09-26T10:11:12.123456") == "2026-09-26 10:11:12"
    assert norm_at(None) == ""
    assert steps_to_tiers([{"userId": 3, "username": "u"}]) == [
        {"order": 0, "approvers": [{"userId": 3, "username": "u", "displayName": "u"}]}]


def test_helpers_package_no_longer_exports_m01_name():
    """CA-O4：`helpers` 套件不再以底線舊名轉出 steps_to_tiers（那個名字是 M01 的；L1 用公開名）。"""
    import helpers
    assert not hasattr(helpers, "_steps_to_tiers")
    from helpers import tiered_approval
    assert callable(tiered_approval.steps_to_tiers)
