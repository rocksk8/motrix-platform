"""案件動態留言與業務開發記錄的附件（DB v82，2026-09-14）。

使用者交辦「業務開發跟案件的動態都要有上傳照片或是檔案的功能」，並裁示了
四件事，這裡把其中三件會安靜壞掉的釘住（第四件「不限制張數與總量」沒有
需要守的行為）：

1. **API 是 multipart、一次送出**——不是「先存文字、再補傳檔案」。所以
   「檔案格式不合」必須讓整次請求失敗、留言不會被建立；半完成狀態是這個
   選擇要避免的東西，測到它才算真的有做到。
2. **刪附件限 admin+**，而刪整則留言／記錄仍是「本人或 admin+」。兩者權限
   刻意不同：抽掉附件是只改證據、留下文字。
3. **刪除要把實體檔案也清掉**。uploads/ 會被 archive.py::_mirror_uploads()
   增量同步進雲端備份而且只增不減——留下孤兒檔案等於永久佔用備份空間。
"""
import io
import json
import os

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _png_bytes():
    """最小的合法 PNG（1x1）。不用 Pillow 產生——測試環境不保證有裝，
    而 save_document_files() 在沒有 Pillow 時本來就會原樣存檔。"""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _seed_case(quote_no="MQ-ATT-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, status, "
            "deal_tag, total, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "測試客戶", "測試案件", "已送出", "已成案", 1000,
             json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    return quote_no


def _abs_path(rel):
    import helpers.uploads as up
    return os.path.join(up.UPLOADS_ROOT, rel)


# ── 案件動態 ──────────────────────────────────────────────────────────

def test_comment_with_photo_is_saved_and_returned(client, make_user):
    u, p = make_user(username="att_a", role="superadmin")
    token = _login(client, u, p)
    qno = _seed_case("MQ-ATT-A")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": "現場照片"},
                    files=[("files", ("site.png", _png_bytes(), "image/png"))])
    assert r.status_code == 201, r.text
    files = r.json()["files"]
    assert len(files) == 1
    assert files[0]["filename"] == "site.png"
    assert os.path.isfile(_abs_path(files[0]["path"])), "回傳了 path，實體檔案卻不在"

    # 讀回來也要帶得出附件——只有 POST 回傳、GET 不回傳的話，重新整理就不見了
    g = client.get(f"/api/quotations/{qno}/updates", headers=_auth(token))
    assert g.status_code == 200
    comment = next(x for x in g.json() if x["source"] == "comment")
    assert len(comment["files"]) == 1
    assert comment["files"][0]["id"] == files[0]["id"]


def test_file_only_comment_is_allowed(client, make_user):
    """只傳圖不打字是合理用法——附件自己就是內容。"""
    u, p = make_user(username="att_b", role="superadmin")
    token = _login(client, u, p)
    qno = _seed_case("MQ-ATT-B")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": ""},
                    files=[("files", ("x.png", _png_bytes(), "image/png"))])
    assert r.status_code == 201, r.text
    assert len(r.json()["files"]) == 1


def test_empty_comment_without_files_is_rejected(client, make_user):
    u, p = make_user(username="att_c", role="superadmin")
    token = _login(client, u, p)
    qno = _seed_case("MQ-ATT-C")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": "   "})
    assert r.status_code == 400, r.text


def test_bad_file_type_fails_the_whole_request(client, make_user):
    """multipart 的重點就是「一次成功或一次失敗」：格式不合時，留言不可以
    被建立。若這裡變成 201（留言建了、檔案沒上），就等於退回成當初刻意
    不選的那個半完成設計。"""
    u, p = make_user(username="att_d", role="superadmin")
    token = _login(client, u, p)
    qno = _seed_case("MQ-ATT-D")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": "帶了不支援的檔"},
                    files=[("files", ("evil.exe", b"MZ\x90\x00", "application/octet-stream"))])
    assert r.status_code == 400, r.text

    g = client.get(f"/api/quotations/{qno}/updates", headers=_auth(token))
    assert [x for x in g.json() if x["source"] == "comment"] == [], "檔案被擋下，留言卻還是建立了"


def test_only_admin_can_delete_an_attachment(client, make_user):
    u, p = make_user(username="att_e", role="superadmin")
    token = _login(client, u, p)
    normal, npw = make_user(username="att_e_user", role="sales", modules=["case_manage"])
    ntoken = _login(client, normal, npw)
    qno = _seed_case("MQ-ATT-E")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": "有附件"},
                    files=[("files", ("a.png", _png_bytes(), "image/png"))])
    uid = r.json()["id"]
    fid = r.json()["files"][0]["id"]
    path = _abs_path(r.json()["files"][0]["path"])

    bad = client.delete(f"/api/quotations/{qno}/updates/{uid}/files/{fid}", headers=_auth(ntoken))
    assert bad.status_code == 403, bad.text
    assert os.path.isfile(path), "403 了卻還是把檔案刪了"

    ok = client.delete(f"/api/quotations/{qno}/updates/{uid}/files/{fid}", headers=_auth(token))
    assert ok.status_code == 200, ok.text
    assert ok.json()["files"] == []
    assert not os.path.isfile(path), "資料庫紀錄刪了，實體檔案還留著"


def test_deleting_comment_removes_its_files_from_disk(client, make_user):
    """孤兒檔案會被 archive.py 的 uploads 鏡像一路帶進雲端備份，而且只增不減。"""
    u, p = make_user(username="att_f", role="superadmin")
    token = _login(client, u, p)
    qno = _seed_case("MQ-ATT-F")

    r = client.post(f"/api/quotations/{qno}/updates", headers=_auth(token),
                    data={"content": "待會刪掉"},
                    files=[("files", ("b.png", _png_bytes(), "image/png"))])
    uid = r.json()["id"]
    path = _abs_path(r.json()["files"][0]["path"])
    assert os.path.isfile(path)

    d = client.delete(f"/api/quotations/{qno}/updates/{uid}", headers=_auth(token))
    assert d.status_code == 200, d.text
    assert not os.path.isfile(path), "留言刪了，附件還留在磁碟上"


# ── 業務開發記錄 ──────────────────────────────────────────────────────

def _seed_dev_case(client, token, name="附件測試案"):
    r = client.post("/api/dev-cases", headers=_auth(token),
                    json={"case_name": name, "customer_name": "測試客戶"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_dev_log_with_photo_and_admin_only_delete(client, make_user):
    u, p = make_user(username="att_g", role="superadmin")
    token = _login(client, u, p)
    normal, npw = make_user(username="att_g_user", role="sales", modules=["dev_crm"])
    ntoken = _login(client, normal, npw)
    case_id = _seed_dev_case(client, token)

    import db
    conn = db.get_db()
    uid_row = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
    conn.close()

    r = client.post(f"/api/dev-cases/{case_id}/logs", headers=_auth(token),
                    data={"log_date": "2026-09-14", "log_by": uid_row["id"],
                          "channel": "面訪", "content": "帶了現場照"},
                    files=[("files", ("visit.png", _png_bytes(), "image/png"))])
    assert r.status_code == 201, r.text

    logs = client.get(f"/api/dev-cases/{case_id}/logs", headers=_auth(token)).json()
    assert len(logs) == 1
    assert len(logs[0]["files"]) == 1
    fid = logs[0]["files"][0]["id"]
    path = _abs_path(logs[0]["files"][0]["path"])
    assert os.path.isfile(path)

    log_id = logs[0]["id"]
    bad = client.delete(f"/api/dev-logs/{log_id}/files/{fid}", headers=_auth(ntoken))
    assert bad.status_code == 403, bad.text
    assert os.path.isfile(path)

    ok = client.delete(f"/api/dev-logs/{log_id}/files/{fid}", headers=_auth(token))
    assert ok.status_code == 200, ok.text
    assert not os.path.isfile(path)


def test_dev_log_without_files_still_works(client, make_user):
    """沒有附件的既有用法不可以壞掉——這支端點是從 JSON body 改成 Form 的。"""
    u, p = make_user(username="att_h", role="superadmin")
    token = _login(client, u, p)
    case_id = _seed_dev_case(client, token, "無附件案")

    import db
    conn = db.get_db()
    uid_row = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()
    conn.close()

    r = client.post(f"/api/dev-cases/{case_id}/logs", headers=_auth(token),
                    data={"log_date": "2026-09-14", "log_by": uid_row["id"],
                          "channel": "電話", "content": "純文字"})
    assert r.status_code == 201, r.text
    logs = client.get(f"/api/dev-cases/{case_id}/logs", headers=_auth(token)).json()
    assert logs[0]["files"] == []
    assert logs[0]["content"] == "純文字"
