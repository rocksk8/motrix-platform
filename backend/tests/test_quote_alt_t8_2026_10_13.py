# -*- coding: utf-8 -*-
"""M3 T7／T8（T57）：altTexts 存檔快照、客戶版輸出資料 case.alt_view、PDF／預覽的擇一呈現與成本不外洩。"""
import json

import pytest

import db
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


def _q(picks=None, **kw):
    q = {"quoteNo": "MQ-ALT-1", "customerName": "客", "taxRate": 5,
         "items": [_it("a", 1, 1000, 600), _it("h", 0, 0, 0, type="header", description="標題"), _it("x1", 1, 3000, 2000, "投影機"),
                   _it("x2", 1, 5000, 3500, "投影機"), _it("y1", 1, 100, 60, "線材"), _it("y2", 1, 150, 90, "線材")],
         "afterSales": "保固一年"}
    if picks is not None:
        q["altPicks"] = picks
    q.update(kw)
    return q


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    vals = {"total_text": "依方案選擇", "note_template": "項次{items}為{group}擇一方案選擇", "show_unpicked_in_pdf": False}
    monkeypatch.setattr(alt_policy, "setting", lambda k, conn=None: vals[k])
    return vals


def _html(q, **kw):
    tot = PG.server_totals(q)
    return pdf_gen._build_quote_html(q, tot, **kw)


# --- alt_view（純資料）---------------------------------------------------------------

def test_view_without_alt_is_empty():
    assert alt_view.view({"items": [_it("a", 1, 1, 1)]}) == {"has_alt": False}


def test_view_pending_numbers_notes_and_total_text():
    v = alt_view.view(_q(totalsByAlt=True))
    assert v["unpicked_groups"] == 2 and v["total_text"] == "依方案選擇"
    assert v["numbers"] == {"a": 1, "x1": 2, "x2": 3, "y1": 4, "y2": 5}      # 標題列不佔項次
    assert v["notes"] == ["項次2、3為投影機擇一方案選擇", "項次4、5為線材擇一方案選擇"]
    assert {r["state"] for r in v["rows"].values()} == {"pending"}


def test_view_total_text_needs_flag_and_unpicked_group():
    assert alt_view.view(_q())["total_text"] is None
    assert alt_view.view(_q({"投影機": "x1", "線材": "y1"}, totalsByAlt=True))["total_text"] is None
    assert alt_view.view(_q({"投影機": "x1"}, totalsByAlt=True))["total_text"] == "依方案選擇"


def test_view_picked_hides_unpicked_by_default_and_renumbers(_settings):
    v = alt_view.view(_q({"投影機": "x2", "線材": "y1"}))
    assert v["rows"]["x1"]["hidden"] and v["rows"]["y2"]["hidden"] and not v["rows"]["x2"]["hidden"]
    assert v["numbers"] == {"a": 1, "x2": 2, "y1": 3}
    assert v["notes"] == ["項次2為投影機擇一方案選擇", "項次3為線材擇一方案選擇"]
    _settings["show_unpicked_in_pdf"] = True
    v = alt_view.view(_q({"投影機": "x2", "線材": "y1"}))
    assert not v["rows"]["x1"]["hidden"] and v["rows"]["x1"]["tag"] == "未選" and v["numbers"]["x1"] == 2


def test_view_uses_snapshot_over_current_settings():
    q = _q(altTexts={"total_text": "舊文字", "note_template": "舊句{group}"}, totalsByAlt=True)
    v = alt_view.view(q)
    assert v["total_text"] == "舊文字" and v["notes"][0] == "舊句投影機"


def test_render_note_is_single_pass_and_never_formats():
    assert alt_view.render_note("{group}:{items}", "{items}", [1, 2]) == "{items}:1、2"
    assert alt_view.render_note("{0}{x}", "g", [1]) == "{0}{x}"
    assert alt_view.render_note("a{group}b", "%s{", []) == "a%s{b"


# --- altTexts 存檔快照 -------------------------------------------------------------------

def test_stamp_drops_client_value_and_takes_current():
    q = _q(altTexts={"total_text": "偽造", "note_template": "偽造"})
    PG.stamp_alt_texts(q, {}, freeze=False)
    assert q["altTexts"] == {"total_text": "依方案選擇", "note_template": "項次{items}為{group}擇一方案選擇"}


def test_stamp_freeze_keeps_old_snapshot_but_unfrozen_refreshes(_settings):
    old = {"altTexts": {"total_text": "當時", "note_template": "當時{group}"}}
    q = _q()
    PG.stamp_alt_texts(q, old, freeze=True)
    assert q["altTexts"]["total_text"] == "當時"
    q = _q()
    PG.stamp_alt_texts(q, old, freeze=False)
    assert q["altTexts"]["total_text"] == "依方案選擇"
    q = _q()
    PG.stamp_alt_texts(q, {}, freeze=True)          # 凍結但舊單沒快照 ⇒ 取目前
    assert q["altTexts"]["total_text"] == "依方案選擇"


def test_stamp_removed_when_no_alt_content():
    q = {"items": [_it("a", 1, 1, 1)], "altTexts": {"total_text": "x", "note_template": "y"}}
    PG.stamp_alt_texts(q, {}, freeze=False)
    assert "altTexts" not in q
    q = {"items": [_it("a", 1, 1, 1)], "totalsByAlt": True}
    PG.stamp_alt_texts(q, {}, freeze=False)
    assert "altTexts" in q


# --- PDF／預覽 ----------------------------------------------------------------------------

def test_pdf_no_alt_quote_identical_with_or_without_provider(client, monkeypatch):
    q = {"quoteNo": "MQ-1", "customerName": "客", "taxRate": 5, "items": [_it("a", 1, 1000, 600), _it("b", 2, 500, 300)]}
    with_prov = _html(q)
    monkeypatch.setattr(pdf_gen, "_alt_view", lambda q: {})
    assert _html(q) == with_prov


def test_pdf_pending_shows_total_text_tags_and_note(client):
    h = _html(_q(totalsByAlt=True))
    assert h.count("依方案選擇") == 2                        # 稅前合計、總計兩格
    assert "〔擇一：投影機〕" in h and "〔擇一：線材〕" in h
    assert "項次2、3為投影機擇一方案選擇" in h and "保固一年" in h
    assert h.index("保固一年") < h.index("項次2、3為投影機")     # 自動句接在使用者備註之後


def test_pdf_without_flag_prints_numbers_even_if_unpicked(client):
    h = _html(_q())
    assert "依方案選擇" not in h.replace("擇一方案選擇", "")
    t = PG.server_totals(_q())
    assert "NT$ %s" % format(t["total"], ",") in h


def test_pdf_picked_restores_numbers_and_drops_unpicked(client):
    q = _q({"投影機": "x2", "線材": "y1"}, totalsByAlt=True)
    h = _html(q)
    assert "品x1" not in h and "品y2" not in h and "品x2" in h and "品y1" in h
    assert "NT$ %s" % format(PG.server_totals(q)["total"], ",") in h
    assert "未選" not in h.replace("擇一方案選擇", "")


def test_pdf_show_unpicked_grays_with_tag(client, _settings):
    _settings["show_unpicked_in_pdf"] = True
    h = _html(_q({"投影機": "x2", "線材": "y1"}))
    assert "品x1" in h and "〔未選〕" in h and "color:#9CA3AF" in h


def test_pdf_escapes_group_name_and_snapshot_text(client):
    q = _q(altTexts={"total_text": "<b>X</b>", "note_template": "<i>{group}</i>"}, totalsByAlt=True)
    q["items"][2]["altGroup"] = q["items"][3]["altGroup"] = "<script>alert(1)</script>"
    h = _html(q)
    assert "<script>alert(1)" not in h and "<b>X</b>" not in h and "<i>" not in h


def test_customer_pdf_contains_no_cost_or_plan_words(client):
    for q in (_q(totalsByAlt=True), _q({"投影機": "x1", "線材": "y2"})):
        h = _html(q)
        body = h.split("<body>")[1]
        for w in SECRET_WORDS:
            assert w not in body, w
        assert "2000" not in body and "3500" not in body        # 成本數字不得出現


def test_preview_uses_same_builder(client):
    q = _q(totalsByAlt=True)
    prev = pdf_gen.build_quote_preview_html(q, "草稿", "未成案")
    assert "〔擇一：投影機〕" in prev


def test_pdf_module_does_not_reference_plan_view():
    import pathlib
    src = pathlib.Path(pdf_gen.__file__).read_text(encoding="utf-8")
    assert "plan_view" not in src and "alt_options" not in src
    assert "plan_view" not in pathlib.Path(alt_view.__file__).read_text(encoding="utf-8").replace("plan_view`", "")
