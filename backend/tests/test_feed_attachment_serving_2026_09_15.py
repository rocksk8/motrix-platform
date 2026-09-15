"""附件「傳完之後真的讀得回來嗎」（2026-09-15）。

起因：動態附件／業務開發記錄附件（DB v82，2026-09-14 上線）**從上線起每一張
都是 403**——前端把 session token 當成 `?pt=` 送給 `/api/uploads/`，而 `pt` 是
`routers/uploads.py` 用 HMAC 簽出來的短效簽章（`{expires}.{sig}`，要先跟
`/api/photo-token` 換）。兩者形狀不同，`_verify_photo_token()` 一 split 就對不上。
使用者看到的是圖片破圖、PDF 點開跳出一段 JSON 錯誤。

**為什麼整套測試沒擋下來**：既有的 `test_feed_attachments_2026_09_14.py` 只驗到
「POST 回傳了 path 且該路徑的實體檔案存在」，沒有任何一題走過讀取端點。而且就算
有人想寫，當時也寫不出來——`conftest.py` 只把 `helpers/uploads.py`（存檔）的
UPLOADS_ROOT 導到 tmp，`routers/uploads.py`（讀檔）那份沒導，讀回來一定 404。
那個缺口已在同一次修復補上。

所以這裡的觀測點刻意放在**回應內容**：位元組要跟上傳的一模一樣。只斷言 200 的話，
端點回一張空檔案也會綠。
"""
import pytest


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def dev_log_attachment(client, make_user):
    """建一則帶附件的業務開發記錄，回傳 (token, 附件 metadata)。"""
    u, p = make_user(username="att_serve", role="superadmin")
    token = _login(client, u, p)

    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    conn.close()

    case_id = client.post("/api/dev-cases", headers=_auth(token),
                          json={"case_name": "附件讀取測試"}).json()["id"]
    r = client.post(f"/api/dev-cases/{case_id}/logs", headers=_auth(token),
                    data={"log_date": "2026-09-15", "log_by": uid, "content": "現場照"},
                    files=[("files", ("site.png", _png_bytes(), "image/png"))])
    assert r.status_code == 201, r.text
    return token, r.json()["files"][0]


def test_attachment_is_actually_readable_back(client, dev_log_attachment):
    """走完整條路：換 pt → 讀檔，回來的要是磁碟上那個檔本身。

    **觀測點不能拿「上傳的原始位元組」來比**：圖片會先過
    `photos.py::_process_project_photo()` 壓浮水印，出來是重新編碼過的 JPEG
    （連副檔名都還是 .png，見下一題）。拿原始位元組比會紅在浮水印上，不是紅在
    讀取路徑上。改比磁碟上的實體檔——只有「端點真的解析到正確的檔案並讀出來」
    才會相符，端點回空 body 或回錯檔案都會紅。
    """
    token, f = dev_log_attachment

    t = client.get(f"/api/photo-token?path={f['path']}", headers=_auth(token))
    assert t.status_code == 200, t.text
    pt = t.json()["token"]

    r = client.get(f"/api/uploads/{f['path']}?pt={pt}")
    assert r.status_code == 200, r.text

    import os
    import helpers.uploads as uploads_helper
    on_disk = open(os.path.join(uploads_helper.UPLOADS_ROOT, f["path"]), "rb").read()
    assert len(on_disk) > 0
    assert r.content == on_disk, "讀回來的位元組跟磁碟上的實體檔不一致"


def test_session_token_is_not_a_photo_token(client, dev_log_attachment):
    """pt 與 session token 是兩種東西——把 session token 當 pt 送必須被擋下。

    這正是 2026-09-14 前端犯的錯。**這一題不是在守後端**（後端行為是對的），
    是把「這兩個 token 不能互相代用」釘成白紙黑字：日後有人想「反正手上就有
    token，直接塞進去」時，這裡會告訴他那條路是死的，要走 /api/photo-token。
    """
    token, f = dev_log_attachment
    r = client.get(f"/api/uploads/{f['path']}?pt={token}")
    assert r.status_code == 403, r.text


def test_attachment_needs_some_credential(client, dev_log_attachment):
    """沒 pt 也沒 Bearer → 401，附件不是公開連結。"""
    token, f = dev_log_attachment
    assert client.get(f"/api/uploads/{f['path']}").status_code == 401
