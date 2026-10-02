# -*- coding: utf-8 -*-
"""叫料審核（31-C S2）端點：送審／核准／退回／撤回／取消／到貨確認、簽核佇列與詳情、通知與稽核。

走真實 HTTP（`client`）。案件 `data_json.caseRecord.materialOrders` 先種好一筆叫料；簽核流程用 `unified_approval_flow`。
每個「不可以」都驗狀態沒變、沒有多出稽核／通知。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

NO = "MQ-MATA-001"
ITEM = "it-api-1"
BASE = "/api/quotations/%s/material-orders/%s" % (NO, ITEM)


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    return _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def _case(assigned=()):
    order = {"itemId": ITEM, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1500, "totalPrice": 3000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    data = {"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "叫料客", "叫料專案", 100000, 95238, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "",
        json.dumps(list(assigned))))


def _flow(tiers):
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


def _one_tier(boss):
    _flow([{"order": 0, "approvers": [{"username": boss, "displayName": "主管"}]}])


def _queue_codes():
    from core import registry
    import db
    conn = db.get_db()
    try:
        return [i["docCode"] for i in registry.providers("approval.queue_items")["case_material"](conn)]
    finally:
        conn.close()


def _audit_actions():
    return [r["action"] for r in _q("SELECT action FROM audit_log WHERE target_id=? ORDER BY id", (NO,))]


@pytest.fixture
def world(client, make_user):
    eng, ep = make_user(username="ma_eng", role="sales")
    boss, bp = make_user(username="ma_boss", role="sales")
    peer, pp = make_user(username="ma_peer", role="sales")
    adm, ap = make_user(username="ma_adm", role="admin")
    nofin, nfp = make_user(username="ma_nofin", role="engineer", modules=[])
    _case(assigned=[_uid(eng), _uid(peer), _uid(nofin)])
    return {"eng": _login(client, eng, ep), "boss": _login(client, boss, bp), "peer": _login(client, peer, pp), "adm": _login(client, adm, ap),
            "nofin": _login(client, nofin, nfp), "boss_name": boss, "eng_name": eng}


def _approval(client, h):
    r = client.get("/api/quotations/%s/material-order-approvals" % NO, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["approvals"][ITEM]


def test_no_tier_submit_is_auto_approved_with_a_document_code_and_audit(client, world):
    _flow([])
    assert _approval(client, world["eng"]) == {"status": "", "legacy": True}                # 還沒有審核單＝舊單
    r = client.post(BASE + "/submit", headers=world["eng"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已核准" and r.json()["autoApproved"] is True and r.json()["docCode"].startswith("MO-")
    a = _approval(client, world["eng"])
    assert a["status"] == "已核准" and a["docCode"] == r.json()["docCode"] and a["legacy"] is False
    assert "material_orders.auto_approve" in _audit_actions()


def test_submit_permissions_and_closed_case(client, world):
    _flow([])
    assert client.post(BASE + "/submit", headers=world["nofin"]).status_code == 403         # 看不到金額的人不能送審
    r = client.post("/api/quotations/NOPE/material-orders/x/submit", headers=world["eng"])
    assert r.status_code == 404
    assert client.post(BASE + "/submit", headers=world["boss"]).status_code == 404          # 非案件成員＝看不到（同一個 404）
    assert _q("SELECT COUNT(*) AS n FROM case_material_approvals")[0]["n"] == 0             # 全部失敗：沒有留審核單
    _x("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (NO,))
    assert client.post(BASE + "/submit", headers=world["eng"]).status_code == 400            # 已結案
    assert _q("SELECT COUNT(*) AS n FROM case_material_approvals")[0]["n"] == 0
    assert "material_orders.submit" not in _audit_actions() and "material_orders.auto_approve" not in _audit_actions()


def test_one_tier_flow_queue_approve_and_reject(client, world):
    _one_tier(world["boss_name"])
    r = client.post(BASE + "/submit", headers=world["eng"])
    assert r.status_code == 200 and r.json()["status"] == "待審核" and r.json()["tierCount"] == 1, r.text
    code = r.json()["docCode"]
    # 簽核人收到站內通知
    notes = _q("SELECT type, ref_id FROM notifications WHERE username=?", (world["boss_name"],))
    assert [(n["type"], n["ref_id"]) for n in notes] == [("material_order_approval_request", code)]
    # 簽核佇列：自帶 typeLabel／approveUrl／rejectUrl／rejectField
    from core import registry
    import db
    conn = db.get_db()
    try:
        items = registry.providers("approval.queue_items")["case_material"](conn)
    finally:
        conn.close()
    assert len(items) == 1
    it = items[0]
    assert (it["type"], it["typeLabel"], it["quoteNo"], it["docCode"], it["linkedQuoteNo"]) == ("material_order", "材料申請", code, code, NO)
    assert it["approveUrl"] == BASE + "/approve" and it["rejectUrl"] == BASE + "/reject" and it["rejectField"] == "reason" and it["total"] == 3000
    # 簽核人在 L1 佇列與詳情看得到
    q = client.get("/api/approval-queue", headers=world["boss"])
    assert q.status_code == 200, q.text
    assert [i["quoteNo"] for g in q.json()["queue"] for i in g["items"] if i.get("type") == "material_order"] == [code], q.text
    d = client.get("/api/approval-queue/detail", params={"type": "material_order", "id": code}, headers=world["boss"])
    assert d.status_code == 200 and {f["label"]: f["value"] for f in d.json()["fields"]}["品名"] == "交換器", d.text
    # 不是當層簽核人：核准／退回都擋，狀態沒變
    for h in (world["peer"], world["eng"]):
        assert client.post(BASE + "/approve", headers=h).status_code == 403
        assert client.post(BASE + "/reject", json={"reason": "x"}, headers=h).status_code == 403
    assert _approval(client, world["eng"])["status"] == "待審核"
    # 退回要原因
    assert client.post(BASE + "/reject", json={"reason": " "}, headers=world["boss"]).status_code == 400
    r = client.post(BASE + "/reject", json={"reason": "單價太高"}, headers=world["boss"])
    assert r.status_code == 200 and r.json()["status"] == "已退回"
    a = _approval(client, world["eng"])
    assert a["status"] == "已退回" and a["rejectReason"] == "單價太高"
    assert ("material_order_returned", code) in [(n["type"], n["ref_id"]) for n in _q("SELECT type, ref_id FROM notifications WHERE username=?", (world["eng_name"],))]
    # 重送 → 核准
    assert client.post(BASE + "/submit", headers=world["eng"]).json()["status"] == "待審核"
    r = client.post(BASE + "/approve", json={"comment": "OK"}, headers=world["boss"])
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text
    assert _approval(client, world["eng"])["status"] == "已核准"
    acts = _audit_actions()
    for need in ("material_orders.submit", "material_orders.reject", "material_orders.approve"):
        assert need in acts, (need, acts)
    assert client.post(BASE + "/approve", headers=world["boss"]).status_code == 409           # 已核准不可再核
    assert _queue_codes() == []                                                               # 已核准：離開佇列


def test_withdraw_and_cancel_rules(client, world):
    _one_tier(world["boss_name"])
    client.post(BASE + "/submit", headers=world["eng"])
    assert client.post(BASE + "/withdraw", headers=world["peer"]).status_code == 403          # 別的成員不能撤回
    assert _approval(client, world["eng"])["status"] == "待審核"
    assert len(_queue_codes()) == 1                                                            # 待審核：在佇列
    r = client.post(BASE + "/withdraw", headers=world["eng"])
    assert r.status_code == 200 and r.json()["status"] == "草稿"
    assert _queue_codes() == []                                                                # 草稿：不在佇列
    assert client.post(BASE + "/cancel", json={"reason": "x"}, headers=world["adm"]).status_code == 409      # 草稿不可取消
    _flow([])
    assert client.post(BASE + "/submit", headers=world["eng"]).json()["status"] == "已核准"
    assert client.post(BASE + "/cancel", json={"reason": "x"}, headers=world["eng"]).status_code == 403      # 非 admin
    assert client.post(BASE + "/cancel", json={"reason": " "}, headers=world["adm"]).status_code == 400      # 沒理由
    assert _approval(client, world["eng"])["status"] == "已核准"
    r = client.post(BASE + "/cancel", json={"reason": "廠商缺貨"}, headers=world["adm"])
    assert r.status_code == 200 and _approval(client, world["eng"])["status"] == "已取消"
    assert _approval(client, world["eng"])["cancelReason"] == "廠商缺貨"
    assert "material_orders.cancel" in _audit_actions() and "material_orders.withdraw" in _audit_actions()


def test_receipt_confirmation_records_date_and_who_without_approval(client, world):
    _flow([])
    assert client.post(BASE + "/receive", json={"receivedOn": "2031-03-05"}, headers=world["eng"]).status_code == 409   # 未核准
    client.post(BASE + "/submit", headers=world["eng"])
    for bad in ({}, {"receivedOn": ""}, {"receivedOn": "2031-13-40"}):
        assert client.post(BASE + "/receive", json=bad, headers=world["eng"]).status_code == 400, bad
    assert _approval(client, world["eng"])["receivedOn"] == ""
    assert client.post(BASE + "/receive", json={"receivedOn": "2031-03-05"}, headers=world["boss"]).status_code == 404   # 非成員
    r = client.post(BASE + "/receive", json={"receivedOn": "2031-03-05"}, headers=world["eng"])                          # 送審人自己確認也可以
    assert r.status_code == 200 and r.json()["receivedOn"] == "2031-03-05" and r.json()["receivedBy"] == world["eng_name"]
    a = _approval(client, world["peer"])
    assert (a["receivedOn"], a["receivedBy"]) == ("2031-03-05", world["eng_name"]) and a["receivedAt"]
    assert "material_orders.receive" in _audit_actions()
    assert client.delete(BASE + "/receive", headers=world["peer"]).status_code == 200
    assert _approval(client, world["eng"])["receivedOn"] == "" and "material_orders.receive_undo" in _audit_actions()
    assert client.delete(BASE + "/receive", headers=world["peer"]).status_code == 409


def test_mail_types_are_registered_for_the_case_module():
    from helpers import mail_types as MT
    for k in ("material_order_submitted", "material_order_next_tier", "material_order_approved", "material_order_returned"):
        assert MT.get(k) is not None and MT.get(k).owner == "case", k
