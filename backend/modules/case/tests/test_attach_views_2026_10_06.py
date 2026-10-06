# -*- coding: utf-8 -*-
"""t44-attach-views：支出申請（費用單據）附件的唯讀顯示——簽核詳情與出納待付款。

① `file_entries` 加性欄位：size／docKind／heic（舊呼叫端的鍵不變）。
② 簽核詳情：簽核人看得到附件（發票／附件標示、大小、HEIC 只是 kind=heic）；金額被遮蔽的人拿不到檔案清單，
   `/api/photo-token` 的簽核佇列情境也不放行那些路徑；沒被列出的路徑不放行。
③ 出納待付款：清單帶 `fileList`（**不含 path**）；`/api/cashier/pending-payables/{source}/{key}/files/{id}` 只給財務角色／superadmin、
   只認清單上那一筆、檔案 id 必須在該筆自己的清單、路徑必須綁這張單據；已登錄付款後不再開。
"""
import json
import os

import pytest

NO = "MQ-202610-881"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _write_upload(rel, data):
    from helpers import uploads as up
    full = os.path.join(up.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)


# ── ① file_entries 加性欄位 ──────────────────────────────────────────────────────────────────────
def test_file_entries_additive_fields():
    from helpers.approval_queue import file_entries
    raw = json.dumps([
        {"id": "a", "filename": "a.JPG", "path": "d/1/a.JPG", "size": 12, "kind": "invoice", "uploadedBy": "u", "uploadedAt": "t"},
        {"id": "b", "filename": "b.pdf", "path": "d/1/b.pdf", "size": True, "kind": "other"},
        {"id": "c", "filename": "c.HEIC", "path": "d/1/c.HEIC", "size": 5},
        {"id": "d", "filename": "d.heif", "path": "d/1/d.heif", "size": -3, "kind": "weird"},
        {"id": "e", "filename": "e.txt"},                                   # 沒有 path ⇒ 略過（舊行為）
    ])
    out = {e["id"]: e for e in file_entries(raw)}
    assert set(out) == {"a", "b", "c", "d"}
    assert out["a"]["kind"] == "image" and out["a"]["size"] == 12 and out["a"]["docKind"] == "invoice"
    assert out["b"]["kind"] == "pdf" and "size" not in out["b"] and out["b"]["docKind"] == "other"      # bool 不是大小
    assert out["c"]["kind"] == "heic" and out["c"]["size"] == 5 and "docKind" not in out["c"]           # 沒 kind、沒預設 ⇒ 不加
    assert out["d"]["kind"] == "heic" and "size" not in out["d"] and "docKind" not in out["d"]          # 負數大小、未知 kind
    dflt = {e["id"]: e for e in file_entries(raw, "other")}
    assert dflt["c"]["docKind"] == "other" and dflt["d"]["docKind"] == "other" and dflt["a"]["docKind"] == "invoice"
    for e in out.values():                                                  # 舊鍵全在
        assert {"id", "name", "path", "kind", "uploadedBy", "uploadedAt"} <= set(e)


# ── ②③ 世界：一張送簽中的費用單據，三個附件 ──────────────────────────────────────────────────────
@pytest.fixture
def world(client, make_user):
    H, ids = {}, {}
    for u, role, mods in (("av_app", "sales", ["expense_forms"]), ("av_col", "sales", None), ("av_fin", "finance", None),
                          ("av_apr", "engineer", None), ("av_eng", "engineer", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        H[u] = _login(client, name, pw)
        ids[u] = _q("SELECT id FROM users WHERE username=?", (u,))[0]["id"]
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "客", "專案", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "",
        json.dumps([ids[k] for k in ("av_app", "av_col", "av_fin")])))          # 簽核人不是案件的人（簽核佇列情境才放行附件）
    r = client.post("/api/quotations/%s/extra-expenses" % NO, headers=H["av_app"],
                    json={"kind": "travel", "lines": [{"category": "其他", "summary": "高鐵", "amount": 4321}], "data": {"applicant": "av_app"},
                          "payeeType": "employee", "payeeName": "申請人"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    folder = "case_extra_expense/%s_%s" % (NO, eid)
    files = [
        {"id": "f1", "filename": "inv.png", "path": folder + "/inv.png", "size": len(PNG), "mime": "image/png", "uploadedBy": "av_app",
         "uploadedAt": "2026-10-06T09:00:00", "kind": "invoice"},
        {"id": "f2", "filename": "memo.pdf", "path": folder + "/memo.pdf", "size": 9, "mime": "application/pdf", "uploadedBy": "av_app",
         "uploadedAt": "2026-10-06T09:01:00", "kind": "other"},
        {"id": "f3", "filename": "IMG_1.HEIC", "path": folder + "/IMG_1.HEIC", "size": 7, "mime": "image/heic", "uploadedBy": "av_app",
         "uploadedAt": "2026-10-06T09:02:00"},                                           # 舊筆：沒有 kind
    ]
    _write_upload(files[0]["path"], PNG)
    _write_upload(files[1]["path"], b"%PDF-1.4 x")
    _write_upload(files[2]["path"], b"heicdat")
    appr = {"requestedBy": "av_app", "requestedByDisplay": "申請人", "requestedAt": "2026-10-06T10:00:00",
            "tiers": [{"order": 0, "approvers": [{"username": "av_apr", "display_name": "簽核人"}]}], "currentTier": 0}
    _x("UPDATE case_extra_expenses SET status='待審核', approval_json=?, files_json=? WHERE id=?", (json.dumps(appr), json.dumps(files), eid))
    return H, eid, files


def _detail(client, h, eid):
    return client.get("/api/approval-queue/detail", params={"type": "extra_expense", "id": str(eid)}, headers=h)


def test_approver_sees_files_with_kinds_sizes_and_heic(client, world):
    H, eid, files = world
    r = _detail(client, H["av_apr"], eid)
    assert r.status_code == 200, r.text
    got = {f["id"]: f for f in r.json()["files"]}
    assert set(got) == {"f1", "f2", "f3"}
    assert got["f1"]["kind"] == "image" and got["f1"]["docKind"] == "invoice" and got["f1"]["size"] == len(PNG)
    assert got["f2"]["kind"] == "pdf" and got["f2"]["docKind"] == "other"
    assert got["f3"]["kind"] == "heic" and got["f3"]["docKind"] == "other"                 # 舊筆預設附件
    assert "filesNeedMoneyView" not in r.json()                                            # 旗標不外洩


def test_money_masked_viewer_gets_no_files_and_no_photo_token(client, world):
    H, eid, files = world
    r = _detail(client, H["av_col"], eid)
    assert r.status_code in (200, 403, 404), r.text
    if r.status_code == 200:
        assert r.json()["files"] == []
    # 簽核佇列情境的簽章：簽核人放行列出的路徑；金額遮蔽的人與沒被列出的路徑一律不放行
    paths = [f["path"] for f in files]
    ok = client.post("/api/photo-token/batch", json={"paths": paths, "type": "extra_expense", "id": str(eid)}, headers=H["av_apr"])
    assert ok.status_code == 200 and set(ok.json()["tokens"]) == set(paths), ok.text
    no = client.post("/api/photo-token/batch", json={"paths": paths, "type": "extra_expense", "id": str(eid)}, headers=H["av_col"])
    assert no.status_code == 200 and no.json()["tokens"] == {}, no.text
    other = "case_extra_expense/%s_%s/other.png" % (NO, eid)
    _write_upload(other, PNG)
    unl = client.post("/api/photo-token/batch", json={"paths": [other], "type": "extra_expense", "id": str(eid)}, headers=H["av_apr"])
    assert unl.json()["tokens"] == {}, "詳情沒列出的路徑不放行"


def _approve(eid):
    _x("UPDATE case_extra_expenses SET status='已核准' WHERE id=?", (eid,))


def test_cashier_list_has_filelist_without_path(client, world):
    H, eid, files = world
    _approve(eid)
    r = client.get("/api/cashier/pending-payables", headers=H["av_fin"])
    assert r.status_code == 200, r.text
    (it,) = [i for i in r.json()["items"] if i["key"] == str(eid)]
    assert it["files"] == 3 and it["invoiceFiles"] == 1
    fl = {f["id"]: f for f in it["fileList"]}
    assert set(fl) == {"f1", "f2", "f3"}
    assert all("path" not in f for f in it["fileList"]), "清單不外洩儲存路徑"
    assert fl["f1"]["docKind"] == "invoice" and fl["f3"]["kind"] == "heic" and fl["f1"]["size"] == len(PNG)


def test_cashier_file_endpoint_streams_for_finance_only(client, world):
    H, eid, files = world
    _approve(eid)
    base = "/api/cashier/pending-payables/case/%s/files/" % eid
    r = client.get(base + "f1", headers=H["av_fin"])
    assert r.status_code == 200 and r.content == PNG
    assert "inline" in r.headers.get("content-disposition", "")
    for who in ("av_col", "av_app", "av_apr", "av_eng"):                    # 不是財務角色／superadmin
        assert client.get(base + "f1", headers=H[who]).status_code == 403, who
    assert client.get(base + "nope", headers=H["av_fin"]).status_code == 404
    assert client.get("/api/cashier/pending-payables/nosuch/%s/files/f1" % eid, headers=H["av_fin"]).status_code == 404
    assert client.get(base + "f1").status_code in (401, 403)


def test_cashier_file_endpoint_refuses_unbound_paths_and_paid_rows(client, world):
    H, eid, files = world
    _approve(eid)
    base = "/api/cashier/pending-payables/case/%s/files/" % eid
    _write_upload("case_extra_expense/OTHER-1_999/x.png", PNG)
    bad = files + [{"id": "f9", "filename": "x.png", "path": "case_extra_expense/OTHER-1_999/x.png", "size": 1, "kind": "other"},
                   {"id": "f8", "filename": "p", "path": "../../etc/passwd", "size": 1, "kind": "other"}]
    _x("UPDATE case_extra_expenses SET files_json=? WHERE id=?", (json.dumps(bad), eid))
    assert client.get(base + "f9", headers=H["av_fin"]).status_code == 404, "路徑不屬於這張單據"
    assert client.get(base + "f8", headers=H["av_fin"]).status_code == 404
    assert client.get(base + "f1", headers=H["av_fin"]).status_code == 200
    _x("UPDATE case_extra_expenses SET paid_date='2026-10-06' WHERE id=?", (eid,))      # 已登錄付款 ⇒ 不在待付款清單
    assert client.get(base + "f1", headers=H["av_fin"]).status_code == 404


# ── S1：舊筆（kind=''）也套同一條「附件＝金額」規則 ──────────────────────────────────
def test_legacy_kind_empty_rows_are_money_masked_too(client, world):
    H, eid, files = world
    _x("UPDATE case_extra_expenses SET kind='' WHERE id=?", (eid,))
    assert _q("SELECT kind FROM case_extra_expenses WHERE id=?", (eid,))[0]["kind"] == ""
    ok = _detail(client, H["av_apr"], eid)
    assert ok.status_code == 200 and {f["id"] for f in ok.json()["files"]} == {"f1", "f2", "f3"}, "簽核人照樣看得到"
    r = _detail(client, H["av_col"], eid)
    assert r.status_code in (200, 403, 404), r.text
    if r.status_code == 200:
        assert r.json()["files"] == [], "舊筆也不給看不到金額的人檔案"
    # photo-token 的「簽核佇列情境」同一條規則；案件協作者本來就能靠**案件頁**的權限開案件檔（那是另一條路、不在 S1 範圍），
    # 所以這裡只驗簽核情境的授權函式（`_approval_context_paths`）對看不到金額的人給空集合
    from routers import uploads as _up
    def ctx(username):
        u = _q("SELECT * FROM users WHERE username=?", (username,))[0]
        return _up._approval_context_paths(u, "extra_expense", str(eid))
    assert ctx("av_apr") == {f["path"] for f in files}, "正對照：簽核人放行三個路徑"
    try:
        assert not ctx("av_col")
    except Exception as e:                                               # noqa: BLE001  詳情守門直接拒絕也算（403）
        assert getattr(e, "status_code", None) in (403, 404), e


# ── S3：沒有 id 的舊筆——出納清單合成 idx-<位置>，不外洩 path，仍可開檔 ─────────────────────────
def test_cashier_legacy_files_without_id_get_synthetic_ids_and_never_leak_path(client, world):
    H, eid, files = world
    _approve(eid)
    legacy = [dict(files[0]), dict(files[1]), dict(files[2])]
    del legacy[0]["id"]                                                      # f1（PNG）沒有 id
    _x("UPDATE case_extra_expenses SET files_json=? WHERE id=?", (json.dumps(legacy), eid))
    r = client.get("/api/cashier/pending-payables", headers=H["av_fin"])
    (it,) = [i for i in r.json()["items"] if i["key"] == str(eid)]
    ids = [f["id"] for f in it["fileList"]]
    assert ids == ["idx-0", "f2", "f3"], ids
    blob = json.dumps(it["fileList"], ensure_ascii=False)
    assert "case_extra_expense/" not in blob and "path" not in blob, "合成 id 之後 id 也不能是路徑"
    base = "/api/cashier/pending-payables/case/%s/files/" % eid
    g = client.get(base + "idx-0", headers=H["av_fin"])
    assert g.status_code == 200 and g.content == PNG
    assert client.get(base + "idx-1", headers=H["av_fin"]).status_code == 404, "有 id 的那筆不能用位置開"
    assert client.get(base + "idx-9", headers=H["av_fin"]).status_code == 404
    assert client.get(base + legacy[0]["path"].replace("/", "%2F"), headers=H["av_fin"]).status_code == 404, "路徑不是 id"
