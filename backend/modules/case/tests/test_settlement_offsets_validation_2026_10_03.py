# -*- coding: utf-8 -*-
"""33-A4：`PUT /api/quotations/{no}/settlement` 對 `settlement.offsets` 的驗證（422）。品項 a、b 見 test_settlement_actuals_2026_10_03。"""
import json

import pytest

import db

from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import BASE, NO, W, _ln, _mk, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _items

URL = "/api/quotations/%s/settlement" % NO


def _put(c, h, offsets, **extra):
    return c.put(URL, json={"settlement": dict({"items": [], "offsets": offsets}, **extra)}, headers=h)


def _mat(ref="X"):
    return {"kind": "material", "ref": ref, "itemId": "b"}


@pytest.fixture
def X(W):
    c, h = W
    _put_materials([_order("X", 1, 250), _order("L", 1, 100, quoteItemId="a")], {"X": "已核准", "L": "已核准"})
    _won(c)
    return c, h


def _won(c):
    """案件存檔會依 data_json.dealTag 重算 deal_tag（只改欄位會在第一次 PUT 後被重設 ⇒ 材料申請不再計入）。"""
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["dealTag"] = "已成案"
        cn.execute("UPDATE quotations SET data_json=?, deal_tag='已成案' WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def test_valid_offset_is_saved_and_applied(X):
    c, h = X
    assert _put(c, h, [_mat()]).status_code == 200
    assert _items(_get(c, h))["b"]["material"]["amount"] == 250


@pytest.mark.parametrize("bad,why", [
    ([{"kind": "bogus", "ref": "X", "itemId": "b"}], "kind"),
    ([{"kind": "material", "ref": "", "itemId": "b"}], "ref 空"),
    ([{"kind": "material", "ref": "X", "itemId": ""}], "itemId 空"),
    ([{"kind": "material", "ref": "X", "itemId": "zzz"}], "品項不存在"),
    ([{"kind": "material", "ref": "NOPE", "itemId": "b"}], "ref 不在未對應清單"),
    ([{"kind": "material", "ref": "L", "itemId": "b"}], "已連品項的材料申請不在未對應清單"),
    ([{"kind": "extra", "ref": "999", "itemId": "b"}], "額外支出不存在"),
    ([_mat(), {"kind": "material", "ref": "X", "itemId": "a"}], "同一 ref 兩個去處"),
    ("oops", "不是清單"),
    (["x"], "列不是物件"),
])
def test_bad_offsets_are_rejected_and_nothing_is_saved(X, bad, why):
    c, h = X
    r = _put(c, h, bad)
    assert r.status_code == 422, (why, r.status_code, r.text)
    assert _get(c, h)["offsets"] == []                                                      # 沒存進去


def test_extra_expense_offset_needs_an_extra_that_exists(X):
    c, h = X
    ex = _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=700)]).json()
    assert _submit(c, h, ex["id"]).status_code == 200
    assert _put(c, h, [{"kind": "extra", "ref": str(ex["id"]), "itemId": "b"}]).status_code == 200
    assert _items(_get(c, h))["b"]["extra"]["amount"] == 700


def test_unchanged_stale_offset_is_tolerated_but_a_new_bad_one_is_not(X):
    c, h = X
    assert _put(c, h, [_mat()]).status_code == 200
    cn = db.get_db()                                                                        # 材料申請事後取消：舊列失效但不卡草稿
    cn.execute("UPDATE case_material_approvals SET status='已取消' WHERE quote_no=? AND item_id='X'", (NO,))
    cn.commit()
    cn.close()
    assert _put(c, h, [_mat()]).status_code == 200
    assert _put(c, h, [_mat(), _mat("NOPE")]).status_code == 422


def test_no_offsets_key_or_empty_list_is_unaffected(X):
    c, h = X
    assert c.put(URL, json={"settlement": {"items": []}}, headers=h).status_code == 200
    assert _put(c, h, []).status_code == 200



def test_unkeyed_old_item_cannot_be_an_offset_target(X):
    c, h = X
    cn = db.get_db()
    q = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    q["items"].append({"id": "z", "description": "", "qty": 1, "cost": 400})
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(q), NO))
    cn.commit()
    cn.close()
    assert _put(c, h, [{"kind": "material", "ref": "X", "itemId": "z"}]).status_code == 422
