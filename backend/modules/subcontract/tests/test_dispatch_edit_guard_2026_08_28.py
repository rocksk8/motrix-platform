"""2026-08-28（金額同步稽核第二輪）：承攬商派發已產生匯款申請後不可再編輯。

delete_dispatch() 原本就有這個守門（避免刪除已被匯款申請引用的紀錄），但
update_dispatch()（PUT，編輯用）完全沒有對應防護——派發的 total_amount 在
匯款申請核准、甚至財務已標記「已匯款」之後仍可被悄悄改掉，讓
contractor_payment_vouchers.snapshot_json 記錄的金額（財務實際依此匯款）
跟派發紀錄的即時金額對不上，且沒有任何比對或警示。"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_dispatch_with_voucher(quote_no, dispatch_total=45000):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "amount", "[]", dispatch_total, "completed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        dispatch_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        snapshot = json.dumps({"vendorName": "測試承攬商", "grandTotal": dispatch_total}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO contractor_payment_vouchers "
            "(voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, data_json, "
            "is_paid, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"PV-GUARD-{dispatch_id}", dispatch_id, quote_no, None, "已核准", snapshot, "{}",
             0, "tester", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
        return dispatch_id
    finally:
        conn.close()


def test_update_dispatch_blocked_once_voucher_exists(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    dispatch_id = _insert_dispatch_with_voucher("MQ-DGUARD-001")

    r = client.put(f"/api/contractor-dispatches/{dispatch_id}", headers=_auth(token), json={
        "quote_no": "MQ-DGUARD-001", "vendor_id": None, "dispatch_date": "2026-01-01",
        "scope": "amount", "items_json": [{"description": "改過的品項", "amount": 99999}],
        "personnel_json": [{"id": 1, "name": "測試人員", "amount": 1000}], "status": "completed",
    })
    assert r.status_code == 409, r.text
    assert "已產生匯款申請" in r.json()["detail"]

    # 資料庫裡的金額應該完全沒變
    import db
    conn = db.get_db()
    row = conn.execute("SELECT total_amount FROM contractor_dispatches WHERE id=?", (dispatch_id,)).fetchone()
    conn.close()
    assert row["total_amount"] == 45000


def test_update_dispatch_still_allowed_without_voucher(client, make_user):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-DGUARD-002", "2026-01-01", "amount", "[]", 10000, "confirmed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        dispatch_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.put(f"/api/contractor-dispatches/{dispatch_id}", headers=_auth(token), json={
        "quote_no": "MQ-DGUARD-002", "vendor_id": None, "dispatch_date": "2026-01-01",
        "scope": "amount", "items_json": [{"description": "正常編輯", "amount": 20000}],
        "personnel_json": [{"id": 1, "name": "測試人員", "amount": 1000}], "status": "confirmed",
    })
    assert r.status_code == 200, r.text
