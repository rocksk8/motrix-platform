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


# ── inventory adjust: void/return_to_stock state-machine guards ─────────────


# ── shipping note revoke-approval (new endpoint, #3c) ────────────────────────


# ── dev_cases optimistic lock (#6 medium risk — was previously missing) ─────


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
