"""API-level integration tests against the real FastAPI app (see conftest.py
for how DB/backup file paths are isolated). Pure-function logic already has
coverage in test_core.py; this file targets the things that only exist at the
HTTP/request layer: auth middleware, demo-account DB isolation, optimistic
locking, login rate limiting, and the /api/uploads path-traversal guard.
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_demo_password(password="60575481"):
    """`IA2` 之後 `init_demo_account()` 產生的是**隨機密碼**（`secrets.
    token_urlsafe`），不再是這裡沿用的舊字面值——直接把 `demo` 這一列的
    `password_hash` 改成已知值，同 `make_user()` fixture 那條「不依賴
    隨機密碼寫檔那條路」的理由（見 `conftest.py::make_user` docstring）。
    """
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = 'demo'",
                    (_hash_pw(password),))
        conn.commit()
    finally:
        conn.close()


# ── Auth middleware ─────────────────────────────────────────────────────────

def test_ping_is_public(client):
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_protected_endpoint_requires_auth(client):
    r = client.get("/api/customers")
    assert r.status_code == 401


def test_protected_endpoint_rejects_garbage_token(client):
    r = client.get("/api/customers", headers=_auth("not-a-real-token"))
    assert r.status_code == 401


def test_login_then_authenticated_request_succeeds(client, make_user):
    username, password = make_user()
    token = _login(client, username, password)
    r = client.get("/api/customers", headers=_auth(token))
    assert r.status_code == 200


def test_wrong_password_rejected(client, make_user):
    username, password = make_user()
    r = client.post("/api/auth/login", json={"username": username, "password": "wrong-password"})
    assert r.status_code == 401


# ── Demo account DB isolation ───────────────────────────────────────────────

def test_demo_login_data_never_touches_real_db(client):
    _set_demo_password()
    demo_token = _login(client, "demo", "60575481")

    r = client.post(
        "/api/customers",
        headers=_auth(demo_token),
        json={"name": "Demo 測試客戶", "tax_id": "", "phone": "", "data": {}},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/customers", headers=_auth(demo_token))
    names = [c["name"] for c in r.json()]
    assert "Demo 測試客戶" in names, "demo session should see the customer it just created"

    # Now log in as a real (non-demo) user and confirm the real DB is empty —
    # the whole point of db.is_demo_mode()/contextvars routing in db.py.
    import db
    real_conn = db.get_db()
    try:
        real_customers = [dict(r) for r in real_conn.execute("SELECT name FROM customers").fetchall()]
    finally:
        real_conn.close()
    assert real_customers == [], (
        f"demo-created data leaked into the real DB: {real_customers}"
    )


def test_demo_login_resets_previous_demo_session_data(client):
    """§3.5: every demo login wipes the demo DB back to empty — two demo
    logins must not accumulate data from a previous 'customer'."""
    _set_demo_password()
    token1 = _login(client, "demo", "60575481")
    client.post(
        "/api/customers", headers=_auth(token1),
        json={"name": "第一次展示留下的客戶", "tax_id": "", "phone": "", "data": {}},
    )

    token2 = _login(client, "demo", "60575481")
    r = client.get("/api/customers", headers=_auth(token2))
    names = [c["name"] for c in r.json()]
    assert names == [], f"second demo login should start from an empty DB, got {names}"


# ── Optimistic locking ──────────────────────────────────────────────────────

def test_customer_visits_conflict_returns_409(client, make_user):
    username, password = make_user()
    token = _login(client, username, password)

    r = client.post(
        "/api/customers", headers=_auth(token),
        json={"name": "衝突測試客戶", "tax_id": "", "phone": "", "data": {}},
    )
    cid = r.json()["id"]
    updated_at = client.get(f"/api/customers/{cid}", headers=_auth(token)).json()["updatedAt"]

    r = client.patch(
        f"/api/customers/{cid}/visits", headers=_auth(token),
        json={"expectedUpdatedAt": "2000-01-01T00:00:00.000000", "note": "stale write"},
    )
    assert r.status_code == 409, r.text

    r = client.patch(
        f"/api/customers/{cid}/visits", headers=_auth(token),
        json={"expectedUpdatedAt": updated_at, "note": "fresh write"},
    )
    assert r.status_code == 200, r.text


# ── Login rate limiting ──────────────────────────────────────────────────────

def test_login_locks_out_after_repeated_failures(client, make_user):
    # Rate limiting is keyed by client IP in a process-global dict (routers/auth.py
    # _rl_state), not by the per-test DB — give this test its own fake IP via
    # X-Forwarded-For so it can't lock out (or be unlocked by) any other test
    # sharing TestClient's default IP.
    headers = {"X-Forwarded-For": "203.0.113.55"}
    username, _ = make_user()
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": username, "password": "wrong"}, headers=headers)
        assert r.status_code == 401

    # 6th attempt, even with the *correct* password, should now be rate-limited.
    r = client.post("/api/auth/login", json={"username": username, "password": "Test-Pass-123"}, headers=headers)
    assert r.status_code == 429, r.text


# ── /api/uploads path traversal guard (regression for the fix in
#    routers/projects.py's serve_upload()/get_photo_token()) ────────────────

def test_uploads_path_traversal_is_blocked(client, make_user):
    username, password = make_user()
    token = _login(client, username, password)

    r = client.get(
        "/api/uploads/..%5Cbackend%5Cmain.py",
        headers=_auth(token),
    )
    assert r.status_code == 403

    r = client.get(
        "/api/photo-token", headers=_auth(token),
        params={"path": "../backend/main.py"},
    )
    assert r.status_code == 403


def test_uploads_normal_path_not_blocked(client, make_user):
    """The traversal guard shouldn't reject legitimate paths — just ones that
    escape uploads/. A nonexistent-but-legitimate path should 404, not 403."""
    username, password = make_user()
    token = _login(client, username, password)

    r = client.get(
        "/api/uploads/projects/does-not-exist.jpg",
        headers=_auth(token),
    )
    assert r.status_code == 404


# ── deal-tag state machine (regression for §5.2 state-diagram bypass) ───────

def _make_quotation(quote_no, deal_tag="", status="草稿"):
    import db
    conn = db.get_db()
    try:
        # dealTag must be mirrored into data_json too — update_deal_tag() reads
        # old_tag from data_json (the hot `deal_tag` column is the derived copy),
        # so a fixture that only sets the column would misrepresent real rows.
        data_json = json.dumps({"dealTag": deal_tag})
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, status, "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag),
        )
        conn.commit()
    finally:
        conn.close()


def test_deal_tag_cannot_jump_straight_to_closed(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-001", deal_tag="")

    r = client.patch(
        "/api/quotations/MQ-TEST-001/deal-tag", headers=_auth(token),
        json={"deal_tag": "已結案"},
    )
    assert r.status_code == 400, r.text


def test_deal_tag_cannot_reach_closed_from_provided(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-002", deal_tag="已提供")

    r = client.patch(
        "/api/quotations/MQ-TEST-002/deal-tag", headers=_auth(token),
        json={"deal_tag": "已結案"},
    )
    assert r.status_code == 400, r.text


def test_deal_tag_closed_allowed_from_won(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-003", deal_tag="已成案")

    r = client.patch(
        "/api/quotations/MQ-TEST-003/deal-tag", headers=_auth(token),
        json={"deal_tag": "已結案"},
    )
    assert r.status_code == 200, r.text


def test_put_quotation_cannot_smuggle_deal_tag_change(client, make_user):
    """PUT is the generic content-save endpoint for an editable (unlocked) quotation;
    it must not let a client-supplied dealTag/settlement.status bypass the state-machine
    guards that live in PATCH /deal-tag and PATCH /settlement."""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-004", deal_tag="", status="草稿")

    r = client.put(
        "/api/quotations/MQ-TEST-004", headers=_auth(token),
        json={
            "status": "草稿",
            "data": {
                "customerName": "測試客戶", "projectName": "測試專案",
                "dealTag": "已成案",  # smuggled — should be ignored, not written
                "settlement": {"status": "finalized"},
                "tot": {}, "items": [],
            },
        },
    )
    assert r.status_code == 200, r.text

    import db
    conn = db.get_db()
    row = conn.execute(
        "SELECT deal_tag, settle_status, data_json FROM quotations WHERE quote_no='MQ-TEST-004'"
    ).fetchone()
    conn.close()
    assert row["deal_tag"] == "", "PUT let a smuggled dealTag through the hot column"
    assert row["settle_status"] == "", "PUT let a smuggled settlement.status through the hot column"
    stored = json.loads(row["data_json"])
    assert stored.get("dealTag", "") == "", "PUT let a smuggled dealTag through into data_json"
    assert stored.get("settlement", {}).get("status", "") == "", \
        "PUT let a smuggled settlement.status through into data_json"


# ── case-record device/stock sync (regression for silent shipped-serial skip) ─

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


# ── inventory adjust: void/return_to_stock state-machine guards ─────────────

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


# ── shipping note revoke-approval (new endpoint, #3c) ────────────────────────

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


# ── dev_cases optimistic lock (#6 medium risk — was previously missing) ─────

def test_dev_case_update_conflict_returns_409(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    r = client.post(
        "/api/dev-cases", headers=_auth(token),
        json={"case_name": "測試開發案件", "customer_name": "", "status": "洽談中"},
    )
    assert r.status_code == 201, r.text
    case = r.json()
    case_id = case["id"]

    r = client.put(
        f"/api/dev-cases/{case_id}", headers=_auth(token),
        json={
            "case_name": "改過的案件名稱", "customer_name": "", "status": "洽談中",
            "expectedUpdatedAt": "2000-01-01T00:00:00.000000",
        },
    )
    assert r.status_code == 409, r.text

    r = client.put(
        f"/api/dev-cases/{case_id}", headers=_auth(token),
        json={
            "case_name": "改過的案件名稱", "customer_name": "", "status": "洽談中",
            "expectedUpdatedAt": case["updatedAt"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["caseName"] == "改過的案件名稱"


def test_dev_case_update_without_expected_updated_at_still_works(client, make_user):
    """Optional lock — omitting it must not break existing callers."""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    r = client.post(
        "/api/dev-cases", headers=_auth(token),
        json={"case_name": "無鎖測試案件", "customer_name": "", "status": "洽談中"},
    )
    case_id = r.json()["id"]

    r = client.put(
        f"/api/dev-cases/{case_id}", headers=_auth(token),
        json={"case_name": "更新後", "customer_name": "", "status": "洽談中"},
    )
    assert r.status_code == 200, r.text


# ── contractor-dispatches optimistic lock (#6 medium risk) ──────────────────


# ── quotation draft PUT optimistic lock (#6 medium risk) ─────────────────────

def test_put_quotation_conflict_returns_409(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-012", status="草稿")

    r = client.put(
        "/api/quotations/MQ-TEST-012", headers=_auth(token),
        json={
            "status": "草稿",
            "data": {
                "customerName": "改過的客戶名稱", "projectName": "測試專案",
                "tot": {}, "items": [],
                "_expectedUpdatedAt": "2000-01-01T00:00:00.000000",
            },
        },
    )
    assert r.status_code == 409, r.text


def test_put_quotation_succeeds_with_correct_expected_updated_at(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-013", status="草稿")

    conn_row = client.get("/api/quotations/MQ-TEST-013", headers=_auth(token)).json()
    current_updated_at = conn_row["updated_at"]

    r = client.put(
        "/api/quotations/MQ-TEST-013", headers=_auth(token),
        json={
            "status": "草稿",
            "data": {
                "customerName": "改過的客戶名稱", "projectName": "測試專案",
                "tot": {}, "items": [],
                "_expectedUpdatedAt": current_updated_at,
            },
        },
    )
    assert r.status_code == 200, r.text


def test_put_quotation_without_expected_updated_at_still_works(client, make_user):
    """Optional lock — omitting it must not break existing callers (e.g. new-record saves)."""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-014", status="草稿")

    r = client.put(
        "/api/quotations/MQ-TEST-014", headers=_auth(token),
        json={
            "status": "草稿",
            "data": {"customerName": "改過的客戶名稱", "projectName": "測試專案", "tot": {}, "items": []},
        },
    )
    assert r.status_code == 200, r.text


# ── dev_case ↔ quotation link integrity (#7 low risk) ────────────────────────

def test_mark_converted_rejects_nonexistent_quote_no(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.post("/api/dev-cases", headers=_auth(token),
                     json={"case_name": "測試連結案件", "customer_name": "", "status": "洽談中"})
    case_id = r.json()["id"]

    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(token),
                      json={"quote_no": "MQ-NOT-EXIST-001"})
    assert r.status_code == 400, r.text


def test_mark_converted_accepts_existing_quote_no(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-020")
    r = client.post("/api/dev-cases", headers=_auth(token),
                     json={"case_name": "測試連結案件2", "customer_name": "", "status": "洽談中"})
    case_id = r.json()["id"]

    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(token),
                      json={"quote_no": "MQ-TEST-020"})
    assert r.status_code == 200, r.text
    assert r.json()["convertedQuoteNo"] == "MQ-TEST-020"
    assert r.json()["status"] == "成案"


def test_delete_quotation_clears_orphaned_dev_case_link(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-021", status="草稿")
    r = client.post("/api/dev-cases", headers=_auth(token),
                     json={"case_name": "測試孤兒連結案件", "customer_name": "", "status": "洽談中"})
    case_id = r.json()["id"]
    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(token),
                      json={"quote_no": "MQ-TEST-021"})
    assert r.status_code == 200, r.text

    r = client.delete("/api/quotations/MQ-TEST-021", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = client.get(f"/api/dev-cases/{case_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["convertedQuoteNo"] == ""
    assert r.json()["status"] == "洽談中"


# ── dev_case relink-quote review flow (DB v42) ────────────────────────────────

def _make_linked_dev_case(client, token, case_name, quote_no):
    _make_quotation(quote_no)
    r = client.post("/api/dev-cases", headers=_auth(token),
                     json={"case_name": case_name, "customer_name": "", "status": "洽談中"})
    case_id = r.json()["id"]
    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(token),
                      json={"quote_no": quote_no})
    assert r.status_code == 200, r.text
    return case_id


def test_convert_rejects_already_linked_case(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    case_id = _make_linked_dev_case(client, token, "測試已連結案件", "MQ-TEST-030")
    _make_quotation("MQ-TEST-031")

    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(token),
                      json={"quote_no": "MQ-TEST-031"})
    assert r.status_code == 409, r.text


def test_request_relink_requires_admin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    case_id = _make_linked_dev_case(client, token, "測試權限案件", "MQ-TEST-032")

    viewer_username, viewer_password = make_user(username="relink-viewer", role="viewer",
                                                  modules=["dev_crm"])
    viewer_token = _login(client, viewer_username, viewer_password)
    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(viewer_token),
                     json={"quote_no": "", "reason": ""})
    assert r.status_code == 403, r.text


def test_request_relink_rejects_nonexistent_target(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    case_id = _make_linked_dev_case(client, token, "測試異動目標不存在", "MQ-TEST-033")

    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(token),
                     json={"quote_no": "MQ-NOT-EXIST-002", "reason": ""})
    assert r.status_code == 400, r.text


def test_relink_unlink_full_flow_reverts_status(client, make_user):
    admin_username, admin_password = make_user(role="admin")
    admin_token = _login(client, admin_username, admin_password)
    case_id = _make_linked_dev_case(client, admin_token, "測試解除連結流程", "MQ-TEST-034")

    superadmin_username, superadmin_password = make_user(username="relink-superadmin",
                                                          role="superadmin")
    superadmin_token = _login(client, superadmin_username, superadmin_password)

    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(admin_token),
                     json={"quote_no": "", "reason": "報價單已取消"})
    assert r.status_code == 200, r.text

    # 已有待審申請時重複申請 → 409
    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(admin_token),
                     json={"quote_no": "", "reason": ""})
    assert r.status_code == 409, r.text

    r = client.get(f"/api/dev-cases/{case_id}", headers=_auth(admin_token))
    body = r.json()
    assert body["pendingRelink"] is True
    assert body["relinkTargetQuoteNo"] == ""
    assert body["convertedQuoteNo"] == "MQ-TEST-034"  # 核准前仍維持原連結

    r = client.post(f"/api/dev-cases/{case_id}/approve-relink-quote", headers=_auth(superadmin_token),
                     json={"approve": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["convertedQuoteNo"] == ""
    assert body["status"] == "洽談中"
    assert body["pendingRelink"] is False


def test_relink_reject_keeps_original_link(client, make_user):
    admin_username, admin_password = make_user(role="admin")
    admin_token = _login(client, admin_username, admin_password)
    case_id = _make_linked_dev_case(client, admin_token, "測試退回申請", "MQ-TEST-035")

    superadmin_username, superadmin_password = make_user(username="relink-reject-superadmin",
                                                          role="superadmin")
    superadmin_token = _login(client, superadmin_username, superadmin_password)

    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(admin_token),
                     json={"quote_no": "", "reason": ""})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/dev-cases/{case_id}/approve-relink-quote", headers=_auth(superadmin_token),
                     json={"approve": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["convertedQuoteNo"] == "MQ-TEST-035"
    assert body["pendingRelink"] is False


def test_cancel_relink_request(client, make_user):
    admin_username, admin_password = make_user(role="admin")
    admin_token = _login(client, admin_username, admin_password)
    case_id = _make_linked_dev_case(client, admin_token, "測試取消申請", "MQ-TEST-036")

    r = client.post(f"/api/dev-cases/{case_id}/request-relink-quote", headers=_auth(admin_token),
                     json={"quote_no": "", "reason": ""})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/dev-cases/{case_id}/cancel-relink-quote", headers=_auth(admin_token))
    assert r.status_code == 200, r.text

    r = client.get(f"/api/dev-cases/{case_id}", headers=_auth(admin_token))
    assert r.json()["pendingRelink"] is False
    assert r.json()["convertedQuoteNo"] == "MQ-TEST-036"

    # 已無待審申請時再取消一次 → 409
    r = client.post(f"/api/dev-cases/{case_id}/cancel-relink-quote", headers=_auth(admin_token))
    assert r.status_code == 409, r.text


# ── parts.py 409/leak fixes (#8 low risk) ────────────────────────────────────

def test_create_part_duplicate_explicit_part_no_returns_409(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.post("/api/parts", headers=_auth(token),
                     json={"partNo": "TEST-DUP-001", "name": "第一次"})
    assert r.status_code == 201, r.text
    r = client.post("/api/parts", headers=_auth(token),
                     json={"partNo": "TEST-DUP-001", "name": "第二次"})
    assert r.status_code == 409, r.text


def test_create_part_missing_category_returns_400_not_500(client, make_user):
    """Regression for the conn.close() leak on this specific error path — a
    follow-up request on the same test session must still work afterward."""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.post("/api/parts", headers=_auth(token), json={"name": "無料號無分類"})
    assert r.status_code == 400, r.text
    r = client.post("/api/parts", headers=_auth(token),
                     json={"partNo": "TEST-AFTER-LEAK-001", "name": "驗證連線沒洩漏"})
    assert r.status_code == 201, r.text


def test_create_part_toctou_race_returns_409_not_500(client, make_user, monkeypatch):
    """Simulates the concurrency race: the pre-INSERT existence check is made to lie
    (report "not found" even though the row already exists), so the only thing that
    can produce the 409 is the `except sqlite3.IntegrityError` branch around the
    INSERT itself — proving that branch actually works, not just the pre-check.

    sqlite3.Connection is a C-level immutable type (can't monkeypatch its `execute`
    directly), so this wraps the connection object returned by get_db() instead —
    intercepting just the specific existence-check SQL and proxying everything else
    (commit, other queries) straight through to the real connection.
    """
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.post("/api/parts", headers=_auth(token),
                     json={"partNo": "TEST-RACE-001", "name": "第一次"})
    assert r.status_code == 201, r.text

    import routers.parts as parts_module
    real_get_db = parts_module.get_db

    class _LyingConn:
        def __init__(self, real_conn):
            self._real = real_conn

        def execute(self, sql, params=()):
            if sql.strip().startswith("SELECT id FROM parts WHERE part_no=?"):
                return self._real.execute("SELECT id FROM parts WHERE part_no=?", ("__never_matches__",))
            return self._real.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(parts_module, "get_db", lambda: _LyingConn(real_get_db()))

    r = client.post("/api/parts", headers=_auth(token),
                     json={"partNo": "TEST-RACE-001", "name": "模擬併發（繞過前置檢查）"})
    assert r.status_code == 409, r.text
    assert "重新整理" in r.text  # confirms the except-branch message, not the pre-check's


# ── company-profile module-gated permission (settings automation account) ───
# PUT /api/settings/company-profile 原本寫死 require_superadmin=True（無 module
# 逃生門），只有真正的超管帳號能改。改用「settings」module 開放非 superadmin
# 角色也能經授權存取——讓可以建立一個低權限自動化帳號專門呼叫這支 API，不必
# 共用 superadmin 個人帳密。

def test_company_profile_put_rejects_non_superadmin_without_settings_module(client, make_user):
    username, password = make_user(role="viewer", modules=[])
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/company-profile", headers=_auth(token),
        json={"name": "測試", "tax_id": "00000000", "contact_info": "Tel: 000"},
    )
    assert r.status_code == 403, r.text


def test_company_profile_put_refuses_non_superadmin_with_settings_module(client, make_user):
    """🔴 §10 SA1：`role=viewer` ＋ `modules` 含 `settings` ⇒ **403**。

    ## ☠️ 這一題原本斷言 200，而題名逐字寫著 `allows_...`

    ```
    舊：test_company_profile_put_allows_non_superadmin_with_settings_module
        assert r.status_code == 200
    ```
    🔑 **它不是沒發現問題 —— 它把問題寫成了規格。**
    正式資料庫裡真的有這種帳號（`automation`，`role=viewer` 而持有 `settings`）
    ⇒ **一個 viewer 改得動匯款帳號**，而這一題每天替那個行為背書。

    ## ⚠️ 而它今天之所以被看見，只是因為**有人改了行為**

    使用者說「只有超級管理員可以修改」⇒ SA1 拿掉 `module='settings'`
    ⇒ 這一題紅了。**沒有那一句話的話，它會永遠綠著。**
    📌 一個鎖住漏洞的測試**不會自己求救**：不紅、不警告、不出現在任何清單上，
    **而它的名字讀起來像一個決定。**

    ## 🔑 為什麼改斷言而不是刪掉它

    刪掉之後，下一個人把 `module='settings'` 加回去時**沒有東西會紅**。
    ⇒ 留著它、把方向轉過來 —— 〈更正要留著錯的那一列〉：
    **改成對的當沒發生過，下一個人只會看到結論。**
    """
    username, password = make_user(role="viewer", modules=["settings"])
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/company-profile", headers=_auth(token),
        json={"name": "允碩整合集創股份有限公司", "tax_id": "60575481",
              "contact_info": "Tel: 04-3610-6566｜info@miactw.com"},
    )
    assert r.status_code == 403, (
        f"持有 `settings` 模組的 viewer 改得動公司資料（{r.status_code}）——\n"
        "☠️ 那個模組同時蓋住「調整介面偏好」與「改匯款帳號」，而它們不是同一件事。\n"
        f"{r.text[:200]}"
    )

    # 📌 讀取**仍然**要通（SA4：匯款帳號印在寄給客戶的請款單上，它不是秘密）。
    # ⚠️ 少了這一行，一個「把整個端點關掉」的實作會讓上面那個斷言綠，
    #    而一般使用者的請款單頁面會整個壞掉。
    r = client.get("/api/settings/company-profile", headers=_auth(token))
    assert r.status_code == 200, (
        f"把寫入關緊的同時把讀取也關掉了（{r.status_code}）：{r.text[:200]}"
    )


def test_company_profile_put_still_allows_superadmin(client, make_user):
    username, password = make_user(role="superadmin", modules=[])
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/company-profile", headers=_auth(token),
        json={"name": "允碩整合集創股份有限公司", "tax_id": "60575481", "contact_info": "Tel: 000"},
    )
    assert r.status_code == 200, r.text
