"""P0 安全修正（2026-09-30）：出貨單單筆讀取／回簽上傳守門，與出貨單回簽檔的上傳檔讀取權限（IP-104）。

修正前 `GET /api/shipping-notes/{no}` 與 `POST /api/shipping-notes/{no}/signed-files` 只要求登入（單號可列舉 ⇒ IDOR），
`/api/photo-token` 對 `shipping_notes/<單號>/<檔名>` 也是任何登入者都簽。
修正後：規則＝出貨單清單帶 quote_no 那一條（業務本人／協作者、admin+、case_manage）；看不到＝查無（同一句 404、不帶案件單號）。
"""
import json
import os

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "出貨單的讀取規則是案件層（guard_case_access）；M01 不在時一律 404，沒有「看得到」的對照")

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
Q = "MQ-P0S-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


@pytest.fixture
def world(client, make_user):
    import db
    users = {}
    for name, role, mods in (("s0_admin", "admin", None), ("s0_owner", "sales", []),
                             ("s0_out", "sales", ["quotation", "work_log"]), ("s0_cm", "sales", ["case_manage"])):
        u, p = make_user(username=name, role=role, modules=mods)
        users[name] = _login(client, u, p)
    c = db.get_db()
    try:
        oid = c.execute("SELECT id FROM users WHERE username='s0_owner'").fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                  "created_at, updated_at, deal_tag, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (Q, "已送出", "客戶", "工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
                   "2026-01-01T00:00:00", "已成案", oid, "s0_owner"))
        c.commit()
    finally:
        c.close()
    r = client.post("/api/shipping-notes", headers=_h(users["s0_admin"]), json={"quote_no": Q, "items": []})
    assert r.status_code == 201, r.text
    body = r.json()
    return users, body.get("noteNo") or body.get("note_no")


def _upload(client, t, note_no):
    return client.post(f"/api/shipping-notes/{note_no}/signed-files", headers=_h(t),
                       files=[("files", ("sign.png", PNG, "image/png"))])


def test_shipping_get_owner_and_case_manage_ok(client, world):
    users, no = world
    for who in ("s0_owner", "s0_cm", "s0_admin"):
        assert client.get(f"/api/shipping-notes/{no}", headers=_h(users[who])).status_code == 200, who


def test_shipping_get_outsider_same_404_as_missing(client, world):
    users, no = world
    denied = client.get(f"/api/shipping-notes/{no}", headers=_h(users["s0_out"]))
    missing = client.get("/api/shipping-notes/SN-NOPE-1", headers=_h(users["s0_out"]))
    assert denied.status_code == 404 and missing.status_code == 404
    assert denied.json()["detail"] == f"出貨單 {no} 不存在"
    assert missing.json()["detail"] == "出貨單 SN-NOPE-1 不存在"
    assert Q not in denied.text


def test_shipping_signed_upload_outsider_404_nothing_written(client, world):
    import helpers.uploads as up
    users, no = world
    r = _upload(client, users["s0_out"], no)
    assert r.status_code == 404, r.text
    assert not os.path.isdir(os.path.join(up.UPLOADS_ROOT, "shipping_notes", no))
    assert _upload(client, users["s0_owner"], no).status_code == 201


def test_shipping_file_photo_token_and_header(client, world):
    users, no = world
    path = _upload(client, users["s0_owner"], no).json()["files"][0]["path"]
    ok = client.get("/api/photo-token", headers=_h(users["s0_owner"]), params={"path": path})
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/uploads/{path}", params={"pt": ok.json()["token"]}).status_code == 200
    assert client.get("/api/photo-token", headers=_h(users["s0_cm"]), params={"path": path}).status_code == 200
    bad = client.get("/api/photo-token", headers=_h(users["s0_out"]), params={"path": path})
    assert bad.status_code == 404, bad.text
    assert client.get(f"/api/uploads/{path}", headers=_h(users["s0_out"])).status_code == 404
