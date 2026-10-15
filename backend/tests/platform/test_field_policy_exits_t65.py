# -*- coding: utf-8 -*-
"""T65 F7 S1b：出口遷移棘輪——出口檔案直接呼叫四支角色函式（quote_money_visible／money_visible／material_money_visible／has_cashier_access）
的次數只准減不准增；新檔案一律 0。遷移後的出口改呼叫 `field_policy.mask_flags()`／`visible()`（之後的受保護授權層才不會被旁路）。
擋整支端點的 403 閘門不在遷移範圍（見 T64-F7-S1-DESIGN §4 判準），所以基準裡仍有數字；下降時請同步調低基準檔（過期＝紅）。"""
import json
from pathlib import Path

import pytest

from tests.platform import _exit_scan_t65 as S

BASELINE = Path(__file__).with_name("field_policy_exits_baseline.json")
#: 已遷移欄位遮蔽點的出口家族（檔案 → 遷移後必須有 mask_flags 呼叫）
MIGRATED = {
    "modules/case/api/material_orders.py": 2,
    "modules/case/api/material_changes.py": 3,
}


def _base():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_no_exit_file_grows_its_direct_role_function_calls():
    now, base = S.scan(), _base()
    grew = {k: (base.get(k, 0), v) for k, v in now.items() if v > base.get(k, 0)}
    assert not grew, "出口直接呼叫角色函式變多了（改用 field_policy.mask_flags／visible）：%r" % grew


def test_baseline_is_not_stale():
    now, base = S.scan(), _base()
    stale = {k: (v, now.get(k, 0)) for k, v in base.items() if now.get(k, 0) < v}
    assert not stale, "已遷移但基準沒調低（請更新 field_policy_exits_baseline.json）：%r" % stale


def test_migrated_families_use_mask_flags():
    for rel, n in MIGRATED.items():
        src = (S.ROOT / rel).read_text(encoding="utf-8")
        assert src.count("mask_flags(") >= n, rel


def test_positive_control_scanner_counts_name_and_attribute_calls_but_not_imports():
    src = ("from helpers.financial_mask import money_visible\n"
           "import helpers.financial_mask as FM\n"
           "def f(u):\n"
           "    a = money_visible(u)\n"
           "    b = FM.quote_money_visible(u)\n"
           "    return a and b and has_cashier_access(u) and other(u)\n")
    assert S.count_calls(src) == 3
    assert S.count_calls("from helpers.financial_mask import money_visible\n# money_visible(u)\n") == 0


def test_scanner_finds_the_known_gates_so_the_ratchet_is_not_vacuous():
    assert S.scan().get("modules/case/api/material_payments.py", 0) >= 1
