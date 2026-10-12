# -*- coding: utf-8 -*-
"""脊柱 E-a：凍結基準依擁有者分檔（核心一份＋每個有設定群組的模組一份），只比對登錄表裡真的有群組的擁有者。"""
import json

import pytest

from helpers import settings_registry as R
from tests.platform import _settings_baseline as B


def _field():
    return R.SettingDef("n", "int", 5, min=1, max=9, question="這項要設多少？", label="測試項目", help="測試用的設定項目。", impact="影響測試用的畫面。")


@pytest.fixture
def fake_owner(tmp_path, monkeypatch):
    """擁有者 ea_o 擁有群組 ea_base_g；基準檔放 tmp_path（不碰真的 modules/）。"""
    R.register_group("ea_base_g", "基準測試群組", [_field()], help="測試用的設定群組。", owner="ea_o")
    path = tmp_path / "settings_deploy_baseline.json"
    orig = B.baseline_path
    monkeypatch.setattr(B, "baseline_path", lambda owner: path if owner == "ea_o" else orig(owner))
    yield path
    R.unregister_owner("ea_o")
    R.invalidate()


def test_core_baseline_is_frozen_for_core_groups_only():
    assert B.problems("core") == []


def test_every_registered_owner_has_a_matching_frozen_baseline():
    """分檔後的合併等價：每個登錄表裡有群組的擁有者都有基準且一致（模組沒載入就不在這裡）。"""
    bad = [p for o in B.owners_with_groups() for p in B.problems(o)]
    assert bad == []


def test_baseline_files_are_well_formed_and_do_not_overlap():
    seen = {}
    files = [B.CORE_BASELINE] + sorted(B.BACKEND.glob("modules/*/tests/settings_deploy_baseline.json"))
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(data.get("groups"), dict), f
        for g in data["groups"]:
            assert g not in seen, "群組 %s 同時在 %s 與 %s 的基準裡" % (g, seen[g], f)
            seen[g] = f


def test_matching_baseline_passes_and_each_kind_of_drift_is_named(fake_owner):
    fake_owner.write_text(json.dumps({"groups": {"ea_base_g": {"n": [5, 1, 9, False]}}}), encoding="utf-8")
    assert B.problems("ea_o") == []
    fake_owner.write_text(json.dumps({"groups": {"ea_base_g": {"n": [6, 1, 9, False]}}}), encoding="utf-8")        # 預設被改
    p = B.problems("ea_o")
    assert len(p) == 1 and "ea_base_g.n" in p[0] and "行為變更" in p[0]
    fake_owner.write_text(json.dumps({"groups": {}}), encoding="utf-8")                                           # 登錄了、基準沒有
    assert "基準沒有" in B.problems("ea_o")[0]
    fake_owner.write_text(json.dumps({"groups": {"ea_base_g": {"n": [5, 1, 9, False]}, "ea_gone": {"n": [1, 0, 1, False]}}}), encoding="utf-8")   # 基準有、登錄表沒有
    assert "登錄表沒有" in B.problems("ea_o")[0]
    fake_owner.unlink()                                                                                           # 有群組卻沒有基準檔
    assert "沒有凍結基準檔" in B.problems("ea_o")[0]


def test_absent_owner_needs_no_baseline_and_core_check_is_order_independent(fake_owner):
    assert B.problems("ea_not_loaded") == []                                   # 沒載入的擁有者：沒有群組也沒有基準 ⇒ 不要求
    before = B.problems("core")
    fake_owner.write_text(json.dumps({"groups": {"ea_base_g": {"n": [5, 1, 9, False]}}}), encoding="utf-8")
    assert B.problems("core") == before == []                                  # 模組群組存在與否不影響核心比對
    assert "ea_base_g" not in B.snapshot_of("core") and "ea_base_g" in B.snapshot_of("ea_o")
