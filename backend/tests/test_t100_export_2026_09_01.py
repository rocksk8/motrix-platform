"""2026-09-01：T100（鼎新）傳票批次匯出，現金基礎，涵蓋已收款發票（沿用
reports.py::_collect_tax_invoices 同一份資料源）與已匯款承攬商費用（沿用
cashier.py 出納模組同一份資料源）。科目代號設定 GET/PUT 僅 superadmin 可寫。

2026-09-01（同日）：科目代號改為分維度——銀行帳戶科目代號直接讀「標記已付款/
收款當下」寫進各筆交易自己身上的 bankAccountCode（不是查全公司統一的設定），
料件分類科目代號則是 inventoryExpenseAccounts 字典即時查表（見
accounting_export.py 檔頭 docstring 完整說明）。
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


def test_t100_voucher_export_balances_and_excludes_out_of_range(client, make_user):
    username, password = make_user(username="t100_admin2", role="superadmin")
    token = _login(client, username, password)

    client.put(
        "/api/settings/t100-export-config", headers=_auth(token),
        json={"salesRevenueAccount": "4101", "outputTaxAccount": "2191",
              "contractorExpenseAccount": "6101"},
    )

    v_in_range = _make_paid_contractor_voucher(client, token, "MQ-T100-001", "2026-08-15")
    v_out_of_range = _make_paid_contractor_voucher(client, token, "MQ-T100-002", "2026-01-05")

    _make_invoiced_quotation("MQ-T100-010", "INV-001", "2026-08-20", total=31500, pretax=30000)
    _make_invoiced_quotation("MQ-T100-011", "INV-002", "2026-02-01", total=31500, pretax=30000)

    r = client.get(
        "/api/reports/t100-export/vouchers?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["T100傳票匯出"]

    rows = list(ws.iter_rows(min_row=4, values_only=True))
    body_rows = rows[:-1]
    total_row = rows[-1]

    source_nos = [row[9] for row in body_rows]
    assert "MQ-T100-010" in source_nos
    assert v_in_range in source_nos
    assert "MQ-T100-011" not in source_nos
    assert v_out_of_range not in source_nos

    debit_sum = sum(row[6] or 0 for row in body_rows)
    credit_sum = sum(row[7] or 0 for row in body_rows)
    assert debit_sum == credit_sum

    assert total_row[6] == debit_sum
    assert total_row[7] == credit_sum

    ar_rows = [row for row in body_rows if row[9] == "MQ-T100-010"]
    assert len(ar_rows) == 3
    assert sum(row[6] or 0 for row in ar_rows) == sum(row[7] or 0 for row in ar_rows) == 31500
    # 銀行帳戶科目代號來自這筆交易自己標記時填的 bankAccountCode（"1101"），
    # 不是全公司統一設定（本測試這次刻意沒有設定任何 bankAccounts）
    acct_codes = {row[4] for row in ar_rows}
    assert acct_codes == {"1101", "4101", "2191"}

    ap_rows = [row for row in body_rows if row[9] == v_in_range]
    assert len(ap_rows) == 2
    assert sum(row[6] or 0 for row in ap_rows) == sum(row[7] or 0 for row in ap_rows) == 10500
    ap_acct_codes = {row[4] for row in ap_rows}
    assert ap_acct_codes == {"1101", "6101"}


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


def test_t100_preview_confirm_excludes_from_future_export(client, make_user):
    username, password = make_user(username="t100_admin4", role="superadmin")
    token = _login(client, username, password)

    client.put(
        "/api/settings/t100-export-config", headers=_auth(token),
        json={"salesRevenueAccount": "4101", "outputTaxAccount": "2191",
              "contractorExpenseAccount": "6101"},
    )

    v = _make_paid_contractor_voucher(client, token, "MQ-T100-030", "2026-08-05")
    _make_invoiced_quotation("MQ-T100-031", "INV-030", "2026-08-06", total=31500, pretax=30000)

    # 預覽：兩筆事件都還沒確認，應該都出現
    preview1 = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert preview1.status_code == 200, preview1.text
    keys1 = {(e["sourceType"], e["sourceKey"]) for e in preview1.json()["events"]}
    assert ("contractor_voucher", v) in keys1
    assert ("quotation_payment", "MQ-T100-031::INV-030") in keys1
    assert preview1.json()["count"] == 2

    # 確認整批已匯入
    confirm = client.post(
        "/api/reports/t100-export/confirm", headers=_auth(token),
        json={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["confirmedCount"] == 2

    # 再次確認同一區間：冪等，這次候選清單應為 0（已排除）
    confirm2 = client.post(
        "/api/reports/t100-export/confirm", headers=_auth(token),
        json={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert confirm2.status_code == 200, confirm2.text
    assert confirm2.json()["confirmedCount"] == 0

    # 預覽：確認後這兩筆事件應該從候選清單消失
    preview2 = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert preview2.json()["count"] == 0
    # （Excel 匯出走同一份 _collect_t100_events()，排除邏輯已在其他測試涵蓋，
    # 這裡不重覆呼叫 excel 端點，避免撞上 process-global 匯出冷卻限流，見既有踩坑記錄）

    # 已確認清單應可查到這兩筆
    confirmed_list = client.get(
        "/api/reports/t100-export/confirmed?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert confirmed_list.status_code == 200, confirmed_list.text
    confirmed_keys = {(c["sourceType"], c["sourceKey"]) for c in confirmed_list.json()}
    assert ("contractor_voucher", v) in confirmed_keys
    assert ("quotation_payment", "MQ-T100-031::INV-030") in confirmed_keys

    # 撤銷承攬商費用那一筆的確認
    unconfirm = client.post(
        "/api/reports/t100-export/unconfirm", headers=_auth(token),
        json={"sourceType": "contractor_voucher", "sourceKey": v},
    )
    assert unconfirm.status_code == 200, unconfirm.text

    # 撤銷後應重新出現在預覽（但另一筆仍被排除）
    preview3 = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    keys3 = {(e["sourceType"], e["sourceKey"]) for e in preview3.json()["events"]}
    assert keys3 == {("contractor_voucher", v)}

    # 撤銷不存在的標記應回 404
    unconfirm2 = client.post(
        "/api/reports/t100-export/unconfirm", headers=_auth(token),
        json={"sourceType": "contractor_voucher", "sourceKey": "PV-NOTEXIST"},
    )
    assert unconfirm2.status_code == 404, unconfirm2.text


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
