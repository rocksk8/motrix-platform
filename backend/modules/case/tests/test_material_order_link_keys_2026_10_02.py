# -*- coding: utf-8 -*-
"""32-S4d：材料申請存檔端點（整份覆寫）要原樣保留連結鍵 quoteItemId／poDocCode／poLine／overPlanReason；
空值不寫入（沒用連結的舊單，存檔形狀與以前完全相同）。
（已存在的列再存檔時，哪些鍵可改由 31-C 守門 `material_guard` 決定，不在這裡測。）"""
import json

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401

URL = "/api/quotations/%s/material-orders" % NO


def _order(item_id, **kw):
    d = {"itemId": item_id, "itemName": "品" + item_id, "quantity": 2, "unit": "台", "unitPrice": 100, "totalPrice": 200,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "supplierId": 1}
    d.update(kw)
    return d


def _saved():
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    finally:
        cn.close()
    return {o["itemId"]: o for o in d["caseRecord"]["materialOrders"]}


def _patch(c, h, orders):
    cn = db.get_db()                                                             # 新建列必填供應商（31-C）
    try:
        if not cn.execute("SELECT 1 FROM suppliers WHERE id=1").fetchone():
            cn.execute("INSERT INTO suppliers (id, name, code, created_at, updated_at) VALUES (1,?,?,?,?)", ("甲供應商", "S-001", "2031-01-01", "2031-01-01"))
            cn.commit()
    finally:
        cn.close()
    return c.patch(URL, headers=h, json={"materialOrders": orders})


def test_link_keys_round_trip_and_empty_ones_are_not_written(W):
    c, h = W
    po = _mk(c, h, "purchase_order", [_ln("a", 1), _ln("a", 1)]).json()          # 32-S4 接縫後 poDocCode 必須是有效連結（兩行，才有第 2 列）
    assert _submit(c, h, po["id"]).status_code == 200
    r = _patch(c, h, [_order("L1", quoteItemId="a", poDocCode=po["docCode"], poLine=2, overPlanReason="加購"),
                      _order("L2", quoteItemId="", poDocCode="", poLine=None, overPlanReason=""),
                      _order("L3")])
    assert r.status_code == 200 and not r.json().get("rejected"), r.text
    got = _saved()
    assert (got["L1"]["quoteItemId"], got["L1"]["poDocCode"], got["L1"]["poLine"], got["L1"]["overPlanReason"]) == ("a", po["docCode"], 2, "加購")
    for k in ("L2", "L3"):
        assert not {"quoteItemId", "poDocCode", "poLine", "overPlanReason"} & set(got[k])
    back = {o["itemId"]: o for o in c.get(URL, headers=h).json()["materialOrders"]}
    assert back["L1"]["quoteItemId"] == "a" and back["L1"]["poLine"] == 2


def test_queue_items_carry_an_empty_tags_list_by_default_and_providers_can_set_it():
    """32-S4d：簽核佇列卡片的小標註（L1 加法）：預設 []，提供者經 fields 帶入 [{text, tone}]。"""
    from helpers.approval_queue import base_item
    f = {"requestedBy": "u", "requestedByDisplay": "U", "requestedAt": "2026-10-02", "tiers": [], "currentTier": 1, "tierCount": 1, "currentApprovers": []}
    assert base_item("x", "N1", f)["tags"] == []
    assert base_item("x", "N1", f, tags=[{"text": "該材料申請未申請採購單", "tone": "warn"}])["tags"][0]["tone"] == "warn"


def test_adding_a_po_link_to_an_order_that_already_has_payments_is_rejected_but_resaving_an_existing_link_is_not(W):
    c, h = W
    paid = _order("P1", paidStatus="paid", paidAmount=200, paidDate="2026-08-01")
    assert _patch(c, h, [paid]).status_code == 200 and "P1" in _saved()
    r = _patch(c, h, [dict(paid, poDocCode="PO-X")])                                   # 已有付款紀錄 ⇒ 不可新增採購單連結
    assert r.status_code == 400 and "已有付款紀錄" in r.text
    assert "poDocCode" not in _saved()["P1"]
    cn = db.get_db()                                                                    # 既有連結（先連、後付款）原樣存回不受影響
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["caseRecord"]["materialOrders"][0]["poDocCode"] = "PO-X"
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    assert _patch(c, h, [dict(paid, poDocCode="PO-X")]).status_code == 200
