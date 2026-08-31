"""API-level integration tests for settlement 額外支出 (extraItems) 發票/收據附件
上傳（比照 test_payment_item_and_material_uploads.py 的 _load_payment_item()/
_load_material_item() 模式，這裡是 routers/quotations.py 的
_load_settlement_extra_item() + /settlement/extra/{idx}/files 端點）。"""
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


def _make_quotation(quote_no, extra_items=None, settlement_status="draft"):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "settlement": {
                "status": settlement_status,
                "extraItems": extra_items if extra_items is not None else [
                    {"id": 1, "category": "工時", "description": "測試", "totalCost": 1000},
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


def _get_settlement(client, token, quote_no):
    r = client.get(f"/api/quotations/{quote_no}/settlement", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["settlement"]


def test_settlement_extra_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SEX-001")

    up = client.post(
        "/api/quotations/MQ-SEX-001/settlement/extra/0/files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["added"] == 1
    file_id = body["files"][0]["id"]

    stl = _get_settlement(client, token, "MQ-SEX-001")
    assert len(stl["extraItems"][0]["files"]) == 1

    d = client.delete(
        f"/api/quotations/MQ-SEX-001/settlement/extra/0/files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    stl2 = _get_settlement(client, token, "MQ-SEX-001")
    assert len(stl2["extraItems"][0]["files"]) == 0


def test_settlement_extra_file_upload_rejects_out_of_range_index(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SEX-002")

    r = client.post(
        "/api/quotations/MQ-SEX-002/settlement/extra/5/files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert r.status_code == 400, r.text


def test_settlement_extra_file_upload_blocked_after_finalized(client, make_user):
    """精算已完結後，額外支出附件上傳一律擋下（比照 update_settlement() 的
    完結後鎖定規則，不比照該端點放寬 superadmin 例外——見 _load_settlement_
    extra_item() docstring 的取捨說明）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SEX-003", settlement_status="finalized")

    r = client.post(
        "/api/quotations/MQ-SEX-003/settlement/extra/0/files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert r.status_code == 403, r.text


def test_settlement_extra_file_upload_multi_file(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-SEX-004")

    up = client.post(
        "/api/quotations/MQ-SEX-004/settlement/extra/0/files", headers=_auth(token),
        files=[("files", _png_file("a.png")), ("files", _png_file("b.png"))],
    )
    assert up.status_code == 201, up.text
    assert up.json()["added"] == 2
    stl = _get_settlement(client, token, "MQ-SEX-004")
    assert len(stl["extraItems"][0]["files"]) == 2
