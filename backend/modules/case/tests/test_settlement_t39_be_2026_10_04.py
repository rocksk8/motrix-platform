# -*- coding: utf-8 -*-
"""第 39 班後端（案件／精算）：①公益金下限 0（毛利為負不再算出負的公益金；報價原始側同）②「實際成本 0＝真的 0」——
精算存檔頂層標記 `schemaVersion: 2`：v2 的品項 `actualTotalCost` 是數字（含 0）＝已填、null／沒有＝沒填（用估計）；
沒有標記的舊存檔維持「0＝沒填」。品項 a：估計 10500；品項 b：估計 525；報價稅前 100000（_set_tot）。"""
import json

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import EST_A, EST_B, _get, _items, _put_settlement
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import _set_tot, page_payload
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  第 40 班：完結要已成案（autouse）

URL = "/api/quotations/%s/settlement" % NO


def _saved():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        cn.close()


def _put(c, h, settlement, **kw):
    return c.put(URL, json=dict({"settlement": settlement}, **kw), headers=h)


def _honest(c, h, **summary_over):
    """頁面送出的完結 payload：總成本等一律取伺服器值，公益金依新規則（下限 0）。"""
    d = _get(c, h)
    p = page_payload(c, h)
    t = d["totals"]
    gross = 100000 - t["totalActualCost"]
    admin = SA.round_half_up(100000, 0.10)
    charity = max(0, SA.round_half_up(gross, 0.01))
    net = gross - admin - charity
    p["summary"].update(totalActualCost=t["totalActualCost"], grossProfit=gross, charityDonation=charity, netProfit=net,
                        grossMarginPct=round(gross / 1000, 1), netMarginPct=round(net / 1000, 1))
    p["summary"].update(summary_over)
    return p


# ── ① 公益金下限 0 ───────────────────────────────────────────────────────────────

def test_charity_is_zero_when_gross_is_negative(W):
    c, h = W
    _set_tot()
    _dispatch(150000, 0)                                       # 總成本遠大於報價稅前 100000 ⇒ 毛利為負
    p = _honest(c, h)
    assert p["summary"]["grossProfit"] < 0 and p["summary"]["charityDonation"] == 0
    r = _put(c, h, p)
    assert r.status_code == 200, r.text
    s = _saved()["settlement"]["summary"]
    assert s["charityDonation"] == 0 and s["netProfit"] == s["grossProfit"] - s["adminCost"]


def test_old_negative_charity_from_an_old_page_is_refused_when_gross_is_negative(W):
    c, h = W
    _set_tot()
    _dispatch(150000, 0)
    p = _honest(c, h)
    p["summary"]["charityDonation"] = SA.round_half_up(p["summary"]["grossProfit"], 0.01)           # 舊公式：負的公益金
    p["summary"]["netProfit"] = p["summary"]["grossProfit"] - p["summary"]["adminCost"] - p["summary"]["charityDonation"]
    r = _put(c, h, p)
    assert r.status_code == 409 and "公益金" in r.text


def test_charity_unchanged_when_gross_is_not_negative(W):
    c, h = W
    _set_tot()
    p = _honest(c, h)
    gross = p["summary"]["grossProfit"]
    assert gross > 0 and p["summary"]["charityDonation"] == SA.round_half_up(gross, 0.01)
    assert _put(c, h, p).status_code == 200
    assert _saved()["settlement"]["summary"]["charityDonation"] == SA.round_half_up(gross, 0.01)
    cn = db.get_db()
    try:
        d = SA.compute(cn, NO, freeze=False)
        exp = SA._expected_downstream(cn, NO, d, 2)
    finally:
        cn.close()
    assert exp["charityDonation"][0] == SA.round_half_up(gross, 0.01)


def test_original_side_charity_has_the_same_floor(W):
    c, h = W
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 5000, "total": 5250}                         # 原始成本 10500 > 稅前 5000 ⇒ 原始毛利為負；tot 沒有 charityDonation 欄位 ⇒ 伺服器算
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
        o = SA.original_side(cn, NO, {"netProfit": 0})
    finally:
        cn.close()
    assert o["origDirectProfit"] < 0 and o["origCharity"] == 0
    assert o["origNetProfit"] == o["origDirectProfit"] - o["origAdminCost"]


def test_frozen_finalized_summary_with_negative_charity_stays_as_stored(W):
    c, h = W
    _put_settlement({"status": "finalized", "items": [{"id": "a", "actualTotalCost": 1}], "offsets": [],
                     "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": 200000, "charityDonation": -1000, "grossProfit": -100000}})
    d = _get(c, h)
    assert d["frozen"] is True and d["savedSummary"]["charityDonation"] == -1000


# ── ② schemaVersion 2：實際成本 0＝真的 0 ─────────────────────────────────────────

def test_schema2_zero_actual_cost_is_a_filled_value(W):
    c, h = W
    _put_settlement({"schemaVersion": 2, "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}, {"id": "b", "adoptSystem": False}], "offsets": []})
    d = _get(c, h)
    it = _items(d)
    assert it["a"]["actual"]["amount"] == 0 and it["a"]["actual"]["source"] == "manual"
    assert it["b"]["actual"]["amount"] == EST_B and it["b"]["actual"]["source"] == "estimate"          # 沒有鍵＝沒填
    assert d["totals"]["itemActualTotal"] == 0 + EST_B and d["schemaVersion"] == 2


def test_legacy_zero_actual_cost_still_means_unfilled(W):
    c, h = W
    _put_settlement({"items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}], "offsets": []})
    d = _get(c, h)
    a = _items(d)["a"]["actual"]
    assert a["amount"] == EST_A and a["source"] == "estimate" and d["schemaVersion"] == 1


def test_schema2_null_or_blank_actual_cost_is_unfilled(W):
    c, h = W
    _put_settlement({"schemaVersion": 2, "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": None}, {"id": "b", "adoptSystem": False, "actualTotalCost": ""}], "offsets": []})
    it = _items(_get(c, h))
    assert it["a"]["actual"]["amount"] == EST_A and it["a"]["actual"]["source"] == "estimate"
    assert it["b"]["actual"]["amount"] == EST_B and it["b"]["actual"]["source"] == "estimate"


def test_schema2_positive_and_adopted_purchase_behaviour_unchanged(W):
    c, h = W
    _put_settlement({"schemaVersion": 2, "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 777}], "offsets": []})
    assert _items(_get(c, h))["a"]["actual"] == {"amount": 777.0, "source": "manual", "replacedEstimate": False}


def test_schema2_finalize_with_a_zero_item_agrees_with_the_server_and_freezes_zero(W):
    c, h = W
    _set_tot()
    _put_settlement({"schemaVersion": 2, "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}, {"id": "b", "adoptSystem": False, "actualTotalCost": EST_B}], "offsets": []})
    d = _get(c, h)
    p = _honest(c, h)
    p["schemaVersion"] = 2
    p["items"] = [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}, {"id": "b", "adoptSystem": False, "actualTotalCost": EST_B}]
    r = _put(c, h, p)
    assert r.status_code == 200, r.text
    assert _saved()["settlement"]["schemaVersion"] == 2
    fz = _get(c, h)
    assert fz["frozen"] is True and _items(fz)["a"]["actual"] == {"amount": 0.0, "source": "frozen", "replacedEstimate": False}
    assert fz["totals"]["itemActualTotal"] == d["totals"]["itemActualTotal"] == EST_B


def test_legacy_finalized_case_with_a_zero_item_is_read_as_before(W):
    c, h = W
    _put_settlement({"status": "finalized", "items": [{"id": "a", "actualTotalCost": 0}, {"id": "b", "actualTotalCost": 500}], "offsets": [],
                     "summary": {"itemActualTotal": EST_A + 500, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": EST_A + 500}})
    fz = _get(c, h)
    it = _items(fz)
    assert it["a"]["actual"]["amount"] == EST_A and it["a"]["actual"]["source"] != "frozen"           # 舊案 0＝沒填：保留現算值
    assert it["b"]["actual"] == {"amount": 500.0, "source": "frozen", "replacedEstimate": False}


def test_schema_version_is_validated_and_passed_through(W):
    c, h = W
    for bad in ("2", 2.5, True, 0, -1, [], {}):
        assert _put(c, h, {"schemaVersion": bad, "items": [], "offsets": []}).status_code == 422, bad
    assert _put(c, h, {"schemaVersion": 2, "items": [], "offsets": []}).status_code == 200
    assert _saved()["settlement"]["schemaVersion"] == 2
    assert _put(c, h, {"items": [], "offsets": []}).status_code == 200                                # 沒帶＝舊存檔，照常
    assert "schemaVersion" not in _saved()["settlement"]
    assert _put(c, h, {"schemaVersion": None, "items": [], "offsets": []}).status_code == 200


def test_item_conservation_with_a_v2_zero_item_and_a_dispatch_offset(W):
    c, h = W
    d1 = _dispatch(10000, 2000)
    base = {"schemaVersion": 2, "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}, {"id": "b", "adoptSystem": False}]}
    _put_settlement(dict(base, offsets=[]))
    t0 = _get(c, h)["totals"]
    _put_settlement(dict(base, offsets=[{"kind": "dispatch", "ref": str(d1), "itemId": "a"}]))
    t1 = _get(c, h)["totals"]
    assert t0["totalActualCost"] == t1["totalActualCost"] == 0 + EST_B + 12500                   # 採用關：對應／取消對應不改總成本
    assert t1["dispatchUnassignedTotal"] + t1["dispatchAssignedTotal"] == t1["dispatchTotal"]


# ── 原始側「報價預留間接成本」資訊列（使用者裁示 a）─────────────────────────────────

def _tot_with_indirect():
    """範例：稅前 100000、品項成本 60000、進項稅 3000 ⇒ 直接毛利 37000；管理費 10000、公益金 370、五項預留 5000 ⇒ totalIndirect 15370、淨利 21630。"""
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["tot"] = {"pretax": 100000, "total": 105000, "directProfit": 37000, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 15370, "netProfit": 21630,
                    "netMarginPct": 21.6}
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def test_indirect_reserve_is_total_indirect_minus_admin_and_charity(W):
    c, h = W
    _tot_with_indirect()
    cn = db.get_db()
    try:
        o = SA.original_side(cn, NO, {"netProfit": 0})
    finally:
        cn.close()
    assert o["origIndirectReserve"] == 5000
    assert o["origDirectProfit"] - o["origAdminCost"] - o["origCharity"] - o["origIndirectReserve"] == o["origNetProfit"] == 21630


def test_indirect_reserve_is_zero_when_the_quote_has_no_total_indirect(W):
    c, h = W
    _set_tot()                                                 # tot 只有 pretax／total（早期資料）
    cn = db.get_db()
    try:
        o = SA.original_side(cn, NO, {"netProfit": 0})
    finally:
        cn.close()
    assert o["origIndirectReserve"] == 0


def test_finalize_overwrites_a_forged_indirect_reserve_and_net_profit_is_untouched(W):
    c, h = W
    _tot_with_indirect()
    base = _honest(c, h)
    r0 = _put(c, h, dict(base))
    assert r0.status_code == 200
    s_plain = _saved()["settlement"]["summary"]
    assert s_plain["origIndirectReserve"] == 5000
    _put(c, h, {"status": "draft", "items": [], "offsets": []}, reason="重開")
    p = _honest(c, h, origIndirectReserve=999999)
    assert _put(c, h, p, reason="再完結").status_code == 200
    s = _saved()["settlement"]["summary"]
    assert s["origIndirectReserve"] == 5000
    assert s["netProfit"] == s_plain["netProfit"] and s["charityDonation"] == s_plain["charityDonation"]          # 獎金基數（淨利）不因此改變


def test_legacy_frozen_summary_without_the_reserve_key_reads_unchanged(W):
    c, h = W
    _put_settlement({"status": "finalized", "items": [{"id": "a", "actualTotalCost": 1}], "offsets": [], "summary": {"itemActualTotal": 1, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": 1}})
    d = _get(c, h)
    assert d["frozen"] is True and "origIndirectReserve" not in d["savedSummary"]


def test_closing_report_original_column_shows_the_reserve_row_only_when_present():
    import pdf_gen
    assert pdf_gen._orig_reserve_row({"origCharity": 1}) == "" and pdf_gen._orig_reserve_row({"origIndirectReserve": 0}) == ""
    assert pdf_gen._orig_reserve_note({}) == ""
    row = pdf_gen._orig_reserve_row({"origIndirectReserve": 5000})
    assert "報價預留間接成本" in row and "5,000" in row
    assert "5,000" in pdf_gen._orig_reserve_note({"origIndirectReserve": 5000})
