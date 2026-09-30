# -*- coding: utf-8 -*-
"""額外支出的**舊版**附件資料夾（正式機實測 2026-10-01：8 筆額外支出 `wrong_folder`）。

DB v75 之前額外支出的附件存在 `quotation_settlement_extra/{案件}_{舊陣列索引}/檔名`；v75 只搬 metadata、沒搬檔案，
所以那些列的 `files_json` 至今指向舊資料夾。路徑綁單據（W3）上線後 `open()` 只認 `case_extra_expense/{案件}_{id}`，舊檔會 404。
規則：舊資料夾**只綁案件**（鍵的案件編號＝該列的 quote_no；舊索引不是現在的 id，不比）。別案的路徑、別種資料夾一律照舊 404。
路徑存取（`uploads.path_access`，給 photo-token 之類用）同理：該案某筆額外支出的 `files_json` 真的列了這個路徑才放行。"""
import json
import os

import pytest

from helpers import uploads as up

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
Q = "MQ-202609-881"
OTHER = "MQ-202609-882"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _put(rel, data=PNG):
    full = os.path.join(up.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(data)


def _quote(no):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
                  " updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "客戶", "工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
                   "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _open(client, h, eid, fid):
    return client.get("/api/attachments/open", headers=h, params={"type": "extra_expense", "doc": str(eid), "file": fid})


@pytest.fixture
def world(client, make_user, seed_extra_expense):
    u, p = make_user(username="lx_admin", role="superadmin", modules=None)
    H = _login(client, u, p)
    _quote(Q)
    _quote(OTHER)
    mine_legacy = "quotation_settlement_extra/%s_0/old.png" % Q              # 舊資料夾、同案、舊索引 0（現在的列 id 不是 0）
    mine_new = "case_extra_expense/%s_%s/new.png"                              # 新資料夾：id 要建立後才知道
    foreign_legacy = "quotation_settlement_extra/%s_0/secret.png" % OTHER      # 舊資料夾、別案
    wrong_folder = "completion_notes/CN-1/secret2.png"                         # 別種單據的資料夾
    for rel in (mine_legacy, foreign_legacy, wrong_folder):
        _put(rel)
    files = [{"id": "f-old", "filename": "old.png", "path": mine_legacy, "size": len(PNG)},
             {"id": "f-foreign", "filename": "x.png", "path": foreign_legacy, "size": 1},
             {"id": "f-wrongfolder", "filename": "y.png", "path": wrong_folder, "size": 1}]
    eid = seed_extra_expense(Q, total_cost=500, category="運費", description="舊版附件", expense_date="2026-09-10", files=files)
    new_rel = mine_new % (Q, eid)
    _put(new_rel)
    import db
    c = db.get_db()
    try:
        cur = json.loads(c.execute("SELECT files_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()[0])
        cur.append({"id": "f-new", "filename": "new.png", "path": new_rel, "size": len(PNG)})
        c.execute("UPDATE case_extra_expenses SET files_json=? WHERE id=?", (json.dumps(cur), eid))
        c.commit()
    finally:
        c.close()
    return H, eid, {"legacy": mine_legacy, "foreign": foreign_legacy, "wrong": wrong_folder, "new": new_rel}


def test_legacy_folder_file_of_the_same_case_opens(client, world):
    H, eid, _ = world
    r = _open(client, H, eid, "f-old")
    assert r.status_code == 200 and r.content == PNG
    assert _open(client, H, eid, "f-new").status_code == 200                     # 新資料夾照舊可開


def test_foreign_case_and_wrong_folder_paths_still_404(client, world):
    """**反向控制**：把舊資料夾的案件比對拿掉（或改成不比）⇒ f-foreign 會 200 ⇒ 這題紅。"""
    H, eid, _ = world
    for fid in ("f-foreign", "f-wrongfolder"):
        r = _open(client, H, eid, fid)
        assert r.status_code == 404 and r.json()["detail"] == "檔案不存在", (fid, r.status_code)


def test_legacy_key_must_be_well_formed(client, world, seed_extra_expense):
    """舊資料夾的鍵要是 `{案件}_{數字}`：沒有索引尾巴 ⇒ 404（不能借『前綴相同』放行）。"""
    H, _eid, _ = world
    rel = "quotation_settlement_extra/%s/noindex.png" % Q
    _put(rel)
    eid2 = seed_extra_expense(Q, total_cost=1, category="其他", description="x", expense_date="2026-09-11",
                              files=[{"id": "f-noidx", "filename": "n.png", "path": rel, "size": 1}])
    assert _open(client, H, eid2, "f-noidx").status_code == 404


def test_path_access_provider_binds_legacy_paths_to_the_case_and_listing(client, world):
    from core import registry
    _H, eid, rels = world
    prov = registry.providers(up.PATH_ACCESS)
    assert prov, "uploads.path_access 提供者不在"
    import db
    c = db.get_db()
    try:
        user = dict(c.execute("SELECT * FROM users WHERE username='lx_admin'").fetchone())
        user["modules"] = []
        assert up.upload_readable(c, up.canonical_upload_path(rels["legacy"]), user) is True
        assert up.upload_readable(c, up.canonical_upload_path(rels["foreign"]), user) is False      # 別案：那一案沒有任何額外支出列了它
        assert up.upload_readable(c, up.canonical_upload_path(rels["new"]), user) is True
        # 路徑對得上案件編號但 files_json 沒列 ⇒ 不放行（不能用猜路徑的方式讀）
        ghost = "quotation_settlement_extra/%s_7/ghost.png" % Q
        _put(ghost)
        assert up.upload_readable(c, up.canonical_upload_path(ghost), user) is False
    finally:
        c.close()
