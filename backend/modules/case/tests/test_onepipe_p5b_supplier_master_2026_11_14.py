# -*- coding: utf-8 -*-
"""一條龍 P5b（旗標 `onepipe.supplier_master`，預設開）：採購單廠商可從供應商主檔挑、材料申請沿用採購單的供應商、被引用的供應商不能刪。

- 手動輸入廠商照舊可用（沒有 `supplierId` ⇒ 行為與目前相同）。
- 旗標關 ⇒ 與目前位元組相同：`data.supplierId` 當一般欄位原樣保留、不驗證、不改收款人；供應商刪除不檢查引用；選單路由 404。
"""
import json

import pytest

import db

NO = "MQ-P5B-1"
BASE = "/api/quotations/%s/extra-expenses" % NO


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _flag(monkeypatch, on, *extra):
    from helpers import onepipe_flags
    names = {"supplier_master", *extra}
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field in names)


@pytest.fixture
def W(client, make_user):
    make_user(username="p5b_sa", role="superadmin")
    plain = make_user(username="p5b_plain", role="viewer", modules=[])
    buyer = make_user(username="p5b_buyer", role="sales", modules=["procurement"])
    seller = make_user(username="p5b_seller", role="sales", modules=["quotation", "case_manage", "expense_forms"])
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person, deal_tag)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", "{}", "2026-11-14T00:00:00", "2026-11-14T00:00:00", "p5b_sa", "已成案"))
        for code, name in (("S001", "輝煌網通"), ("S002", "大器線材")):
            conn.execute("INSERT INTO suppliers (code, name, tax_id, phone, lead_time_days, data_json) VALUES (?,?,?,?,?,?)",
                         (code, name, "12345678", "02-1234", 7, json.dumps({"bankAccount": "012-345-6789"})))
        conn.commit()
        ids = [r["id"] for r in conn.execute("SELECT id FROM suppliers ORDER BY code").fetchall()]
    finally:
        conn.close()
    return client, {"sa": _login(client, "p5b_sa", "Test-Pass-123"), "plain": _login(client, *plain), "buyer": _login(client, *buyer), "seller": _login(client, *seller)}, ids


def _po(data=None, **kw):
    b = {"kind": "purchase_order", "lines": [{"category": "雜項", "summary": "x", "qty": 1, "unitCost": 100}],
         "payeeType": "vendor", "payeeName": "手打廠商", "data": dict({"applicant": "p5b_sa"}, **(data or {}))}
    b.update(kw)
    return b


def _row(eid):
    conn = db.get_db()
    try:
        r = conn.execute("SELECT payee_type, payee_name, data_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()
        return r["payee_type"], r["payee_name"], json.loads(r["data_json"] or "{}")
    finally:
        conn.close()


# ── 登錄表欄位 ──────────────────────────────────────────────────────────────
def test_registry_field_is_an_ordinary_default_on_flag():
    from helpers import settings_registry as R
    f = R.field_defs("onepipe")["supplier_master"]
    assert f.default == 1 and f.recommended == 1 and not f.loosen
    from helpers import startup
    assert "supplier_master" not in startup._ONEPIPE_PERMISSION_FLAGS


# ── 採購單挑供應商主檔 ───────────────────────────────────────────────────────
def test_picking_a_supplier_stores_the_id_and_the_master_name_wins(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    r = c.post(BASE, headers=h["sa"], json=_po({"supplierId": ids[0]}))
    assert r.status_code == 201, r.text
    ptype, pname, data = _row(r.json()["id"])
    assert (ptype, pname, data["supplierId"]) == ("vendor", "輝煌網通", ids[0]), "收款人名稱以主檔為準，不採用手打的"


def test_string_id_is_normalised_and_unknown_id_is_refused_in_plain_words(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    r = c.post(BASE, headers=h["sa"], json=_po({"supplierId": str(ids[1])}))
    assert r.status_code == 201 and _row(r.json()["id"])[2]["supplierId"] == ids[1]
    for bad in (999999, "abc", True, -1):
        r = c.post(BASE, headers=h["sa"], json=_po({"supplierId": bad}))
        assert r.status_code == 400, (bad, r.text)
        assert "供應商" in r.json()["detail"]


def test_manual_entry_is_unchanged(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    r = c.post(BASE, headers=h["sa"], json=_po())
    assert r.status_code == 201
    assert _row(r.json()["id"]) == ("vendor", "手打廠商", {"applicant": "p5b_sa"})


def test_switching_back_to_manual_clears_the_link_and_a_typed_name_overrides_a_stale_link(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    eid = c.post(BASE, headers=h["sa"], json=_po({"supplierId": ids[0]})).json()["id"]
    # 明確送 null ⇒ 清掉，收款人照使用者手打的
    r = c.patch("%s/%d" % (BASE, eid), headers=h["sa"], json=_po({"supplierId": None}, payeeName="另一家"))
    assert r.status_code == 200, r.text
    assert _row(eid) == ("vendor", "另一家", {"applicant": "p5b_sa"})
    # 沒明確送 supplierId、但手改了廠商名稱 ⇒ 視為改回手動，不讓名稱與編號不一致
    eid2 = c.post(BASE, headers=h["sa"], json=_po({"supplierId": ids[0]})).json()["id"]
    r = c.patch("%s/%d" % (BASE, eid2), headers=h["sa"], json=_po(payeeName="手改廠商"))
    assert r.status_code == 200, r.text
    ptype, pname, data = _row(eid2)
    assert pname == "手改廠商" and "supplierId" not in data


def test_flag_off_supplier_id_is_just_an_ordinary_key(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h, ids = W
    r = c.post(BASE, headers=h["sa"], json=_po({"supplierId": 999999}))
    assert r.status_code == 201, r.text
    assert _row(r.json()["id"]) == ("vendor", "手打廠商", {"applicant": "p5b_sa", "supplierId": 999999})


def test_other_kinds_ignore_supplier_id(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    r = c.post(BASE, headers=h["sa"], json=_po({"supplierId": 999999}, kind="purchase_req", payeeType="employee"))
    assert r.status_code == 201, r.text


# ── 選單路由 ────────────────────────────────────────────────────────────────
def test_picker_is_404_when_flag_off_and_minimal_when_on(W, monkeypatch):
    c, h, ids = W
    _flag(monkeypatch, False)
    assert c.get("/api/extra-expenses/suppliers", headers=h["sa"]).status_code == 404
    _flag(monkeypatch, True)
    r = c.get("/api/extra-expenses/suppliers", headers=h["sa"])
    assert r.status_code == 200
    rows = r.json()["suppliers"]
    assert [x["name"] for x in rows] == sorted(x["name"] for x in rows) and len(rows) == 2
    assert all(set(x) == {"id", "code", "name"} for x in rows)
    assert "012-345-6789" not in r.text and "12345678" not in r.text
    assert c.get("/api/extra-expenses/suppliers", headers=h["plain"]).status_code == 403


def test_picker_is_never_wider_than_the_supplier_list(W, monkeypatch):
    """與 GET /api/suppliers 同或更窄：報價單／案件管理／費用單據模組的人（名單對他們是空的）一律 403；採購同仁只在 buyer_access 開時看得到。"""
    c, h, ids = W
    _flag(monkeypatch, True)                                              # buyer_access 關
    for who in ("seller", "buyer", "plain"):
        assert c.get("/api/extra-expenses/suppliers", headers=h[who]).status_code == 403, who
    _flag(monkeypatch, True, "buyer_access")                              # buyer_access 開
    assert c.get("/api/extra-expenses/suppliers", headers=h["buyer"]).status_code == 200
    for who in ("seller", "plain"):
        assert c.get("/api/extra-expenses/suppliers", headers=h[who]).status_code == 403, who


# ── 材料申請沿用採購單的供應商 ───────────────────────────────────────────────
def _mk_po_row(supplier_id, doc="PO-20261114-0001"):
    conn = db.get_db()
    try:
        data = {"supplierId": supplier_id} if supplier_id else {}
        conn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, kind, doc_code, status, created_by, created_by_name,"
                     " created_at, updated_at, data_json, lines_json, total_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "其他", "po", "purchase_order", doc, "已核准", "p5b_sa", "p5b_sa", "2026-11-14T00:00:00", "2026-11-14T00:00:00",
                      json.dumps(data), "[]", 0))
        conn.commit()
    finally:
        conn.close()
    return doc


def _inherit(order, monkeypatch, on=True):
    from modules.case import material_guard as MG
    _flag(monkeypatch, on)
    conn = db.get_db()
    try:
        return MG._inherit_po_supplier(conn, NO, order), order
    finally:
        conn.close()


def test_material_order_inherits_the_po_supplier_when_none_given(W, monkeypatch):
    _, _, ids = W
    doc = _mk_po_row(ids[0])
    msg, o = _inherit({"poDocCode": doc}, monkeypatch)
    assert msg is None and o["supplierId"] == ids[0]


def test_material_order_with_a_different_supplier_is_refused_and_same_is_fine(W, monkeypatch):
    _, _, ids = W
    doc = _mk_po_row(ids[0])
    msg, o = _inherit({"poDocCode": doc, "supplierId": ids[1]}, monkeypatch)
    assert msg and "不一致" in msg and doc in msg and o["supplierId"] == ids[1]
    msg, o = _inherit({"poDocCode": doc, "supplierId": str(ids[0])}, monkeypatch)
    assert msg is None


def test_manual_po_missing_po_no_link_and_flag_off_change_nothing(W, monkeypatch):
    _, _, ids = W
    manual = _mk_po_row(None, "PO-20261114-0002")
    for order in ({"poDocCode": manual}, {"poDocCode": "PO-NOPE"}, {}):
        msg, o = _inherit(dict(order), monkeypatch)
        assert msg is None and "supplierId" not in o
    doc = _mk_po_row(ids[0], "PO-20261114-0003")
    msg, o = _inherit({"poDocCode": doc}, monkeypatch, on=False)
    assert msg is None and "supplierId" not in o


# ── 供應商刪除前檢查引用 ─────────────────────────────────────────────────────
def _set_orders(supplier_id):
    conn = db.get_db()
    try:
        d = {"caseRecord": {"materialOrders": [{"itemId": "m1", "supplierId": supplier_id}]}}
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        conn.commit()
    finally:
        conn.close()


def _exists(sid):
    conn = db.get_db()
    try:
        return conn.execute("SELECT 1 FROM suppliers WHERE id=?", (sid,)).fetchone() is not None
    finally:
        conn.close()


def test_supplier_used_by_a_po_cannot_be_deleted(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    doc = _mk_po_row(ids[0])
    r = c.delete("/api/suppliers/%d" % ids[0], headers=h["sa"])
    assert r.status_code == 409 and doc in r.json()["detail"] and "輝煌網通" in r.json()["detail"], r.text
    assert _exists(ids[0])


def test_supplier_used_by_a_material_order_cannot_be_deleted_but_unused_can(W, monkeypatch):
    _flag(monkeypatch, True)
    c, h, ids = W
    _set_orders(ids[1])
    r = c.delete("/api/suppliers/%d" % ids[1], headers=h["sa"])
    assert r.status_code == 409 and NO in r.json()["detail"], r.text
    assert _exists(ids[1])
    assert c.delete("/api/suppliers/%d" % ids[0], headers=h["sa"]).status_code == 200
    assert not _exists(ids[0])


def test_flag_off_delete_does_not_check_references(W, monkeypatch):
    _flag(monkeypatch, False)
    c, h, ids = W
    _mk_po_row(ids[0])
    assert c.delete("/api/suppliers/%d" % ids[0], headers=h["sa"]).status_code == 200
