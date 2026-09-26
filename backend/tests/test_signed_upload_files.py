"""API-level integration tests for the 回簽/開立 attachment upload endpoints
added to quotations / shipping_notes / invoice_vouchers (see
helpers/uploads.py and each router's signed-files / issued-files endpoints)."""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _png_file(name="test.png"):
    # Minimal valid 1x1 PNG
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae42"
        "6082"
    )
    return (name, io.BytesIO(data), "image/png")


def _make_quotation(quote_no, status="已送出"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, status, "測試客戶", "測試專案", json.dumps({}),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _make_invoice_voucher(voucher_no, quote_no, status="已核准"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, amount, status, "
            "snapshot_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (voucher_no, quote_no, "amount", 10000, status, json.dumps({"customerName": "測試客戶"}), "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


# ── quotations ──────────────────────────────────────────────────────────────

def test_quotation_signed_toggle_and_upload(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SIGN-001")

    r = client.post(
        "/api/quotations/MQ-SIGN-001/signed-toggle", headers=_auth(token),
        json={"action": "sign", "note": "客戶已簽回"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_signed"] is True

    up = client.post(
        "/api/quotations/MQ-SIGN-001/signed-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["added"] == 1
    file_id = body["files"][0]["id"]

    detail = client.get("/api/quotations/MQ-SIGN-001", headers=_auth(token)).json()
    assert detail["is_signed"] == 1
    assert len(detail["signed_files"]) == 1

    d = client.delete(f"/api/quotations/MQ-SIGN-001/signed-files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    detail2 = client.get("/api/quotations/MQ-SIGN-001", headers=_auth(token)).json()
    assert len(detail2["signed_files"]) == 0


def test_quotation_signed_toggle_blocked_before_sent(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SIGN-002", status="草稿")

    r = client.post(
        "/api/quotations/MQ-SIGN-002/signed-toggle", headers=_auth(token),
        json={"action": "sign"},
    )
    assert r.status_code == 409, r.text


def test_quotation_signed_files_upload_rejects_bad_extension(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SIGN-003")

    r = client.post(
        "/api/quotations/MQ-SIGN-003/signed-files", headers=_auth(token),
        files={"files": ("evil.exe", io.BytesIO(b"not really an exe"), "application/octet-stream")},
    )
    assert r.status_code == 400, r.text


# ── shipping_notes ──────────────────────────────────────────────────────────


# ── invoice_vouchers ────────────────────────────────────────────────────────
