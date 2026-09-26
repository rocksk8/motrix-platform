"""M03 庫存序號（案件設備認領、作廢／回庫狀態機）與出貨單撤銷核准退庫。

2026-09-26 自 `backend/tests/test_api_integration.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

from tests.test_api_integration import _auth, _login, _make_quotation
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _make_stock_item(part_no, serial_no, status="in_stock"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_items (part_no, serial_no, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (part_no, serial_no, status, "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_device_install_flips_in_stock_serial_to_installed(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-005")
    _make_stock_item("NET-001", "SN-AVAILABLE")

    r = client.patch(
        "/api/quotations/MQ-TEST-005/case-record", headers=_auth(token),
        json={"case_record": {"devices": [{"id": 1, "sn": "SN-AVAILABLE"}]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stockConflicts"] == []

    import db
    conn = db.get_db()
    row = conn.execute("SELECT status, quote_no FROM stock_items WHERE serial_no='SN-AVAILABLE'").fetchone()
    conn.close()
    assert row["status"] == "installed"
    assert row["quote_no"] == "MQ-TEST-005"


def test_device_install_reports_conflict_for_already_shipped_serial(client, make_user):
    """Regression: a serial that's already 'shipped' elsewhere must not be silently
    skipped as if it were untracked — the case-record save should surface the
    conflict, and stock_items must NOT be flipped to 'installed' underneath it."""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-006")
    _make_stock_item("NET-002", "SN-ALREADY-SHIPPED", status="shipped")

    r = client.patch(
        "/api/quotations/MQ-TEST-006/case-record", headers=_auth(token),
        json={"case_record": {"devices": [{"id": 1, "sn": "SN-ALREADY-SHIPPED"}]}},
    )
    assert r.status_code == 200, r.text
    conflicts = r.json()["stockConflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["sn"] == "SN-ALREADY-SHIPPED"
    assert conflicts[0]["stockStatus"] == "shipped"

    import db
    conn = db.get_db()
    row = conn.execute("SELECT status FROM stock_items WHERE serial_no='SN-ALREADY-SHIPPED'").fetchone()
    conn.close()
    assert row["status"] == "shipped", "conflicting serial must not be silently flipped to installed"


def test_device_install_skips_untracked_serial_without_conflict(client, make_user):
    """A serial with no stock_items record at all is the common case (most devices
    aren't stock-tracked) — must stay a silent no-op, not a conflict."""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-007")

    r = client.patch(
        "/api/quotations/MQ-TEST-007/case-record", headers=_auth(token),
        json={"case_record": {"devices": [{"id": 1, "sn": "SN-NEVER-TRACKED"}]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stockConflicts"] == []


def test_void_is_terminal_and_clears_linkage_fields(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    conn.execute(
        "INSERT INTO stock_items (part_no, serial_no, status, quote_no, case_device_id, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        ("NET-003", "SN-TO-VOID", "installed", "MQ-TEST-008", "7",
         "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    item_id = conn.execute("SELECT id FROM stock_items WHERE serial_no='SN-TO-VOID'").fetchone()["id"]
    conn.commit()
    conn.close()

    r = client.post(f"/api/inventory/stock-items/{item_id}/adjust", headers=_auth(token),
                     json={"action": "void"})
    assert r.status_code == 200, r.text

    conn = db.get_db()
    row = conn.execute("SELECT status, quote_no, case_device_id FROM stock_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    assert row["status"] == "void"
    assert row["quote_no"] == "", "void must clear stale quote_no linkage"
    assert row["case_device_id"] == "", "void must clear stale case_device_id linkage"

    # already void — re-voiding should be rejected, not silently accepted
    r2 = client.post(f"/api/inventory/stock-items/{item_id}/adjust", headers=_auth(token),
                      json={"action": "void"})
    assert r2.status_code == 409, r2.text

    # void is terminal — cannot return_to_stock from it
    r3 = client.post(f"/api/inventory/stock-items/{item_id}/adjust", headers=_auth(token),
                      json={"action": "return_to_stock"})
    assert r3.status_code == 409, r3.text


def test_return_to_stock_rejects_already_in_stock(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_stock_item("NET-004", "SN-ALREADY-IN-STOCK", status="in_stock")
    import db
    conn = db.get_db()
    item_id = conn.execute("SELECT id FROM stock_items WHERE serial_no='SN-ALREADY-IN-STOCK'").fetchone()["id"]
    conn.close()

    r = client.post(f"/api/inventory/stock-items/{item_id}/adjust", headers=_auth(token),
                     json={"action": "return_to_stock"})
    assert r.status_code == 409, r.text


def _make_shipping_note(note_no, quote_no, part_no=None, serial_no=None, is_signed=0):
    import db
    conn = db.get_db()
    try:
        items = [{"part_no": part_no, "serials": [serial_no]}] if part_no else []
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, "
            "data_json, is_signed, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (note_no, quote_no, "已核准", "測試客戶", json.dumps(items),
             json.dumps({"approval": {"requestedBy": "someone"}}), is_signed,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_revoke_approval_reverts_status_and_returns_stock(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-009")
    _make_stock_item("NET-005", "SN-SHIPPED-001", status="shipped")
    import db
    conn = db.get_db()
    conn.execute(
        "UPDATE stock_items SET shipping_note_no='DN-TEST-001', quote_no='MQ-TEST-009' "
        "WHERE serial_no='SN-SHIPPED-001'"
    )
    conn.commit()
    conn.close()
    _make_shipping_note("DN-TEST-001", "MQ-TEST-009", "NET-005", "SN-SHIPPED-001")

    r = client.post(
        "/api/shipping-notes/DN-TEST-001/revoke-approval", headers=_auth(token),
        json={"note": "測試撤銷"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stockReturned"] == 1

    conn = db.get_db()
    note_row = conn.execute("SELECT status, data_json FROM shipping_notes WHERE note_no='DN-TEST-001'").fetchone()
    stock_row = conn.execute("SELECT status, shipping_note_no, quote_no FROM stock_items WHERE serial_no='SN-SHIPPED-001'").fetchone()
    conn.close()
    assert note_row["status"] == "草稿"
    assert "approval" not in json.loads(note_row["data_json"])
    assert stock_row["status"] == "in_stock"
    assert stock_row["shipping_note_no"] == ""
    assert stock_row["quote_no"] == ""


def test_revoke_approval_blocked_when_signed(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-010")
    _make_shipping_note("DN-TEST-002", "MQ-TEST-010", is_signed=1)

    r = client.post(
        "/api/shipping-notes/DN-TEST-002/revoke-approval", headers=_auth(token),
        json={},
    )
    assert r.status_code == 409, r.text
