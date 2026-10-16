# -*- coding: utf-8 -*-
"""T66 L0／L1：清單目錄（`helpers/list_catalog.py`）——登記驗證、金額欄衍生、先導清單（供應商）與版面登記互核。零行為變更。"""
import copy
import json
from pathlib import Path

import pytest

from helpers import field_catalog as FC
from helpers import list_catalog as LC
import modules.supply.api.suppliers  # noqa: F401  登記先導清單

ROOT = Path(__file__).resolve().parents[2]


def _spec(**over):
    s = {"label": "測試清單",
         "columns": [{"id": "a", "label": "甲", "sortable": True, "required": True},
                     {"id": "b", "label": "乙", "sortable": True},
                     {"id": "m", "label": "含稅總額", "catalogId": "quotation.total", "sortable": True}],
         "defaults": {"columns": ["a", "b", "m"], "sort": {"col": "a", "dir": "asc"}, "pageSize": 50},
         "pageSizeCeiling": 200, "pageSizeMenu": [20, 50, 200], "sortGuard": True}
    s.update(over)
    return s


@pytest.fixture()
def clean():
    st = LC.snapshot()
    yield
    LC.restore(st)


def test_pilot_suppliers_registered_clean_and_no_money():
    e = LC.by_id("supply:suppliers")
    assert e and e["owner"] == "supply"
    assert LC.problems() == []
    assert LC.money_column_ids("supply:suppliers") == ()


def test_pilot_columns_match_module_json_layout_fields():
    m = json.loads((ROOT / "modules" / "supply" / "module.json").read_text(encoding="utf-8"))
    lst = [l for p in m["customization"]["pages"] for l in p.get("lists", []) if l["key"] == "suppliers"][0]
    assert [c["id"] for c in LC.columns_of("supply:suppliers")] == [c["field"] for c in lst["columns"]]


def test_money_flag_is_derived_from_field_catalog(clean):
    assert LC.register_list("t:money", "test", _spec()) == []
    assert LC.money_column_ids("t:money") == ("m",)
    assert FC.by_id("quotation.total")["moneyClass"] != "none"
    # 衍生而非另外宣告：同一個 catalogId 在不同清單都是金額欄；沒有 catalogId 的不是
    assert [c["money"] for c in LC.columns_of("t:money")] == [False, False, True]
    # 未知 catalogId 的 is_money_column 保守當金額欄
    assert LC.is_money_column({"catalogId": "no.such"}) is True
    assert LC.is_money_column({"catalogId": None}) is False


@pytest.mark.parametrize("mut,frag", [
    (lambda s: s["columns"].append({"id": "a", "label": "重"}), "重複"),
    (lambda s: s["columns"].append({"id": "z", "label": "Z", "catalogId": "no.such"}), "不在欄位目錄"),
    (lambda s: s["defaults"].update(columns=["a", "zz"]), "子集"),
    (lambda s: s["defaults"].update(columns=["b", "m"]), "必留欄位"),
    (lambda s: s["defaults"].update(sort={"col": "a", "dir": "up"}), "defaults.sort"),
    (lambda s: s["defaults"].update(sort={"col": "zz", "dir": "asc"}), "defaults.sort"),
    (lambda s: s["columns"][1].update(sortable=False) or s["defaults"].update(sort={"col": "b", "dir": "asc"}), "defaults.sort"),
    (lambda s: s.update(pageSizeCeiling=501), "pageSizeCeiling"),
    (lambda s: s.update(pageSizeMenu=[50, 20]), "pageSizeMenu"),
    (lambda s: s.update(pageSizeMenu=[20, 50, 300]), "pageSizeMenu"),
    (lambda s: s["defaults"].update(pageSize=30), "pageSize 必須在"),
    (lambda s: s.update(label=" "), "白話名稱"),
])
def test_bad_specs_are_rejected_and_not_registered(clean, mut, frag):
    s = copy.deepcopy(_spec())
    mut(s)
    probs = LC.register_list("t:bad", "test", s)
    assert probs and any(frag in p for p in probs), probs
    assert LC.by_id("t:bad") is None            # fail closed：沒登記


def test_bad_list_id_rejected(clean):
    for bad in ("Bad", "1x", "a b", "", None):
        assert LC.register_list(bad, "test", _spec())


def test_owner_conflict_raises_same_owner_reregister_ok(clean):
    assert LC.register_list("t:own", "a", _spec()) == []
    assert LC.register_list("t:own", "a", _spec(label="改名")) == []
    assert LC.by_id("t:own")["label"] == "改名"
    with pytest.raises(ValueError):
        LC.register_list("t:own", "b", _spec())


def test_returned_values_are_copies(clean):
    LC.register_list("t:cp", "test", _spec())
    e = LC.by_id("t:cp")
    e["columns"].clear()
    e["defaults"]["columns"].clear()
    assert len(LC.by_id("t:cp")["columns"]) == 3
    LC.lists()[0]["columns"].clear()
    assert LC.by_id("t:cp")["defaults"]["columns"] == ["a", "b", "m"]


def test_registration_does_not_alias_caller_spec(clean):
    s = _spec()
    LC.register_list("t:al", "test", s)
    s["columns"].clear()
    assert len(LC.by_id("t:al")["columns"]) == 3


def test_problems_recheck_catches_later_catalog_change(clean, monkeypatch):
    LC.register_list("t:late", "test", _spec())
    assert LC.problems() == []
    monkeypatch.setattr(FC, "by_id", lambda fid: None)
    assert any("不在欄位目錄" in p for p in LC.problems())


def test_section_payload_lists_everything_sorted(clean):
    LC.register_list("t:b2", "test", _spec())
    LC.register_list("t:a1", "test", _spec())
    ids = [x["id"] for x in LC.section_payload()["lists"]]
    assert ids == sorted(ids) and {"t:a1", "t:b2", "supply:suppliers"} <= set(ids)


def test_core_catalog_section_is_wired_but_not_expected():
    from core import catalog
    assert LC.SECTION_NAME not in catalog.EXPECTED_SECTIONS         # 沒載入時不算缺口
    owner, fn = catalog.snapshot()[LC.SECTION_NAME]
    assert owner == "helpers.list_catalog" and fn is LC.section_payload

def test_money_list_without_sort_guard_declaration_is_rejected(clean):
    s = _spec()
    del s["sortGuard"]
    probs = LC.register_list("t:noguard", "test", s)
    assert probs and any("sortGuard" in p for p in probs)
    assert LC.by_id("t:noguard") is None
    # 沒有金額欄的清單不需要宣告（先導清單）
    s2 = _spec(columns=[{"id": "a", "label": "甲", "sortable": True, "required": True}],
               defaults={"columns": ["a"], "sort": {"col": "a", "dir": "asc"}, "pageSize": 50})
    del s2["sortGuard"]
    assert LC.register_list("t:plain", "test", s2) == []
