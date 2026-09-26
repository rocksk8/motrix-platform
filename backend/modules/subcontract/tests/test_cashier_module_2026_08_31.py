"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_cashier_module_2026_08_31.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-08-31：財務/出納權限分工。出納模組新增跨案件「待付款」（已核准未
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


def test_payable_queue_requires_admin_or_cashier(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.get("/api/cashier/payable-queue", headers=_auth(viewer_token))
    assert r.status_code == 403, r.text

    admin_username, admin_password = make_user(username="cash_admin", role="admin")
    admin_token = _login(client, admin_username, admin_password)
    r2 = client.get("/api/cashier/payable-queue", headers=_auth(admin_token))
    assert r2.status_code == 200, r2.text

    cashier_username, cashier_password = make_user(username="cash_only", role="sales", modules=["cashier"])
    cashier_token = _login(client, cashier_username, cashier_password)
    r3 = client.get("/api/cashier/payable-queue", headers=_auth(cashier_token))
    assert r3.status_code == 200, r3.text


def test_payable_queue_only_approved_unpaid_sorted_by_payable_date(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    v_late = _make_approved_voucher(client, token, "MQ-CASH-001", payable_date="2026-09-20")
    v_soon = _make_approved_voucher(client, token, "MQ-CASH-002", payable_date="2026-09-01")
    v_none = _make_approved_voucher(client, token, "MQ-CASH-003")  # 沒填 payable_date

    r = client.get("/api/cashier/payable-queue", headers=_auth(token))
    assert r.status_code == 200, r.text
    vouchers = r.json()
    nos = [v["voucherNo"] for v in vouchers]
    assert v_late in nos and v_soon in nos and v_none in nos
    # 依 payableDate 升冪，空值排最後
    assert nos.index(v_soon) < nos.index(v_late) < nos.index(v_none)

    # 標記已匯款後不應再出現在待付款清單
    pay = client.post(
        f"/api/contractor-vouchers/{v_soon}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-31"},
    )
    assert pay.status_code == 200, pay.text
    r2 = client.get("/api/cashier/payable-queue", headers=_auth(token))
    assert v_soon not in [v["voucherNo"] for v in r2.json()]


def test_finance_module_can_view_but_not_execute(client, make_user):
    """v2：finance 模組使用者沿用 receivables.html 原本的查詢權限（可看
    payable/receivable/execution-history），但標記動作走 admin+/cashier 專用
    的 mark_payment／paid-toggle，finance 不含在內，維持查看/執行分權。"""
    admin_username, admin_password = make_user(username="cash_admin5", role="superadmin")
    admin_token = _login(client, admin_username, admin_password)
    voucher_no = _make_approved_voucher(client, admin_token, "MQ-CASH-050")
    _make_quotation_with_unreceived_item("MQ-CASH-051")

    finance_username, finance_password = make_user(username="finance_user", role="sales", modules=["finance"])
    finance_token = _login(client, finance_username, finance_password)

    assert client.get("/api/cashier/payable-queue", headers=_auth(finance_token)).status_code == 200
    assert client.get("/api/cashier/receivable-queue?status=all", headers=_auth(finance_token)).status_code == 200
    assert client.get("/api/cashier/execution-history", headers=_auth(finance_token)).status_code == 200

    pay = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(finance_token),
        json={"action": "pay", "paid_at": "2026-08-31"},
    )
    assert pay.status_code == 403, pay.text

    mark = client.patch(
        "/api/quotations/MQ-CASH-051/payment/0", headers=_auth(finance_token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 30000, "feeAmount": 0},
    )
    assert mark.status_code == 403, mark.text


def test_cashier_module_user_can_mark_paid_and_received(client, make_user):
    """cashier 模組使用者（非 admin+）能執行 paid-toggle／mark_payment，
    這兩支端點這一輪一併補上 cashier 模組判斷。"""
    admin_username, admin_password = make_user(username="cash_admin3", role="superadmin")
    admin_token = _login(client, admin_username, admin_password)
    voucher_no = _make_approved_voucher(client, admin_token, "MQ-CASH-030")
    _make_quotation_with_unreceived_item("MQ-CASH-031")

    cashier_username, cashier_password = make_user(username="cash_user", role="sales", modules=["cashier"])
    cashier_token = _login(client, cashier_username, cashier_password)

    pay = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(cashier_token),
        json={"action": "pay", "paid_at": "2026-08-31"},
    )
    assert pay.status_code == 200, pay.text

    mark = client.patch(
        "/api/quotations/MQ-CASH-031/payment/0", headers=_auth(cashier_token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 30000, "feeAmount": 0},
    )
    assert mark.status_code == 200, mark.text
