# -*- coding: utf-8 -*-
"""建構器第三輪 S2（2026-09-30）：組織元件——人員／部門的單選與複選（都是 `ref`，複選 `multiple: true`）。
單選＝原本的參照行為不變（反向控制）；複選＝代號清單，去重、逐一驗證存在、必填＝至少一個。"""
import sqlite3

from helpers import custom_modules as CM


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE users (username TEXT PRIMARY KEY, display_name TEXT, active INTEGER DEFAULT 1)")
    c.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT)")
    c.executemany("INSERT INTO users VALUES (?,?,?)", [("amy", "艾咪", 1), ("bob", "鮑伯", 1), ("old", "離職者", 0)])
    c.executemany("INSERT INTO departments VALUES (?,?)", [(1, "工程部"), (2, "業務部")])
    return c


def _body(**over):
    f = {"key": "who", "label": "承辦", "type": "ref", "target": "users", "multiple": True, "required": False, "dataClass": "T1"}
    f.update(over)
    return {"fields": [f]}


def test_org_elements_are_catalog_presets_of_ref_and_grouped():
    els = {e["id"]: e for e in CM.FIELD_ELEMENTS}
    assert {e for e in ("user", "users", "dept", "depts")} <= set(els)
    assert all(els[i]["type"] == "ref" and els[i]["group"] == "org" for i in ("user", "users", "dept", "depts"))
    assert els["users"]["preset"] == {"target": "users", "multiple": True} and "multiple" not in els["user"]["preset"]
    assert "org" in [g["id"] for g in CM.ELEMENT_GROUPS]
    assert "departments" in CM.ref_targets()
    assert ("multiple", "可複選", "bool") in CM.FIELD_ATTRS["ref"]


def test_multiple_must_be_boolean():
    probs = CM.validate_module({"name": "x", "permission": "custom.x", "numbering": {"prefix": "X", "period": "none", "digits": 3},
                                "fields": _body(multiple="yes")["fields"],
                                "workflow": {"initial": "d", "states": [{"key": "d", "label": "d", "final": True}], "transitions": []}}, "x")
    assert any(p["path"].endswith(".multiple") for p in probs)


def test_multi_ref_dedupes_keeps_order_and_verifies_each():
    c = _conn()
    vals, errs, _d = CM.clean_values(c, _body(), {"who": ["bob", "amy", "bob", " amy "]})
    assert errs == [] and vals["who"] == ["bob", "amy"]
    _v, errs, _d = CM.clean_values(c, _body(), {"who": ["amy", "ghost"]})
    assert [e["key"] for e in errs] == ["who"] and "ghost" in errs[0]["message"]
    _v, errs, _d = CM.clean_values(c, _body(), {"who": "amy"})              # 不是清單
    assert errs and "清單" in errs[0]["message"]
    _v, errs, _d = CM.clean_values(c, _body(), {"who": [{"a": 1}]})
    assert errs


def test_multi_ref_required_means_at_least_one_and_optional_may_be_empty():
    c = _conn()
    for empty in ([], None, ""):
        _v, errs, _d = CM.clean_values(c, _body(required=True), {"who": empty})
        assert errs and "必填" in errs[0]["message"], empty
        vals, errs, _d = CM.clean_values(c, _body(required=False), {"who": empty})
        assert errs == [] and "who" not in vals


def test_departments_multi_and_single_ref_behaviour_unchanged():
    c = _conn()
    vals, errs, _d = CM.clean_values(c, _body(key="d", target="departments"), {"d": ["1", 2]})
    assert errs == [] and vals["d"] == ["1", "2"]
    # 單選（沒有 multiple）＝原行為：字串、存在才過
    single = _body(multiple=False)
    vals, errs, _d = CM.clean_values(c, single, {"who": "amy"})
    assert errs == [] and vals["who"] == "amy"
    _v, errs, _d = CM.clean_values(c, single, {"who": "ghost"})
    assert errs and "參照不到" in errs[0]["message"]


def test_ref_labels_resolve_names_for_single_and_multi_and_keep_unknown_codes():
    c = _conn()
    body = {"fields": [{"key": "a", "type": "ref", "target": "users"},
                       {"key": "b", "type": "ref", "target": "departments", "multiple": True},
                       {"key": "n", "type": "text"}]}
    out = CM.ref_labels(c, body, {"a": "amy", "b": ["1", "2", "99"], "n": "x"})
    assert out == {"a": "艾咪", "b": ["工程部", "業務部", "99"]}
    assert CM.ref_labels(c, body, {"a": "", "b": []}) == {}


def test_ref_options_for_departments_lists_names():
    opts = CM.ref_options(_conn(), "departments", "工")
    assert opts == [{"value": 1, "label": "工程部"}]
