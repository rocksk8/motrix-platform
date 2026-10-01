# -*- coding: utf-8 -*-
"""表單設計器資料層（static/form-designer-model.js）的契約題——在真瀏覽器載入那支檔，用 evaluate 呼叫（不需要伺服器）。

- G-D2 相容：每份出貨的請款類型定義（expense_type_defs/*.json）載入後不動就輸出，位元相同；空 groups 仍是空、list.columns 保持原順序、
  不認得的鍵（output.template、未知欄位屬性）原樣保留；設計器暫存鍵（底線開頭）輸出時剔除。
- 計算器 build⇄parse 往返；認不得的公式不被改寫（進階公式）；明細表欄的 `round_half_up(qty * unitCost)` 認得為「數量×單價（四捨五入）」。
- 區塊：groups 為空時的虛擬區塊、孤兒欄位接在「其他」、重複代碼偵測、跨區塊搬移、清單欄位插入位置（不重排其他欄）。
- 引用檢查（刪除前）、自動帶入的可用來源與「不能改」限制、本機檢查。
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "frontend" / "static" / "form-designer-model.js"
DEFS = ROOT / "backend" / "helpers" / "expense_type_defs"


@pytest.fixture()
def M(new_context):
    page = new_context().new_page()
    page.set_content("<html><body></body></html>")
    page.add_script_tag(path=str(MODEL))

    class _M:
        def call(self, expr, arg=None):
            return page.evaluate("(a) => { const M = window.FDModel; return (%s) }" % expr, arg)
    return _M()


def test_every_shipped_expense_def_round_trips_unchanged(M):
    names = sorted(p.name for p in DEFS.glob("*.json"))
    assert names, "找不到出貨的請款類型定義"
    for n in names:
        d = json.loads((DEFS / n).read_text(encoding="utf-8"))
        out = M.call("M.strip(a)", d)
        assert out == d, n + "：不動就輸出應與原檔相同"


def test_unknown_keys_and_designer_scratch_keys(M):
    d = {"fields": [{"key": "a", "label": "甲", "type": "text", "weird": {"x": 1}, "_calc": {"p": "sum"},
                     "columns": [{"key": "c", "_tmp": 1}]}], "output": {"template": {"blocks": ["a"]}}, "ui": {"form": {"groups": []}}}
    out = M.call("M.strip(a)", d)
    assert out["output"] == d["output"] and out["fields"][0]["weird"] == {"x": 1}
    assert "_calc" not in out["fields"][0] and "_tmp" not in out["fields"][0]["columns"][0]
    assert out["ui"]["form"]["groups"] == []


def test_empty_groups_is_one_virtual_section_and_stays_empty_until_a_section_is_added(M):
    d = {"fields": [{"key": "a", "label": "甲", "type": "text"}, {"key": "b", "label": "乙", "type": "text"}], "ui": {"form": {"groups": []}}}
    assert M.call("M.groupsOf(a).map(g => [g.virtual === true, g.keys])", d) == [[True, ["a", "b"]]]
    out = M.call("(() => { const x = M.clone(a); M.addField(x, { id: 'text', type: 'text', preset: {} }, '丙'); return x })()", d)
    assert out["ui"]["form"]["groups"] == [], "加欄位不應把空 groups 變成明確區塊"
    assert [f["label"] for f in out["fields"]] == ["甲", "乙", "丙"]
    out = M.call("(() => { const x = M.clone(a); M.addSection(x); return x })()", d)
    assert out["ui"]["form"]["groups"] == [{"title": "基本資料", "fields": ["a", "b"]}, {"title": "新區塊", "fields": []}]


def test_orphans_are_shown_under_other_and_duplicates_are_detected(M):
    d = {"fields": [{"key": "a", "label": "甲", "type": "text"}, {"key": "b", "label": "乙", "type": "text"}, {"key": "c", "label": "丙", "type": "text"}],
         "ui": {"form": {"groups": [{"title": "一", "fields": ["a", "ghost"]}, {"title": "二", "fields": ["a", "b"]}]}}}
    assert M.call("M.groupsOf(a).map(g => [g.title, g.keys, !!g.other])", d) == [["一", ["a"], False], ["二", ["b"], False], ["其他", ["c"], True]]
    assert M.call("M.orphans(a)", d) == ["c"] and M.call("M.duplicateKeys(a)", d) == ["a"]


def test_list_columns_keep_their_order_and_new_ones_are_inserted_after_the_nearest_shown_predecessor(M):
    d = {"fields": [{"key": k, "label": k, "type": "text"} for k in "abcd"], "ui": {"form": {"groups": []}, "list": {"columns": ["d", "a"]}}}
    out = M.call("(() => { const x = M.clone(a); M.setListed(x, 'c', true); return x.ui.list.columns })()", d)
    assert out == ["d", "a", "c"], "c 的前一個已顯示欄位是 a ⇒ 接在 a 後面，原本的 d,a 順序不動"
    out = M.call("(() => { const x = M.clone(a); M.setListed(x, 'a', false); return x.ui.list.columns })()", d)
    assert out == ["d"]
    assert M.call("(() => { const x = M.clone(a); M.setListed(x, 'a', true); return x.ui.list.columns })()", d) == ["d", "a"], "已在清單的不重複加"


def test_move_between_sections_nudge_across_the_edge_and_never_duplicates(M):
    d = {"fields": [{"key": k, "label": k, "type": "text"} for k in "abc"],
         "ui": {"form": {"groups": [{"title": "一", "fields": ["a", "b"]}, {"title": "二", "fields": ["c"]}]}}}
    out = M.call("(() => { const x = M.clone(a); M.nudge(x, 'b', 1); return x.ui.form.groups })()", d)
    assert out == [{"title": "一", "fields": ["a"]}, {"title": "二", "fields": ["b", "c"]}]
    out = M.call("(() => { const x = M.clone(a); M.placeKey(x, 'a', 1, 1); return x.ui.form.groups })()", d)
    assert out == [{"title": "一", "fields": ["b"]}, {"title": "二", "fields": ["c", "a"]}]
    assert M.call("(() => { const x = M.clone(a); M.placeKey(x, 'a', 1, 1); return M.duplicateKeys(x) })()", d) == []


def test_remove_field_cleans_groups_and_list_and_reports_references(M):
    d = {"fields": [{"key": "qty", "label": "數量", "type": "number"}, {"key": "tot", "label": "合計", "type": "formula", "formula": "qty * 2"},
                    {"key": "t", "label": "明細", "type": "table", "columns": [{"key": "x", "label": "X", "type": "number"}, {"key": "y", "label": "Y", "type": "formula", "formula": "x * 2"}]}],
         "ui": {"form": {"groups": [{"title": "一", "fields": ["qty", "tot", "t"]}]}, "list": {"columns": ["qty", "tot"]}}, "output": {"template": {"x": "tot"}}}
    uses = M.call("M.usedBy(a, 'qty')", d)
    assert [u["key"] for u in uses] == ["tot"] and "用到它" in uses[0]["text"]
    assert any(u["where"] == "output" for u in M.call("M.usedBy(a, 'tot')", d))
    out = M.call("(() => { const x = M.clone(a); M.removeField(x, 'qty'); return x })()", d)
    assert [f["key"] for f in out["fields"]] == ["tot", "t"] and out["ui"]["form"]["groups"][0]["fields"] == ["tot", "t"] and out["ui"]["list"]["columns"] == ["tot"]


@pytest.mark.parametrize("formula,kind", [
    ('total(lines, "amount")', "sumtable"), ("a + b + c", "sum"), ("a * b", "mul"), ("a - b", "sub"),
    ("round_half_up(a * 30 / 100)", "pct"), ("days_between(a, b)", "days"), ("round_half_up(a * 0.05)", "tax"),
    ("round_half_up(a * 1.05)", "tax"), ("round_half_up(a - a / 1.05)", "tax"), ("round_half_up(qty * unitCost)", "mul"),
])
def test_known_formulas_round_trip_through_the_calculators(M, formula, kind):
    c = M.call("M.parseCalcExact(a)", formula)
    assert c and c["p"] == kind
    assert M.call("M.buildCalc(M.parseCalcExact(a))", formula) == formula


@pytest.mark.parametrize("formula", ["if(a > 1, 2, 3)", "a * b + c", "round(a / 3, 2)", "coalesce(a, 0) + b"])
def test_unrecognised_formulas_stay_advanced_and_are_never_rewritten(M, formula):
    assert M.call("M.parseCalcExact(a)", formula) is None


def test_calculator_examples_and_incomplete_settings(M):
    d = {"fields": [{"key": "net", "label": "未稅", "type": "number"}]}
    assert M.call("M.calcResult(a, { p: 'tax', a: 'net', mode: 'net', out: 'tax', rate: '5' })", d) == 50, "未稅 1,000（樣本）× 5%"
    assert M.call("M.calcResult(a, { p: 'tax', a: 'net', mode: 'net', out: 'gross', rate: 'free' })", d) == 1000
    assert M.call("M.calcResult(a, { p: 'sumtable' })", d) == 6000
    assert M.call("M.buildCalc({ p: 'mul', a: 'qty' })") == "", "沒選完整就不產生公式"
    assert M.call("M.localProblems({ fields: [{ key: 'f', label: '算', type: 'formula', formula: '' }] }, {}).map(p => p.path)") == ["fields[0].formula"]


def test_prefill_sources_filtering_and_the_lock_rule(M):
    reg = [{"token": "requester", "applies_to": [["ref", "users"]], "lockable": True},
           {"token": "requesterDept", "applies_to": [["ref", "departments"]], "lockable": True},
           {"token": "now", "applies_to": [["date", None]], "lockable": True, "requires_time": True},
           {"token": "today", "applies_to": [["date", None]], "lockable": True},
           {"token": "caseCustomer", "applies_to": [["text", None]], "lockable": False, "needs_context": True},
           {"token": "lastUsed", "applies_to": [["text", None], ["date", None]], "lockable": False}]
    names = lambda f, case=False: M.call("M.fillsFor(a.f, a.r, a.c).map(s => s.token)", {"f": f, "r": reg, "c": case})
    assert names({"type": "ref", "target": "users"}) == ["requester"] and names({"type": "ref", "target": "departments"}) == ["requesterDept"]
    assert names({"type": "date"}) == ["today", "lastUsed"] and names({"type": "date", "withTime": True}) == ["now", "today", "lastUsed"]
    assert names({"type": "text"}) == ["lastUsed"] and names({"type": "text"}, True) == ["caseCustomer", "lastUsed"]
    can = lambda f: M.call("M.canLock(a.f, a.r)", {"f": f, "r": reg})
    assert can({"type": "text"})["ok"] is False                                          # 沒選來源
    assert can({"type": "text", "default": {"$": "lastUsed"}})["ok"] is False             # 不可鎖
    assert can({"type": "ref", "target": "users", "default": {"$": "requester"}})["ok"] is True
    assert can({"type": "text", "default": "固定"})["ok"] is True
