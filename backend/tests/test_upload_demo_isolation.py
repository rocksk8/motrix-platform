"""Confirms helpers/uploads.py::save_document_files() redirects the 'demo'
showcase account's uploads into the isolated _demo_uploads/ subfolder instead
of leaking into real permanent storage — matching the existing photos.py
DEMO_PROJECT_PHOTOS_DIR pattern (see db.py's is_demo_mode()/reset_demo_db()
docstring). This gap was found and fixed 2026-08-24: save_document_files()
originally had no demo-mode awareness at all."""
import io
import json
import os


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_demo_password(password="60575481"):
    """`IA2` 之後 `init_demo_account()` 產生的是**隨機密碼**，不再是這裡
    沿用的舊字面值——直接把 `demo` 這一列的 `password_hash` 改成已知值，
    同 `make_user()` fixture 那條「不依賴隨機密碼寫檔那條路」的理由。"""
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = 'demo'",
                    (_hash_pw(password),))
        conn.commit()
    finally:
        conn.close()


def _png_file(name="test.png"):
    data = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155a5e6ce0000000049454e44ae42"
        "6082"
    )
    return (name, io.BytesIO(data), "image/png")


def _make_quotation_in_demo_db():
    """Insert a quotation directly into the demo DB file (bypassing the
    request-scoped is_demo_mode() context, which only applies during an
    actual HTTP request handled by the auth middleware)."""
    import db
    conn = db.get_demo_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-DEMO-001", "已送出", "Demo客戶", "Demo專案", json.dumps({}),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def test_demo_account_signed_file_upload_is_isolated(client):
    import db
    import helpers.uploads as uploads_helper

    _set_demo_password()
    demo_token = _login(client, "demo", "60575481")
    _make_quotation_in_demo_db()

    up = client.post(
        "/api/quotations/MQ-DEMO-001/signed-files", headers=_auth(demo_token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    saved_path = up.json()["files"][0]["path"]

    # 1. Stored path must carry the demo-isolation prefix
    assert saved_path.startswith("_demo_uploads/"), saved_path

    # 2. The file must physically exist under the demo-isolated subfolder...
    demo_full_path = os.path.join(uploads_helper.UPLOADS_ROOT, saved_path)
    assert os.path.isfile(demo_full_path), f"expected file at {demo_full_path}"

    # 3. ...and NOT under the real (non-demo) quotations/ folder a real user's
    # upload would use.
    leaked_path = os.path.join(uploads_helper.UPLOADS_ROOT, "quotations", "MQ-DEMO-001")
    assert not os.path.isdir(leaked_path), f"demo upload leaked into real storage: {leaked_path}"

    # 4. The isolation subfolder name must match what db.reset_demo_db() wipes
    # on every demo login (db.DEMO_UPLOADS_DIR's basename), so a fresh demo
    # session never sees a previous session's leftover uploads.
    assert saved_path.split("/")[0] == os.path.basename(db.DEMO_UPLOADS_DIR)
