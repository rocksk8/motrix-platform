# -*- coding: utf-8 -*-
"""34-S1：case 提供者 `material.shippable`（出貨單連動；契約 SHIPPING-MATERIAL-LINK-CONTRACT-S1）。只回已核准＋已到貨確認的材料申請；唯讀。"""
import json

import db
from core import registry
from modules.case import material_shippable as MS
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401


def _set(item_id, status="已核准", received_on="2026-10-03", doc=None, received_qty=None):
    cn = db.get_db()
    try:
        cn.execute("UPDATE case_material_approvals SET status=?, doc_code=?, received_on=? WHERE quote_no=? AND item_id=?", (status, doc or "MO-" + item_id, received_on, NO, item_id))
        if received_qty is not None:
            cn.execute("ALTER TABLE case_material_approvals ADD COLUMN received_qty REAL")
            cn.execute("UPDATE case_material_approvals SET received_qty=? WHERE quote_no=? AND item_id=?", (received_qty, NO, item_id))
        cn.commit()
    finally:
        cn.close()


def _get(quote_no=NO):
    cn = db.get_db()
    try:
        return MS.material_shippable(cn, quote_no)
    finally:
        cn.close()


def test_only_approved_and_received_rows_are_shippable_with_the_contract_fields(W):
    _put_materials([_order("A", 5, 500, quoteItemId="a", unit="台"), _order("B", 2, 200), _order("C", 1, 100), _order("D", 1, 100), _order("E", 1, 100)],
                   {"A": "已核准", "B": "已核准", "C": "待審核", "D": "已取消", "E": "已退回"})
    _set("A", doc="MO-A")
    _set("B", received_on="")                                      # 已核准、還沒到貨確認
    for i in "CDE":
        _set(i, status={"C": "待審核", "D": "已取消", "E": "已退回"}[i])   # 其他狀態即使有到貨日也不回
    assert _get() == [{"materialItemId": "A", "docCode": "MO-A", "name": "品A", "unit": "台", "quoteItemId": "a", "appliedQty": 5.0, "arrivedQty": 5.0, "status": "已核准"}]


def test_arrived_qty_defaults_to_everything_and_uses_the_optional_received_qty_capped_at_applied(W):
    _put_materials([_order("A", 5, 500)], {"A": "已核准"})
    _set("A", received_qty=3)
    assert _get()[0]["arrivedQty"] == 3.0
    cn = db.get_db()
    cn.execute("UPDATE case_material_approvals SET received_qty=9 WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()
    assert _get()[0]["arrivedQty"] == 5.0                          # 實收不超過已核准量
    cn = db.get_db()
    cn.execute("UPDATE case_material_approvals SET received_qty=NULL WHERE quote_no=?", (NO,))
    cn.commit()
    cn.close()
    assert _get()[0]["arrivedQty"] == 5.0                          # 沒填＝全數


def test_unknown_case_legacy_orders_and_empty_input(W):
    assert _get("NO-SUCH") == [] and _get("") == []
    _put_materials([_order("L", 1, 100)], {})                       # 舊單（沒有疊加列）：沒有到貨確認 ⇒ 不回
    assert _get() == []


def test_provider_is_registered_and_read_only(W):
    fn = registry.single_provider("material.shippable")
    assert fn is MS.material_shippable
    _put_materials([_order("A", 5, 500)], {"A": "已核准"})
    _set("A")
    cn = db.get_db()
    try:
        before = cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]
        total0 = cn.total_changes
        assert len(fn(cn, NO)) == 1
        assert cn.total_changes == total0 and cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"] == before
    finally:
        cn.close()
