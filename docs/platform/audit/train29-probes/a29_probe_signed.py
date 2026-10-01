# -*- coding: utf-8 -*-
"""A29 稽核探針 §9.11（客戶回簽單）：狀態閘、權限矩陣、IDOR、刪除規則、路徑竄改、類型／大小、稽核（包 47db5613；不進倉庫）。"""
import json
import os

import pytest

PDF = b"%PDF-1.4 probe"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _up(client, hdr, qno, name="a.pdf", data=PDF, ctype="application/pdf"):
    return client.post("/api/quotations/%s/signed-files" % qno, headers=hdr, files=[("files", (name, data, ctype))])


def _del(client, hdr, qno, fid):
    return client.delete("/api/quotations/%s/signed-files/%s" % (qno, fid), headers=hdr)


def _row(qno):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT signed_files_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()[0] or "[]")
    finally:
        conn.close()


def _acts():
    import db
    conn = db.get_db()
    try:
        return [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    import db
    users = {
        "owner": make_user(username="sg_owner", role="user", modules=["quotation", "case_manage"]),
        "collab": make_user(username="sg_collab", role="user", modules=["quotation", "case_manage"]),
        "admin": make_user(username="sg_admin", role="admin", modules=["quotation", "case_manage"]),
        "out": make_user(username="sg_out", role="user", modules=["quotation"]),
        "viewer": make_user(username="sg_viewer", role="viewer", modules=[]),
    }
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username='sg_owner'").fetchone()[0]
        cid = conn.execute("SELECT id FROM users WHERE username='sg_collab'").fetchone()[0]
        for qno, st in (("MQ-SG-DR", "草稿"), ("MQ-SG-PD", "待審核"), ("MQ-SG-SG", "簽核中"), ("MQ-SG-OK", "已送出"), ("MQ-SG-OK2", "已送出")):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag, sales_person, sales_person_id, assigned_user_ids)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (qno, st, "客", "案", "{}", "2026-09-01", "2026-09-01", "已成案", "sg_owner", oid, json.dumps([cid])))
        conn.commit()
    finally:
        conn.close()
    return client, {k: _login(client, v[0], v[1]) for k, v in users.items()}


def test_state_gate_and_denied_audit(world):
    client, h = world
    for qno in ("MQ-SG-DR", "MQ-SG-PD", "MQ-SG-SG"):
        r = _up(client, h["owner"], qno)
        assert r.status_code == 400, (qno, r.status_code, r.text[:120])                 # 未送出 ⇒ 400（不是 200／500）
        assert _row(qno) == []
    assert "quotation.upload_signed_files_denied" in _acts()
    ok = _up(client, h["owner"], "MQ-SG-OK")
    assert ok.status_code == 201, ok.text                                                 # 已送出階段既有上傳照常可用
    f = _row("MQ-SG-OK")[0]
    assert f["uploaderUsername"] == "sg_owner"
    from helpers import uploads as UP
    assert os.path.isfile(os.path.join(UP.UPLOADS_ROOT, f["path"])), "實體檔應落在 uploads 之內"
    assert f["path"].startswith("quotations/MQ-SG-OK/"), f["path"]


def test_permission_matrix_upload_and_idor(world):
    client, h = world
    assert _up(client, h["collab"], "MQ-SG-OK").status_code == 201                        # 協作者可傳
    assert _up(client, h["admin"], "MQ-SG-OK").status_code == 201
    for who in ("out", "viewer"):
        assert _up(client, h[who], "MQ-SG-OK").status_code == 404, who                    # 外人：看不到＝不存在
        assert _up(client, h[who], "MQ-SG-DR").status_code == 404, who                    # 連未送出的也是 404（不洩漏狀態）
    assert len(_row("MQ-SG-OK")) == 2


def test_delete_rules(world):
    import db
    client, h = world
    _up(client, h["collab"], "MQ-SG-OK")
    _up(client, h["owner"], "MQ-SG-OK")
    fc, fo = _row("MQ-SG-OK")
    assert _del(client, h["owner"], "MQ-SG-OK", fc["id"]).status_code == 403              # 擁有者不能刪別人上傳的
    assert "quotation.delete_signed_file_denied" in _acts()                               # 被擋也有稽核
    assert _del(client, h["out"], "MQ-SG-OK", fc["id"]).status_code == 404                # 外人 404
    assert _del(client, h["collab"], "MQ-SG-OK", fc["id"]).status_code == 200            # 上傳者本人
    from helpers import uploads as UP
    assert not os.path.isfile(os.path.join(UP.UPLOADS_ROOT, fc["path"])), "實體檔應一併刪除"
    assert _del(client, h["admin"], "MQ-SG-OK", fo["id"]).status_code == 200              # admin 刪別人的
    assert _row("MQ-SG-OK") == []
    # 舊檔（沒有 uploaderUsername）：只有 admin+ 刪得掉
    legacy = {"id": "legacy1", "filename": "舊.pdf", "path": "quotations/MQ-SG-OK2/legacy.pdf", "size": 5, "uploadedBy": "某人"}
    os.makedirs(os.path.join(UP.UPLOADS_ROOT, "quotations", "MQ-SG-OK2"), exist_ok=True)
    open(os.path.join(UP.UPLOADS_ROOT, legacy["path"]), "wb").write(b"x")
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET signed_files_json=? WHERE quote_no='MQ-SG-OK2'", (json.dumps([legacy]),))
        conn.commit()
    finally:
        conn.close()
    assert _del(client, h["owner"], "MQ-SG-OK2", "legacy1").status_code == 403
    assert _del(client, h["collab"], "MQ-SG-OK2", "legacy1").status_code == 403
    assert _del(client, h["admin"], "MQ-SG-OK2", "legacy1").status_code == 200
    assert _del(client, h["admin"], "MQ-SG-OK2", "nope").status_code == 404


def test_foreign_file_id_and_tampered_path(world, tmp_path):
    import db
    client, h = world
    _up(client, h["owner"], "MQ-SG-OK")
    _up(client, h["owner"], "MQ-SG-OK2")
    f_ok2 = _row("MQ-SG-OK2")[0]
    assert _del(client, h["owner"], "MQ-SG-OK", f_ok2["id"]).status_code == 404           # 別案的 file_id
    assert len(_row("MQ-SG-OK2")) == 1
    from helpers import uploads as UP
    outside = os.path.join(os.path.dirname(UP.UPLOADS_ROOT), "outside_keep.txt")
    open(outside, "w").write("keep")
    f = _row("MQ-SG-OK")[0]
    for evil in ("../outside_keep.txt", "..\\outside_keep.txt", outside, "C:/Windows/win.ini", "quotations/MQ-SG-OK2/other.pdf", "quotations/MQ-SG-OK/a.pdf:evil"):
        conn = db.get_db()
        try:
            conn.execute("UPDATE quotations SET signed_files_json=? WHERE quote_no='MQ-SG-OK'", (json.dumps([dict(f, path=evil)]),))
            conn.commit()
        finally:
            conn.close()
        r = _del(client, h["admin"], "MQ-SG-OK", f["id"])
        assert r.status_code == 409, (evil, r.status_code, r.text[:120])
        assert os.path.isfile(outside), "路徑竄改後刪到 uploads 之外的檔案：" + evil
        assert len(_row("MQ-SG-OK")) == 1, "被拒絕的刪除不該動清單：" + evil


def test_upload_type_and_size(world):
    client, h = world
    for name, data, ct in (("x.exe", b"MZ", "application/octet-stream"), ("x.html", b"<script>", "text/html"), ("x.svg", b"<svg/>", "image/svg+xml"),
                           ("a.pdf.exe", b"MZ", "application/pdf"), ("../../evil.pdf", PDF, "application/pdf")):
        r = _up(client, h["owner"], "MQ-SG-OK", name=name, data=data, ctype=ct)
        if name == "../../evil.pdf":                                                      # 檔名穿越：要嘛擋、要嘛伺服器改名但仍在 uploads 內
            if r.status_code == 201:
                p = _row("MQ-SG-OK")[-1]["path"]
                assert p.startswith("quotations/MQ-SG-OK/") and ".." not in p, p
            continue
        assert r.status_code in (400, 415, 422), (name, r.status_code, r.text[:100])
    assert _up(client, h["owner"], "MQ-SG-OK", name="big.pdf", data=PDF + b"0" * (20 * 1024 * 1024 + 1)).status_code in (400, 413)
    n = len(_row("MQ-SG-OK"))
    assert n <= 1, "危險類型／超大檔不該被存：%d 筆" % n
