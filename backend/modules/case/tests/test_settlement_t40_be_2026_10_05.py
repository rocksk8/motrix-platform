# -*- coding: utf-8 -*-
"""第 40 班後端（案件／精算）：①完結要求報價單已成案 ②進項稅階段 0——稅基標示（settlement-actuals `taxBasis`、結案 PDF 稅基說明行），
不改任何金額；守門題釘住 ESTIMATE_RATE ③稽核 T39 的兩項修正（預留說明不宣稱差額、舊虧損報價的負公益金在伺服器也下限 0）。
品項 a：估計 10500；品項 b：估計 525；報價稅前 100000（_set_tot）。"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import EST_A, EST_B, _get
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import _set_tot, page_payload

URL = "/api/quotations/%s/settlement" % NO


def _set_deal_tag(tag):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["dealTag"] = tag
        cn.execute("UPDATE quotations SET data_json=?, deal_tag=? WHERE quote_no=?", (json.dumps(d), tag, NO))
        cn.commit()
    finally:
        cn.close()


def _put(c, h, settlement, **kw):
    return c.put(URL, json=dict({"settlement": settlement}, **kw), headers=h)


def _honest(c, h):
    d = _get(c, h)
    p = page_payload(c, h)
    t = d["totals"]
    gross = 100000 - t["totalActualCost"]
    admin = SA.round_half_up(100000, 0.10)
    charity = max(0, SA.round_half_up(gross, 0.01))
    net = gross - admin - charity
    p["summary"].update(totalActualCost=t["totalActualCost"], grossProfit=gross, charityDonation=charity, netProfit=net,
                        grossMarginPct=round(gross / 1000, 1), netMarginPct=round(net / 1000, 1))
    return p


# ── ① 完結要求已成案 ──────────────────────────────────────────────────────────────

def test_finalize_is_refused_until_the_quote_is_won(W):
    c, h = W
    _set_tot()
    _set_deal_tag("")
    r = _put(c, h, _honest(c, h))
    assert r.status_code == 409 and "還沒成案" in r.text
    assert _put(c, h, {"status": "draft", "items": [], "offsets": []}).status_code == 200            # 草稿存檔不受影響
    _set_deal_tag("已成案")
    assert _put(c, h, _honest(c, h)).status_code == 200


def test_refinalize_after_reopen_is_allowed_on_a_closed_case(W):
    c, h = W
    _set_tot()
    _set_deal_tag("已成案")
    assert _put(c, h, _honest(c, h)).status_code == 200
    _set_deal_tag("已結案")
    assert _put(c, h, {"status": "draft", "items": [], "offsets": []}, reason="重開").status_code == 200
    assert _put(c, h, _honest(c, h), reason="再完結").status_code == 200


# ── ② 進項稅階段 0：稅基標示、不改金額 ─────────────────────────────────────────────

def test_estimate_rate_and_item_estimate_basis_are_pinned():
    assert SA.ESTIMATE_RATE == 1.05
    assert SA.estimate_amount(10, 1000) == 10500 and SA.estimate_amount(100, 5) == 525
    assert SA.TAX_BASIS["estimateRate"] == 1.05 and SA.TAX_BASIS["itemEstimate"]["basis"] == "taxed"


def test_tax_basis_is_exposed_per_cost_source_without_changing_amounts(W):
    c, h = W
    d = _get(c, h)
    tb = d["taxBasis"]
    assert {k: tb[k]["basis"] for k in ("itemEstimate", "purchase", "material", "extra", "dispatch", "remitFee", "customExpense")} == {
        "itemEstimate": "taxed", "purchase": "taxed", "material": "taxed", "extra": "unsplit", "dispatch": "pretax", "remitFee": "actual", "customExpense": "actual"}
    assert tb["estimateRate"] == 1.05 and d["totals"]["itemActualTotal"] == EST_A + EST_B                  # 金額照舊


def test_closing_pdf_cost_basis_notes_add_text_only():
    import pdf_gen
    assert "含 5% 稅" in pdf_gen._cost_basis_note("item", {})
    assert "未拆稅" in pdf_gen._cost_basis_note("extra", {})
    assert "含稅" in pdf_gen._cost_basis_note("dispatch_legacy", {})                                       # 舊精算（沒有口徑標記）
    assert pdf_gen._cost_basis_note("dispatch_legacy", {"dispatchBasis": "pretax"}) == ""                  # 新口徑已有稅額說明行


def test_settlement_rows_labels_are_untouched():
    from modules.payroll.bonus import SETTLEMENT_ROWS
    assert [r[1] for r in SETTLEMENT_ROWS] == ["報價稅前收入", "品項實際成本", "額外支出", "承攬商派發成本", "實際總成本", "真實毛利", "真實毛利率",
                                               "管銷分攤（10%）", "公益捐款（1%）", "真實淨利", "真實淨利率"]


# ── ③ 稽核 T39 ───────────────────────────────────────────────────────────────────

def test_reserve_note_does_not_claim_the_difference_contains_the_reserve():
    import pdf_gen
    note = pdf_gen._orig_reserve_note({"origIndirectReserve": 5000})
    assert "5,000" in note and "其中" not in note and "單據" in note


def test_original_side_floors_a_stored_negative_charity_and_keeps_net_profit(W):
    c, h = W
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 100000, "total": 105000, "directProfit": -4000, "adminCost": 10000, "charityDonation": -40, "totalIndirect": 14960, "netProfit": -18960}
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
        o = SA.original_side(cn, NO, {"netProfit": 0})
    finally:
        cn.close()
    assert o["origCharity"] == 0 and o["origIndirectReserve"] == 4960
    assert o["origNetProfit"] == -18960 and o["origDirectProfit"] - o["origAdminCost"] - o["origCharity"] - o["origIndirectReserve"] == -18960
