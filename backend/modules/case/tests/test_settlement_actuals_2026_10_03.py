# -*- coding: utf-8 -*-
"""33-A2：`GET /api/quotations/{no}/settlement-actuals`（完結精算實際成本單一來源）。規則 A、單一歸屬、offsets、三態採用、權限、與營運報表同源。
品項 a：計畫 10×成本 1000 ⇒ 估計 10500；品項 b：100×5 ⇒ 估計 525（estimate＝round_half_up(qty×cost, 1.05)）。"""
import json

import pytest

import db
from modules.case import recognition as R
from modules.case import settlement_actuals as SA
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import BASE, NO, W, _body, _ln, _login, _mk, _status, _submit  # noqa: F401

EST_A, EST_B = 10500, 525
URL = "/api/quotations/%s/settlement-actuals" % NO


def _get(c, h, no=NO):
    r = c.get("/api/quotations/%s/settlement-actuals" % no, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _items(d):
    return {i["itemId"]: i for i in d["items"]}


def _put_settlement(settlement):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["settlement"] = settlement
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def test_no_purchase_keeps_the_estimate_and_the_shape(W):
    c, h = W
    d = _get(c, h)
    it = _items(d)
    assert (it["a"]["estimate"]["amount"], it["b"]["estimate"]["amount"]) == (EST_A, EST_B)
    assert it["a"]["actual"] == {"amount": EST_A, "source": "estimate", "replacedEstimate": False} and it["a"]["hasPurchase"] is False
    assert d["totals"]["itemActualTotal"] == EST_A + EST_B and d["totals"]["extraTotal"] == 0 and d["totals"]["purchasedTotal"] == 0
    assert set(d) >= {"quoteNo", "basis", "items", "extra", "unassigned", "offsets", "sources", "totals", "warnings"}


def test_rule_a_purchase_replaces_the_estimate_of_that_item_only(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])                                   # 採購單連品項 a：3000
    d = _get(c, h)
    it = _items(d)
    assert it["a"]["po"]["amount"] == 3000 and it["a"]["purchased"] == 3000
    assert it["a"]["actual"] == {"amount": 3000, "source": "purchase", "replacedEstimate": True}
    assert it["b"]["actual"]["amount"] == EST_B                                         # 沒採購的品項仍用估計
    assert d["totals"]["itemActualTotal"] == 3000 + EST_B and d["totals"]["itemPoUnadopted"] == 0
    assert it["a"]["actualIfNot"] == EST_A and it["a"]["actualIfAdopted"] == 3000


def test_materials_count_by_link_status_and_never_double_with_the_po(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1),   # 連到有效採購單：金額在採購單
                    _order("N", 2, 800, quoteItemId="a"),                                       # 沒連採購單：歸品項 a
                    _order("D", 1, 500, quoteItemId="a"),                                       # 草稿：不計
                    _order("X", 1, 250)],                                                       # 沒有品項：未對應
                   {"K": "已核准", "N": "已核准", "D": "草稿", "X": "待審核"})
    d = _get(c, h)
    a = _items(d)["a"]
    assert (a["po"]["amount"], a["material"]["amount"], a["purchased"]) == (3000, 800, 3800)
    assert [(m["itemId"], m["assignedBy"]) for m in a["material"]["orders"]] == [("N", "link")]
    assert [(m["itemId"], m["amount"], m["pending"]) for m in d["unassigned"]["materials"]] == [("X", 250.0, True)]
    assert d["totals"]["materialUnassignedTotal"] == 250 and d["totals"]["pendingTotal"] == 250


def test_offsets_move_an_unassigned_material_and_an_extra_expense_onto_an_item(W):
    c, h = W
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()                # 沒連品項的採購單＝額外支出
    assert _submit(c, h, ex["id"]).status_code == 200
    d0 = _get(c, h)
    assert d0["totals"]["extraTotal"] == 700 and d0["totals"]["materialUnassignedTotal"] == 250
    assert _items(d0)["b"]["actual"]["amount"] == EST_B
    _put_settlement({"items": [], "offsets": [{"kind": "material", "ref": "X", "itemId": "b"},
                                               {"kind": "extra", "ref": str(ex["id"]), "itemId": "b"},
                                               {"kind": "material", "ref": "X", "itemId": "a"},       # 同一 ref 第二個去處：忽略
                                               {"kind": "extra", "ref": "999", "itemId": "zzz"}]})    # 品項不存在：忽略
    d = _get(c, h)
    b = _items(d)["b"]
    assert (b["material"]["amount"], b["extra"]["amount"], b["purchased"]) == (250, 700, 950)
    assert b["actual"] == {"amount": 950, "source": "purchase", "replacedEstimate": True}
    assert [m["assignedBy"] for m in b["material"]["orders"]] == ["offset"]
    assert d["totals"]["extraTotal"] == 0 and d["totals"]["materialUnassignedTotal"] == 0 and d["unassigned"]["extras"] == []
    assert d["totals"]["purchasedTotal"] == 950                                          # 搬家不改總額（沖銷前 950＝700＋250）
    assert d0["totals"]["purchasedTotal"] == 950


def test_adopt_off_uses_manual_and_purchase_is_not_added_unless_legacy_mode(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_settlement({"items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 9000}, {"id": "b", "actualTotalCost": 400}]})
    d = _get(c, h)
    it = _items(d)
    assert it["a"]["adopt"] is False and it["a"]["actual"] == {"amount": 9000, "source": "manual", "replacedEstimate": False}
    assert it["a"]["purchasedNotAdopted"] == 3000 and d["totals"]["itemPoUnadopted"] == 0                   # D8 建議：手填取代、採購不另加
    assert it["b"]["actual"] == {"amount": 400, "source": "manual", "replacedEstimate": False} and it["b"]["adopt"] is False   # 舊存檔（品項有存、沒 adoptSystem 鍵）＝歷史相容不採用（da S2）；沒有採購所以金額不受影響
    assert d["totals"]["itemActualTotal"] == 9000 + 400
    cn = db.get_db()
    try:
        legacy = SA.compute(cn, NO, unadopted=SA.UNADOPTED_ADD)
    finally:
        cn.close()
    assert legacy["totals"]["itemPoUnadopted"] == 3000                                                     # 舊行為開關（D8 若改裁示）


def test_same_rows_as_the_operating_report_and_gl(W):
    """與營運報表同源：精算的「採購類」總額＝報表料件（材料申請）＋額外支出（含採購單連品項）；材料申請連採購單只算一次。"""
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000), _ln(None, 1, unitCost=500)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1), _order("N", 2, 800, quoteItemId="b"), _order("X", 1, 250)],
                   {"K": "已核准", "N": "已核准", "X": "已核准"})
    d = _get(c, h)
    cn = db.get_db()
    try:
        report = sum(e["amount"] for e in R.material_entries(cn, "accrual") if e["quoteNo"] == NO) + sum(e["amount"] for e in R.extra_entries(cn, "accrual") if e["quoteNo"] == NO)
    finally:
        cn.close()
    assert d["totals"]["purchasedTotal"] == report == 3000 + 500 + 800 + 250


def test_deleted_item_goes_back_to_extra_and_money_is_conserved(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"] = [i for i in d["items"] if i["id"] != "a"]
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    out = _get(c, h)
    assert [i["itemId"] for i in out["items"]] == ["b"]
    assert out["totals"]["extraTotal"] == 3000 and out["totals"]["purchasedTotal"] == 3000


def test_permissions_other_cases_and_financial_view(W, make_user):
    c, h = W
    eu, ep = make_user(username="sa_eng", role="engineer", modules=["case_manage", "expense_forms"])
    ou, op = make_user(username="sa_out", role="engineer", modules=["case_manage"])
    he, ho = _login(c, eu, ep), _login(c, ou, op)
    cn = db.get_db()
    uid = cn.execute("SELECT id FROM users WHERE username='sa_eng'").fetchone()["id"]
    cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
    cn.commit()
    cn.close()
    assert c.get(URL, headers=he).status_code == 403                                                    # 看得到案件、沒有財務檢視 ⇒ 403
    assert c.get(URL, headers=ho).status_code == 404                                                    # 看不到案件＝不存在
    assert c.get("/api/quotations/MQ-NOPE/settlement-actuals", headers=h).status_code == 404
    assert c.get("/api/quotations/-/settlement-actuals", headers=h).status_code == 400
    assert c.get(URL).status_code in (401, 403)


def test_material_order_on_a_deleted_item_goes_back_to_unassigned_with_a_warning(W):
    c, h = W
    _put_materials([_order("G", 2, 900, quoteItemId="gone"), _order("N", 1, 100, quoteItemId="a")], {"G": "已核准", "N": "已核准"})
    d = _get(c, h)
    assert [(m["itemId"], m["amount"]) for m in d["unassigned"]["materials"]] == [("G", 900.0)]      # 品項不在報價單：錢不消失
    assert _items(d)["a"]["material"]["amount"] == 100                                              # 正對照：品項在 ⇒ 歸品項
    assert [(w["code"], w["ref"]) for w in d["warnings"]] == [("item_removed", "G")]
    assert d["totals"]["materialUnassignedTotal"] == 900 and d["totals"]["purchasedTotal"] == 1000



def test_unkeyed_old_items_are_counted_with_a_temporary_key_and_warned(W):
    c, h = W
    cn = db.get_db()
    q = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    n_live = len(q["items"])
    q["items"] += [{"description": "無id", "qty": 2, "cost": 100}, {"id": "z", "description": "", "qty": 1, "cost": 400}]
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(q), NO))
    cn.commit()
    cn.close()
    d = _get(c, h)
    assert len(d["items"]) == n_live + 2 and [w["code"] for w in d["warnings"]] == ["item_unkeyed"]
    assert d["totals"]["itemActualTotal"] == EST_A + EST_B + 210 + 420                           # 與今天頁面逐位相同：全部品項估計 ×1.05
    assert _items(d)["z"]["actual"]["amount"] == 420 and _items(d)[[k for k in _items(d) if k.startswith("~")][0]]["actual"]["amount"] == 210


def test_finalized_settlement_is_frozen_and_does_not_drift(W):
    c, h = W
    _put_settlement({"status": "finalized", "summary": {"itemActualTotal": 9999, "extraTotal": 5, "purchasedTotal": 7},
                     "items": [{"id": "a", "adoptSystem": True, "actualTotalCost": 9999}]})
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])                                              # 完結後才核准的採購單：不得改動凍結值
    d = _get(c, h)
    assert d["finalized"] is True and d["frozen"] is True and d["savedSummary"]["itemActualTotal"] == 9999
    assert _items(d)["a"]["actual"] == {"amount": 9999, "source": "frozen", "replacedEstimate": False}
    assert (d["totals"]["itemActualTotal"], d["totals"]["extraTotal"], d["totals"]["purchasedTotal"]) == (9999, 5, 7)                       # summary 為準
    assert d["live"]["purchasedTotal"] == 3000                                                    # 現算值另放，頁面可提示「完結後有新採購」
    _put_settlement({"status": "draft", "items": [{"id": "a", "adoptSystem": True, "actualTotalCost": 9999}]})
    d2 = _get(c, h)
    assert d2["frozen"] is False and _items(d2)["a"]["actual"]["source"] == "purchase"            # 反向控制：草稿照常重算


def test_legacy_save_without_adopt_key_means_not_adopted_but_new_items_default_on(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000), _ln("b", 1, unitCost=5)])
    _put_settlement({"status": "draft", "items": [{"id": "a", "actualTotalCost": 9000}, {"id": "b", "adoptSystem": True}]})   # a：第 32 班前存的（無鍵）
    d = _get(c, h)
    it = _items(d)
    assert d["legacySave"] is True
    assert it["a"]["adopt"] is False and it["a"]["actual"] == {"amount": 9000, "source": "manual", "replacedEstimate": False}   # 歷史相容＝今天頁面
    assert it["b"]["adopt"] is True and it["b"]["actual"]["source"] == "purchase"
    _put_settlement({"status": "draft", "items": []})                                              # 品項沒存過＝預設採用
    assert _items(_get(c, h))["a"]["adopt"] is True


def test_frozen_extra_total_excludes_remit_fee_and_custom_expense_the_page_adds(W):
    c, h = W
    _put_settlement({"status": "finalized", "items": [], "summary": {"itemActualTotal": 100, "extraTotal": 1000 + 30 + 4, "remitFeeTotal": 30, "customExpenseTotal": 4}})
    assert _get(c, h)["totals"]["extraTotal"] == 1000                       # 頁面的 extraTotal＝額外支出＋手續費＋自訂；端點只管額外支出（手續費／自訂第 34 班）


def test_offsets_query_is_a_preview_that_does_not_save(W):
    c, h = W
    _put_materials([_order("X", 1, 250)], {"X": "已核准"})
    import urllib.parse
    q = urllib.parse.quote(json.dumps([{"kind": "material", "ref": "X", "itemId": "b"}]))
    r = c.get(URL + "?offsets=" + q, headers=h)
    assert r.status_code == 200 and _items(r.json())["b"]["material"]["amount"] == 250 and r.json()["totals"]["materialUnassignedTotal"] == 0
    assert _get(c, h)["totals"]["materialUnassignedTotal"] == 250           # 沒存：下一次還是未對應
    assert c.get(URL + "?offsets=%7Bnot", headers=h).status_code == 422
    assert c.get(URL + "?offsets=%7B%7D", headers=h).status_code == 422
