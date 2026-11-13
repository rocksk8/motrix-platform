# -*- coding: utf-8 -*-
"""一條龍 D6=B（旗標 `onepipe.po_skip_resign`，預設關、放寬類）：叫料連到已核准採購單行、且沒超出採購單 ⇒ 送審即核准，不再走簽核層。

符合條件才免簽；任何一項不符（超出數量／小計、採購單未核准、供應商不同、已有付款紀錄、沒連採購單）⇒ 照原本簽核流程。
旗標關 ⇒ 與目前完全相同（一律簽核）；已在簽核中的單不追溯；審核紀錄註明原因。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

NO = "MQ-D6-001"
ITEM = "it-d6-1"
BASE = "/api/quotations/%s/material-orders/%s" % (NO, ITEM)
PO = "PO-20261114-0001"

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "po_skip_resign")


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _case(**order_kw):
    order = {"itemId": ITEM, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1500, "totalPrice": 3000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "poDocCode": PO, "poLine": 1}
    order.update(order_kw)
    data = {"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "叫料客", "叫料專案", 100000, 95238, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))


def _po(status="已核准", supplier_id=None, qty=2, amount=3000, doc=PO):
    data = {"supplierId": supplier_id} if supplier_id else {}
    lines = [{"summary": "交換器", "qty": qty, "unit": "台", "unitCost": amount / qty if qty else 0, "amount": amount}]
    _x("INSERT INTO case_extra_expenses (quote_no, category, description, kind, doc_code, status, created_by, created_by_name,"
       " created_at, updated_at, data_json, lines_json, total_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "其他", "po", "purchase_order", doc, status, "d6_eng", "d6_eng", "2026-01-01T00:00:00", "2026-01-01T00:00:00",
        json.dumps(data), json.dumps(lines), amount))


def _flow_one_tier(boss):
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": [{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}],
                                            "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


@pytest.fixture
def world(client, make_user):
    eng, ep = make_user(username="d6_eng", role="superadmin")
    boss, _bp = make_user(username="d6_boss", role="sales")
    _flow_one_tier(boss)
    return client, _login(client, eng, ep)


def _submit(world):
    c, h = world
    return c.post(BASE + "/submit", headers=h)


def _approval_json():
    return json.loads(_q("SELECT approval_json FROM case_material_approvals WHERE quote_no=?", (NO,))[0]["approval_json"])


# ── 登錄表 ──────────────────────────────────────────────────────────────────
def test_registry_flag_is_a_loosening_default_off_setting():
    from helpers import settings_registry as R
    f = R.field_defs("onepipe")["po_skip_resign"]
    assert f.default == 0 and f.recommended == 0 and f.loosen == "up"
    from helpers import startup
    assert "po_skip_resign" in startup._ONEPIPE_PERMISSION_FLAGS


# ── 符合條件 ⇒ 免簽 ─────────────────────────────────────────────────────────
def test_linked_to_an_approved_po_within_limits_is_approved_on_submit(world, monkeypatch):
    _flag(monkeypatch, True)
    _case()
    _po()
    r = _submit(world)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已核准" and r.json()["autoApproved"] is True and r.json()["tierCount"] == 0 and r.json().get("poAutoApproved") is True
    a = _approval_json()
    assert a["poAutoApproved"] is True and PO in a["note"] and a["history"][-1]["comment"] == a["note"]
    assert _q("SELECT status FROM case_material_approvals WHERE quote_no=?", (NO,))[0]["status"] == "已核准"
    assert "material_orders.auto_approve" in [x["action"] for x in _q("SELECT action FROM audit_log WHERE target_id=?", (NO,))]
    assert _q("SELECT COUNT(*) AS n FROM notifications WHERE type='material_order_approval_request'")[0]["n"] == 0, "沒有簽核人需要被通知"


def test_lower_quantity_and_total_than_the_po_line_is_still_fine(world, monkeypatch):
    _flag(monkeypatch, True)
    _case(quantity=1, totalPrice=1500)
    _po()
    assert _submit(world).json()["status"] == "已核准"


def test_same_supplier_is_fine(world, monkeypatch):
    _flag(monkeypatch, True)
    _case(supplierId=7)
    _po(supplier_id=7)
    assert _submit(world).json()["status"] == "已核准"


# ── 不符合 ⇒ 照原本簽核 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("order_kw,po_kw", [
    ({"quantity": 3, "totalPrice": 3000}, {}),                          # 數量超出
    ({"totalPrice": 3001}, {}),                                          # 小計超出
    ({}, {"status": "待審核"}),                                           # 採購單還沒核准
    ({}, {"status": "簽核中"}),
    ({"supplierId": 8}, {"supplier_id": 7}),                             # 供應商不同
    ({"poDocCode": "", "poLine": ""}, {}),                              # 沒連採購單
    ({"poLine": 2}, {}),                                                 # 列序不存在
], ids=["qty-over", "total-over", "po-pending", "po-in-progress", "supplier-differs", "no-link", "bad-line"])
def test_anything_off_goes_through_the_normal_approval(world, monkeypatch, order_kw, po_kw):
    _flag(monkeypatch, True)
    _case(**order_kw)
    _po(**po_kw)
    r = _submit(world)
    if r.status_code != 200:                                            # 連結檢查本來就會擋的（例：列序不存在）⇒ 不是免簽
        assert r.status_code == 400 and _q("SELECT COUNT(*) AS n FROM case_material_approvals WHERE status='已核准'")[0]["n"] == 0
        return
    assert r.json()["status"] == "待審核" and r.json()["autoApproved"] is False and "poAutoApproved" not in r.json()


def test_a_paid_order_never_skips(world, monkeypatch):
    _flag(monkeypatch, True)
    _case(paidAmount=100, paidStatus="partial")
    _po()
    r = _submit(world)
    assert r.status_code != 200 or r.json()["status"] == "待審核"


def test_flag_off_is_exactly_today(world, monkeypatch):
    _flag(monkeypatch, False)
    _case()
    _po()
    r = _submit(world)
    assert r.status_code == 200 and r.json()["status"] == "待審核" and r.json()["tierCount"] == 1 and "poAutoApproved" not in r.json()
    assert "poAutoApproved" not in _approval_json()


def test_no_tier_flow_message_is_unchanged_when_not_po_linked(world, monkeypatch):
    """沒設簽核層的原本自動核准：紀錄文字不變（旗標開也一樣，只要不是連採購單免簽）。"""
    _flag(monkeypatch, True)
    _x("DELETE FROM system_settings WHERE key='unified_approval_flow'")
    _case(poDocCode="", poLine="")
    r = _submit(world)
    assert r.status_code == 200 and r.json()["autoApproved"] is True and "poAutoApproved" not in r.json()
    assert _approval_json()["note"] == "未設定任何簽核層，送審即視為核准"


# ── 判斷函式本身 ────────────────────────────────────────────────────────────
def test_decision_function_never_raises_and_is_empty_when_flag_off(world, monkeypatch):
    import db
    from modules.case.po_auto_approve import auto_approve_note
    _case()
    _po()
    conn = db.get_db()
    try:
        _flag(monkeypatch, False)
        assert auto_approve_note(conn, NO, {"poDocCode": PO, "poLine": 1, "quantity": 1, "totalPrice": 1}) == ""
        _flag(monkeypatch, True)
        assert PO in auto_approve_note(conn, NO, {"poDocCode": PO, "poLine": 1, "quantity": 1, "totalPrice": 1})
        for bad in (None, {}, {"poDocCode": PO, "poLine": "x"}, {"poDocCode": PO, "poLine": True}, {"poDocCode": "NOPE"}, {"poDocCode": PO, "poLine": 1, "totalPrice": "abc"}):
            assert isinstance(auto_approve_note(conn, NO, bad), str)
        assert auto_approve_note(conn, "MQ-OTHER", {"poDocCode": PO, "poLine": 1}) == "", "別的案件的採購單不算"
    finally:
        conn.close()


def test_already_in_flight_orders_are_not_retroactive(world, monkeypatch):
    """旗標關時送審（待審核）；之後開旗標，這筆仍是待審核、不會被自動核准。"""
    _case()
    _po()
    _flag(monkeypatch, False)
    assert _submit(world).json()["status"] == "待審核"
    _flag(monkeypatch, True)
    assert _q("SELECT status FROM case_material_approvals WHERE quote_no=?", (NO,))[0]["status"] == "待審核"
    c, h = world
    assert c.post(BASE + "/submit", headers=h).status_code == 409, "待審核不能重複送審；不會因旗標開啟而改核准"
