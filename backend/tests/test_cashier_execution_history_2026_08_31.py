"""2026-08-31 v2：出納模組「執行歷史」（已匯款／已收款彙整）＋ Excel 匯出。
`/api/cashier/execution-history` 依 paid_at／receivedAt 落在區間內篩選，
`/api/cashier/export` 沿用 reports.py 既有 Excel 樣式 helper 產出兩個
sheet（已匯款明細／已收款明細）。
"""
import io
import json

import openpyxl


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


def test_execution_history_requires_view_access(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.get("/api/cashier/execution-history", headers=_auth(viewer_token))
    assert r.status_code == 403, r.text


def test_export_requires_view_access(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.get("/api/cashier/export", headers=_auth(viewer_token))
    assert r.status_code == 403, r.text
