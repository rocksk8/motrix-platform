# -*- coding: utf-8 -*-
"""權限矩陣框架 P0：能力登錄（core/capabilities.py）的宣告規則、真實模組宣告的健檢、與 auth 角色清單同步。"""
import json
from pathlib import Path

import pytest

from core import capabilities as C
from helpers import auth as A
from helpers import perm as P  # noqa: F401  載入時 configure(valid_roles)

MODULES_DIR = Path(__file__).resolve().parents[2] / "modules"


def _ok(**kw):
    d = {"key": "zz.doc.view", "label": "檢視", "legacy": {"module": "payslip"}}
    d.update(kw)
    return d


def test_vocabulary_is_the_user_approved_set_and_high_risk_is_a_subset():
    assert len(C.ACTIONS) == 18 and len(set(C.ACTIONS)) == 18
    assert set(C.HIGH_RISK_ACTIONS) <= set(C.ACTIONS)
    assert {"view_money", "approve", "pay", "delete"} <= set(C.HIGH_RISK_ACTIONS), "使用者裁示的四個高風險動作"
    assert "export" in C.ACTIONS and "print" in C.ACTIONS, "匯出與列印各自獨立"


def test_valid_decl_is_parsed_with_derived_leaves():
    c = C.parse_decl("zz", _ok(legacy={"any": [{"role": ["admin", "superadmin"]}, {"module": "cashier"}]}))
    assert (c.unit, c.obj, c.action) == ("zz", "doc", "view") and c.roles == frozenset({"admin"}) and c.modules == frozenset({"cashier"})
    assert c.delegable and not c.reserved and c.risk == "low"


@pytest.mark.parametrize("decl,needle", [
    ({"key": "zz.view", "label": "x", "legacy": {"module": "a"}}, "格式"),
    ({"key": "yy.doc.view", "label": "x", "legacy": {"module": "a"}}, "第一段"),
    ({"key": "zz.doc.fly", "label": "x", "legacy": {"module": "a"}}, "詞彙"),
    ({"key": "zz.doc.view", "label": " ", "legacy": {"module": "a"}}, "label"),
    ({"key": "zz.doc.view", "label": "x"}, "legacy"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"module": "a"}, "risk": "extreme"}, "risk"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"role": ["nobody"]}}, "角色"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"role": []}}, "非空"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"module": "A b"}}, "模組鍵"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"any": []}}, "非空"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"superadmin": False}}, "true"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"module": "a", "role": ["admin"]}}, "一個鍵"),
    ({"key": "zz.doc.view", "label": "x", "legacy": {"all": []}}, "不認得"),
    ("not a dict", "物件"),
])
def test_bad_declarations_are_rejected_with_a_readable_reason(decl, needle):
    with pytest.raises(C.CapabilityError) as e:
        C.parse_decl("zz", decl, valid_roles=A.VALID_ROLES)
    assert needle in str(e.value)


def test_high_risk_actions_are_raised_to_high_regardless_of_the_declared_risk():
    for act in C.HIGH_RISK_ACTIONS:
        assert C.parse_decl("zz", _ok(key="zz.doc." + act, risk="low")).risk == "high"
    assert C.parse_decl("zz", _ok(key="zz.doc.comment", risk="mid")).risk == "mid"


def test_collect_reports_problems_without_failing_and_skips_duplicates():
    caps, probs = C.collect({"zz": {"capabilities": [_ok(), _ok(), {"key": "bad"}]}, "yy": {"capabilities": "oops"}, "ww": {}})
    assert list(caps) == ["zz.doc.view"] and len(probs) == 3
    assert any("重複" in p for p in probs) and any("清單" in p for p in probs)


def test_roles_come_from_auth_not_from_a_second_list():
    assert C._VALID_ROLES == tuple(A.VALID_ROLES), "角色清單唯一來源是 helpers.auth.VALID_ROLES"
    assert not hasattr(C, "ROLES"), "capabilities 不得再寫一份角色清單"


def test_every_real_module_json_capabilities_block_parses_cleanly():
    """真實宣告的健檢（現在多半是空的；P2 起各模組加入後這題就會擋壞宣告）。"""
    manifests = {}
    for mj in MODULES_DIR.glob("*/module.json"):
        m = json.loads(mj.read_text(encoding="utf-8"))
        manifests[m["key"]] = m
    caps, probs = C.collect(manifests, valid_roles=A.VALID_ROLES)
    assert probs == [], probs


def test_all_caps_follows_the_loaded_modules_and_a_missing_module_means_no_capabilities(monkeypatch):
    from core import registry

    class _LM:
        def __init__(self, key, manifest):
            self.key, self.manifest = key, manifest
    mans = [_LM("zz", {"version": "1.0.0", "capabilities": [_ok()]})]
    monkeypatch.setattr(registry, "loaded", lambda: list(mans))
    C.reset_cache()
    assert list(C.all_caps()) == ["zz.doc.view"] and C.get("zz.doc.view") is not None
    sig1 = C.signature()
    mans.clear()
    assert C.all_caps() == {} and C.signature() != sig1, "模組缺席 ⇒ 能力不存在（不是錯誤）"
    C.reset_cache()
