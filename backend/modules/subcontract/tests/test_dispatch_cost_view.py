"""IP-15 追加 `dispatch.cost_for_case`：派工成本檢視（M04 → M06 傳票；需要本模組在）。

- 登記、權限（finance／cashier 放行，沒有相關模組 ⇒ 403）
- 白名單：回應只有規定的鍵，**任何層都沒有姓名欄位**，外包人員姓名字串不出現在回應裡；外包人數＝有名字的人員數
- 金額與 `dispatch.row` 的 grandTotal 同一份算法
- `dispatch.list_for_case` 的回應不變（只新增）
本模組不在時：取用方拿到 None，照 INTEGRATION-POINTS IP-15 那一列的說明明說（M06 的題負責）。
"""
import json

import pytest

from core import registry

QNO = "MQ-202609-C15"
SECRET_NAMES = ("王小明", "陳大華")
ALLOWED = {"id", "quoteNo", "vendorName", "scope", "invoiceNo", "dispatchDate", "invoiceDate", "payableDate", "amount", "totalWithTax",
           "personnelTotal", "personnelCount", "items"}


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Cost-Pass-123", role=role, modules=modules)[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return "Bearer " + r.json()["token"]


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES (?,?,?)",
                     ("甲工程行", "2026-09-26T00:00:00", "2026-09-26T00:00:00"))
        vid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, "
                     "total_amount, notes, status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (QNO, vid, "2026-09-20", "機房配線（內部細節）",
                      json.dumps([{"description": "配線", "qty": 3, "unit": "式", "unitPrice": 1200, "amount": 3600},
                                  {"description": "", "amount": 0}]),
                      json.dumps([{"id": 1, "name": SECRET_NAMES[0], "amount": 2000},
                                  {"id": 2, "name": SECRET_NAMES[1], "amount": 1500},
                                  {"id": 3, "name": "", "amount": 0}]),
                      3600, "派工備註（內部）", "pending", "creator_x", "2026-09-26T00:00:00", "2026-09-26T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _keys_anywhere(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys_anywhere(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys_anywhere(v)


def test_cost_view_is_registered_and_list_for_case_is_unchanged(client, make_user):
    fn = registry.single_provider("dispatch.cost_for_case")
    assert fn is not None
    _seed()
    auth = _login(client, make_user, "c15_sa", role="superadmin")
    full = registry.single_provider("dispatch.list_for_case")(QNO, auth)
    assert full and full[0]["personnel"] and full[0]["scope"], "只新增：IP-15 既有回應照舊（含 personnel、scope）"


@pytest.mark.parametrize("modules", [["finance"], ["cashier"]])
def test_finance_and_cashier_get_the_cost_view(client, make_user, modules):
    _seed()
    auth = _login(client, make_user, "c15_" + modules[0], modules=modules)
    got = registry.single_provider("dispatch.cost_for_case")(QNO, auth)
    assert len(got) == 1
    row = got[0]
    assert set(row) == ALLOWED, set(row) ^ ALLOWED
    assert row["vendorName"] == "甲工程行" and row["quoteNo"] == QNO and row["dispatchDate"] == "2026-09-20"
    assert row["personnelCount"] == 2 and row["personnelTotal"] == 3500
    assert row["items"] == [{"description": "配線", "amount": 3600}]
    assert row["scope"] == "機房配線（內部細節）" and row["invoiceNo"] == ""
    assert row["amount"] == 3600 * 1.05 + 3500, "金額與 dispatch.row 的 grandTotal 同一份算法"


def test_cost_view_carries_no_names_or_details(client, make_user):
    """白名單的反向：任何層都沒有姓名類欄位（name／personnel／createdBy／acceptedBy…），姓名與派工細節字串不出現。
    突變：cost view 帶回 personnel 或 notes ⇒ 紅。（scope、invoiceNo 是主持裁示加入的會計欄位，不在禁止之列）"""
    _seed()
    auth = _login(client, make_user, "c15_fin2", modules=["finance"])
    got = registry.single_provider("dispatch.cost_for_case")(QNO, auth)
    keys = set(_keys_anywhere(got))
    assert not {k for k in keys if "name" in k.lower() and k != "vendorName"}, keys
    assert not keys & {"personnel", "notes", "files", "createdBy", "acceptedBy", "status"}, keys
    text = json.dumps(got, ensure_ascii=False)
    for s in SECRET_NAMES + ("派工備註（內部）", "creator_x"):
        assert s not in text, (s, text)


def test_users_without_a_related_module_are_refused(client, make_user):
    from fastapi import HTTPException
    _seed()
    auth = _login(client, make_user, "c15_none", modules=["dashboard"])
    with pytest.raises(HTTPException) as e:
        registry.single_provider("dispatch.cost_for_case")(QNO, auth)
    assert e.value.status_code == 403
