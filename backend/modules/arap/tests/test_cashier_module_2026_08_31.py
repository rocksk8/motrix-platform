"""2026-08-31：財務/出納權限分工。出納模組新增跨案件「待付款」（已核准未
匯款的承攬商匯款申請）與「待收款」（未收款的案件款項期別）彙整端點，取代
原本要一個案件一個案件點進去才看得到待辦事項的做法。

權限：admin+ 或具備 cashier 模組（helpers.user_has_module()）——跟同一輪
一併補上 cashier 判斷的 paid-toggle／mark_payment／bank-reconcile 一致。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_approved_voucher(client, token, quote_no, payable_date=None):
    r = client.post(
        "/api/vendor-contractors", headers=_auth(token),
        json={"name": f"廠商{quote_no}", "data": {}},
    )
    assert r.status_code == 201, r.text
    vendor_id = r.json()["id"]

    body = {
        "quote_no": quote_no, "vendor_id": vendor_id,
        "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}],
        "status": "completed",
    }
    if payable_date:
        body["payable_date"] = payable_date
    r = client.post("/api/contractor-dispatches", headers=_auth(token), json=body)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    cv = client.post("/api/contractor-vouchers", headers=_auth(token), json={"dispatch_id": did})
    assert cv.status_code == 201, cv.text
    voucher_no = cv.json()["voucher_no"]

    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (voucher_no,))
        conn.commit()
    finally:
        conn.close()
    return voucher_no


def _make_quotation_with_unreceived_item(quote_no, expected_receipt_date=""):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 30, "amount": 30000, "received": False,
                     "expectedReceiptDate": expected_receipt_date},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 30000, 28571, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()


def test_receivable_queue_requires_admin_or_cashier_and_excludes_received(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    assert client.get("/api/cashier/receivable-queue", headers=_auth(viewer_token)).status_code == 403

    admin_username, admin_password = make_user(username="cash_admin2", role="admin")
    admin_token = _login(client, admin_username, admin_password)

    _make_quotation_with_unreceived_item("MQ-CASH-010", expected_receipt_date="2026-09-15")
    r = client.get("/api/cashier/receivable-queue", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    items = [i for i in r.json() if i["quoteNo"] == "MQ-CASH-010"]
    assert len(items) == 1
    assert items[0]["expectedReceiptDate"] == "2026-09-15"
    assert items[0]["idx"] == 0

    # 標記已收款後不應再出現
    mark = client.patch(
        "/api/quotations/MQ-CASH-010/payment/0", headers=_auth(admin_token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 30000, "feeAmount": 0},
    )
    assert mark.status_code == 200, mark.text
    r2 = client.get("/api/cashier/receivable-queue", headers=_auth(admin_token))
    assert not any(i["quoteNo"] == "MQ-CASH-010" for i in r2.json())


def test_receivable_queue_status_all_includes_received_and_unreceived(client, make_user):
    """v2：status=all 併入 receivables.html 的完整歷史查詢，含已收+未收，
    且每筆品項要帶出發票登錄/取消收款/手續費統計用得到的欄位。"""
    username, password = make_user(username="cash_admin4", role="admin")
    token = _login(client, username, password)

    _make_quotation_with_unreceived_item("MQ-CASH-040", expected_receipt_date="2026-09-10")
    mark = client.patch(
        "/api/quotations/MQ-CASH-040/payment/0", headers=_auth(token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 29500, "feeAmount": 500,
              "invoiceNo": "AB12345678"},
    )
    assert mark.status_code == 200, mark.text

    # 預設 unreceived 不應再出現這筆（已收款）
    r_unreceived = client.get("/api/cashier/receivable-queue", headers=_auth(token))
    assert not any(i["quoteNo"] == "MQ-CASH-040" for i in r_unreceived.json())

    r_all = client.get("/api/cashier/receivable-queue?status=all", headers=_auth(token))
    assert r_all.status_code == 200, r_all.text
    items = [i for i in r_all.json() if i["quoteNo"] == "MQ-CASH-040"]
    assert len(items) == 1
    it = items[0]
    assert it["received"] is True
    assert it["actualAmount"] == 29500
    assert it["feeAmount"] == 500
    assert it["invoiceNo"] == "AB12345678"

    r_received = client.get("/api/cashier/receivable-queue?status=received", headers=_auth(token))
    assert any(i["quoteNo"] == "MQ-CASH-040" for i in r_received.json())

    bad = client.get("/api/cashier/receivable-queue?status=bogus", headers=_auth(token))
    assert bad.status_code == 400
