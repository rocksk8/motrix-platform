"""2026-09-01：料件/設備進貨批次新增供應商/發票號/付款狀態追蹤（DB v70
`stock_batches`），供 T100 傳票批次匯出（accounting_export.py）納入現金基礎
的付款事件來源。過去系統完全沒有追蹤進貨是否已付款（見
db.py::_m070_stock_batches() docstring），這是本輪要補的前置功能。
"""
import io

import openpyxl


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_part(client, token, part_no):
    r = client.post(
        "/api/parts", headers=_auth(token),
        json={"part_no": part_no, "name": f"測試料件{part_no}", "category": "其他", "cost": 5000},
    )
    assert r.status_code == 201, r.text


def _make_supplier(client, token, name):
    r = client.post("/api/suppliers", headers=_auth(token), json={"name": name})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _make_batch(client, token, part_no, supplier_id=None, cost=5000, qty=2, invoice_no=""):
    body = {
        "part_no": part_no,
        "serials": [{"serial_no": f"{part_no}-SN{i}"} for i in range(qty)],
        "cost": cost,
    }
    if supplier_id:
        body["supplier_id"] = supplier_id
    if invoice_no:
        body["invoice_no"] = invoice_no
    r = client.post("/api/inventory/batches", headers=_auth(token), json=body)
    assert r.status_code == 201, r.text
    return r.json()["batchNo"]


def test_create_batch_writes_stock_batches_header(client, make_user):
    username, password = make_user(username="stk_admin1", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P1")
    supplier_id = _make_supplier(client, token, "測試供應商A")

    batch_no = _make_batch(client, token, "STK-P1", supplier_id=supplier_id, cost=6000, qty=3, invoice_no="INV-SUP-001")

    r = client.get("/api/inventory/batches", headers=_auth(token))
    assert r.status_code == 200, r.text
    row = next(b for b in r.json()["items"] if b["batch_no"] == batch_no)
    assert row["qty"] == 3
    assert row["total_cost"] == 18000
    assert row["supplier_id"] == supplier_id
    assert row["supplier_name"] == "測試供應商A"
    assert row["invoice_no"] == "INV-SUP-001"
    assert row["is_paid"] == 0

    detail = client.get(f"/api/inventory/batches/{batch_no}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["header"]["supplier_name"] == "測試供應商A"


def test_paid_toggle_pay_and_unpay_with_guards(client, make_user):
    username, password = make_user(username="stk_admin2", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P2")
    batch_no = _make_batch(client, token, "STK-P2", cost=5000, qty=1)

    pay = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-20"},
    )
    assert pay.status_code == 200, pay.text

    dup_pay = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-20"},
    )
    assert dup_pay.status_code == 409, dup_pay.text

    r = client.get("/api/inventory/batches", headers=_auth(token))
    row = next(b for b in r.json()["items"] if b["batch_no"] == batch_no)
    assert row["is_paid"] == 1
    assert row["paid_at"] == "2026-08-20"

    unpay = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(token),
        json={"action": "unpay"},
    )
    assert unpay.status_code == 200, unpay.text

    dup_unpay = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(token),
        json={"action": "unpay"},
    )
    assert dup_unpay.status_code == 409, dup_unpay.text


def test_paid_toggle_requires_admin(client, make_user):
    admin_username, admin_password = make_user(username="stk_admin3", role="superadmin")
    admin_token = _login(client, admin_username, admin_password)
    _make_part(client, admin_token, "STK-P3")
    batch_no = _make_batch(client, admin_token, "STK-P3", cost=1000, qty=1)

    viewer_username, viewer_password = make_user(role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(viewer_token),
        json={"action": "pay"},
    )
    assert r.status_code == 403, r.text


def test_update_batch_header_edits_supplier_and_invoice(client, make_user):
    username, password = make_user(username="stk_admin4", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P4")
    batch_no = _make_batch(client, token, "STK-P4", cost=2000, qty=1)
    supplier_id = _make_supplier(client, token, "測試供應商B")

    r = client.put(
        f"/api/inventory/batches/{batch_no}", headers=_auth(token),
        json={"supplier_id": supplier_id, "invoice_no": "INV-EDIT-1", "note": "補登"},
    )
    assert r.status_code == 200, r.text

    detail = client.get(f"/api/inventory/batches/{batch_no}", headers=_auth(token))
    header = detail.json()["header"]
    assert header["supplier_name"] == "測試供應商B"
    assert header["invoice_no"] == "INV-EDIT-1"
    assert header["note"] == "補登"


def test_stock_batch_flows_into_t100_export_and_can_be_confirmed(client, make_user):
    username, password = make_user(username="stk_admin5", role="superadmin")
    token = _login(client, username, password)

    client.put(
        "/api/settings/t100-export-config", headers=_auth(token),
        json={"salesRevenueAccount": "4101", "outputTaxAccount": "2191",
              "contractorExpenseAccount": "6101",
              "inventoryExpenseAccounts": {"其他": "5101"}},
    )

    _make_part(client, token, "STK-P5")
    supplier_id = _make_supplier(client, token, "測試供應商C")
    batch_no = _make_batch(client, token, "STK-P5", supplier_id=supplier_id, cost=3000, qty=2)  # total 6000

    pay = client.post(
        f"/api/inventory/batches/{batch_no}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-18",
              "bankAccountName": "第一銀行", "bankAccountCode": "1101"},
    )
    assert pay.status_code == 200, pay.text

    preview = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert preview.status_code == 200, preview.text
    events = preview.json()["events"]
    ev = next(e for e in events if e["sourceKey"] == batch_no)
    assert ev["sourceType"] == "stock_batch"
    assert ev["amount"] == 6000

    xlsx_resp = client.get(
        "/api/reports/t100-export/vouchers?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_resp.content))
    ws = wb["T100傳票匯出"]
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    body_rows = rows[:-1]
    batch_rows = [row for row in body_rows if row[9] == batch_no]
    assert len(batch_rows) == 2
    assert sum(row[6] or 0 for row in batch_rows) == sum(row[7] or 0 for row in batch_rows) == 6000
    acct_codes = {row[4] for row in batch_rows}
    assert acct_codes == {"5101", "1101"}

    confirm = client.post(
        "/api/reports/t100-export/confirm", headers=_auth(token),
        json={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert confirm.status_code == 200, confirm.text

    preview2 = client.get(
        "/api/reports/t100-export/preview?start=2026-08-01&end=2026-08-31",
        headers=_auth(token),
    )
    assert all(e["sourceKey"] != batch_no for e in preview2.json()["events"])


def test_unpaid_batch_excluded_from_t100_export(client, make_user):
    username, password = make_user(username="stk_admin6", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P6")
    _make_batch(client, token, "STK-P6", cost=1000, qty=1)  # 未標記已付款

    preview = client.get(
        "/api/reports/t100-export/preview?start=2026-01-01&end=2026-12-31",
        headers=_auth(token),
    )
    assert preview.status_code == 200, preview.text
    assert all(e["sourceType"] != "stock_batch" or e["sourceKey"] != "STK-P6" for e in preview.json()["events"])
