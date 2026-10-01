# -*- coding: utf-8 -*-
"""選單紅點／數字徽章／登入橫幅的唯一來源 `/api/approval-queue/count` 必須涵蓋**每一類**單據的待簽（使用者 2026-10-01：輪到我簽就要有紅點）。
這裡一次放三類——報價單、自訂模組單據、承攬商匯款申請——都輪到同一個人：count 必須是 3，且等於佇列列表裡「輪到我」的項目數
（canApprove 的規則：目前層第一個未簽的人是我）。簽掉其中一類 ⇒ 少 1。反向控制：count 若漏了某一類，這題的數字會對不上。"""
import json

import pytest

from tests.test_e2e_p8_gaps_2026_09_26 import _submitted_record

ME = "ac_me"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed_quote_waiting():
    import db
    appr = {"requestedBy": "ac_req", "requestedByDisplay": "申請人", "requestedAt": "2026-10-01T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": ME, "displayName": ME, "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at)"
                     " VALUES ('MQ-AC-1','待審核','客','案',1000,?,'2026-10-01','2026-10-01')", (json.dumps({"approval": appr}, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()


def _seed_voucher_waiting():
    import db
    snap = {"vendorName": "承攬商", "grandTotal": 500}
    appr = {"requestedBy": "ac_req", "requestedByDisplay": "申請人", "requestedAt": "2026-10-01T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": ME, "displayName": ME, "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES ('MQ-AC-2','已送出','客','案','{}','2026-09-01','2026-09-01')")
        conn.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, tax_rate, status, notes,"
                     " created_by, created_at, updated_at, accepted_at, accepted_by, files_json, invoice_files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (99301, "MQ-AC-2", None, "2026-09-01", "測試", "[]", "[]", 500, 0, "已完成", "", "x", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "", "[]", "[]"))
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, dispatch_id, status, snapshot_json, data_json, created_by, created_at, updated_at)"
                     " VALUES ('CV-AC-1','MQ-AC-2',99301,'待審核',?,?,'x','2026-10-01T00:00:00','2026-10-01T00:00:00')",
                     (json.dumps(snap, ensure_ascii=False), json.dumps({"approval": appr}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def test_count_covers_quotation_custom_record_and_contractor_voucher(client, make_user):
    admin = make_user(username="ac_admin", role="superadmin")
    me = make_user(username=ME, role="admin")
    req = make_user(username="ac_req", role="user", modules=["custom.ac_custom"])
    _seed_quote_waiting()
    _seed_voucher_waiting()
    _submitted_record(client, admin, req, "ac_custom", ME)
    h = _login(client, me[0], me[1])
    count = client.get("/api/approval-queue/count", headers=h).json()
    assert count["count"] == 3, count
    types = sorted(i["type"] for i in count["items"])
    assert len(types) == 3 and len(set(types)) == 3, types                      # 三種不同的單據類型各一
    queue = client.get("/api/approval-queue", headers=h).json()["queue"]
    items = [it for g in queue for it in g["items"]]
    mine = [it for it in items if it.get("tiers") and it["tiers"][it.get("currentTier") or 0]["approvers"][0].get("username") == ME] if all(
        it.get("tiers") for it in items) else None
    assert mine is None or len(mine) == 3, mine                                 # 數字＝佇列列表裡輪到我的項目數（有 tiers 的類型）
    # 簽掉報價單 ⇒ 少 1
    assert client.post("/api/quotations/MQ-AC-1/approve", headers=h, json={}).status_code == 200
    assert client.get("/api/approval-queue/count", headers=h).json()["count"] == 2
