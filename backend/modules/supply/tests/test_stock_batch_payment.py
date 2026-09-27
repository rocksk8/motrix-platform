"""入庫批次的付款註記、T100 匯出（M03 批次端點）；付款帳戶預設設定欄位那一題留在原檔。

2026-09-26 自 `backend/tests/test_stock_batch_payment_2026_09_01.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
import io

import openpyxl

from tests.test_stock_batch_payment_2026_09_01 import _auth, _login
from core import source_tree
import pytest


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
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
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
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    username, password = make_user(username="stk_admin6", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P6")
    batch_no = _make_batch(client, token, "STK-P6", cost=1000, qty=1)  # 未標記已付款

    preview = client.get(
        "/api/reports/t100-export/preview?start=2026-01-01&end=2026-12-31",
        headers=_auth(token),
    )
    assert preview.status_code == 200, preview.text
    # 2026-09-26：原本比的是料號（sourceKey 是批次號）⇒ 永遠成立的假綠；改比批次號
    assert not [e for e in preview.json()["events"] if e["sourceType"] == "stock_batch" and e["sourceKey"] == batch_no]


def test_paid_batches_provider_requires_is_paid_not_just_a_paid_at(client, make_user):
    """IP-20 提供者：`is_paid=0` 卻留著 `paid_at` 的列（舊資料／中途失敗）不可以進 T100 付款傳票。

    經端點取消付款會一起清掉 paid_at，所以這個狀態只能直接寫表造出來；它是提供者自己的判準，不靠日期剛好擋住。"""
    from modules.supply.api import inventory
    username, password = make_user(username="stk_admin6b", role="superadmin")
    token = _login(client, username, password)
    _make_part(client, token, "STK-P6B")
    batch_no = _make_batch(client, token, "STK-P6B", cost=800, qty=1)
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE stock_batches SET is_paid=0, paid_at='2026-05-01' WHERE batch_no=?", (batch_no,))
        conn.commit()
    finally:
        conn.close()
    assert batch_no not in [b["batch_no"] for b in inventory.paid_batches("2026-01-01", "2026-12-31")]
    conn = db.get_db()
    try:
        conn.execute("UPDATE stock_batches SET is_paid=1 WHERE batch_no=?", (batch_no,))
        conn.commit()
    finally:
        conn.close()
    got = [b for b in inventory.paid_batches("2026-01-01", "2026-12-31") if b["batch_no"] == batch_no]
    assert len(got) == 1 and got[0]["total_cost"] == 800 and got[0]["part_no"] == "STK-P6B", got


def test_last_paid_bank_account_for_supplier(client, make_user):
    """2026-09-02：標記已付款時銀行帳戶下拉的預設值——查這個供應商上次用的帳戶。"""
    username, password = make_user(username="stk_admin7", role="superadmin")
    token = _login(client, username, password)
    supplier_id = _make_supplier(client, token, "測試供應商D")

    # 未查過任何紀錄前，回傳空字串（不噴錯）
    r0 = client.get("/api/inventory/batches/last-paid-bank-account", headers=_auth(token))
    assert r0.status_code == 200, r0.text
    assert r0.json() == {"name": "", "acctCode": ""}

    r0b = client.get(
        f"/api/inventory/batches/last-paid-bank-account?supplier_id={supplier_id}", headers=_auth(token)
    )
    assert r0b.json() == {"name": "", "acctCode": ""}

    _make_part(client, token, "STK-BANK1")
    batch1 = _make_batch(client, token, "STK-BANK1", supplier_id=supplier_id, cost=1000, qty=1)
    client.post(
        f"/api/inventory/batches/{batch1}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-10", "bankAccountName": "舊帳戶", "bankAccountCode": "1101"},
    )

    _make_part(client, token, "STK-BANK2")
    batch2 = _make_batch(client, token, "STK-BANK2", supplier_id=supplier_id, cost=2000, qty=1)
    client.post(
        f"/api/inventory/batches/{batch2}/paid-toggle", headers=_auth(token),
        json={"action": "pay", "paid_at": "2026-08-20", "bankAccountName": "最新帳戶", "bankAccountCode": "1102"},
    )

    r1 = client.get(
        f"/api/inventory/batches/last-paid-bank-account?supplier_id={supplier_id}", headers=_auth(token)
    )
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"name": "最新帳戶", "acctCode": "1102"}

    # 不同供應商查不到這筆紀錄
    other_supplier_id = _make_supplier(client, token, "測試供應商E")
    r2 = client.get(
        f"/api/inventory/batches/last-paid-bank-account?supplier_id={other_supplier_id}", headers=_auth(token)
    )
    assert r2.json() == {"name": "", "acctCode": ""}
