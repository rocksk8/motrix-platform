"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_signed_upload_files.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
API-level integration tests for the 回簽/開立 attachment upload endpoints
added to quotations / shipping_notes / invoice_vouchers (see
helpers/uploads.py and each router's signed-files / issued-files endpoints).
"""
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


def _make_shipping_note(note_no, quote_no, status="已核准"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, "
            "items_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (note_no, quote_no, status, "測試客戶", "測試專案", "[]", "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
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


# ── shipping_notes ──────────────────────────────────────────────────────────


# ── invoice_vouchers ────────────────────────────────────────────────────────

def test_invoice_voucher_issued_files_upload(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SIGN-020")
    _make_invoice_voucher("IV-SIGN-001", "MQ-SIGN-020")

    up = client.post(
        "/api/invoice-vouchers/IV-SIGN-001/issued-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    file_id = up.json()["files"][0]["id"]

    detail = client.get("/api/invoice-vouchers/IV-SIGN-001", headers=_auth(token)).json()
    assert len(detail["issuedFiles"]) == 1

    d = client.delete(f"/api/invoice-vouchers/IV-SIGN-001/issued-files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
