# -*- coding: utf-8 -*-
"""BP-2 R0：規則文法驗證器與評估器（純函式，不需要資料庫）。
- 文法：合法規則通過；任何不在文法內的輸入都回問題清單（突變參數化）；上限（節點、深度、規則數、文字）
- 評估：三態（缺值＝unknown＝不標記）、and/or/not 的 Kleene 語意、between/in/empty
- 遮蔽優先：條件用到檢視者看不到的欄位 ⇒ 不評估（結果裡不出現、不計命中）
- 故障：預算用完／評估例外 ⇒ 只丟那一條規則並回報 degraded，其他規則照常、不丟例外
- 靜態守門：評估器與文法模組不得 import 或呼叫 eval／exec／compile／importlib／subprocess／os（附故意違規的正對照）"""
import ast
import copy
from pathlib import Path

import pytest

from helpers import rule_engine as E
from helpers import rule_grammar as G

FIELDS = {
    "netMarginPct": {"type": "number"},
    "total": {"type": "number"},
    "status": {"type": "enum", "options": ["草稿", "已送出", "已成交"]},
    "note": {"type": "text"},
    "startDate": {"type": "date"},
    "urgent": {"type": "bool"},
}


_DEFAULT = object()


def rule(rid="low_margin", when=_DEFAULT, **kw):
    r = {"id": rid, "name": "低毛利", "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
         "when": {"op": "lt", "field": "netMarginPct", "value": 15} if when is _DEFAULT else when,
         "mark": {"level": "red", "text": "毛利偏低", "target": "row"}}
    r.update(kw)
    return r


def v(rules):
    return G.validate_rule_set({"rules": rules}, FIELDS)


def rec(i, **vals):
    return {"id": i, "values": vals}


ALL = set(FIELDS)


# ── 文法 ───────────────────────────────────────────────────────────────────────
def test_a_valid_rule_set_passes_and_empty_is_valid():
    assert v([rule()]) == [] and G.validate_rule_set({"rules": []}, FIELDS) == [] and G.validate_rule_set({}, FIELDS) == []


@pytest.mark.parametrize("when", [
    {"op": "lt", "field": "netMarginPct", "value": 15},
    {"op": "between", "field": "total", "min": 1, "max": 9},
    {"op": "in", "field": "status", "values": ["草稿", "已送出"]},
    {"op": "empty", "field": "note"}, {"op": "not_empty", "field": "startDate"},
    {"op": "eq", "field": "urgent", "value": True},
    {"op": "gt", "field": "startDate", "value": "2026-10-14"},
    {"op": "and", "args": [{"op": "lt", "field": "total", "value": 5}, {"op": "not", "arg": {"op": "eq", "field": "status", "value": "已成交"}}]},
])
def test_each_supported_shape_is_valid(when):
    assert v([rule(when=when)]) == []


@pytest.mark.parametrize("bad", [
    None, [], "x", 5, {"op": "lt"}, {"op": "lt", "field": "nope", "value": 1}, {"op": "lt", "field": "netMarginPct", "value": "15"},
    {"op": "lt", "field": "netMarginPct", "value": True}, {"op": "lt", "field": "netMarginPct", "value": float("inf")},
    {"op": "lt", "field": "netMarginPct", "value": 1, "extra": 1}, {"op": "like", "field": "note", "value": "x"},
    {"op": "lt", "field": "note", "value": "x"},                                   # 文字欄不能比大小
    {"op": "eq", "field": "status", "value": "不存在的選項"},
    {"op": "between", "field": "total", "min": 9, "max": 1}, {"op": "between", "field": "total", "min": 1},
    {"op": "in", "field": "status", "values": []}, {"op": "in", "field": "status", "values": "草稿"},
    {"op": "gt", "field": "startDate", "value": "2026-13-45"}, {"op": "gt", "field": "startDate", "value": "yesterday"},
    {"op": "and", "args": []}, {"op": "and"}, {"op": "not"}, {"op": "or", "args": "x"},
    {"op": "eq", "field": "urgent", "value": 1},
    {"op": "lt", "field": "netMarginPct", "value": "__import__('os')"},               # 運算式字串當然不行
])
def test_anything_outside_the_grammar_is_rejected(bad):
    assert v([rule(when=bad)]), bad


@pytest.mark.parametrize("patch", [
    {"mode": "block"}, {"on_failure": "fail_closed"}, {"enabled": "yes"}, {"id": "Bad-Id"}, {"id": "x"}, {"name": ""}, {"name": "字" * 31},
    {"unknown": 1}, {"mark": None}, {"mark": {"level": "purple", "text": "x"}}, {"mark": {"level": "red", "text": ""}},
    {"mark": {"level": "red", "text": "字" * 41}}, {"mark": {"level": "red", "text": "{threshold}"}}, {"mark": {"level": "red", "text": "<b>x</b>"}},
    {"mark": {"level": "red", "text": "x", "target": "field"}}, {"mark": {"level": "red", "text": "x", "target": "field", "field": "nope"}},
    {"mark": {"level": "red", "text": "x", "target": "row", "field": "total"}}, {"mark": {"level": "red", "text": "x", "extra": 1}},
])
def test_rule_level_mutations_are_rejected(patch):
    assert v([rule(**patch)]), patch


def test_duplicate_ids_and_too_many_rules_are_rejected():
    assert v([rule("aa"), rule("aa")])
    assert v([rule("r%02d" % i) for i in range(G.LIMITS["rules"] + 1)])
    assert v([rule("r%02d" % i) for i in range(G.LIMITS["rules"])]) == []


def test_node_and_depth_limits():
    deep = {"op": "eq", "field": "urgent", "value": True}
    for _ in range(G.LIMITS["depth"]):
        deep = {"op": "not", "arg": deep}
    assert v([rule(when=deep)])                                                    # 深度 9
    ok = {"op": "eq", "field": "urgent", "value": True}
    for _ in range(G.LIMITS["depth"] - 1):
        ok = {"op": "not", "arg": ok}
    assert v([rule(when=ok)]) == []                                                # 深度 8
    wide = {"op": "or", "args": [{"op": "eq", "field": "urgent", "value": True}] * (G.LIMITS["nodes"] + 1)}
    assert v([rule(when=wide)])


def test_validator_never_raises_on_garbage():
    for junk in (None, 5, "x", [], {"rules": None}, {"rules": [None]}, {"rules": [{"when": object()}]}, {"rules": [[]]}):
        assert isinstance(G.validate_rule_set(junk, FIELDS), list)
    assert G.validate_rule_set({"rules": [rule()]}, None)                          # 沒有目錄 ⇒ 欄位都不在目錄內 ⇒ 不合法


# ── 評估 ───────────────────────────────────────────────────────────────────────
def run(rules, records, visible=ALL, **kw):
    return E.evaluate(rules, records, visible, **kw)


def test_basic_marks_and_hit_counts():
    out = run([rule()], [rec(1, netMarginPct=10), rec(2, netMarginPct=15), rec(3, netMarginPct=20)])
    assert list(out["marks"]) == [1] and out["hits"] == {"low_margin": 1} and out["degraded"] == []
    assert out["marks"][1] == [{"ruleId": "low_margin", "level": "red", "text": "毛利偏低", "target": "row"}]


def test_missing_value_is_unknown_not_zero():
    out = run([rule()], [rec(1), rec(2, netMarginPct=None), rec(3, netMarginPct="")])
    assert out["marks"] == {} and out["hits"] == {"low_margin": 0}                 # 缺＝不標記（不當 0 ⇒ 不會被『< 15』抓到）


def test_kleene_logic():
    a, b = {"op": "lt", "field": "total", "value": 5}, {"op": "eq", "field": "urgent", "value": True}
    both = rule(when={"op": "and", "args": [a, b]})
    either = rule("either", when={"op": "or", "args": [a, b]})
    neg = rule("neg", when={"op": "not", "arg": b})
    out = run([both, either, neg], [rec(1, total=1), rec(2, total=9, urgent=True), rec(3, total=1, urgent=True), rec(4, total=9, urgent=False)])
    got = {r: sorted(i for i, ms in out["marks"].items() for m in ms if m["ruleId"] == r) for r in ("low_margin", "either", "neg")}
    assert got == {"low_margin": [3], "either": [1, 2, 3], "neg": [4]}
    # unknown 與 false 的 and ＝ false；與 true 的 and ＝ unknown（不標記）
    assert 1 not in out["marks"] or all(m["ruleId"] != "low_margin" for m in out["marks"][1])


def test_type_mismatch_in_data_is_unknown_not_a_failure():
    out = run([rule()], [rec(1, netMarginPct="很低"), rec(2, netMarginPct=True), rec(3, netMarginPct=[1])])
    assert out["marks"] == {} and out["degraded"] == []


def test_between_in_empty_dates():
    rules = [rule("btw", when={"op": "between", "field": "total", "min": 5, "max": 10}),
             rule("inn", when={"op": "in", "field": "status", "values": ["草稿"]}),
             rule("emp", when={"op": "empty", "field": "note"}),
             rule("dat", when={"op": "lt", "field": "startDate", "value": "2026-10-14"})]
    out = run(rules, [rec(1, total=5, status="草稿", note="", startDate="2026-01-01"), rec(2, total=11, status="已成交", note="x", startDate="2027-01-01")])
    assert out["hits"] == {"btw": 1, "inn": 1, "emp": 1, "dat": 1}
    assert {m["ruleId"] for m in out["marks"][1]} == {"btw", "inn", "emp", "dat"} and 2 not in out["marks"]


def test_disabled_rules_are_ignored_and_field_target_is_carried():
    r = rule("fld", mark={"level": "yellow", "text": "注意", "target": "field", "field": "total"}, when={"op": "gt", "field": "total", "value": 1})
    out = run([rule(enabled=False), r], [rec(1, total=5, netMarginPct=1)])
    assert out["hits"] == {"fld": 1} and out["marks"][1] == [{"ruleId": "fld", "level": "yellow", "text": "注意", "target": "field", "field": "total"}]


# ── 遮蔽優先 ───────────────────────────────────────────────────────────────────
def test_rule_on_a_hidden_field_is_not_evaluated_and_leaves_no_trace():
    records = [rec(1, netMarginPct=1, total=100), rec(2, netMarginPct=99, total=100)]
    seen = run([rule()], records, visible=ALL)
    masked = run([rule()], records, visible=ALL - {"netMarginPct"})
    assert 1 in seen["marks"] and seen["hits"] == {"low_margin": 1}
    assert masked["marks"] == {} and masked["hits"] == {} and masked["degraded"] == [] and masked["notApplicable"] == ["low_margin"]
    # 紅或不紅都推不出毛利：兩筆（毛利 1 與 99）在遮蔽下的輸出逐位元相同
    assert run([rule()], records[:1], visible=ALL - {"netMarginPct"}) == run([rule()], records[1:], visible=ALL - {"netMarginPct"})


def test_any_hidden_field_in_a_compound_condition_hides_the_whole_rule():
    cond = rule(when={"op": "and", "args": [{"op": "lt", "field": "total", "value": 5}, {"op": "lt", "field": "netMarginPct", "value": 5}]})
    out = run([cond], [rec(1, total=1, netMarginPct=1)], visible={"total"})
    assert out["marks"] == {} and out["notApplicable"] == ["low_margin"]


def test_values_of_hidden_fields_are_never_read():
    class Trap(dict):
        def get(self, k, d=None):
            if k == "netMarginPct":
                raise AssertionError("讀了被遮蔽的欄位")
            return super().get(k, d)
    r = rule("only_total", when={"op": "lt", "field": "total", "value": 5})
    out = run([r], [{"id": 1, "values": Trap(total=1, netMarginPct=1)}], visible={"total"})
    assert 1 in out["marks"]


# ── 故障 ───────────────────────────────────────────────────────────────────────
def test_budget_overrun_degrades_only_the_late_rules():
    ticks = iter([0.0, 0.0] + [100.0] * 1000)                                       # 第一次檢查在預算內，之後都超時
    out = run([rule("first"), rule("second")], [rec(i, netMarginPct=1) for i in range(5)], budget_ms=10, clock=lambda: next(ticks))
    assert {d["ruleId"] for d in out["degraded"]} <= {"first", "second"} and out["degraded"]
    assert all(d["reason"] == "budget" for d in out["degraded"])
    for d in out["degraded"]:
        assert d["ruleId"] not in out["hits"] and all(m["ruleId"] != d["ruleId"] for ms in out["marks"].values() for m in ms)


def test_an_evaluator_error_drops_only_that_rule_and_never_raises():
    broken = rule("broken", when={"op": "lt", "field": "total"})                    # 沒有 value ⇒ KeyError（驗證器擋得住，這裡模擬被繞過）
    out = run([broken, rule()], [rec(1, netMarginPct=1, total=1)])
    assert out["degraded"] == [{"ruleId": "broken", "reason": "error"}] and out["hits"] == {"low_margin": 1}


@pytest.mark.parametrize("junk", [None, [None], [5], ["x"], [{}], [{"id": "a"}]])
def test_garbage_rules_or_records_never_raise(junk):
    assert isinstance(E.evaluate(junk, [rec(1, total=1)], ALL), dict)
    assert isinstance(E.evaluate([rule()], junk, ALL), dict)


def test_non_mark_modes_are_not_applicable_even_if_validation_was_bypassed():
    out = run([rule(mode="block")], [rec(1, netMarginPct=1)])
    assert out["marks"] == {} and out["notApplicable"] == ["low_margin"]


def test_evaluation_does_not_mutate_its_inputs():
    rules, records = [rule()], [rec(1, netMarginPct=1)]
    r0, c0 = copy.deepcopy(rules), copy.deepcopy(records)
    run(rules, records)
    assert rules == r0 and records == c0


# ── 靜態守門 ───────────────────────────────────────────────────────────────────
_BANNED_IMPORTS = {"importlib", "subprocess", "os", "sys", "builtins", "ctypes", "socket", "sqlite3", "db"}
_BANNED_CALLS = {"eval", "exec", "compile", "__import__", "open", "getattr", "setattr", "globals", "locals"}


def _violations(src):
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names if a.name.split(".")[0] in _BANNED_IMPORTS]
        elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in _BANNED_IMPORTS:
            out.append(n.module)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _BANNED_CALLS:
            out.append(n.func.id)
    return out


@pytest.mark.parametrize("name", ["rule_engine.py", "rule_grammar.py"])
def test_evaluator_and_grammar_modules_are_pure(name):
    src = (Path(E.__file__).parent / name).read_text(encoding="utf-8")
    assert _violations(src) == []


def test_the_static_scan_catches_violations_positive_control():
    assert _violations("import os\nx = eval('1')") == ["os", "eval"]
    assert _violations("from subprocess import run\ncompile('x','y','exec')") == ["subprocess", "compile"]
