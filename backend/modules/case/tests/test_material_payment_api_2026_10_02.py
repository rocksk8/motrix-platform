# -*- coding: utf-8 -*-
"""叫料匯款申請（31-C 匯款切片）端點與出納整合：建立／額度／簽核／佇列／出納分次付款／差額審核／舊「登記已付」關閉／帳戶不外洩。

走真實 HTTP。叫料單 L1＝2 台 × 5,000＝小計 10,000（已核准）。手算：
  申請 1＝6,000，申請 2＝剩餘 4,000，申請 3＝1 元 ⇒ 409。
  出納對申請 1 先付 2,500（待付款剩 3,500，叫料單 partial 2,500），再付 3,500（結清，從待付款消失；叫料單 partial 6,000）。
  申請 2 付 4,500（多付 500 ⇒ 差額待審核）。
收款帳號 28881234567890 只許出現在：資料庫快照、出納專用端點；任何列表、佇列詳情、建立回應都只給末四碼 ****7890。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料匯款申請")

NO = "MQ-MPA-001"
ITEM = "L1"
ACCT = "28881234567890"
BODY = {"bankCode": "812", "bankName": "台新", "bankAccountName": "甲供應商有限公司", "bankAccountNumber": ACCT}


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


def _flow(tiers):
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


def _order_json():
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]["materialOrders"][0]


def _audit_actions():
    return [r["action"] for r in _q("SELECT action FROM audit_log WHERE target_id=? ORDER BY id", (NO,))]


@pytest.fixture
def world(client, make_user):
    adm, ap = make_user(username="mpa_adm", role="admin")
    adm2, ap2 = make_user(username="mpa_adm2", role="admin")
    sa, sp = make_user(username="mpa_sa", role="superadmin")
    boss, bp = make_user(username="mpa_boss", role="sales")
    cash, cp = make_user(username="mpa_cash", role="sales", modules=["cashier"])
    eng, ep = make_user(username="mpa_eng", role="sales")
    out, op = make_user(username="mpa_out", role="sales")
    order = {"itemId": ITEM, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 5000, "totalPrice": 10000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "匯款客", "匯款專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}),
        "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", json.dumps([_uid(eng)])))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (NO, ITEM, "MO-20310101-0001", "已核准", "2031-01-01", "2031-01-01"))
    _x("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2031-01-01", "2031-01-01"))
    sid = _q("SELECT id FROM suppliers WHERE name='甲供應商'")[0]["id"]
    _flow([])
    return {"adm": _login(client, adm, ap), "adm2": _login(client, adm2, ap2), "sa": _login(client, sa, sp), "boss": _login(client, boss, bp),
            "cash": _login(client, cash, cp), "eng": _login(client, eng, ep), "out": _login(client, out, op), "boss_name": boss, "sid": sid}


def _create(client, w, amount=None, who="adm", **kw):
    body = dict(BODY, supplierId=w["sid"], payeeNoticeAcked=True, **kw)
    if amount is not None:
        body["amount"] = amount
    return client.post("/api/quotations/%s/material-orders/%s/payments" % (NO, ITEM), json=body, headers=w[who])


def _approved(client, w, amount=None):
    _flow([])
    r = _create(client, w, amount)
    assert r.status_code == 200, r.text
    pid = r.json()["payment"]["id"]
    s = client.post("/api/material-payments/%d/submit" % pid, headers=w["adm"])
    assert s.status_code == 200 and s.json()["status"] == "已核准", s.text
    return pid


def _pending_items(client, w):
    r = client.get("/api/cashier/pending-payables", headers=w["cash"])
    assert r.status_code == 200, r.text
    return [i for i in r.json()["items"] if i["source"] == "case_material"]


def test_create_permissions_quota_and_the_account_never_leaks(client, world):
    w = world
    assert _create(client, w, 6000, who="eng").status_code == 403                  # 一般案件成員（非 admin／project_manage）不能開
    assert _create(client, w, 6000, who="out").status_code == 404                  # 非案件成員＝看不到
    assert _q("SELECT COUNT(*) AS n FROM case_material_payments")[0]["n"] == 0
    r1 = _create(client, w, 6000)
    assert r1.status_code == 200, r1.text
    p1 = r1.json()["payment"]
    assert p1["status"] == "草稿" and p1["seq"] == 1 and p1["docCode"].startswith("MP-") and p1["amount"] == 6000.0
    assert p1["payee"]["bankAccountNumber"] == "****7890" and ACCT not in r1.text   # 回應只給末四碼
    snap = json.loads(_q("SELECT snapshot_json FROM case_material_payments")[0]["snapshot_json"])
    assert snap["bankAccountNumber"] == ACCT and snap["supplierName"] == "甲供應商"   # 完整帳號只在資料庫快照
    r2 = _create(client, w)
    assert r2.json()["payment"]["amount"] == 4000.0 and r2.json()["payment"]["seq"] == 2
    assert _create(client, w, 1).status_code == 409                                  # 額度用完
    assert _create(client, w, 1, who="sa").status_code == 409                        # superadmin 沒理由也不行
    ok = _create(client, w, 1, who="sa", overCapReason="客戶加購")
    assert ok.status_code == 200 and ok.json()["payment"]["overCapReason"] == "客戶加購"
    g = client.get("/api/quotations/%s/material-payments" % NO, headers=w["adm"])
    assert g.status_code == 200 and ACCT not in g.text
    q = g.json()["orders"][ITEM]
    assert q["quota"] == {"total": 10000.0, "legacyPaid": 0.0, "committed": 10001.0, "remaining": -1.0}
    assert [p["seq"] for p in q["payments"]] == [1, 2, 3]
    assert client.get("/api/quotations/%s/material-payments" % NO, headers=w["out"]).status_code == 404
    assert _audit_actions().count("material_payment.create") == 3


def test_supplier_picker_is_light_and_gated(client, world):
    w = world
    r = client.get("/api/material-suppliers", headers=w["adm"])
    assert r.status_code == 200 and r.json()["suppliers"] == [{"id": w["sid"], "code": "S-001", "name": "甲供應商"}]
    assert client.get("/api/material-suppliers", headers=w["eng"]).status_code == 403


def test_approval_flow_queue_detail_and_cashier_handoff(client, world):
    w = world
    _flow([{"order": 0, "approvers": [{"username": w["boss_name"], "displayName": "主管"}]}])
    p = _create(client, w, 6000).json()["payment"]
    assert _pending_items(client, w) == []                                           # 草稿不進出納
    r = client.post("/api/material-payments/%d/submit" % p["id"], headers=w["adm"])
    assert r.status_code == 200 and r.json()["status"] == "待審核", r.text
    assert _pending_items(client, w) == []                                           # 審核中也不進出納
    from core import registry
    import db
    conn = db.get_db()
    try:
        items = registry.providers("approval.queue_items")["case_material_payment"](conn)
        det = registry.providers("approval.detail")["material_payment"](conn, p["docCode"])
    finally:
        conn.close()
    assert [(i["type"], i["docCode"], i["total"], i["approveUrl"]) for i in items] == [("material_payment", p["docCode"], 6000.0, "/api/material-payments/%d/approve" % p["id"])]
    assert ACCT not in json.dumps(det, ensure_ascii=False) and "****7890" in json.dumps(det, ensure_ascii=False)   # 詳情不放完整帳號
    assert client.post("/api/material-payments/%d/approve" % p["id"], headers=w["eng"]).status_code == 403          # 不是當層簽核人
    r = client.post("/api/material-payments/%d/reject" % p["id"], json={"reason": "金額先抓大"}, headers=w["boss"])
    assert r.status_code == 200 and r.json()["status"] == "已退回"
    assert client.post("/api/material-payments/%d/submit" % p["id"], headers=w["adm"]).json()["status"] == "待審核"   # 退回後修改可重送
    assert client.post("/api/material-payments/%d/approve" % p["id"], headers=w["boss"]).json()["status"] == "已核准"
    got = _pending_items(client, w)
    assert [(i["key"], i["amount"], i["payee"], i["docCode"], i["kind"]) for i in got] == [(str(p["id"]), 6000.0, "甲供應商", p["docCode"], "material_payment")]
    assert got[0]["payeeBank"].endswith("****7890") and ACCT not in json.dumps(got)  # 出納列表只給遮罩
    acts = _audit_actions()
    for a in ("material_payment.submit", "material_payment.reject", "material_payment.approve"):
        assert a in acts, a


def test_cashier_pays_in_two_steps_and_the_order_paid_fields_follow(client, world):
    w = world
    pid = _approved(client, w, 6000)
    pb = client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w["cash"])
    assert pb.status_code == 200 and pb.json()["account"] == ACCT and pb.json()["accountName"] == "" and pb.json()["bank"].startswith("812")   # 出納專用端點才有完整帳號
    assert "cashier.payee_bank_view" in [r["action"] for r in _q("SELECT action FROM audit_log")]
    assert client.get("/api/cashier/pending-payables/case_material/%d/payee-bank" % pid, headers=w["eng"]).status_code == 403
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-05", "actualAmount": 2500}, headers=w["cash"])
    assert r.status_code == 200 and (r.json()["actual"], r.json()["remaining"], r.json()["settled"]) == (2500.0, 3500.0, False), r.text
    assert [(i["key"], i["amount"], i["paid"]) for i in _pending_items(client, w)] == [(str(pid), 3500.0, 2500.0)]       # 未結清留在待付款，顯示剩餘
    o = _order_json()
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 2500.0, "2031-03-05")
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-09", "hasFee": True, "fee": 15}, headers=w["cash"])
    assert r.status_code == 200 and (r.json()["actual"], r.json()["fee"], r.json()["settled"]) == (3500.0, 15.0, True), r.text
    assert _pending_items(client, w) == []                                           # 結清後消失
    o = _order_json()
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 6000.0, "2031-03-09")
    assert client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-10"}, headers=w["cash"]).status_code == 409   # 已結清
    assert client.post("/api/cashier/pending-payables/case_material/999999/pay", json={"paidDate": "2031-03-10"}, headers=w["cash"]).status_code == 404
    assert client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-10", "actualAmount": 0}, headers=w["cash"]).status_code in (400, 409)
    assert _q("SELECT COUNT(*) AS n FROM case_material_payment_lines")[0]["n"] == 2
    fees = registry_fee_entries("2031-03-01", "2031-03-31")
    assert [(e["date"], e["amount"], e["category"], e["pending"]) for e in fees] == [("2031-03-09", 15.0, "匯款手續費", False)]


def registry_fee_entries(start, end):
    from core import registry
    import db
    conn = db.get_db()
    try:
        return registry.providers("expense.entries")["remit_fee_case_material"](conn, start, end)
    finally:
        conn.close()


def test_overpayment_goes_to_remit_review_and_only_another_admin_decides(client, world):
    w = world
    pid = _approved(client, w, 4000)
    r = client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-20", "actualAmount": 4500}, headers=w["adm"])
    assert r.status_code == 200 and (r.json()["remitReview"], r.json()["diff"]) == ("pending", 500.0), r.text
    rv = client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"]
    mine = [i for i in rv if i["source"] == "case_material"]
    assert [(i["payable"], i["actual"], i["diff"]) for i in mine] == [(4000.0, 4500.0, 500.0)]
    lid = mine[0]["key"]
    assert client.post("/api/cashier/remit-reviews/case_material/%s/decision" % lid, json={"decision": "approve"}, headers=w["cash"]).status_code == 403   # 非 admin
    assert client.post("/api/cashier/remit-reviews/case_material/%s/decision" % lid, json={"decision": "approve"}, headers=w["adm"]).status_code == 403   # 自己登錄的不能自審
    r = client.post("/api/cashier/remit-reviews/case_material/%s/decision" % lid, json={"decision": "reject", "note": "多付請追回"}, headers=w["adm2"])
    assert r.status_code == 200
    assert _q("SELECT COUNT(*) AS n FROM case_material_payment_lines")[0]["n"] == 0
    assert [i["amount"] for i in _pending_items(client, w)] == [4000.0]              # 退回＝回待付款（剩餘回到 4,000）
    assert _order_json()["paidStatus"] == "pending"
    client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json={"paidDate": "2031-03-21", "actualAmount": 4200}, headers=w["adm"])
    lid = [i for i in client.get("/api/cashier/remit-reviews", headers=w["adm2"]).json()["items"] if i["source"] == "case_material"][0]["key"]
    assert client.post("/api/cashier/remit-reviews/case_material/%s/decision" % lid, json={"decision": "approve"}, headers=w["adm2"]).status_code == 200
    assert _q("SELECT remit_review FROM case_material_payment_lines")[0]["remit_review"] == "approved"


def test_the_old_register_as_paid_path_is_closed_for_legacy_and_new_orders(client, world):
    w = world
    rows = [dict(_order_json(), paidStatus="paid", paidAmount=10000, paidDate="2031-03-06")]
    r = client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=w["adm"])
    assert r.status_code == 200, r.text
    assert {(x["itemId"], x["field"], x["code"]) for x in r.json()["rejected"]} == {
        (ITEM, "paidStatus", "paid_via_remittance"), (ITEM, "paidAmount", "paid_via_remittance"), (ITEM, "paidDate", "paid_via_remittance")}
    assert _order_json()["paidStatus"] == "pending"
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]
    cr["materialOrders"][0].update({"paidStatus": "paid", "paidAmount": 10000, "paidDate": "2031-03-06"})
    r = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=w["adm"])
    assert r.status_code == 200 and any(x["code"] == "paid_via_remittance" for x in r.json()["rejected"])
    assert _order_json()["paidStatus"] == "pending"


def test_orders_with_applications_are_frozen_and_void_releases(client, world):
    w = world
    p = _create(client, w, 6000).json()["payment"]
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (NO,))[0]["data_json"])["caseRecord"]
    cr["materialOrders"][0].update({"unitPrice": 6000, "totalPrice": 12000})
    r = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=w["adm"])
    assert [x["code"] for x in r.json()["rejected"]] == ["has_payments"] and _order_json()["totalPrice"] == 10000   # 有申請時不可改金額
    assert client.post("/api/quotations/%s/material-orders/%s/cancel" % (NO, ITEM), json={"reason": "x"}, headers=w["adm"]).status_code == 409
    cr["materialOrders"] = []
    r = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=w["adm"])
    assert [x["code"] for x in r.json()["rejected"]] == ["delete_blocked"]                                           # 已核准的也不可刪
    _x("DELETE FROM case_material_approvals WHERE quote_no=?", (NO,))                                                 # 舊單（沒有審核單）：刪除本來可以，但有匯款申請紀錄就不行
    r = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=w["adm"])
    assert [x["code"] for x in r.json()["rejected"]] == ["delete_blocked"] and _order_json()["itemId"] == ITEM
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (NO, ITEM, "MO-20310101-0001", "已核准", "2031-01-01", "2031-01-01"))                                             # 還原審核單，後面的題照常
    assert client.post("/api/material-payments/%d/void" % p["id"], json={}, headers=w["adm"]).status_code == 400    # 理由必填
    assert client.post("/api/material-payments/%d/void" % p["id"], json={"reason": "改下次"}, headers=w["adm"]).json()["status"] == "作廢"
    g = client.get("/api/quotations/%s/material-payments" % NO, headers=w["adm"]).json()["orders"][ITEM]
    assert g["quota"]["remaining"] == 10000.0 and g["payments"][0]["voidReason"] == "改下次"                          # 額度釋出
    assert "material_payment.void" in _audit_actions()
    assert client.post("/api/material-payments/999999/submit", headers=w["adm"]).status_code == 404


def test_update_payment_edits_draft_only(client, world):
    w = world
    p = _create(client, w, 6000).json()["payment"]
    r = client.patch("/api/material-payments/%d" % p["id"], json={"amount": 5000, "bankAccountNumber": "99887766"}, headers=w["adm"])
    assert r.status_code == 200 and r.json()["payment"]["amount"] == 5000.0 and r.json()["payment"]["payee"]["bankAccountNumber"] == "****7766"
    assert json.loads(_q("SELECT snapshot_json FROM case_material_payments")[0]["snapshot_json"])["bankAccountNumber"] == "99887766"
    assert client.patch("/api/material-payments/%d" % p["id"], json={"amount": 99999}, headers=w["adm"]).status_code == 409     # 超額
    _flow([])
    assert client.post("/api/material-payments/%d/submit" % p["id"], headers=w["adm"]).json()["status"] == "已核准"
    assert client.patch("/api/material-payments/%d" % p["id"], json={"amount": 100}, headers=w["adm"]).status_code == 409        # 已核准不可改
    assert "material_payment.update" in _audit_actions()


def test_payee_privacy_notice_is_required_recorded_and_audited(client, world):
    """收款人（供應商可能是自然人）的個資告知（使用者裁示 A）：沒有勾「已告知收款人」不能建立申請（400、不留任何申請）；
    建立時伺服器記錄告知（時間與人員）並寫稽核；讀取端點只給有權的人；補記端點冪等（已記錄的不覆蓋）。"""
    from helpers import privacy_notice as pn
    w = world
    url = "/api/quotations/%s/material-orders/%s/payments" % (NO, ITEM)
    for extra in ({}, {"payeeNoticeAcked": False}, {"payeeNoticeAcked": "yes"}):
        r = client.post(url, json=dict(BODY, supplierId=w["sid"], amount=1000, **extra), headers=w["adm"])
        assert r.status_code == 400 and "告知" in r.text, (extra, r.text)
    assert _q("SELECT COUNT(*) AS n FROM case_material_payments")[0]["n"] == 0
    r = _create(client, w, 1000)
    assert r.status_code == 200, r.text
    pay = r.json()["payment"]
    ack = pn.get_ack("material_payment", pay["docCode"])
    assert ack and ack.get("at") and ack.get("by"), ack
    assert r.json()["payment"]["payeeNotice"]["at"] == ack["at"]
    assert _audit_actions().count("material_payment.privacy_notice_ack") == 1
    g = client.get("/api/material-payments/%d/privacy-notice" % pay["id"], headers=w["adm"])
    assert g.status_code == 200 and g.json()["ack"]["at"] == ack["at"] and ACCT not in g.text
    assert client.get("/api/material-payments/%d/privacy-notice" % pay["id"], headers=w["out"]).status_code == 404       # 非案件成員＝看不到
    assert client.get("/api/material-payments/%d/privacy-notice" % pay["id"]).status_code in (401, 403)                   # 未登入
    again = client.post("/api/material-payments/%d/privacy-notice/ack" % pay["id"], headers=w["adm"])
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["ack"]["at"] == ack["at"]        # 已記錄的不覆蓋
    assert _audit_actions().count("material_payment.privacy_notice_ack") == 1
    assert client.post("/api/material-payments/%d/privacy-notice/ack" % pay["id"], headers=w["eng"]).status_code == 403     # 沒有編輯叫料權限的人不能補記
