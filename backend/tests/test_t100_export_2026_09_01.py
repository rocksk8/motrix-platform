"""2026-09-01：T100（鼎新）傳票批次匯出，現金基礎，涵蓋已收款發票（沿用
reports.py::_collect_tax_invoices 同一份資料源）與已匯款承攬商費用（沿用
cashier.py 出納模組同一份資料源）。科目代號設定 GET/PUT 僅 superadmin 可寫。

2026-09-01（同日）：科目代號改為分維度——銀行帳戶科目代號直接讀「標記已付款/
收款當下」寫進各筆交易自己身上的 bankAccountCode（不是查全公司統一的設定），
料件分類科目代號則是 inventoryExpenseAccounts 字典即時查表（見
accounting_export.py 檔頭 docstring 完整說明）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
import json

import openpyxl
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_paid_contractor_voucher(client, token, quote_no, paid_at, bank_name="第一銀行", bank_code="1101"):
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

    pay = client.post(
        f"/api/contractor-vouchers/{voucher_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": paid_at, "bankAccountName": bank_name, "bankAccountCode": bank_code},
    )
    assert pay.status_code == 200, pay.text
    return voucher_no


def _make_invoiced_quotation(quote_no, invoice_no, received_at, total=31500, pretax=30000,
                              bank_name="第一銀行", bank_code="1101"):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 100, "amount": total, "received": True,
                     "receivedAt": received_at, "invoiceNo": invoice_no, "actualAmount": total,
                     "bankAccountName": bank_name, "bankAccountCode": bank_code},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, pretax, data_json,
             "2026-08-01T00:00:00", "2026-08-01T00:00:00", "已成案", "2026-08-01"),
        )
        conn.commit()
    finally:
        conn.close()


def test_t100_export_config_defaults_blank_and_superadmin_only_write(client, make_user):
    username, password = make_user(username="t100_admin1", role="superadmin")
    token = _login(client, username, password)

    r = client.get("/api/settings/t100-export-config", headers=_auth(token))
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["bankAccounts"] == []
    assert cfg["voucherCategory"] == "轉"
    # 料件分類科目代號應自動補齊所有已知分類鍵（皆留白）
    assert "其他" in cfg["inventoryExpenseAccounts"]
    assert cfg["inventoryExpenseAccounts"]["其他"] == ""

    non_super_username, non_super_password = make_user(role="admin")
    non_super_token = _login(client, non_super_username, non_super_password)
    r2 = client.put(
        "/api/settings/t100-export-config", headers=_auth(non_super_token),
        json={"bankAccounts": [{"name": "第一銀行", "acctCode": "1101"}]},
    )
    assert r2.status_code == 403, r2.text

    r3 = client.put(
        "/api/settings/t100-export-config", headers=_auth(token),
        json={"bankAccounts": [{"name": "第一銀行", "acctCode": "1101"}],
              "salesRevenueAccount": "4101", "outputTaxAccount": "2191",
              "contractorExpenseAccount": "6101",
              "inventoryExpenseAccounts": {"其他": "5109"}},
    )
    assert r3.status_code == 200, r3.text

    r4 = client.get("/api/settings/t100-export-config", headers=_auth(token))
    assert r4.json()["bankAccounts"] == [{"name": "第一銀行", "acctCode": "1101"}]
    assert r4.json()["salesRevenueAccount"] == "4101"
    assert r4.json()["inventoryExpenseAccounts"]["其他"] == "5109"


def test_t100_voucher_export_requires_admin(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.get(
        "/api/reports/t100-export/vouchers?start=2026-08-01&end=2026-08-31",
        headers=_auth(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_t100_voucher_export_rejects_invalid_range(client, make_user):
    username, password = make_user(username="t100_admin3", role="superadmin")
    token = _login(client, username, password)
    r = client.get(
        "/api/reports/t100-export/vouchers?start=2026-08-31&end=2026-08-01",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


def test_t100_preview_and_confirm_require_admin(client, make_user):
    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)

    r1 = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(viewer_token),
    )
    assert r1.status_code == 403, r1.text

    r2 = client.post(
        "/api/reports/t100-export/confirm", headers=_auth(viewer_token),
        json={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert r2.status_code == 403, r2.text


def test_last_received_bank_account_for_customer(client, make_user):
    """2026-09-02：標記已收款時銀行帳戶下拉的預設值——查這個客戶上次用的帳戶
    （依 quotations.customer_name 熱路徑欄位比對）。"""
    username, password = make_user(username="t100_admin6", role="superadmin")
    token = _login(client, username, password)

    r0 = client.get("/api/quotations/last-received-bank-account", headers=_auth(token))
    assert r0.status_code == 200, r0.text
    assert r0.json() == {"name": "", "acctCode": ""}

    r0b = client.get(
        "/api/quotations/last-received-bank-account?customerName=從沒收過款的客戶", headers=_auth(token)
    )
    assert r0b.json() == {"name": "", "acctCode": ""}

    import db
    conn = db.get_db()
    try:
        for quote_no, received_at, bank_name, bank_code in [
            ("MQ-BANKC-001", "2026-08-05", "舊收款帳戶", "1101"),
            ("MQ-BANKC-002", "2026-08-20", "最新收款帳戶", "1102"),
        ]:
            data_json = json.dumps({
                "dealTag": "已成案",
                "caseRecord": {"payment": {"items": [
                    {"type": "訂金款", "pct": 100, "amount": 10000, "received": True,
                     "receivedAt": received_at, "invoiceNo": f"INV-{quote_no}", "actualAmount": 10000,
                     "bankAccountName": bank_name, "bankAccountCode": bank_code},
                ]}},
            })
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (quote_no, "已送出", "測試銀行客戶A", "測試專案", 10000, 9524, data_json,
                 "2026-08-01T00:00:00", "2026-08-01T00:00:00", "已成案", "2026-08-01"),
            )
        conn.commit()
    finally:
        conn.close()

    r1 = client.get(
        "/api/quotations/last-received-bank-account?customerName=測試銀行客戶A", headers=_auth(token)
    )
    assert r1.json() == {"name": "最新收款帳戶", "acctCode": "1102"}

    # 不同客戶名稱查不到
    r2 = client.get(
        "/api/quotations/last-received-bank-account?customerName=測試銀行客戶B", headers=_auth(token)
    )
    assert r2.json() == {"name": "", "acctCode": ""}
