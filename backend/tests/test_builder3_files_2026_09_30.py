# -*- coding: utf-8 -*-
"""建構器第三輪 S2（2026-09-30）：附件欄（file／image）——先傳後綁單、副檔名白名單子集、讀檔權限（uploads.path_access／IP-104）、
從單據拿掉即刪檔、欄位可見設定也擋讀檔、暫存檔只有上傳者讀得到。"""
import os

import pytest

KEY = "b3files"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PDF = b"%PDF-1.4\n" + b"0" * 32


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _body(**over):
    b = {"name": "附件測試", "permission": "custom." + KEY, "numbering": {"prefix": "FL", "period": "none", "digits": 3},
         "fields": [{"key": "title", "label": "標題", "type": "text", "required": True, "dataClass": "T1"},
                    {"key": "pics", "label": "照片", "type": "image", "maxFiles": 2, "dataClass": "T1"},
                    {"key": "doc", "label": "文件", "type": "file", "accept": ["pdf"], "dataClass": "T1"}],
         "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                      "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}
    b.update(over)
    return b


def _publish(client, h, body, key=KEY):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body}).json()
    if r["problems"]:
        return r["problems"]
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200
    return []


def _up(client, h, field, name, data, key=KEY):
    return client.post("/api/custom/%s/files/%s" % (key, field), headers=h, files=[("files", (name, data))])


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _exists(path):
    from helpers import uploads
    return os.path.isfile(os.path.join(uploads.UPLOADS_ROOT, path))


@pytest.fixture()
def world(client, make_user):
    hb = _login(client, make_user, "b3f_boss", role="superadmin")
    hs = _login(client, make_user, "b3f_staff", modules=["custom." + KEY])
    ho = _login(client, make_user, "b3f_other", modules=[])
    assert _publish(client, hb, _body()) == []
    return client, hb, hs, ho


def test_upload_stages_then_save_binds_and_view_lists_meta(world):
    client, hb, hs, ho = world
    up = _up(client, hs, "pics", "a.png", PNG)
    assert up.status_code == 200, up.text
    m = up.json()[0]
    assert m["filename"] == "a.png" and m["path"].startswith("custom_records/%s/" % KEY) and _exists(m["path"])
    assert _rows("SELECT record_id, uploaded_by FROM custom_record_files WHERE id=?", (m["id"],))[0]["record_id"] == 0
    r = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "pics": [m["id"]]}})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["data"]["pics"] == [m["id"]] and rec["fileMeta"]["pics"][0]["filename"] == "a.png"
    assert rec["view"]["fields"]["pics"] == ["a.png"]                         # 輸出只放檔名
    assert _rows("SELECT record_id FROM custom_record_files WHERE id=?", (m["id"],))[0]["record_id"] == rec["id"]
    out = client.get("/api/custom/%s/records/%s/output" % (KEY, rec["record_no"]), headers=hs)
    assert out.status_code == 200 and "a.png" in out.text


def test_extension_rules_are_field_accept_intersect_whitelist(world):
    client, hb, hs, ho = world
    assert _up(client, hs, "pics", "x.pdf", PDF).status_code == 400          # image 欄不收 pdf
    assert _up(client, hs, "doc", "x.png", PNG).status_code == 400            # doc 欄 accept 只有 pdf
    assert _up(client, hs, "doc", "x.pdf", PDF).status_code == 200
    assert _up(client, hs, "pics", "x.exe", b"MZ").status_code == 400
    assert _up(client, hs, "nofield", "x.png", PNG).status_code == 404
    # 定義驗證：accept 只能是白名單子集（反向控制：exe 不可）
    bad = _body()
    bad["fields"][2]["accept"] = ["pdf", "exe"]
    assert any("不允許的副檔名" in p["message"] for p in _publish(client, hb, bad, key="b3files2"))
    bad2 = _body()
    bad2["fields"][1]["maxFiles"] = 0
    assert any("最多檔數" in p["message"] for p in _publish(client, hb, bad2, key="b3files3"))


def test_read_access_staged_only_uploader_bound_needs_module_permission(world):
    client, hb, hs, ho = world
    m = _up(client, hs, "pics", "a.png", PNG).json()[0]

    def tok(h):
        return client.get("/api/photo-token", params={"path": m["path"]}, headers=h).status_code
    assert tok(hs) == 200                                                      # 上傳者
    assert tok(ho) in (403, 404)                                               # 暫存檔別人（沒權限）讀不到
    client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "pics": [m["id"]]}})
    assert tok(hs) == 200 and tok(hb) == 200                                   # 綁單後：有模組權限者＋超管
    assert tok(ho) in (403, 404)                                               # 沒有模組權限 ⇒ 擋


def test_someone_elses_staged_file_cannot_be_attached(world):
    client, hb, hs, ho = world
    m = _up(client, hs, "pics", "a.png", PNG).json()[0]
    r = client.post("/api/custom/%s/records" % KEY, headers=hb, json={"values": {"title": "T", "pics": [m["id"]]}})
    assert r.status_code >= 400 and "找不到這個檔案" in r.text
    r2 = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "doc": [m["id"]]}})   # 錯的欄位
    assert r2.status_code >= 400
    assert _exists(m["path"]) and _rows("SELECT record_id FROM custom_record_files WHERE id=?", (m["id"],))[0]["record_id"] == 0


def test_removing_from_the_draft_deletes_row_and_file_and_max_files_enforced(world):
    client, hb, hs, ho = world
    a = _up(client, hs, "pics", "a.png", PNG).json()[0]
    b = _up(client, hs, "pics", "b.png", PNG).json()[0]
    c = _up(client, hs, "pics", "c.png", PNG).json()[0]
    r = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "pics": [a["id"], b["id"], c["id"]]}})
    assert r.status_code >= 400 and "最多 2 個檔案" in r.text
    rec = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "pics": [a["id"], b["id"]]}}).json()
    upd = client.put("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=hs, json={"values": {"title": "T", "pics": [b["id"]]}})
    assert upd.status_code == 200 and upd.json()["data"]["pics"] == [b["id"]]
    assert not _rows("SELECT 1 FROM custom_record_files WHERE id=?", (a["id"],)) and not _exists(a["path"])
    assert _exists(b["path"])
    # 送出後內容凍結 ⇒ 不能再改附件（要改開修訂版）
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, rec["record_no"]), headers=hs, json={}).status_code == 200
    assert client.put("/api/custom/%s/records/%s" % (KEY, rec["record_no"]), headers=hs, json={"values": {"title": "T", "pics": []}}).status_code == 409
    assert _exists(b["path"])


def test_staged_delete_only_own_unbound(world):
    client, hb, hs, ho = world
    m = _up(client, hs, "pics", "a.png", PNG).json()[0]
    assert client.delete("/api/custom/%s/files/%s" % (KEY, m["id"]), headers=hb).status_code == 404       # 別人的
    assert client.delete("/api/custom/%s/files/%s" % (KEY, m["id"]), headers=hs).status_code == 200
    assert not _exists(m["path"]) and not _rows("SELECT 1 FROM custom_record_files WHERE id=?", (m["id"],))
    m2 = _up(client, hs, "pics", "b.png", PNG).json()[0]
    client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "pics": [m2["id"]]}})
    assert client.delete("/api/custom/%s/files/%s" % (KEY, m2["id"]), headers=hs).status_code == 404      # 已綁單


def test_stale_staged_files_are_purged_on_next_upload(world):
    client, hb, hs, ho = world
    m = _up(client, hs, "pics", "old.png", PNG).json()[0]
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE custom_record_files SET uploaded_at='2020-01-01T00:00:00' WHERE id=?", (m["id"],))
        c.commit()
    finally:
        c.close()
    _up(client, hs, "pics", "new.png", PNG)
    assert not _rows("SELECT 1 FROM custom_record_files WHERE id=?", (m["id"],)) and not _exists(m["path"])


def test_field_visibility_also_blocks_upload_and_read(client, make_user):
    hb = _login(client, make_user, "b3f_boss", role="superadmin")
    hs = _login(client, make_user, "b3f_staff", modules=["custom." + KEY])
    b = _body()
    b["fields"][2]["access"] = {"visibleTo": {"users": ["b3f_boss"]}}
    assert _publish(client, hb, b) == []
    assert _up(client, hs, "doc", "x.pdf", PDF).status_code == 403             # 看不到的欄位不能上傳
    m = _up(client, hb, "doc", "x.pdf", PDF).json()[0]
    no = client.post("/api/custom/%s/records" % KEY, headers=hb, json={"values": {"title": "T", "doc": [m["id"]]}}).json()["record_no"]
    assert client.get("/api/photo-token", params={"path": m["path"]}, headers=hb).status_code == 200
    assert client.get("/api/photo-token", params={"path": m["path"]}, headers=hs).status_code in (403, 404)
    rec = client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hs).json()
    assert "doc" not in rec["data"] and "doc" not in rec["fileMeta"]


def test_provider_is_registered_for_the_folder(client):
    from core import registry
    from helpers import uploads
    claimed = {f for p in registry.providers(uploads.PATH_ACCESS).values() for f in (getattr(p, "FOLDERS", ()) or ())}
    assert "custom_records" in claimed
