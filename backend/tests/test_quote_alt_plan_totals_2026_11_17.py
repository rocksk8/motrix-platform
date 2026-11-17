# -*- coding: utf-8 -*-
"""T88：擇一方案未選完時，報價單／估價單 PDF 與預覽的『四、報價合計』改列各方案金額（使用者 2026-11-17 裁示）。

釘住：
1. 未選完 ⇒ 合計框換成『各方案金額』小表（方案／品項小計／[稅前合計]／營業稅／總計）；標題下說明＝設定中心 total_text＋『請擇一方案，回簽時勾選』。
2. 每個方案的金額＝回簽選定該方案後 `server_totals` 的結果（含共同品項、折讓、運費、稅別）；有共同品項 ⇒ 註明『各方案皆含共同品項 NT$ X』。
3. 兩組以上 ⇒ 列搭配（組合數 ≤ combo_view_max）；超過 ⇒ 兩段式（各組各選項金額＋共同品項），不印搭配總計。
4. 有運費／折讓 ⇒ 多一欄稅前合計；沒有 ⇒ 4 欄。
5. 全選定、總開關沒開、沒有擇一的單：合計框逐位元不變。
6. 客戶版輸出不含成本／毛利字樣與數字；可變文字 esc。估價單共用同一個 builder。
"""
import re
from html.parser import HTMLParser

import pytest

import pdf_gen
from modules.case import alt_policy, alt_view
from modules.case import profit_guard as PG

SECRET_WORDS = ("成本", "毛利", "管銷", "營業利益", "組合", "plan_view", "方案比較")


def _it(id_, qty, price, cost, group=None, **kw):
    d = {"id": id_, "qty": qty, "unitPrice": price, "cost": cost, "amount": qty * price, "description": "品" + id_, "unit": "式"}
    if group is not None:
        d["altGroup"] = group
    d.update(kw)
    return d


def _q(items, picks=None, **kw):
    q = {"quoteNo": "MQ-PLAN-1", "customerName": "客", "taxRate": 5, "items": items, "totalsByAlt": True}
    if picks is not None:
        q["altPicks"] = picks
    q.update(kw)
    return q


def _one_group(**kw):
    """共同品項 a（1000）＋一組『擇一組1』兩個選項（x1 3000、x2 5000）。"""
    return _q([_it("a", 1, 1000, 600), _it("x1", 1, 3000, 2000, "擇一組1"), _it("x2", 1, 5000, 3500, "擇一組1")], **kw)


def _two_groups(**kw):
    return _q([_it("a", 1, 1000, 600), _it("x1", 1, 3000, 2000, "投影機"), _it("x2", 1, 5000, 3500, "投影機"),
               _it("y1", 1, 100, 60, "螢幕"), _it("y2", 1, 150, 90, "螢幕")], **kw)


@pytest.fixture(autouse=True)
def _settings(monkeypatch, client):      # client：載入案件模組，pdf_gen 才找得到 case.alt_view 提供者
    vals = {"total_text": "依方案選擇", "note_template": "項次{items}為{group}擇一方案選擇", "show_unpicked_in_pdf": False, "combo_view_max": 24}
    monkeypatch.setattr(alt_policy, "setting", lambda k, conn=None: vals[k])
    return vals


def _html(q, **kw):
    return pdf_gen._build_quote_html(q, PG.server_totals(q), **kw)


def _body(h):
    return re.sub(r"(?s)\A.*?<body[^>]*>", "", h, count=1)          # 去掉 <head>（含 <style>），只留 <body> 之後


_VOID = {"br", "img", "meta", "link", "input", "hr", "col"}


class _Node:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.kids, self.parts = tag, dict(attrs), [], []

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        return "".join(self.parts) + "".join(k.text() for k in self.kids)

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()

    def find_all(self, tag=None, cls=None):
        return [n for n in self.walk() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())]


class _Tree(HTMLParser):
    """極小的 DOM：測試用結構（標籤、class、欄數）定位，不靠文案子字串。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = _Node(tag, attrs)
        self.stack[-1].kids.append(n)
        if tag not in _VOID:
            self.stack.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].parts.append(data)


def _doc(h):
    t = _Tree()
    t.feed(_body(h))
    t.close()
    return t.root


def _total_rows(doc):
    """原合計框的列：{標籤: 值}（只認 .totals 底下的 .total-row，兩個 span：標籤、值）。"""
    out = {}
    for row in doc.find_all("div", cls="total-row"):
        spans = row.find_all("span")
        if len(spans) >= 2:
            out[spans[0].text()] = spans[1].text()
    return out


def _money(v):
    return "NT$ {:,}".format(int(v))


def _total_after_pick(q, picks):
    return PG.server_totals(dict(q, altPicks=picks))


# ── alt_view.plans（純資料）──────────────────────────────────────────────────

def test_plans_none_when_all_groups_picked_and_present_otherwise():
    assert alt_view.view(_one_group(picks={"擇一組1": "x1"}))["plans"] is None
    assert alt_view.view(_one_group())["plans"]["mode"] == "combos"


def test_each_plan_equals_totals_after_picking_it():
    q = _one_group(freight=500, discount=200)
    rows = alt_view.view(q)["plans"]["rows"]
    assert [r["numbers"] for r in rows] == ["2", "3"] and [r["no"] for r in rows] == ["方案一", "方案二"]
    for r, pick in zip(rows, ("x1", "x2")):
        t = _total_after_pick(q, {"擇一組1": pick})
        assert (r["subtotal"], r["pretax"], r["tax"], r["total"]) == (t["subtotal"], t["pretax"], t["tax"], t["total"]), pick
    assert rows[0]["subtotal"] == 4000 and rows[0]["pretax"] == 4300 and rows[0]["tax"] == 215 and rows[0]["total"] == 4515


def test_two_groups_list_every_pairing_in_item_order():
    q = _two_groups()
    p = alt_view.view(q)["plans"]
    assert p["mode"] == "combos" and len(p["rows"]) == 4
    assert [r["numbers"] for r in p["rows"]] == ["2＋4", "2＋5", "3＋4", "3＋5"]
    assert [r["name"] for r in p["rows"]] == ["品x1＋品y1", "品x1＋品y2", "品x2＋品y1", "品x2＋品y2"]
    for r, picks in zip(p["rows"], ({"投影機": "x1", "螢幕": "y1"}, {"投影機": "x1", "螢幕": "y2"}, {"投影機": "x2", "螢幕": "y1"}, {"投影機": "x2", "螢幕": "y2"})):
        assert r["total"] == _total_after_pick(q, picks)["total"]
    assert p["common"] == {"amount": 1000, "numbers": [1]}


def test_partially_picked_group_becomes_common():
    q = _two_groups(picks={"投影機": "x2"})
    p = alt_view.view(q)["plans"]
    assert [r["numbers"] for r in p["rows"]] == ["3", "4"], "未選的 x1 不印（show_unpicked_in_pdf 關）⇒ 項次往前補"
    assert p["common"]["amount"] == 1000 + 5000                    # 已選定的投影機 x2 併入共同品項
    assert p["rows"][0]["subtotal"] == 6100 and p["rows"][1]["subtotal"] == 6150


def test_over_limit_switches_to_groups_mode(_settings):
    _settings["combo_view_max"] = 3                                # 2×2＝4 > 3
    p = alt_view.view(_two_groups())["plans"]
    assert p["mode"] == "groups" and "rows" not in p
    assert [(g["group"], [o["amount"] for o in g["options"]]) for g in p["groups"]] == [("投影機", [3000, 5000]), ("螢幕", [100, 150])]
    _settings["combo_view_max"] = 4                                # 剛好等於上限 ⇒ 仍列搭配
    assert alt_view.view(_two_groups())["plans"]["mode"] == "combos"


def test_combo_limit_falls_back_when_setting_unreadable_and_is_capped(monkeypatch):
    def boom(k, conn=None):
        if k == "combo_view_max":
            raise RuntimeError("設定讀不到")
        return {"total_text": "依方案選擇", "note_template": "{group}", "show_unpicked_in_pdf": False}[k]
    monkeypatch.setattr(alt_policy, "setting", boom)
    assert alt_view.view(_two_groups())["plans"]["mode"] == "combos"        # 後備 24
    monkeypatch.setattr(alt_policy, "setting", lambda k, conn=None: 9999 if k == "combo_view_max" else "x")
    assert alt_view._combo_limit() == 200                                   # 硬頂


# ── PDF／預覽 ────────────────────────────────────────────────────────────────

def test_pdf_single_group_table_replaces_totals_box():
    q = _one_group()
    h = _html(q)
    b = _body(h)
    assert '<div class="totals">' not in b, "未選完不再印原合計框"
    assert "依方案選擇：請擇一方案，回簽時勾選" in b
    assert _total_rows(_doc(h)) == {}, "兩個合計格不再印文字：原合計框的列整組不在"
    for col in ("方案</th>", "品項小計（未稅）</th>", "營業稅 5%</th>", "總計</th>"):
        assert col in b, col
    assert "稅前合計</th>" not in b, "沒運費／折讓 ⇒ 4 欄"
    assert "方案一　項次 2　品x1" in b and "方案二　項次 3　品x2" in b
    for pick in ("x1", "x2"):
        t = _total_after_pick(q, {"擇一組1": pick})
        assert _money(t["subtotal"]) in b and _money(t["tax"]) in b and _money(t["total"]) in b
    assert "各方案皆含共同品項 NT$ 1,000（項次 1）" in b
    assert _money(PG.server_totals(q)["total"]) not in b, "不印『只算共同品項』的部分合計"


def test_pdf_without_common_items_has_no_common_note():
    q = _q([_it("x1", 1, 3000, 2000, "擇一組1"), _it("x2", 1, 5000, 3500, "擇一組1")])
    b = _body(_html(q))
    assert "共同品項" not in b and "NT$ 3,000" in b and "NT$ 5,250" in b


def test_pdf_with_freight_discount_adds_pretax_column_and_note():
    q = _one_group(freight=500, discount=200)
    b = _body(_html(q))
    assert "稅前合計</th>" in b and "NT$ 4,300" in b and "NT$ 6,300" in b
    assert "各方案同：運費 NT$ 500、折讓 -NT$ 200（已計入稅前合計）" in b
    only_freight = _body(_html(_one_group(freight=500)))
    assert "各方案同：運費 NT$ 500（已計入稅前合計）" in only_freight and "折讓" not in only_freight


@pytest.mark.parametrize("kw,label,tax", [({"taxType": "zero", "taxRate": 0}, "營業稅（零稅率）", 0), ({"taxType": "exempt", "taxRate": 0}, "免稅", 0),
                                          ({"taxRate": 5}, "營業稅 5%", 200)])
def test_pdf_tax_label_and_amounts_follow_tax_type(kw, label, tax):
    q = _q([_it("x1", 1, 4000, 2000, "擇一組1"), _it("x2", 1, 5000, 3500, "擇一組1")], **kw)
    b = _body(_html(q))
    assert label + "</th>" in b
    assert _total_after_pick(q, {"擇一組1": "x1"})["tax"] == tax
    assert _money(_total_after_pick(q, {"擇一組1": "x1"})["total"]) in b


def test_pdf_groups_mode_two_part_layout(_settings):
    _settings["combo_view_max"] = 3
    q = _two_groups(freight=300)
    b = _body(_html(q))
    for col in ("組別</th>", "選項</th>", "金額（未稅）</th>"):
        assert col in b, col
    assert "稅前合計</th>" not in b and "方案一" not in b
    assert "項次 2　品x1" in b and "NT$ 3,000" in b and "NT$ 5,000" in b and "NT$ 150" in b
    assert "共同品項 NT$ 1,000（項次 1），各組選定後依所選項目另加計算總計。" in b
    assert "各方案同：運費 NT$ 300。" in b


def test_pdf_picked_all_keeps_original_totals_box():
    q = _one_group(picks={"擇一組1": "x2"})
    h = _html(q)
    b = _body(h)
    assert '<div class="totals">' in b and "請擇一方案" not in b and "共同品項" not in b
    assert _money(PG.server_totals(q)["total"]) in b


def test_pdf_switch_off_or_no_alt_is_unchanged(monkeypatch):
    q = _one_group(totalsByAlt=False)
    off = _html(q)
    assert '<div class="totals">' in off and "請擇一方案" not in off
    plain = {"quoteNo": "MQ-1", "customerName": "客", "taxRate": 5, "items": [_it("a", 1, 1000, 600), _it("b", 2, 500, 300)]}
    with_prov = _html(plain)
    monkeypatch.setattr(pdf_gen, "_alt_view", lambda q: {})
    assert _html(plain) == with_prov


def test_pdf_falls_back_to_old_box_when_plan_data_is_broken(monkeypatch):
    real = alt_view.view
    monkeypatch.setattr(pdf_gen, "_alt_view", lambda q: dict(real(q), plans={"mode": "combos"}))      # 缺 rows ⇒ KeyError 被吞
    h = _html(_one_group())
    assert '<div class="totals">' in _body(h)
    rows = _total_rows(_doc(h))
    assert rows["稅前合計"] == rows["總　計"] == "依方案選擇", "退回原合計框：兩格仍印設定文字"


def test_pdf_escapes_every_variable_text(_settings):
    q = _one_group(altTexts={"total_text": "<b>X</b>", "note_template": "{group}"})
    q["items"][1]["altGroup"] = q["items"][2]["altGroup"] = "<i>組</i>"
    q["items"][1]["description"] = "<script>alert(1)</script>"
    h = _html(q)
    assert "<script>alert(1)" not in h and "<b>X</b>" not in h and "<i>組</i>" not in h
    _settings["combo_view_max"] = 1
    h = _html(q)                                                    # 兩段式也要跳脫組名與品名
    assert "<script>alert(1)" not in h and "<i>組</i>" not in h and "&lt;script&gt;" in h


def test_long_item_name_is_truncated_in_plan_name():
    q = _one_group()
    q["items"][1]["description"] = "甲" * 40 + "\n第二行"
    row = alt_view.view(q)["plans"]["rows"][0]
    assert row["name"] == "甲" * 16 + "…" and "第二行" not in row["name"]


def test_estimate_uses_same_table_with_estimate_label():
    q = _one_group(docType="estimate", quoteNo="ME-PLAN-1")
    h = _html(q)
    b = _body(h)
    assert "四、估價合計" in b and "請擇一方案，回簽時勾選" in b and "方案一" in b
    assert '<div class="totals">' not in b


def test_customer_output_never_leaks_cost_or_internal_words():
    for q in (_one_group(), _two_groups(), _one_group(freight=100, discount=50)):
        b = _body(_html(q))
        for w in SECRET_WORDS:
            assert w not in b, w
        for n in ("2000", "3500", "2,000", "3,500", "600"):
            assert ("NT$ " + n) not in b, n


def test_preview_uses_same_builder_and_shows_plans():
    prev = pdf_gen.build_quote_preview_html(_one_group(), "草稿", "未成案")
    assert "方案一　項次 2" in prev and "請擇一方案，回簽時勾選" in prev


def test_pdf_and_view_do_not_reference_internal_plan_module():
    import pathlib
    src = pathlib.Path(pdf_gen.__file__).read_text(encoding="utf-8")
    assert "plan_view" not in src and "alt_options" not in src
    vsrc = pathlib.Path(alt_view.__file__).read_text(encoding="utf-8")
    assert "import alt_options" not in vsrc and "alt_options import" not in vsrc and "plan_view(" not in vsrc


def test_plan_table_html_has_no_unbalanced_tags():
    doc = _doc(_html(_two_groups(freight=100)))
    plan = [t for t in doc.find_all("table") if t.find_all("th") and t.find_all("th")[0].text() == "方案"][0]
    assert len(plan.find_all("th")) == 5, "有運費 ⇒ 方案／品項小計／稅前合計／稅額／總計"
    assert len(plan.find_all("tr")) >= 2
    for tr in plan.find_all("tr")[1:]:
        assert len(tr.find_all("td")) == 5, "每列欄數＝表頭欄數（標籤沒配對好會對不上）"


def test_plans_failure_does_not_break_view_or_pdf_and_falls_back_to_old_box(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("算不出來")
    monkeypatch.setattr(alt_view, "plans", boom)
    q = _one_group()
    v = alt_view.view(q)
    assert v["has_alt"] is True and v["plans"] is None and v["total_text"] == "依方案選擇"
    b = _body(_html(q))
    assert '<div class="totals">' in b and "請擇一方案" not in b
    rows = _total_rows(_doc(_html(q)))
    assert rows["稅前合計"] == rows["總　計"] == "依方案選擇", "退回原合計框：兩格仍印設定文字"


def test_alt_view_has_no_double_star_call_arguments():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(alt_view.__file__).read_text(encoding="utf-8"))
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and any(k.arg is None for k in n.keywords)]
    assert bad == [], "守門（test_case_summary_purpose）禁止 ** 傳參數：%s" % bad
