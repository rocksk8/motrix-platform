# -*- coding: utf-8 -*-
"""32-S4c：連到有效採購單的叫料，營運報表來源（權責／現金）與總帳 E12／E12b 略過其金額（一筆採購只算一次）；
沒有連結的叫料照舊計入並帶 `noPo` 備註（舊單、$0 不標）；連結失效（採購單作廢／駁回）⇒ 叫料金額回來；沒有連結資料的歷史叫料數字不變。"""
import json
from datetime import date

import pytest

import db
from modules.case import gl_events as GE
from modules.case import recognition as R
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _status, _submit  # noqa: F401

TODAY = date.today().isoformat()


def _approved_po(c, h, lines):
    r = _mk(c, h, "purchase_order", lines).json()
    assert _submit(c, h, r["id"]).status_code == 200
    return r


@pytest.fixture(autouse=True)
def _won_case(W):
    """叫料來源只讀「已成案／已結案」的案件（recognition._case_rows）。"""
    cn = db.get_db()
    cn.execute("UPDATE quotations SET deal_tag='已成案' WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()


def _order(item_id, qty, total, **kw):
    d = {"itemId": item_id, "itemName": "品" + item_id, "quantity": qty, "unit": "台", "unitPrice": (total / qty) if qty else 0, "totalPrice": total,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "invoiceDate": TODAY}
    d.update(kw)
    return d


def _mat(basis="accrual"):
    cn = db.get_db()
    try:
        return [e for e in R.material_entries(cn, basis) if e["quoteNo"] == NO]
    finally:
        cn.close()


def _extra(basis="accrual"):
    cn = db.get_db()
    try:
        return [e for e in R.extra_entries(cn, basis) if e["quoteNo"] == NO]
    finally:
        cn.close()


def _gl():
    return GE.gl_events("2000-01-01", "2099-12-31")["events"]


def test_linked_order_money_is_skipped_everywhere_and_counted_once_via_the_po(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])                        # 採購單 3000（連品項 a）
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1),     # 連到有效採購單
                    _order("N", 2, 800)],                                                         # 沒連結
                   {"K": "已核准", "N": "已核准"})
    m = _mat()
    assert [(e["itemId"], e["amount"]) for e in m] == [("N", 800.0)] and m[0]["noPo"] is True    # 連結的不計；沒連結的計並標註
    total_cost = sum(e["amount"] for e in m) + sum(e["amount"] for e in _extra())
    assert total_cost == 3000 + 800                                                              # 採購單 3000 只算一次，另加叫料 800
    ev = _gl()
    assert [e["source_key"] for e in ev if e["event_code"] == "E12"] == ["%s::N" % NO]            # E12 只有沒連結的那張
    assert any(e["event_code"] == "E11" and e["source_key"] == str(po["id"]) for e in ev)


def test_cash_basis_also_skips_linked_orders(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], paidStatus="paid", paidAmount=3000, paidDate=TODAY),
                    _order("N", 2, 800, paidStatus="paid", paidAmount=800, paidDate=TODAY)], {"K": "已核准", "N": "已核准"})
    cash = _mat("cash")
    assert [(e["itemId"], e["amount"]) for e in cash] == [("N", 800.0)]
    assert [e["source_key"] for e in _gl() if e["event_code"] == "E12b"] == ["%s::N" % NO]


def test_link_that_becomes_invalid_brings_the_order_amount_back(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1)], {"K": "已核准"})
    assert _mat() == []
    _status(po["id"], "已作廢")                                                                   # 採購單作廢 ⇒ 連結失效 ⇒ 叫料金額回來（錢不消失）
    m = _mat()
    assert [(e["itemId"], e["amount"], e["noPo"]) for e in m] == [("K", 3000.0, True)]
    assert sum(e["amount"] for e in m) + sum(e["amount"] for e in _extra()) == 3000


def test_noPo_flag_legacy_zero_amount_and_history_unchanged(W):
    c, h = W
    _put_materials([_order("L", 1, 500),                 # 舊單（沒有疊加列）：計入、不標
                    _order("Z", 1, 0),                   # $0：沒有金額、不產生列
                    _order("A", 1, 700)], {"A": "已核准"})
    got = {e["itemId"]: e for e in _mat()}
    assert got["L"]["amount"] == 500 and got["L"]["noPo"] is False and "Z" not in got
    assert got["A"]["amount"] == 700 and got["A"]["noPo"] is True
    # 歷史（沒有任何連結鍵）：金額與 31-C 的規則一致，只多了 noPo 備註鍵
    assert sorted((e["itemId"], e["amount"]) for e in _mat()) == [("A", 700.0), ("L", 500.0)]


def test_operating_report_marks_unlinked_material_and_amounts_are_unchanged(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _put_materials([_order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"]), _order("N", 2, 800)], {"K": "已核准", "N": "已核准"})
    month = date.today().strftime("%Y-%m")
    r = c.get("/api/reports/expenses-monthly", params={"year": date.today().year, "month": month, "basis": "accrual"}, headers=h)
    assert r.status_code == 200, r.text
    mat = [x for x in r.json()["expenses"]["details"]["material"] if x.get("quoteNo") == NO and "叫料" in x["desc"]]
    assert len(mat) == 1 and mat[0]["amount"] == 800 and "｜未申請採購單" in mat[0]["taxNote"] and mat[0]["noPo"] is True
