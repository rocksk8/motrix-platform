"""API-level integration tests for contractor dispatch quote-document uploads
(files_json column added 2026-08-25 migration v60, see
routers/vendor_contractors.py upload_dispatch_files()/delete_dispatch_file())."""
import io


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


def _make_dispatch(client, token, quote_no="MQ-DISP-001"):
    r = client.post(
        "/api/contractor-dispatches", headers=_auth(token),
        json={"quote_no": quote_no, "personnel_json": [{"id": "p1", "name": "測試點工", "amount": 1000}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_dispatch_file_upload_and_delete(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    did = _make_dispatch(client, token)

    up = client.post(
        f"/api/contractor-dispatches/{did}/files", headers=_auth(token),
        files={"files": _png_file()},
    )
    assert up.status_code == 201, up.text
    assert up.json()["added"] == 1
    file_id = up.json()["files"][0]["id"]

    r = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert len(r.json()["files"]) == 1

    d = client.delete(f"/api/contractor-dispatches/{did}/files/{file_id}", headers=_auth(token))
    assert d.status_code == 200, d.text
    r2 = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert len(r2.json()["files"]) == 0


def test_dispatch_file_upload_multi_file(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    did = _make_dispatch(client, token, "MQ-DISP-002")

    up = client.post(
        f"/api/contractor-dispatches/{did}/files", headers=_auth(token),
        files=[("files", _png_file("a.png")), ("files", _png_file("b.png"))],
    )
    assert up.status_code == 201, up.text
    assert up.json()["added"] == 2
    r = client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token))
    assert len(r.json()["files"]) == 2


def test_dispatch_file_upload_requires_admin(client, make_user):
    admin_username, admin_password = make_user(username="disp_admin", role="superadmin")
    admin_token = _login(client, admin_username, admin_password)
    did = _make_dispatch(client, admin_token, "MQ-DISP-003")

    viewer_username, viewer_password = make_user(username="disp_viewer", role="viewer", modules=[])
    viewer_token = _login(client, viewer_username, viewer_password)

    up = client.post(
        f"/api/contractor-dispatches/{did}/files", headers=_auth(viewer_token),
        files={"files": _png_file()},
    )
    assert up.status_code == 403, up.text
