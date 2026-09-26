"""業務開發 API 整合題（開發案件更新衝突、轉建、重新連結、刪報價單解除連結）。

（2026-09-26 自 tests/test_api_integration.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
API-level integration tests against the real FastAPI app (see conftest.py
for how DB/backup file paths are isolated). Pure-function logic already has
coverage in test_core.py; this file targets the things that only exist at the
HTTP/request layer: auth middleware, demo-account DB isolation, optimistic
locking, login rate limiting, and the /api/uploads path-traversal guard.
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


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


# ── company-profile module-gated permission (settings automation account) ───
# PUT /api/settings/company-profile 原本寫死 require_superadmin=True（無 module
# 逃生門），只有真正的超管帳號能改。改用「settings」module 開放非 superadmin
# 角色也能經授權存取——讓可以建立一個低權限自動化帳號專門呼叫這支 API，不必
# 共用 superadmin 個人帳密。
