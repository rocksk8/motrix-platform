# -*- coding: utf-8 -*-
"""32-S4c 預審（c7）：連到有效採購單的材料申請，現金口徑「略過金額」是否連**已經付出去的歷史**一起吞掉。
情境：舊單材料申請（沒有審核列）有舊「登記已付」歷史（已付 3000、付款日 2026-08-01）；之後它被連到一張有效的採購單。
現金口徑報表是否仍看得到那筆已付的 3000（付出去的錢是事實）？不隨產品出貨。"""
import db
from modules.case.tests.test_material_link_booking_2026_10_02 import (  # noqa: F401
    NO, TODAY, W, _approved_po, _extra, _gl, _ln, _mat, _order, _won_case, _put_materials)


def test_cash_basis_keeps_the_money_already_paid_on_a_legacy_order_that_is_later_linked_to_a_po(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    paid = _order("K", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, paidStatus="paid", paidAmount=3000, paidDate="2026-08-01")
    _put_materials([paid], {})                                   # 舊單（沒有審核列）＋舊的已付歷史＋之後才連到採購單
    cash = _mat("cash")
    acc = _mat("accrual")
    print("cash entries:", [(e["itemId"], e["amount"], e["date"]) for e in cash], "| accrual:", [(e["itemId"], e["amount"]) for e in acc])
    assert [e["amount"] for e in cash if e["itemId"] == "K"] == [3000.0], "現金口徑：已經付出去的 3000 不該因為事後連了採購單而從報表消失"
