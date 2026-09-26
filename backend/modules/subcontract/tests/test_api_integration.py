"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_api_integration.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
API-level integration tests against the real FastAPI app (see conftest.py
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


# ── Demo account DB isolation ───────────────────────────────────────────────


# ── Optimistic locking ──────────────────────────────────────────────────────


# ── Login rate limiting ──────────────────────────────────────────────────────


# ── /api/uploads path traversal guard (regression for the fix in
#    routers/projects.py's serve_upload()/get_photo_token()) ────────────────


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


# ── inventory adjust: void/return_to_stock state-machine guards ─────────────


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


# ── dev_cases optimistic lock (#6 medium risk — was previously missing) ─────


# ── contractor-dispatches optimistic lock (#6 medium risk) ──────────────────

def test_contractor_dispatch_update_conflict_returns_409(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-TEST-011")

    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={
            "quote_no": "MQ-TEST-011",
            "personnel_json": [{"id": 1, "name": "測試工班", "amount": 1000, "note": ""}],
        },
    )
    assert r.status_code == 201, r.text
    dispatch = r.json()
    did = dispatch["id"]

    r = client.put(
        f"/api/contractor-dispatches/{did}", headers=_auth(token),
        json={
            "quote_no": "MQ-TEST-011",
            "personnel_json": [{"id": 1, "name": "測試工班", "amount": 2000, "note": ""}],
            "expectedUpdatedAt": "2000-01-01T00:00:00.000000",
        },
    )
    assert r.status_code == 409, r.text

    r = client.put(
        f"/api/contractor-dispatches/{did}", headers=_auth(token),
        json={
            "quote_no": "MQ-TEST-011",
            "personnel_json": [{"id": 1, "name": "測試工班", "amount": 2000, "note": ""}],
            # created_at == updated_at at creation time (both set to `now` in the INSERT)
            "expectedUpdatedAt": dispatch["created_at"],
        },
    )
    assert r.status_code == 200, r.text


# ── quotation draft PUT optimistic lock (#6 medium risk) ─────────────────────


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


# ── company-profile module-gated permission (settings automation account) ───
# PUT /api/settings/company-profile 原本寫死 require_superadmin=True（無 module
# 逃生門），只有真正的超管帳號能改。改用「settings」module 開放非 superadmin
# 角色也能經授權存取——讓可以建立一個低權限自動化帳號專門呼叫這支 API，不必
# 共用 superadmin 個人帳密。
