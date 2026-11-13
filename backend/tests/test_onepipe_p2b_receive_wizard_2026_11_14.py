# -*- coding: utf-8 -*-
"""T85 一條龍 P2b「一站式到貨」（旗標 onepipe.receive_wizard；決策 D1＝A 入庫或直送、D2＋D8＝A 耗材到貨即領用、D7＝A 已到數量分批累計）。

關＝與今天逐位元相同（端點 404、核准摘要沒有 receivedQty 鍵、時間軸到貨格文字不變、舊的「確認到貨」與「撤銷」照舊）；
開＝已到數量分批累計（超收擋下）、入庫（序號貼上逐列回報）／直送／耗材、沒有入庫權限只做案件那一半、補入庫不動數量、撤銷清空已到數量。
"""
import json

import pytest

from tests._requires import requires_module
pytestmark = requires_module("supply", "本檔測案件到貨與庫存入庫的串接")
needs_m01 = requires_module("case", "本檔測 M01 的材料申請到貨")

from tests.test_api_integration import _auth, _login

NO = "MQ-P2B-001"
ITEM = "w1"
BASE = "/api/quotations/%s/material-orders/%s" % (NO, ITEM)


def _flags(monkeypatch, **on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on.get(field)))


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
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _part(part_no="NET-P2B", cost=100):
    _x("INSERT OR IGNORE INTO parts (part_no, name, active, cost, created_at, updated_at) VALUES (?,?,1,?,?,?)",
       (part_no, "測試交換器", cost, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))


def _case(assigned=(), qty=12, approved=True, received_on=""):
    order = {"itemId": ITEM, "itemName": "交換器 24 埠", "quantity": qty, "unit": "台", "unitPrice": 1500, "totalPrice": 1500 * qty, "poDocCode": "PO-77", "supplierId": None}
    data = {"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "客", "專案", 100000, 95238, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", json.dumps(list(assigned))))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)",
       (NO, ITEM, "MR-P2B-1", "已核准" if approved else "草稿", received_on))


def _row():
    return _q("SELECT received_on, received_qty FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, ITEM))[0]


def _admin(client, make_user, name="p2b_admin"):
    return _auth(_login(client, *make_user(username=name, role="admin")))


# ── parse_serials ─────────────────────────────────────────────────────────

def test_parse_serials_accepts_lines_commas_tabs_and_mac():
    from modules.case.material_receive import parse_serials
    got = parse_serials({"serialsText": "SN1\nSN2, SN3;SN4\n\n  \nSN5\t00:11:22:33:44:55\n", "serials": ["SN0", {"serialNo": "SN9", "mac": "aa"}, ""]})
    assert [g["serialNo"] for g in got] == ["SN0", "SN9", "SN1", "SN2", "SN3", "SN4", "SN5"]
    assert got[-1]["mac"] == "00:11:22:33:44:55" and got[1]["mac"] == "aa"
    assert parse_serials({}) == [] and parse_serials({"serialsText": "  \n "}) == []


# ── migration ─────────────────────────────────────────────────────────────

@needs_m01
def test_migration_adds_nullable_received_qty(client):
    cols = {r["name"]: r for r in _q("PRAGMA table_info(case_material_approvals)")}
    assert "received_qty" in cols and cols["received_qty"]["notnull"] == 0


# ── 旗標關＝今天 ──────────────────────────────────────────────────────────

@needs_m01
def test_flag_off_endpoint_404_keys_and_old_receive_unchanged(client, make_user, monkeypatch):
    _flags(monkeypatch)
    admin = _admin(client, make_user)
    _case()
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "consumable"}, headers=admin)
    assert r.status_code == 404 and _row() == {"received_on": "", "received_qty": None}
    ap = client.get("/api/quotations/%s/material-order-approvals" % NO, headers=admin).json()["approvals"][ITEM]
    assert "receivedQty" not in ap
    assert client.post(BASE + "/receive", json={"receivedOn": "2026-11-10"}, headers=admin).status_code == 200
    assert _row() == {"received_on": "2026-11-10", "received_qty": None}                  # 舊的確認到貨不寫已到數量（＝全數）
    assert client.delete(BASE + "/receive", headers=admin).status_code == 200
    assert _row() == {"received_on": "", "received_qty": None}


# ── 分批累計與超收 ────────────────────────────────────────────────────────

@needs_m01
def test_partial_receipts_accumulate_and_over_receipt_is_rejected(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True)
    admin = _admin(client, make_user)
    _case(qty=12)
    r1 = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "consumable", "receivedOn": "2026-11-10"}, headers=admin)
    assert r1.status_code == 200, r1.text
    b = r1.json()
    assert (b["receivedQty"], b["appliedQty"], b["remaining"], b["mode"]) == (4, 12, 8, "consumable") and b["stock"] == {"skipped": "consumable"}
    assert _row() == {"received_on": "2026-11-10", "received_qty": 4.0}
    ap = client.get("/api/quotations/%s/material-order-approvals" % NO, headers=admin).json()["approvals"][ITEM]
    assert ap["receivedQty"] == 4.0 and ap["receivedOn"] == "2026-11-10"
    from modules.case import material_shippable as MS
    import db
    conn = db.get_db()
    try:
        arrived = MS.material_shippable(conn, NO)[0]["arrivedQty"]
    finally:
        conn.close()
    assert arrived == 4                                                                       # 出貨側只看到已到的 4 件
    assert client.post(BASE + "/receive-stock", json={"qty": 9, "mode": "consumable"}, headers=admin).status_code == 409   # 4＋9 超收
    assert _row()["received_qty"] == 4.0
    r2 = client.post(BASE + "/receive-stock", json={"qty": 8, "mode": "consumable", "receivedOn": "2026-11-12"}, headers=admin)
    assert r2.status_code == 200 and r2.json()["remaining"] == 0 and _row() == {"received_on": "2026-11-12", "received_qty": 12.0}
    assert client.post(BASE + "/receive-stock", json={"qty": 1, "mode": "consumable"}, headers=admin).status_code == 409
    assert "material_orders.receive_stock" in {r["action"] for r in _q("SELECT action FROM audit_log")}
    assert client.delete(BASE + "/receive", headers=admin).status_code == 200
    assert _row() == {"received_on": "", "received_qty": None}                                # 撤銷一併清空已到數量


@needs_m01
def test_timeline_arrive_cell_shows_partial_only_when_flag_on(client, make_user, monkeypatch):
    from modules.case import material_flow as MF
    import db
    _flags(monkeypatch, receive_wizard=True)
    admin = _admin(client, make_user)
    _case(qty=12)
    client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "consumable"}, headers=admin)
    data = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])
    conn = db.get_db()
    try:
        _call, arrive = MF._call_and_arrive(conn, NO, data)
        _flags(monkeypatch)                                                                   # 關：同一份資料，文字與今天相同
        _call2, arrive_off = MF._call_and_arrive(conn, NO, data)
    finally:
        conn.close()
    assert arrive["state"] == "inprogress" and arrive["summary"] == "1 張已核准的材料申請單，0 張已到貨；1 張只到部分"
    assert arrive["items"][0]["receivedQty"] == 4 and arrive["items"][0]["appliedQty"] == 12 and arrive["items"][0]["arrived"] is False
    assert arrive_off["summary"] == "1 張已核准的材料申請單，1 張已到貨" and "receivedQty" not in arrive_off["items"][0]


# ── 入庫、直送、耗材 ──────────────────────────────────────────────────────

@needs_m01
def test_stock_mode_writes_serials_row_by_row_and_counts_the_case_half(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _part()
    _case(qty=12)
    text = "SN-A\nSN-B\nSN-A\nSN-C"                                                           # SN-A 重複貼上
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "stock", "partNo": "NET-P2B", "serialsText": text, "receivedOn": "2026-11-10", "unitCost": 250}, headers=admin)
    assert r.status_code == 200, r.text
    st = r.json()["stock"]
    assert st["ok"] and st["written"] == 3 and st["rejected"] == 1
    assert [x["status"] for x in st["batches"][0]["rows"]].count("rejected") == 1
    assert _row() == {"received_on": "2026-11-10", "received_qty": 4.0}
    hdr = _q("SELECT quote_no, po_doc_code, material_item_id, delivery_mode FROM stock_batches")[0]
    assert hdr == {"quote_no": NO, "po_doc_code": "PO-77", "material_item_id": ITEM, "delivery_mode": "stock"}
    assert sorted(i["serial_no"] for i in _q("SELECT serial_no FROM stock_items")) == ["SN-A", "SN-B", "SN-C"]
    assert {i["cost"] for i in _q("SELECT cost FROM stock_items")} == {250}
    assert _q("SELECT 1 FROM stock_item_events WHERE event='receive'") and len(_q("SELECT 1 FROM stock_item_events WHERE event='receive'")) == 3


@needs_m01
def test_direct_mode_and_second_partial_direct_are_allowed(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _case(qty=10)
    a = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "direct"}, headers=admin)
    b = client.post(BASE + "/receive-stock", json={"qty": 6, "mode": "direct"}, headers=admin)      # 分批直送：數量上限由案件側管
    assert a.status_code == b.status_code == 200
    assert [r["delivery_mode"] for r in _q("SELECT delivery_mode FROM stock_batches ORDER BY batch_no")] == ["direct", "direct"]
    assert _q("SELECT 1 FROM stock_items") == [] and _row()["received_qty"] == 10.0
    assert client.post(BASE + "/receive-stock", json={"qty": 1, "mode": "direct"}, headers=admin).status_code == 409   # 已到齊再送＝超收


@needs_m01
def test_validation_errors_write_nothing(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _part()
    _case(qty=12)
    bad = [({"qty": 4, "mode": "teleport"}, 400),
           ({"mode": "consumable"}, 400),                                                    # 沒填數量
           ({"qty": 0, "mode": "consumable"}, 400),
           ({"supplement": True, "mode": "stock", "serialsText": "S1"}, 409),                 # 還沒確認到貨就補入庫
           ({"qty": 1, "mode": "stock", "partNo": "NET-P2B", "serialsText": "S1\nS2"}, 400),   # 序號比數量多
           ({"qty": 4, "mode": "consumable", "serialsText": "S1"}, 400),                     # 耗材沒有序號
           ({"qty": 60, "mode": "stock", "partNo": "NET-P2B", "serialsText": "\n".join("S%03d" % i for i in range(51))}, 400),
           ({"qty": 4, "mode": "consumable", "receivedOn": "2026-13-40"}, 400)]
    for body, code in bad:
        assert client.post(BASE + "/receive-stock", json=body, headers=admin).status_code == code, body
    assert _row() == {"received_on": "", "received_qty": None} and _q("SELECT 1 FROM stock_items") == [] and _q("SELECT 1 FROM stock_batches") == []


@needs_m01
def test_unapproved_item_is_rejected(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True)
    admin = _admin(client, make_user)
    _case(approved=False)
    assert client.post(BASE + "/receive-stock", json={"qty": 1, "mode": "consumable"}, headers=admin).status_code == 409


# ── 權限降級（D9）與補入庫 ────────────────────────────────────────────────

@needs_m01
def test_no_stock_permission_does_case_half_only_and_admin_supplements_later(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    _part()
    staff_name, staff_pw = make_user(username="p2b_staff", role="sales")
    uid = _q("SELECT id FROM users WHERE username=?", (staff_name,))[0]["id"]
    _case(assigned=[uid], qty=12)
    staff = _auth(_login(client, staff_name, staff_pw))
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "stock", "partNo": "NET-P2B", "serialsText": "SN-S1\nSN-S2"}, headers=staff)
    assert r.status_code == 200, r.text
    assert r.json()["stock"] == {"ok": False, "reason": "NO_PERMISSION"} and r.json()["receivedQty"] == 4
    assert _row()["received_qty"] == 4.0 and _q("SELECT 1 FROM stock_items") == []         # 案件那一半成立、庫存沒寫
    admin = _admin(client, make_user)
    rec = client.get("/api/inventory/reconcile", headers=admin).json()
    assert [(i["quoteNo"], i["itemId"]) for i in rec["items"]] == [(NO, ITEM)]               # 對帳表列出待補入庫
    s = client.post(BASE + "/receive-stock", json={"supplement": True, "mode": "stock", "partNo": "NET-P2B", "serialsText": "SN-S1\nSN-S2"}, headers=admin)
    assert s.status_code == 200 and s.json()["stock"]["written"] == 2 and s.json()["supplement"] is True
    assert _row()["received_qty"] == 4.0                                                      # 補入庫不動已到數量
    assert client.get("/api/inventory/reconcile", headers=admin).json()["items"] == []
    assert client.post(BASE + "/receive-stock", json={"supplement": True, "mode": "consumable"}, headers=admin).status_code == 400


@needs_m01
def test_non_member_cannot_receive(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True)
    _case(assigned=[])
    other = _auth(_login(client, *make_user(username="p2b_other", role="sales")))
    r = client.post(BASE + "/receive-stock", json={"qty": 1, "mode": "consumable"}, headers=other)
    assert r.status_code in (403, 404) and _row() == {"received_on": "", "received_qty": None}


@needs_m01
def test_stock_module_absent_does_case_half_only(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    from core import registry
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "stock.receive" else real(cap))
    admin = _admin(client, make_user)
    _case(qty=12)
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "direct"}, headers=admin)
    assert r.status_code == 200 and r.json()["stock"] == {"ok": False, "reason": "NO_STOCK_MODULE"} and _row()["received_qty"] == 4.0


@needs_m01
def test_stock_line_error_rolls_back_the_case_half(client, make_user, monkeypatch):
    """庫存那一半整列被擋（直送重複）⇒ 案件那一半一起回滾（同一筆交易）。"""
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    from core import registry
    real = registry.single_provider

    def fake(conn, quote_no, lines, caller=None):
        return {"ok": True, "batches": [{"batchNo": "", "error": "這筆材料申請已經登載過直送，請勿重複送出", "rows": []}], "written": 0, "rejected": 0}
    monkeypatch.setattr(registry, "single_provider", lambda cap: fake if cap == "stock.receive" else real(cap))
    admin = _admin(client, make_user)
    _case(qty=12)
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "direct"}, headers=admin)
    assert r.status_code == 409 and "直送" in r.text
    assert _row() == {"received_on": "", "received_qty": None}


# ── P2b 審查補強（h9／PM）：案件權限者、撤銷、耗材、零數量 ─────────────────────────

def _staff(make_user, client, name="p2b_staff"):
    n, pw = make_user(username=name, role="sales")
    uid = _q("SELECT id FROM users WHERE username=?", (n,))[0]["id"]
    return uid, lambda: _auth(_login(client, n, pw))


@needs_m01
def test_case_only_user_can_register_stock_mode_without_part_no(client, make_user, monkeypatch):
    """只有案件權限的人讀不到料號清單：入庫方式不給料號 ⇒ 只做案件那一半（不是 400），序號不寫、由管理員補。"""
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    uid, login = _staff(make_user, client)
    _case(assigned=[uid], qty=12)
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "stock", "serialsText": "SN-X1"}, headers=login())
    assert r.status_code == 200, r.text
    assert r.json()["stock"] == {"ok": False, "reason": "NO_PART"} and _row()["received_qty"] == 4.0
    assert _q("SELECT 1 FROM stock_items") == []
    admin = _admin(client, make_user)
    assert [i["itemId"] for i in client.get("/api/inventory/reconcile", headers=admin).json()["items"]] == [ITEM]       # 對帳表仍列出
    assert client.post(BASE + "/receive-stock", json={"supplement": True, "mode": "stock", "serialsText": "SN-X1"}, headers=admin).status_code == 400   # 補入庫一定要料號


@needs_m01
def test_consumable_writes_header_is_handled_and_needs_no_stock_permission(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    uid, login = _staff(make_user, client)
    _case(assigned=[uid], qty=10)
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "consumable"}, headers=login())       # 非管理員也行（沒有庫存可動）
    assert r.status_code == 200, r.text
    assert r.json()["stock"]["ok"] is True and r.json()["stock"]["batches"][0]["batchNo"].startswith("CN")
    hdr = _q("SELECT delivery_mode, material_item_id, quote_no FROM stock_batches")
    assert hdr == [{"delivery_mode": "consumable", "material_item_id": ITEM, "quote_no": NO}] and _q("SELECT 1 FROM stock_items") == []
    admin = _admin(client, make_user)
    assert client.get("/api/inventory/reconcile", headers=admin).json()["items"] == []                     # 耗材算已處理，不再永遠列在對帳表
    assert client.post(BASE + "/receive-stock", json={"qty": 6, "mode": "consumable"}, headers=admin).status_code == 200   # 分批第二筆
    assert len(_q("SELECT 1 FROM stock_batches WHERE delivery_mode='consumable'")) == 2


@needs_m01
def test_consumable_with_ledger_off_skips_stock_half(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True)
    admin = _admin(client, make_user)
    _case(qty=10)
    r = client.post(BASE + "/receive-stock", json={"qty": 4, "mode": "consumable"}, headers=admin)
    assert r.status_code == 200 and r.json()["stock"] == {"skipped": "consumable"} and _q("SELECT 1 FROM stock_batches") == []


@needs_m01
def test_undo_removes_direct_and_consumable_headers_and_allows_reregister(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _case(qty=10)
    assert client.post(BASE + "/receive-stock", json={"qty": 10, "mode": "direct"}, headers=admin).status_code == 200
    assert len(_q("SELECT 1 FROM stock_batches")) == 1
    assert client.delete(BASE + "/receive", headers=admin).status_code == 200
    assert _q("SELECT 1 FROM stock_batches") == [] and _row() == {"received_on": "", "received_qty": None}
    assert [i["itemId"] for i in client.get("/api/inventory/reconcile", headers=admin).json()["items"]] == []   # 撤銷後沒有殘影
    r = client.post(BASE + "/receive-stock", json={"qty": 10, "mode": "direct"}, headers=admin)               # 重新登載不再被「已登載過直送」擋住
    assert r.status_code == 200, r.text
    assert len(_q("SELECT 1 FROM stock_batches")) == 1


@needs_m01
def test_undo_is_blocked_when_serials_were_stocked_and_changes_nothing(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _part()
    _case(qty=12)
    assert client.post(BASE + "/receive-stock", json={"qty": 2, "mode": "stock", "partNo": "NET-P2B", "serialsText": "U1\nU2", "receivedOn": "2026-11-10"}, headers=admin).status_code == 200
    d = client.delete(BASE + "/receive", headers=admin)
    assert d.status_code == 409 and "庫存" in d.text
    assert _row() == {"received_on": "2026-11-10", "received_qty": 2.0}                                   # 案件那一半也沒動
    assert sorted(i["serial_no"] for i in _q("SELECT serial_no FROM stock_items")) == ["U1", "U2"] and len(_q("SELECT 1 FROM stock_batches")) == 1
    _x("DELETE FROM stock_items")                                                                            # 序號處理掉（刪除）後，空的入庫表頭可被收回
    assert client.delete(BASE + "/receive", headers=admin).status_code == 200
    assert _q("SELECT 1 FROM stock_batches") == [] and _row() == {"received_on": "", "received_qty": None}


@needs_m01
def test_undo_is_blocked_when_a_header_is_marked_paid(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True, receive_ledger=True)
    admin = _admin(client, make_user)
    _case(qty=10)
    assert client.post(BASE + "/receive-stock", json={"qty": 10, "mode": "direct", "invoiceNo": "INV-1"}, headers=admin).status_code == 200
    _x("UPDATE stock_batches SET is_paid=1, paid_by='x', paid_at='2026-11-12T00:00:00' WHERE quote_no=?", (NO,))
    d = client.delete(BASE + "/receive", headers=admin)
    assert d.status_code == 409 and "付款" in d.text
    assert len(_q("SELECT 1 FROM stock_batches")) == 1 and _row()["received_qty"] == 10.0                 # 付款紀錄與案件那一半都沒動


@needs_m01
def test_undo_with_wizard_off_never_touches_stock(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_ledger=True)
    admin = _admin(client, make_user)
    _case(received_on="2026-11-10")
    _x("INSERT INTO stock_batches (batch_no, part_no, created_at, updated_at, quote_no, po_doc_code, material_item_id, delivery_mode) VALUES ('DR-9','',?,?,?,?,?,'direct')",
       ("2026-11-10T00:00:00", "2026-11-10T00:00:00", NO, "PO-77", ITEM))
    assert client.delete(BASE + "/receive", headers=admin).status_code == 200
    assert len(_q("SELECT 1 FROM stock_batches")) == 1                                                       # 旗標關＝今天的行為，不碰庫存


@needs_m01
def test_zero_quantity_order_cannot_bypass_over_receipt_cap(client, make_user, monkeypatch):
    _flags(monkeypatch, receive_wizard=True)
    admin = _admin(client, make_user)
    _case(qty=0)
    r = client.post(BASE + "/receive-stock", json={"qty": 5, "mode": "consumable"}, headers=admin)
    assert r.status_code == 409 and _row() == {"received_on": "", "received_qty": None}

