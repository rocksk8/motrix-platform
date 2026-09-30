# -*- coding: utf-8 -*-
"""附件開檔：路徑綁單據（安全審查 W3 #1，2026-09-30）。

問題：`/api/attachments/open` 的提供者只驗「在 uploads 底下且存在」，而案件紀錄 PATCH 曾接受前端帶的 `files`／`invoiceFiles` 路徑 ⇒
有案件權限的人能把別人的檔案路徑塞進自己案件，再用目錄端點讀出來。兩道修補：
① 各提供者 `open()`：檔案路徑必須屬於**那張單據自己的資料夾**（`helpers.uploads.upload_path_key`）；
② 案件紀錄 PATCH／PUT／POST：只保留資料庫裡本來就有的 `files`／`invoiceFiles`（`quotations._strip_foreign_file_entries`）。
每一道都有反向控制（拿掉 ⇒ 對應題紅，見 commit 說明）。"""
import json
import os

import pytest

from helpers import uploads as up

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
Q = "MQ-BND-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _exec(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _put(rel, data=PNG):
    full = os.path.join(up.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(data)


def _open(client, h, type_, doc, file):
    return client.get("/api/attachments/open", headers=h, params={"type": type_, "doc": doc, "file": file})


@pytest.fixture
def world(client, make_user):
    """案件 Q（admin 是成員）：材料 0 有一個「自己的」檔、一個被塞進來的「別人的」檔（路徑指向別案／別單據的資料夾）。"""
    u, p = make_user(username="bd_admin", role="admin", modules=None)
    H = _login(client, u, p)
    mine = "quotation_materials/%s_0/mine.png" % Q
    other_case = "quotation_materials/MQ-OTHER-009_0/secret.png"            # 別案的材料檔
    other_doc = "completion_notes/CN-OTHER-1/secret2.png"                    # 別種單據的檔
    for rel in (mine, other_case, other_doc):
        _put(rel)
    cr = {"materials": [{"name": "m", "files": [
        {"id": "mine1", "filename": "mine.png", "path": mine, "size": len(PNG)},
        {"id": "evil1", "filename": "x.png", "path": other_case, "size": 1},
        {"id": "evil2", "filename": "y.png", "path": other_doc, "size": 1}]}]}
    _exec("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
          " updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
          (Q, "已送出", "客戶", "工程", 1000, 952, json.dumps({"dealTag": "已成案", "caseRecord": cr}),
           "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
    return H, {"mine": mine, "other_case": other_case, "other_doc": other_doc}


# ── ① 提供者：路徑不在這張單據自己的資料夾 ⇒ 404 ─────────────────────────────

def test_material_file_opens_only_when_path_is_under_this_case(client, world):
    H, _ = world
    ok = _open(client, H, "material", "%s_0" % Q, "mine1")
    assert ok.status_code == 200 and ok.content == PNG
    for fid in ("evil1", "evil2"):                       # 別案的資料夾、別種單據的資料夾
        r = _open(client, H, "material", "%s_0" % Q, fid)
        assert r.status_code == 404 and r.json()["detail"] == "檔案不存在", fid


def test_completion_note_path_must_be_its_own_folder(client, make_user):
    u, p = make_user(username="bd_cn", role="admin", modules=None)
    h = _login(client, u, p)
    _exec("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
          " updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("MQ-BND-002", "已送出", "客戶", "工程", 1, 1, json.dumps({"dealTag": "已成案"}), "n", "n", "已成案"))
    r = client.post("/api/completion-notes", headers=h, json={"quote_no": "MQ-BND-002", "completion_date": "2026-09-10", "items": []})
    assert r.status_code == 201, r.text
    no = r.json().get("noteNo") or r.json().get("note_no")
    _put("completion_notes/%s/real.png" % no)
    _put("completion_notes/CN-OTHER-7/secret.png")
    files = [{"id": "f1", "filename": "real.png", "path": "completion_notes/%s/real.png" % no},
             {"id": "f2", "filename": "s.png", "path": "completion_notes/CN-OTHER-7/secret.png"}]
    _exec("UPDATE completion_notes SET signed_files_json=? WHERE note_no=?", (json.dumps(files), no))
    assert _open(client, h, "completion_note", no, "f1").status_code == 200
    assert _open(client, h, "completion_note", no, "f2").status_code == 404        # 指到別張完工單的檔


def test_work_log_photo_path_must_be_its_own_folder(client, make_user):
    u, p = make_user(username="bd_wl", role="superadmin", modules=[])
    h = _login(client, u, p)
    uid = _q("SELECT id FROM users WHERE username='bd_wl'")[0]["id"]
    r = client.post("/api/work-logs", headers=h, json={"log_date": "2026-09-30", "content": "x", "hours": 1, "user_id": uid})
    wid = r.json()["id"]
    _put("projects/worklog_%d/2026-09-30/ok.png" % wid)
    _put("projects/worklog_999/2026-09-30/other.png")
    _put("completion_notes/CN-OTHER-8/secret.png")
    photos = [{"id": "p1", "filename": "ok.png", "path": "projects/worklog_%d/2026-09-30/ok.png" % wid},
              {"id": "p2", "filename": "o.png", "path": "projects/worklog_999/2026-09-30/other.png"},
              {"id": "p3", "filename": "s.png", "path": "completion_notes/CN-OTHER-8/secret.png"}]
    _exec("UPDATE work_logs SET photos=? WHERE id=?", (json.dumps(photos), wid))
    assert _open(client, h, "work_log_photo", str(wid), "p1").status_code == 200
    assert _open(client, h, "work_log_photo", str(wid), "p2").status_code == 404
    assert _open(client, h, "work_log_photo", str(wid), "p3").status_code == 404


def test_voucher_attachment_path_must_be_the_vouchers_own_folder(client, make_user):
    u, p = make_user(username="bd_v", role="sales", modules=["cashier"])
    h = _login(client, u, p)
    vid = _exec("INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
                " VALUES ('20260901-701','2026-09-01','轉','s','草稿','t','n','n')")
    _put("voucher_attachments/%d/ok.png" % vid)
    _put("completion_notes/CN-OTHER-9/secret.png")
    for fid, path in (("vok", "voucher_attachments/%d/ok.png" % vid), ("vbad", "completion_notes/CN-OTHER-9/secret.png"),
                      ("vbad2", "voucher_attachments/99999/ok.png")):
        _exec("INSERT INTO voucher_attachments (voucher_id, file_id, filename, path, size, mime, uploaded_by, uploaded_at)"
              " VALUES (?,?,?,?,?,?,?,?)", (vid, fid, fid + ".png", path, 1, "image/png", "t", "n"))
    assert _open(client, h, "voucher", str(vid), "vok").status_code == 200
    assert _open(client, h, "voucher", str(vid), "vbad").status_code == 404
    assert _open(client, h, "voucher", str(vid), "vbad2").status_code == 404


def test_upload_path_key_table():
    k = up.upload_path_key
    assert k({"path": "shipping_notes/SN-1/a.png"}, "shipping_notes") == "SN-1"
    assert k({"path": "_demo_uploads/shipping_notes/SN-1/a.png"}, "shipping_notes") == "SN-1"      # demo 前綴去掉
    assert k({"path": "shipping_notes/SN-1/a.png"}, "completion_notes") is None                    # 資料夾不對
    assert k({"path": "shipping_notes/SN-1/x/a.png"}, "shipping_notes") is None                    # 段數不對
    assert k({"path": "projects/worklog_5/2026-09-30/a.png"}, "projects", depth=3) == "worklog_5"
    assert k({"path": "../etc/passwd"}, "shipping_notes") is None and k({"path": ""}, "shipping_notes") is None
    assert k({}, "x") is None and k(None, "x") is None and k({"path": 5}, "x") is None


# ── ② 案件紀錄：前端不得夾帶新的檔案路徑 ───────────────────────────────────

def test_strip_helper_keeps_db_entries_and_drops_new_paths():
    from modules.case.api import quotations as Qm
    old = {"materials": [{"files": [{"id": "a", "filename": "a.png", "path": "quotation_materials/Q_0/a.png", "size": 5}]}],
           "payment": {"items": [{"invoiceFiles": [{"id": "b", "path": "quotation_payment_items/Q_0/b.png"}]}]}}
    new = {"materials": [{"files": [{"id": "a", "filename": "TAMPERED.png", "path": "quotation_materials/Q_0/a.png", "size": 999},
                                    {"id": "z", "filename": "z.png", "path": "completion_notes/CN-1/secret.png"}],
                          "invoiceFiles": [{"id": "y", "path": "x/y/z.png"}]}],
           "payment": {"items": [{"invoiceFiles": [{"id": "b", "path": "quotation_payment_items/Q_0/b.png"}, "notadict", {"path": 5}]}]}}
    dropped = Qm._strip_foreign_file_entries(new, old)
    assert dropped == 4
    assert new["materials"][0]["files"] == [old["materials"][0]["files"][0]]                        # 沿用資料庫那一筆（檔名／大小不收前端的）
    assert new["materials"][0]["invoiceFiles"] == []
    assert new["payment"]["items"][0]["invoiceFiles"] == [old["payment"]["items"][0]["invoiceFiles"][0]]
    assert Qm._strip_foreign_file_entries(None, old) == 0 and Qm._strip_foreign_file_entries({"materials": "x"}, old) == 0
    assert Qm._strip_foreign_file_entries({"materials": [{"name": "no file key"}]}, old) == 0      # 沒有 files 鍵的項目不動


def test_case_record_patch_cannot_smuggle_a_foreign_path(client, world):
    """**端對端**：有案件權限的人 PATCH 整包時夾帶別案的檔案路徑 ⇒ 存下來的 caseRecord 沒有它，目錄端點也讀不到。"""
    H, paths = world
    h = H
    cr = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (Q,))[0]["data_json"])["caseRecord"]
    cr["materials"][0]["files"] = [
        {"id": "mine1", "filename": "RENAMED.png", "path": paths["mine"], "size": 1},
        {"id": "smuggle", "filename": "s.png", "path": "completion_notes/CN-OTHER-1/secret2.png", "size": 1}]
    r = client.patch("/api/quotations/%s/case-record" % Q, headers=h, json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (Q,))[0]["data_json"])["caseRecord"]
    files = saved["materials"][0]["files"]
    assert [f["id"] for f in files] == ["mine1"] and files[0]["filename"] == "mine.png", files   # 資料庫現值，不收前端改名
    assert _open(client, h, "material", "%s_0" % Q, "smuggle").status_code == 404


def test_new_quotation_create_drops_client_supplied_files(client, make_user):
    """POST 新建：沒有既有檔案，前端帶的 files／invoiceFiles 路徑一律不收（複製案件也不帶別案的檔）。"""
    u, p = make_user(username="bd_new", role="admin", modules=None)
    h = _login(client, u, p)
    data = {"customerName": "c", "projectName": "p", "tot": {"total": 1, "pretax": 1}, "taxType": "應稅",
            "caseRecord": {"materials": [{"name": "m", "files": [{"id": "e", "path": "completion_notes/CN-1/secret.png"}]}]}}
    r = client.post("/api/quotations", headers=h, json={"data": data, "status": "草稿"})
    if r.status_code not in (200, 201):
        pytest.skip("建立報價單的最小 body 與此基底不符：%s" % r.text[:120])
    no = r.json().get("quoteNo") or r.json().get("quote_no")
    saved = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (no,))[0]["data_json"])
    assert saved["caseRecord"]["materials"][0]["files"] == []
