# -*- coding: utf-8 -*-
"""T66 L1：清單偏好公司政策（`helpers/list_pref_policy.py`）——驗證器、寬嚴比較、惰性登記、讀取（旗標關＝None）、管線與能力目錄接線。純函式為主，不需要資料庫。"""
import copy

import pytest

from core import catalog as CAT
from core import definitions as D
from helpers import list_catalog as LC
from helpers import list_pref_policy as LP
import modules.supply.api.suppliers  # noqa: F401  登記先導清單

LID = "supply:suppliers"


def _good(**over):
    b = {"version": 1, "allowUserPrefs": True,
         "columns": {"allowed": ["name", "alias", "taxId", "phone"], "pinned": ["name"], "defaultHidden": ["alias"]},
         "sort": {"allowed": ["name", "taxId"], "default": {"col": "name", "dir": "asc"}},
         "pageSize": {"allowed": [20, 50], "default": 20}}
    b.update(over)
    return b


def test_good_policy_passes_and_empty_policy_passes():
    assert LP.definition_problems(LID, _good()) == []
    assert LP.definition_problems(LID, {"version": 1}) == []


@pytest.mark.parametrize("mut,frag", [
    (lambda b: b.update(version=2), "version"),
    (lambda b: b.update(zzz=1), "不認得"),
    (lambda b: b.update(allowUserPrefs="yes"), "true"),
    (lambda b: b["columns"].update(allowed=["name", "nope"]), "沒有這個欄位"),
    (lambda b: b["columns"].update(allowed=["alias", "taxId"], pinned=[]), "必留"),
    (lambda b: b["columns"].update(pinned=["phone", "name"], allowed=["name", "alias"]), "固定欄位必須"),
    (lambda b: b["columns"].update(defaultHidden=["name"]), "不可預設隱藏"),
    (lambda b: b["columns"].update(defaultHidden=["name", "alias", "taxId", "phone"], pinned=[]), "至少要有"),
    (lambda b: b["columns"].update(pinned=["name", "name"]), "不重複"),
    (lambda b: b["sort"].update(allowed=["phone"]), "不能排序"),
    (lambda b: b["sort"].update(allowed=["category"]), "允許欄位內"),
    (lambda b: b["sort"].update(default={"col": "taxId", "dir": "sideways"}), "dir"),
    (lambda b: b["sort"].update(default={"col": "alias", "dir": "asc"}), "允許排序"),
    (lambda b: b["pageSize"].update(allowed=[20, 999]), "允許範圍"),
    (lambda b: b["pageSize"].update(allowed=[]), "整數清單"),
    (lambda b: b["pageSize"].update(allowed=[True]), "整數清單"),
    (lambda b: b["pageSize"].update(default=100), "預設筆數"),
])
def test_bad_policies_rejected(mut, frag):
    b = copy.deepcopy(_good())
    mut(b)
    probs = LP.definition_problems(LID, b)
    assert probs and any(frag in p["message"] for p in probs), probs


def test_default_sort_column_must_be_visible_by_default():
    b = _good()
    b["columns"]["defaultHidden"] = ["alias"]
    b["sort"] = {"allowed": ["alias"], "default": {"col": "alias", "dir": "asc"}}
    assert any("預設隱藏" in p["message"] for p in LP.definition_problems(LID, b))


def test_unknown_list_and_global_key_rules():
    assert LP.definition_problems("no:such", {"version": 1})
    assert LP.definition_problems("*", {"version": 1, "allowUserPrefs": False, "pageSize": {"allowed": [10, 500], "default": 10}}) == []
    assert LP.definition_problems("*", {"version": 1, "pageSize": {"allowed": [501]}})
    assert LP.definition_problems("*", {"version": 1, "columns": {"allowed": ["name"]}})
    assert LP.definition_problems("*", {"version": 1, "sort": {"allowed": ["name"]}})
    assert LP.definition_problems(LID, "x") and LP.definition_problems(LID, None)


# ── 寬嚴比較 ──
def _cls(old, new):
    return LP.compare(old, new)[0]


def test_compare_loosening_cases():
    base = _good()
    cases = [
        lambda b: b["columns"].update(allowed=["name", "alias", "taxId", "phone", "currency"]),
        lambda b: b["columns"].update(pinned=[]),
        lambda b: b["columns"].update(defaultHidden=[]),
        lambda b: b["sort"].update(allowed=["name", "taxId", "alias"]),
        lambda b: b["pageSize"].update(allowed=[20, 50, 100]),
        lambda b: b["pageSize"].update(default=50),
        lambda b: b.update(mystery=1),
    ]
    off = copy.deepcopy(base)
    off["allowUserPrefs"] = False
    assert _cls(off, base) == "loosen"                      # 個人設定 關→開
    for mut in cases[1:]:
        n = copy.deepcopy(base)
        mut(n)
        assert _cls(base, n) == "loosen", n


def test_compare_tightening_and_neutral():
    base = _good()
    off = copy.deepcopy(base)
    off["allowUserPrefs"] = False
    assert _cls(base, off) == "tighten"
    for mut in (lambda b: b["columns"].update(allowed=["name", "alias", "taxId"]),
                lambda b: b["columns"].update(defaultHidden=["alias", "phone"]),
                lambda b: b["columns"].update(pinned=["name", "phone"]),
                lambda b: b["sort"].update(allowed=["name"]),
                lambda b: b["pageSize"].update(allowed=[20], default=20)):
        n = copy.deepcopy(base)
        mut(n)
        assert _cls(base, n) == "tighten", n
    n = copy.deepcopy(base)
    n["sort"]["default"] = {"col": "taxId", "dir": "desc"}   # 只改預設排序 ＝ 中性
    assert _cls(base, n) == "neutral"
    assert _cls(base, copy.deepcopy(base)) == "neutral"


def test_compare_unlimited_and_garbage():
    assert _cls({"version": 1}, {"version": 1, "columns": {"allowed": ["name"]}}) == "tighten"   # 不限 → 限定
    assert _cls({"version": 1, "columns": {"allowed": ["name"]}}, {"version": 1}) == "loosen"    # 限定 → 不限
    assert _cls(None, "not a dict") == "loosen"
    assert _cls(_good(), None) == "loosen"
    # 同時有放寬與收緊 ⇒ 整體算放寬（需核准）
    n = _good()
    n["columns"]["allowed"] = ["name", "alias", "taxId", "phone", "currency"]
    n["pageSize"] = {"allowed": [20], "default": 20}
    assert _cls(_good(), n) == "loosen"


def test_pipeline_wiring_uses_this_comparator():
    from routers import def_pipeline as P
    assert LP.KIND in P.ACTIVE_KINDS and LP.KIND in P.COMPARATORS
    assert P.classify(LP.KIND, _good(), _good(pageSize={"allowed": [20, 50, 100], "default": 20}))[0] == "loosen"
    assert P.classify(LP.KIND, _good(), _good())[0] == "neutral"


# ── 旗標與惰性登記 ──
def test_flag_off_means_no_kind_registered(monkeypatch):
    monkeypatch.setattr(D, "_EXTRA_KINDS", {k: v for k, v in D._EXTRA_KINDS.items() if k != LP.KIND})
    monkeypatch.setattr(LP, "enabled", lambda conn=None: False)
    assert LP.ensure_kind() is False
    assert LP.KIND not in D.kinds()


def test_flag_on_registers_kind_with_validator(monkeypatch):
    monkeypatch.setattr(D, "_EXTRA_KINDS", {k: v for k, v in D._EXTRA_KINDS.items() if k != LP.KIND})
    monkeypatch.setattr(D, "_VALIDATORS", dict(D._VALIDATORS))
    monkeypatch.setattr(LP, "enabled", lambda conn=None: True)
    assert LP.ensure_kind() is True and LP.KIND in D.kinds()
    assert LP.ensure_kind() is True                          # 重複呼叫不丟例外
    assert D.validate(LP.KIND, LID, _good()) == []
    assert D.validate(LP.KIND, LID, {"version": 9})


def test_kind_validator_refuses_when_flag_off(monkeypatch):
    monkeypatch.setattr(LP, "enabled", lambda conn=None: False)
    out = LP._kind_validator(_good(), LID)
    assert out and out[0]["message"] == LP.OFF_REASON


def test_enabled_is_fail_closed_on_error(monkeypatch):
    from helpers import settings_registry as SR

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(SR, "get", boom)
    assert LP.enabled() is False


def test_enabled_needs_both_flags(monkeypatch):
    from helpers import settings_registry as SR
    vals = {("list_prefs", "enabled"): 1, ("builder_governance", "enabled"): 0}
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: vals[(g, f)])
    assert LP.enabled() is False
    vals[("builder_governance", "enabled")] = 1
    assert LP.enabled() is True
    vals[("list_prefs", "enabled")] = 0
    assert LP.enabled() is False


# ── policy_for ──
def test_policy_for_none_when_flag_off_or_unknown_list(monkeypatch):
    monkeypatch.setattr(LP, "enabled", lambda conn=None: False)
    monkeypatch.setattr(D, "resolve", lambda *a, **k: (_good(), "company v1"))
    assert LP.policy_for(None, LID) is None
    monkeypatch.setattr(LP, "enabled", lambda conn=None: True)
    assert LP.policy_for(None, "no:such") is None
    assert LP.policy_for(None, LID) is not None


def test_policy_for_merges_global_under_list_specific(monkeypatch):
    monkeypatch.setattr(LP, "enabled", lambda conn=None: True)
    own = {"version": 1, "columns": {"allowed": ["name"]}, "pageSize": {"default": 20}}
    glob = {"version": 1, "allowUserPrefs": False, "pageSize": {"allowed": [20, 50], "default": 50}}
    monkeypatch.setattr(D, "resolve", lambda conn, kind, key, role=None: (own if key == LID else glob, "x"))
    got = LP.policy_for(None, LID)
    assert got["allowUserPrefs"] is False and got["columns"] == {"allowed": ["name"]}
    assert got["pageSize"] == {"allowed": [20, 50], "default": 20}


def test_policy_for_never_raises_and_rejects_bad_versions(monkeypatch):
    monkeypatch.setattr(LP, "enabled", lambda conn=None: True)

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(D, "resolve", boom)
    assert LP.policy_for(None, LID) is None
    monkeypatch.setattr(D, "resolve", lambda *a, **k: ({"version": 7}, "x"))
    assert LP.policy_for(None, LID) is None
    monkeypatch.setattr(D, "resolve", lambda *a, **k: (None, "none"))
    assert LP.policy_for(None, LID) is None


# ── 能力目錄接線與設定群組 ──
def test_catalog_section_registered_and_not_expected():
    assert LC.SECTION_NAME == "listCatalog" and LC.SECTION_NAME not in CAT.EXPECTED_SECTIONS
    owner, fn = CAT.snapshot()[LC.SECTION_NAME]
    assert owner == "helpers.list_catalog"
    assert any(x["id"] == LID for x in fn()["lists"])
    assert CAT.section(LC.SECTION_NAME)["lists"]


def test_flag_group_registered_default_off():
    import json
    from pathlib import Path
    from helpers import settings_groups  # noqa: F401  載入時登錄群組
    base = json.loads((Path(__file__).resolve().parent / "settings_deploy_baseline.json").read_text(encoding="utf-8"))
    assert base["groups"]["list_prefs"] == {"enabled": [0, 0, 1, False]}
