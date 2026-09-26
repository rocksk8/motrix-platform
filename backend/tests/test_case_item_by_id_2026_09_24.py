"""款項期別／料件的單筆端點改以項目 id 定位（CM2，2026-09-24）。

過去 payment/{idx}、materials/{idx} 的附件上傳刪除與沖銷只看陣列位置 ⇒ 畫面載入後有人刪除或
重排，同一個 idx 指到別的列，發票掛到別期、沖銷打到別期。呼叫端帶 ?itemId= 時以 id 找列；
找不到（尚未存檔或已被刪除）⇒ 409，不寫入。不帶 itemId 維持舊行為（早期沒有 id 的資料）。
半解鎖排進審核的變更也記 itemId，核准時以 id 套用。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-BYID-001"
PDF = ("a.pdf", b"%PDF-1.4 fake", "application/pdf")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(deal_tag="已成案"):
    import db
    cr = {"payment": {"items": [{"id": 101, "type": "訂金款", "pct": 30, "received": False},
                                {"id": 102, "type": "尾款", "pct": 70, "received": False}]},
          "materials": [{"id": 201, "name": "甲", "files": [], "invoiceFiles": []},
                        {"id": 202, "name": "乙", "files": [], "invoiceFiles": []}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100000, 95238,
             json.dumps({"dealTag": deal_tag, "caseRecord": cr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag))
        if deal_tag == "已結案":
            now = "2026-01-01T00:00:00"
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?,?)", (NO, "階段一", 0, 1, now, now, now))
        conn.commit()
    finally:
        conn.close()


def _cr():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]


def _by_id(arr, i):
    return next(x for x in arr if x.get("id") == i)


def test_payment_invoice_upload_lands_on_item_by_id(client, make_user):
    h = _login(client, *make_user(username="byid1", role="admin"))
    _seed()
    # 畫面上它在第 0 列，但伺服器上已被重排到第 1 列
    r = client.post(f"/api/quotations/{NO}/payment/0/invoice-files?itemId=102", headers=h, files={"files": PDF})
    assert r.status_code == 201, r.text
    items = _cr()["payment"]["items"]
    assert len(_by_id(items, 102).get("invoiceFiles") or []) == 1
    assert not _by_id(items, 101).get("invoiceFiles")


def test_payment_invoice_delete_by_id(client, make_user):
    h = _login(client, *make_user(username="byid2", role="admin"))
    _seed()
    fid = client.post(f"/api/quotations/{NO}/payment/1/invoice-files?itemId=102", headers=h,
                      files={"files": PDF}).json()["files"][0]["id"]
    r = client.delete(f"/api/quotations/{NO}/payment/0/invoice-files/{fid}?itemId=102", headers=h)
    assert r.status_code == 200, r.text
    assert not _by_id(_cr()["payment"]["items"], 102).get("invoiceFiles")


def test_unknown_item_id_is_409_and_nothing_written(client, make_user):
    h = _login(client, *make_user(username="byid3", role="admin"))
    _seed()
    before = _cr()
    for url in (f"/api/quotations/{NO}/payment/0/invoice-files?itemId=999",
                f"/api/quotations/{NO}/materials/0/files?itemId=999",
                f"/api/quotations/{NO}/materials/0/invoice-files?itemId=999"):
        r = client.post(url, headers=h, files={"files": PDF})
        assert r.status_code == 409, (url, r.text)
        assert "存檔" in r.json()["detail"]
    assert _cr() == before


def test_material_files_and_invoice_files_land_by_id(client, make_user):
    h = _login(client, *make_user(username="byid4", role="admin"))
    _seed()
    assert client.post(f"/api/quotations/{NO}/materials/0/files?itemId=202", headers=h,
                       files={"files": PDF}).status_code == 201
    assert client.post(f"/api/quotations/{NO}/materials/0/invoice-files?itemId=202", headers=h,
                       files={"files": PDF}).status_code == 201
    mats = _cr()["materials"]
    b = _by_id(mats, 202)
    assert len(b["files"]) == 1 and len(b["invoiceFiles"]) == 1
    assert _by_id(mats, 201)["files"] == [] and _by_id(mats, 201)["invoiceFiles"] == []
    fid = b["files"][0]["id"]
    assert client.delete(f"/api/quotations/{NO}/materials/0/files/{fid}?itemId=202", headers=h).status_code == 200
    iid = b["invoiceFiles"][0]["id"]
    assert client.delete(f"/api/quotations/{NO}/materials/0/invoice-files/{iid}?itemId=202",
                         headers=h).status_code == 200
    b = _by_id(_cr()["materials"], 202)
    assert b["files"] == [] and b["invoiceFiles"] == []


def test_writeoff_request_cancel_approve_by_id(client, make_user):
    h = _login(client, *make_user(username="byid5", role="admin"))
    sa = _login(client, *make_user(username="byid5sa", role="superadmin"))
    _seed()
    r = client.post(f"/api/quotations/{NO}/payment/0/request-writeoff?itemId=102", headers=h, json={"reason": "r"})
    assert r.status_code == 200, r.text
    items = _cr()["payment"]["items"]
    assert _by_id(items, 102).get("writeOffStatus") == "pending"
    assert not _by_id(items, 101).get("writeOffStatus")
    r = client.post(f"/api/quotations/{NO}/payment/0/cancel-writeoff?itemId=102", headers=h)
    assert r.status_code == 200, r.text
    assert not _by_id(_cr()["payment"]["items"], 102).get("writeOffStatus")
    client.post(f"/api/quotations/{NO}/payment/1/request-writeoff?itemId=102", headers=h, json={"reason": "r"})
    r = client.post(f"/api/quotations/{NO}/payment/0/approve-writeoff?itemId=102", headers=sa, json={"approve": True})
    assert r.status_code == 200, r.text
    items = _cr()["payment"]["items"]
    assert _by_id(items, 102).get("taxExempt") is True
    assert not _by_id(items, 101).get("taxExempt")


def test_legacy_idx_without_item_id_still_works(client, make_user):
    h = _login(client, *make_user(username="byid6", role="admin"))
    _seed()
    r = client.post(f"/api/quotations/{NO}/materials/1/files", headers=h, files={"files": PDF})
    assert r.status_code == 201, r.text
    assert len(_by_id(_cr()["materials"], 202)["files"]) == 1


def test_semi_unlocked_upload_applies_to_item_by_id_after_reorder(client, make_user):
    h = _login(client, *make_user(username="byid7", role="admin"))
    sa = _login(client, *make_user(username="byid7sa", role="superadmin"))
    _seed("已結案")
    assert client.post(f"/api/quotations/{NO}/case-unlock", headers=h).status_code == 200
    r = client.post(f"/api/quotations/{NO}/materials/1/files?itemId=202", headers=h, files={"files": PDF})
    assert r.status_code == 201, r.text
    change_id = r.json()["changeRequestId"]
    # 審核前有人把料件順序對調
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
        d["caseRecord"]["materials"].reverse()
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()
    r = client.post(f"/api/case-changes/{change_id}/approve", headers=sa)
    assert r.status_code == 200, r.text
    mats = _cr()["materials"]
    assert len(_by_id(mats, 202)["files"]) == 1
    assert _by_id(mats, 201)["files"] == []
