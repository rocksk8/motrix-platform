"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_t100_export_2026_09_01.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-09-01：T100（鼎新）傳票批次匯出，現金基礎，涵蓋已收款發票（沿用
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
import pytest

#: 2026-09-26 M05 搬遷：下列題同時需要應收應付（出納／收款資料）
_NEEDS_ARAP = pytest.mark.skipif(not __import__("core.source_tree", fromlist=["x"]).module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包（PLAYBOOK §B-11）")


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


@_NEEDS_ARAP
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


@_NEEDS_ARAP
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


def test_last_paid_bank_account_for_vendor(client, make_user):
    """2026-09-02：標記已匯款時銀行帳戶下拉的預設值——查這個承攬商上次用的帳戶。"""
    username, password = make_user(username="t100_admin5", role="superadmin")
    token = _login(client, username, password)

    r0 = client.get("/api/contractor-vouchers/last-paid-bank-account", headers=_auth(token))
    assert r0.status_code == 200, r0.text
    assert r0.json() == {"name": "", "acctCode": ""}

    v1 = _make_paid_contractor_voucher(client, token, "MQ-BANK-001", "2026-08-05", bank_name="舊帳戶", bank_code="1101")
    vendor_id = client.get(f"/api/contractor-vouchers/{v1}", headers=_auth(token)).json()["vendorId"]

    r1 = client.get(
        f"/api/contractor-vouchers/last-paid-bank-account?vendor_id={vendor_id}", headers=_auth(token)
    )
    assert r1.json() == {"name": "舊帳戶", "acctCode": "1101"}

    # 同一個承攬商再匯款一次（用不同的派發/申請），查詢應回傳「最新」那筆
    r_dispatch = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-BANK-001", "vendor_id": vendor_id,
            "items_json": [{"description": "第二筆", "qty": 1, "unit": "式", "unitPrice": 5000, "amount": 5000}],
            "status": "completed",
        },
    )
    did = r_dispatch.json()["id"]
    cv = client.post("/api/contractor-vouchers", headers=_auth(token), json={"dispatch_id": did})
    voucher_no2 = cv.json()["voucher_no"]
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (voucher_no2,))
        conn.commit()
    finally:
        conn.close()
    client.post(
        f"/api/contractor-vouchers/{voucher_no2}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-25", "bankAccountName": "最新帳戶", "bankAccountCode": "1102"},
    )

    r2 = client.get(
        f"/api/contractor-vouchers/last-paid-bank-account?vendor_id={vendor_id}", headers=_auth(token)
    )
    assert r2.json() == {"name": "最新帳戶", "acctCode": "1102"}
