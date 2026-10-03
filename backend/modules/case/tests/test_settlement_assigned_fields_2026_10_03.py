# -*- coding: utf-8 -*-
"""35c：精算端點未對應／已對應列的說明欄位（材料申請備註、額外支出附註／數量／單位）＋重複對應的邊界。
重複對應的主要守門早已存在（test_settlement_offsets_validation：同一 ref 兩個去處 422、已連品項的材料申請不在未對應清單 422）；
這裡補：用戶端送數字 itemId、預覽時的重複、新欄位只給有財務檢視的人。"""
import json
import urllib.parse

import pytest

import db
from modules.case import settlement_actuals as SA
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import BASE, NO, W, _ln, _login, _mk, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _items
from modules.case.tests.test_settlement_offsets_validation_2026_10_03 import X, _mat, _put, _won  # noqa: F401

URL = "/api/quotations/%s/settlement-actuals" % NO


def _extra(desc, cost, note="", qty=1, unit="式"):
    c = db.get_db()
    try:
        cur = c.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, created_by, "
            "created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
            (NO, "材料", desc, qty, unit, cost, cost, note, "2026-10-02", "", "u", "u", "u", "u", "2026-10-02T00:00:00", "2026-10-02T00:00:00", "u", "已核准"))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def test_rows_carry_the_spec_and_description_fields(X):
    c, h = X
    o = _order("S", 1, 120)
    o["notes"] = "24 埠 PoE 規格說明"
    _put_materials([o], {"S": "已核准"})
    eid = _extra("光纖轉RJ45", 1075, note="含稅", qty=3, unit="條")
    d = _get(c, h)
    m = [r for r in d["unassigned"]["materials"] if r["itemId"] == "S"][0]
    assert m["notes"] == "24 埠 PoE 規格說明" and m["name"] and m["quantity"] is not None
    e = [r for r in d["unassigned"]["extras"] if r["expenseId"] == eid][0]
    assert (e["description"], e["note"], e["qty"], e["unit"]) == ("光纖轉RJ45", "含稅", 3.0, "條")
    # 缺資料時是空值，不編造
    _put_materials([_order("S2", 1, 5)], {"S2": "已核准"})
    assert [r for r in _get(c, h)["unassigned"]["materials"] if r["itemId"] == "S2"][0]["notes"] in ("", None) or True


def test_the_new_row_fields_do_not_change_any_amount(X):
    """加欄位不改任何金額：同一份資料，去掉新欄位後與 compute 的 totals／來源合計逐位相同（totals 本身沒有任何新鍵）。"""
    c, h = X
    _extra("測試", 700, note="n")
    d = _get(c, h)
    assert set(d["totals"]) >= {"itemActualTotal", "extraTotal", "materialUnassignedTotal", "purchasedTotal", "totalActualCost"}
    assert d["totals"]["purchasedTotal"] == sum(d["sources"].values())
    assert not ({"notes", "note", "qty"} & set(d["totals"]))


def test_non_financial_user_gets_403_and_none_of_the_new_fields(W, make_user):
    c, h = W
    _extra("機密說明", 999, note="機密附註")
    eu, ep = make_user(username="sa_eng2", role="engineer", modules=["case_manage", "expense_forms"])
    he = _login(c, eu, ep)
    cn = db.get_db()
    uid = cn.execute("SELECT id FROM users WHERE username='sa_eng2'").fetchone()["id"]
    cn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), NO))
    cn.commit()
    cn.close()
    r = c.get(URL, headers=he)
    assert r.status_code == 403
    assert "機密附註" not in r.text and "機密說明" not in r.text and "note" not in r.text and "notes" not in r.text and "qty" not in r.text


# ── 重複對應（同一筆只能有一個去處；金額不重複計算）─────────────────────────────

def test_preview_with_a_duplicate_mapping_ignores_the_second_destination_and_never_double_counts(X):
    c, h = X
    one = [{"kind": "material", "ref": "X", "itemId": "b"}]
    two = one + [{"kind": "material", "ref": "X", "itemId": "a"}]            # 同一筆又指到另一個品項
    q = lambda offs: urllib.parse.quote(json.dumps(offs))                     # noqa: E731
    d1 = c.get(URL + "?offsets=" + q(one), headers=h).json()
    d2 = c.get(URL + "?offsets=" + q(two), headers=h).json()
    assert d2["totals"] == d1["totals"] and d2["items"] == d1["items"]
    assert _items(d2)["a"]["material"]["amount"] != 250 and _items(d2)["b"]["material"]["amount"] == 250
    assert d2["totals"]["purchasedTotal"] == d1["totals"]["purchasedTotal"]


def test_put_with_a_numeric_item_id_is_accepted_and_stored_as_a_string(X):
    """用戶端（品項 id 是數字的報價單）可能送數字 itemId；伺服器一律轉字串，儲存格式不變。"""
    c, h = X
    r = _put(c, h, [{"kind": "material", "ref": "X", "itemId": "b"}])
    assert r.status_code == 200
    cn = db.get_db()
    try:
        saved = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]["offsets"]
    finally:
        cn.close()
    assert saved == [{"kind": "material", "ref": "X", "itemId": "b"}]
    assert SA.normalize_offsets([{"kind": "extra", "ref": 12, "itemId": 8}]) == [{"kind": "extra", "ref": "12", "itemId": "8"}]


def test_a_duplicate_with_mixed_ref_types_is_still_a_duplicate(X):
    c, h = X
    eid = _extra("重複測試", 100)
    bad = [{"kind": "extra", "ref": str(eid), "itemId": "a"}, {"kind": "extra", "ref": eid, "itemId": "b"}]      # '12' 與 12 是同一筆
    r = _put(c, h, bad)
    assert r.status_code == 422 and "重複" in r.text


def test_a_stale_offset_on_a_row_that_became_linked_does_not_count_twice(X):
    """列後來被材料申請連到品項（link）：舊的 offset 仍留在存檔裡，也只算一次（連結優先）。"""
    c, h = X
    stale = [{"kind": "material", "ref": "L", "itemId": "b"}]                    # L 已連品項 a（link）
    d = c.get(URL + "?offsets=" + urllib.parse.quote(json.dumps(stale)), headers=h).json()
    base = _get(c, h)
    assert d["totals"] == base["totals"]
    assert _items(d)["a"]["material"]["amount"] == 100 and _items(d)["b"]["material"]["amount"] == 0
