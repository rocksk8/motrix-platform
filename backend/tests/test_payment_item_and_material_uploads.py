"""API-level integration tests for per-payment-item invoice uploads and
per-material-item attachment uploads (both live inside quotations.data_json.
caseRecord — see routers/quotations.py _load_payment_item()/_load_material_item()
and the /payment/{idx}/invoice-files, /materials/{idx}/files endpoints)."""
import io
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _png_file(name="test.png"):
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae42"
        "6082"
    )
    return (name, io.BytesIO(data), "image/png")


def _make_quotation(quote_no, payment_items=None, materials=None):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": payment_items if payment_items is not None else [
                    {"type": "訂金款", "pct": 30, "invoiceNo": ""},
                ]},
                "materials": materials if materials is not None else [
                    {"id": 1, "name": "測試料件", "qty": 1, "unit": "台", "ordered": True, "arrived": False},
                ],
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _get_case_record(client, token, quote_no):
    r = client.get(f"/api/quotations/{quote_no}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["caseRecord"]


# ── payment items ────────────────────────────────────────────────────────────

def test_payment_item_invoice_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-UP-001")

    up = client.post(
        "/api/quotations/MQ-UP-001/payment/0/invoice-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["added"] == 1
    file_id = body["files"][0]["id"]

    cr = _get_case_record(client, token, "MQ-UP-001")
    assert len(cr["payment"]["items"][0]["invoiceFiles"]) == 1

    d = client.delete(f"/api/quotations/MQ-UP-001/payment/0/invoice-files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    cr2 = _get_case_record(client, token, "MQ-UP-001")
    assert len(cr2["payment"]["items"][0]["invoiceFiles"]) == 0


def test_payment_item_invoice_upload_rejects_out_of_range_index(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-UP-002")

    r = client.post(
        "/api/quotations/MQ-UP-002/payment/5/invoice-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert r.status_code == 400, r.text


# ── materials ────────────────────────────────────────────────────────────────

def test_material_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-UP-010")

    up = client.post(
        "/api/quotations/MQ-UP-010/materials/0/files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    file_id = up.json()["files"][0]["id"]

    cr = _get_case_record(client, token, "MQ-UP-010")
    assert len(cr["materials"][0]["files"]) == 1

    d = client.delete(f"/api/quotations/MQ-UP-010/materials/0/files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    cr2 = _get_case_record(client, token, "MQ-UP-010")
    assert len(cr2["materials"][0]["files"]) == 0


def test_material_file_upload_multi_file(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-UP-011")

    up = client.post(
        "/api/quotations/MQ-UP-011/materials/0/files", headers=_auth(token),
        files=[("files", _png_file("a.png")), ("files", _png_file("b.png"))],
    )
    assert up.status_code == 201, up.text
    assert up.json()["added"] == 2
    cr = _get_case_record(client, token, "MQ-UP-011")
    assert len(cr["materials"][0]["files"]) == 2


# ── material invoice files（獨立於上面的一般附件，2026-08-25 新增）────────────

def test_material_invoice_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-UP-020")

    up = client.post(
        "/api/quotations/MQ-UP-020/materials/0/invoice-files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    file_id = up.json()["files"][0]["id"]

    cr = _get_case_record(client, token, "MQ-UP-020")
    assert len(cr["materials"][0]["invoiceFiles"]) == 1
    # 一般附件（files）跟發票附件（invoiceFiles）互不影響，各自獨立
    assert cr["materials"][0].get("files", []) == []

    d = client.delete(f"/api/quotations/MQ-UP-020/materials/0/invoice-files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    cr2 = _get_case_record(client, token, "MQ-UP-020")
    assert len(cr2["materials"][0]["invoiceFiles"]) == 0
