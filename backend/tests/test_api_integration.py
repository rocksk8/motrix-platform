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
