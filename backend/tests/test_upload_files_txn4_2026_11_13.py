# -*- coding: utf-8 -*-
"""T86（feat/upload-files-txn-4，接在 T85 之後）：剩下所有「先刪實體檔、後寫庫」的刪檔路徑收尾。

範圍：
  案件額外支出  刪附件／刪變更申請待核准附件／撤銷變更申請（附件）／（作廢、刪整筆已是 commit 後刪，但清單改鎖內重讀）
  業務開發記錄  刪附件（remove_json_item）／刪整筆記錄（原本在 commit 之前刪檔）
  案件留言      刪整則留言（原本先刪附件、後 DELETE）
  已結案半解鎖  拒絕變更（原本在改狀態之前清暫存檔；且與核准不互斥）／核准上傳（原本 shutil.move 暫存檔、commit 失敗後暫存檔就不在了）
新作法一律：鎖內重讀 → 只改紀錄 → commit → **commit 之後**才動實體檔。

觀測點：磁碟（檔還在不在）與資料表；「動檔當下」的觀測用 `os.remove` 的包裝（只攔 uploads 底下的路徑）：
那一刻 ① 資料庫的狀態必須已經 commit、② 別條連線必須拿得到寫鎖。
"""
import io
import json
import os
import sqlite3

import pytest

from tests.test_payment_item_and_material_uploads import _make_quotation as _mk_q

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
PDF = b"%PDF-1.4\n" + b"0" * 32


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _exec(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _on_disk(entries):
    import helpers.uploads as up
    return [e for e in entries if os.path.isfile(os.path.join(up.UPLOADS_ROOT, e["path"]))]


def _trigger(name, event, table):
    _exec("CREATE TRIGGER %s BEFORE %s ON %s BEGIN SELECT RAISE(ABORT, 'blocked-by-test'); END" % (name, event, table))


def _untrigger(name):
    _exec("DROP TRIGGER IF EXISTS %s" % name)


def _spy_os_remove(monkeypatch, probe):
    """包住 os.remove：只攔 uploads 底下的路徑；真正刪檔「之前」先跑 probe(path)，記下回傳。"""
    import helpers.uploads as up
    real = os.remove
    root = os.path.abspath(up.UPLOADS_ROOT)
    seen = []

    def wrapper(path, *a, **k):
        if os.path.abspath(str(path)).startswith(root):
            seen.append(probe(path))
        return real(path, *a, **k)
    monkeypatch.setattr(os, "remove", wrapper)
    return seen


def _lock_free():
    import db
    c = db.get_db()
    try:
        c.execute("PRAGMA busy_timeout=200")
        try:
            c.execute("BEGIN IMMEDIATE")
            c.rollback()
            return True
        except sqlite3.OperationalError:
            return False
    finally:
        c.close()


# ═════════════════════════ 案件額外支出 ═════════════════════════

NO = "MQ-T86-X"


@pytest.fixture()
def expense(client, make_user, seed_extra_expense):
    h = _login(client, make_user, "t86_x")
    _mk_q(NO)
    eid = seed_extra_expense(NO, total_cost=1000, description="T86", status="草稿")
    return client, h, eid


def _x_url(eid, tail=""):
    return "/api/quotations/%s/extra-expenses/%s%s" % (NO, eid, tail)


def _x_files(eid):
    return json.loads(_rows("SELECT files_json FROM case_extra_expenses WHERE id=?", (eid,))[0]["files_json"] or "[]")


def _x_upload(client, h, eid):
    r = client.post(_x_url(eid, "/files"), headers=h, files=[("files", ("a.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    assert _on_disk([f])
    return f


def test_x_delete_file_normal_and_404(expense):
    client, h, eid = expense
    f = _x_upload(client, h, eid)
    assert client.delete(_x_url(eid, "/files/nope"), headers=h).status_code == 404
    assert [x["id"] for x in _x_files(eid)] == [f["id"]] and _on_disk([f]) == [f]
    assert client.delete(_x_url(eid, "/files/" + f["id"]), headers=h).status_code == 200
    assert _x_files(eid) == [] and _on_disk([f]) == []


def test_x_delete_file_db_failure_keeps_record_and_file(expense):
    client, h, eid = expense
    f = _x_upload(client, h, eid)
    _trigger("t86_x_blk", "UPDATE OF files_json", "case_extra_expenses")
    try:
        with pytest.raises(Exception):
            client.delete(_x_url(eid, "/files/" + f["id"]), headers=h)
    finally:
        _untrigger("t86_x_blk")
    assert [x["id"] for x in _x_files(eid)] == [f["id"]] and _on_disk([f]) == [f]


def test_x_delete_file_removed_after_commit_and_lock_release(expense, monkeypatch):
    client, h, eid = expense
    f = _x_upload(client, h, eid)
    seen = _spy_os_remove(monkeypatch, lambda _p: {"listed": [x["id"] for x in _x_files(eid)], "lock_free": _lock_free()})
    assert client.delete(_x_url(eid, "/files/" + f["id"]), headers=h).status_code == 200
    assert seen == [{"listed": [], "lock_free": True}], seen


def test_x_delete_file_rechecks_status_under_lock(expense, monkeypatch):
    """鎖外檢查過了、拿鎖之前單據被核准 ⇒ 鎖內重驗擋下（409），紀錄與檔都在。"""
    client, h, eid = expense
    f = _x_upload(client, h, eid)
    from modules.case.api import case_extra_expenses as M
    import core.txn as T
    real = M.begin_write

    def flip_then_lock(conn):
        _exec("UPDATE case_extra_expenses SET status='已核准' WHERE id=?", (eid,))
        monkeypatch.setattr(M, "begin_write", real)
        return real(conn)
    monkeypatch.setattr(M, "begin_write", flip_then_lock)
    r = client.delete(_x_url(eid, "/files/" + f["id"]), headers=h)
    assert r.status_code == 409, r.text
    assert [x["id"] for x in _x_files(eid)] == [f["id"]] and _on_disk([f]) == [f]
    assert T


@pytest.fixture()
def change_draft(client, make_user, seed_extra_expense):
    """已核准的額外支出＋一份變更申請草稿＋一個待核准附件。"""
    h = _login(client, make_user, "t86_c")
    _mk_q(NO + "C")
    eid = seed_extra_expense(NO + "C", total_cost=1000, description="T86C", status="已核准")
    _exec("UPDATE case_extra_expenses SET change_status='草稿', change_json=? WHERE id=?",
          (json.dumps({"description": "改", "totalCost": 1, "qty": 1, "unitCost": 1}), eid))
    url = "/api/quotations/%sC/extra-expenses/%s" % (NO, eid)
    r = client.post(url + "/change-request/files", headers=h, files=[("files", ("c.pdf", io.BytesIO(PDF), "application/pdf"))])
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    assert _on_disk([f])
    return client, h, eid, url, f


def _chg(eid):
    r = _rows("SELECT change_status, change_json FROM case_extra_expenses WHERE id=?", (eid,))[0]
    return r["change_status"], json.loads(r["change_json"] or "{}")


def test_x_change_file_delete_normal_and_db_failure_and_after_commit(change_draft, monkeypatch):
    client, h, eid, url, f = change_draft
    assert client.delete(url + "/change-request/files/nope", headers=h).status_code == 404
    _trigger("t86_cf_blk", "UPDATE OF change_json", "case_extra_expenses")
    try:
        with pytest.raises(Exception):
            client.delete(url + "/change-request/files/" + f["id"], headers=h)
    finally:
        _untrigger("t86_cf_blk")
    assert [x["id"] for x in _chg(eid)[1]["addFiles"]] == [f["id"]] and _on_disk([f]) == [f]
    seen = _spy_os_remove(monkeypatch, lambda _p: {"listed": [x["id"] for x in _chg(eid)[1].get("addFiles", [])], "lock_free": _lock_free()})
    assert client.delete(url + "/change-request/files/" + f["id"], headers=h).status_code == 200
    assert seen == [{"listed": [], "lock_free": True}], seen
    assert _chg(eid)[1]["addFiles"] == [] and _on_disk([f]) == []


def test_x_change_file_delete_blocked_once_submitted(change_draft):
    client, h, eid, url, f = change_draft
    _exec("UPDATE case_extra_expenses SET change_status='待審核' WHERE id=?", (eid,))
    assert client.delete(url + "/change-request/files/" + f["id"], headers=h).status_code == 409
    assert _on_disk([f]) == [f]


def test_x_cancel_change_request_db_failure_keeps_files_then_removes_after_commit(change_draft, monkeypatch):
    client, h, eid, url, f = change_draft
    _trigger("t86_cc_blk", "UPDATE OF change_status", "case_extra_expenses")
    try:
        with pytest.raises(Exception):
            client.delete(url + "/change-request", headers=h)
    finally:
        _untrigger("t86_cc_blk")
    assert _chg(eid)[0] == "草稿" and _on_disk([f]) == [f]            # 紀錄與檔都在（舊程式先刪檔 ⇒ 草稿還在、檔沒了）
    seen = _spy_os_remove(monkeypatch, lambda _p: {"status": _chg(eid)[0], "lock_free": _lock_free()})
    assert client.delete(url + "/change-request", headers=h).status_code == 200
    assert seen == [{"status": "", "lock_free": True}], seen
    assert _on_disk([f]) == []


def test_x_void_removes_pending_files_only_after_commit(change_draft, monkeypatch):
    client, h, eid, url, f = change_draft
    seen = _spy_os_remove(monkeypatch, lambda _p: {"status": _rows("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"],
                                                   "lock_free": _lock_free()})
    r = client.post(url + "/void", headers=h, json={"reason": "測試作廢"})
    assert r.status_code == 200, r.text
    assert len(seen) == 1 and seen[0]["lock_free"] is True and seen[0]["status"] != "已核准", seen
    assert _on_disk([f]) == []


# ═════════════════════════ 業務開發記錄 ═════════════════════════

@pytest.fixture()
def devlog(client, make_user):
    h = _login(client, make_user, "t86_d")
    r = client.post("/api/dev-cases", headers=h, json={"case_name": "T86 案件"})
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    uid = _rows("SELECT id FROM users WHERE username='t86_d'")[0]["id"]
    r = client.post("/api/dev-cases/%s/logs" % cid, headers=h, data={"log_date": "2026-11-13", "log_by": uid, "content": "拜訪"},
                    files=[("files", ("a.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    f = r.json()["files"][0]
    assert _on_disk([f])
    return client, h, lid, f


def _d_files(lid):
    rows = _rows("SELECT files_json FROM dev_logs WHERE id=?", (lid,))
    return json.loads(rows[0]["files_json"] or "[]") if rows else None


def test_d_delete_file_normal_404_and_db_failure(devlog):
    client, h, lid, f = devlog
    assert client.delete("/api/dev-logs/%s/files/nope" % lid, headers=h).status_code == 404
    assert client.delete("/api/dev-logs/%s/files/%s" % (lid + 99, f["id"]), headers=h).status_code == 404
    _trigger("t86_d_blk", "UPDATE OF files_json", "dev_logs")
    try:
        with pytest.raises(Exception):
            client.delete("/api/dev-logs/%s/files/%s" % (lid, f["id"]), headers=h)
    finally:
        _untrigger("t86_d_blk")
    assert [x["id"] for x in _d_files(lid)] == [f["id"]] and _on_disk([f]) == [f]
    assert client.delete("/api/dev-logs/%s/files/%s" % (lid, f["id"]), headers=h).status_code == 200
    assert _d_files(lid) == [] and _on_disk([f]) == []


def test_d_delete_file_removed_after_commit_and_lock_release(devlog, monkeypatch):
    client, h, lid, f = devlog
    seen = _spy_os_remove(monkeypatch, lambda _p: {"listed": [x["id"] for x in _d_files(lid)], "lock_free": _lock_free()})
    assert client.delete("/api/dev-logs/%s/files/%s" % (lid, f["id"]), headers=h).status_code == 200
    assert seen == [{"listed": [], "lock_free": True}], seen


def test_d_delete_log_removes_files_only_after_commit(devlog, monkeypatch):
    client, h, lid, f = devlog
    seen = _spy_os_remove(monkeypatch, lambda _p: {"row_gone": _d_files(lid) is None, "lock_free": _lock_free()})
    r = client.delete("/api/dev-logs/%s" % lid, headers=h)
    assert r.status_code == 204, r.text
    assert seen == [{"row_gone": True, "lock_free": True}], seen
    assert _on_disk([f]) == []


def test_d_delete_log_blocked_keeps_files(devlog):
    """已有批示的記錄不可刪（409）⇒ 附件不動。"""
    client, h, lid, f = devlog
    cid = _rows("SELECT case_id FROM dev_logs WHERE id=?", (lid,))[0]["case_id"]
    _exec("INSERT INTO dev_log_directive (log_id, case_id, author_id, content, parent_id, created_at) VALUES (?,?,?,?,?,?)",
          (lid, cid, 1, "批示", None, "2026-11-13T00:00:00"))
    r = client.delete("/api/dev-logs/%s" % lid, headers=h)
    assert r.status_code == 409, r.text
    assert _d_files(lid) is not None and _on_disk([f]) == [f]


# ═════════════════════════ 案件留言整則刪除 ═════════════════════════

@pytest.fixture()
def update_with_file(client, make_user):
    qn = "MQ-T86-U"
    _mk_q(qn)
    h = _login(client, make_user, "t86_u")
    r = client.post("/api/quotations/%s/updates" % qn, headers=h, data={"content": "現場"}, files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    f = json.loads(_rows("SELECT files_json FROM case_updates WHERE id=?", (uid,))[0]["files_json"])[0]
    assert _on_disk([f])
    return client, h, qn, uid, f


def _u_exists(uid):
    return bool(_rows("SELECT 1 FROM case_updates WHERE id=?", (uid,)))


def test_u_delete_update_db_failure_keeps_comment_and_file(update_with_file):
    client, h, qn, uid, f = update_with_file
    _trigger("t86_u_blk", "DELETE", "case_updates")
    try:
        with pytest.raises(Exception):
            client.delete("/api/quotations/%s/updates/%s" % (qn, uid), headers=h)
    finally:
        _untrigger("t86_u_blk")
    assert _u_exists(uid) and _on_disk([f]) == [f]                    # 舊程式先刪檔 ⇒ 留言還在、附件沒了


def test_u_delete_update_normal_and_files_removed_after_commit(update_with_file, monkeypatch):
    client, h, qn, uid, f = update_with_file
    seen = _spy_os_remove(monkeypatch, lambda _p: {"exists": _u_exists(uid), "lock_free": _lock_free()})
    r = client.delete("/api/quotations/%s/updates/%s" % (qn, uid), headers=h)
    assert r.status_code == 200, r.text
    assert seen == [{"exists": False, "lock_free": True}], seen
    assert _on_disk([f]) == []


def test_u_delete_update_picks_up_file_added_before_lock(update_with_file, monkeypatch):
    """鎖外讀到清單之後、鎖內之前又補了一個附件 ⇒ 鎖內重讀，也一併回收（舊程式只刪鎖外那份）。"""
    client, h, qn, uid, f = update_with_file
    extra = {"id": "extra1", "filename": "e.png", "path": f["path"].rsplit("/", 1)[0] + "/extra1.png"}
    import helpers.uploads as up
    with open(os.path.join(up.UPLOADS_ROOT, extra["path"]), "wb") as fh:
        fh.write(PNG)
    from modules.case.api import quotations as Q
    real = Q.write_txn

    class flip(real):
        def __enter__(self):
            _exec("UPDATE case_updates SET files_json=? WHERE id=?", (json.dumps([f, extra]), uid))
            return super().__enter__()
    monkeypatch.setattr(Q, "write_txn", flip)
    assert client.delete("/api/quotations/%s/updates/%s" % (qn, uid), headers=h).status_code == 200
    assert _on_disk([f, extra]) == []


# ═════════════════════════ 已結案半解鎖：拒絕／核准上傳 ═════════════════════════

@pytest.fixture()
def staged_request(client, make_user, monkeypatch):
    qn = "MQ-T86-G"
    _mk_q(qn)
    _exec("UPDATE quotations SET deal_tag='已結案', case_semi_unlocked=1 WHERE quote_no=?", (qn,))
    h = _login(client, make_user, "t86_g")
    from modules.case.api import quotations as Q
    monkeypatch.setattr(Q, "spawn_bg_thread", lambda fn, *a, **k: None)
    r = client.post("/api/quotations/%s/materials/0/files" % qn, headers=h, files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 201 and r.json().get("pending") is True, r.text
    cid = r.json()["changeRequestId"]
    staged = json.loads(_rows("SELECT staged_files_json FROM case_change_requests WHERE id=?", (cid,))[0]["staged_files_json"])
    assert len(staged) == 1 and _on_disk(staged) == staged
    su = _login(client, make_user, "t86_g_su")
    return client, su, cid, qn, staged


def _status(cid):
    return _rows("SELECT status FROM case_change_requests WHERE id=?", (cid,))[0]["status"]


def test_g_reject_normal_cleans_staging(staged_request):
    client, su, cid, qn, staged = staged_request
    r = client.post("/api/case-changes/%s/reject" % cid, headers=su, json={"reason": "no"})
    assert r.status_code == 200, r.text
    assert _status(cid) == "rejected" and _on_disk(staged) == []


def test_g_reject_db_failure_keeps_staging_and_pending(staged_request):
    client, su, cid, qn, staged = staged_request
    _trigger("t86_g_blk", "UPDATE OF status", "case_change_requests")
    try:
        with pytest.raises(Exception):
            client.post("/api/case-changes/%s/reject" % cid, headers=su, json={"reason": "no"})
    finally:
        _untrigger("t86_g_blk")
    assert _status(cid) == "pending" and _on_disk(staged) == staged   # 舊程式先清暫存檔 ⇒ 申請還在、檔沒了（之後核准套用不到）


def test_g_reject_cleans_staging_only_after_commit(staged_request, monkeypatch):
    client, su, cid, qn, staged = staged_request
    seen = _spy_os_remove(monkeypatch, lambda _p: {"status": _status(cid), "lock_free": _lock_free()})
    assert client.post("/api/case-changes/%s/reject" % cid, headers=su, json={"reason": "x"}).status_code == 200
    assert seen == [{"status": "rejected", "lock_free": True}], seen


def test_g_reject_after_someone_else_decided_is_409_and_touches_nothing(staged_request):
    """與核准互斥：別人先核准（或駁回）了 ⇒ 這邊 409，不動任何檔。"""
    client, su, cid, qn, staged = staged_request
    assert client.post("/api/case-changes/%s/approve" % cid, headers=su).status_code == 200
    r = client.post("/api/case-changes/%s/reject" % cid, headers=su, json={"reason": "late"})
    assert r.status_code == 409, r.text


def _final_files(qn):
    d = json.loads(_rows("SELECT data_json FROM quotations WHERE quote_no=?", (qn,))[0]["data_json"])
    return d["caseRecord"]["materials"][0].get("files", [])


def test_g_approve_normal_moves_files_and_cleans_staging(staged_request):
    client, su, cid, qn, staged = staged_request
    r = client.post("/api/case-changes/%s/approve" % cid, headers=su)
    assert r.status_code == 200, r.text
    fin = _final_files(qn)
    assert len(fin) == 1 and _on_disk(fin) == fin and _on_disk(staged) == []


def test_g_approve_db_failure_keeps_staging_and_leaves_no_copy_then_retry_works(staged_request):
    client, su, cid, qn, staged = staged_request
    _trigger("t86_ga_blk", "UPDATE OF status", "case_change_requests")
    try:
        with pytest.raises(Exception):
            client.post("/api/case-changes/%s/approve" % cid, headers=su)
    finally:
        _untrigger("t86_ga_blk")
    assert _status(cid) == "pending" and _on_disk(staged) == staged   # 舊程式 shutil.move ⇒ 暫存檔已不在原處
    assert _final_files(qn) == []
    import helpers.uploads as up
    d = os.path.join(up.UPLOADS_ROOT, "quotation_materials", "%s_0" % qn)
    assert not os.path.isdir(d) or os.listdir(d) == [], "失敗時複製出來的正式檔要回收"
    r = client.post("/api/case-changes/%s/approve" % cid, headers=su)    # 重試成功
    assert r.status_code == 200, r.text
    fin = _final_files(qn)
    assert len(fin) == 1 and _on_disk(fin) == fin and _on_disk(staged) == []


def test_g_approve_cleans_staging_only_after_commit(staged_request, monkeypatch):
    client, su, cid, qn, staged = staged_request
    seen = _spy_os_remove(monkeypatch, lambda _p: {"status": _status(cid), "lock_free": _lock_free()})
    assert client.post("/api/case-changes/%s/approve" % cid, headers=su).status_code == 200
    assert seen == [{"status": "approved", "lock_free": True}], seen


# ═════════════════════════ 路徑限定（_remove_physical 第二道防線）＋ 駁回不刪檔 ═════════════════════════

def test_remove_physical_refuses_paths_outside_uploads_root(tmp_path, caplog):
    """metadata 的 path 若指到上傳根目錄之外（絕對路徑／..／反斜線）⇒ 拒絕刪除並記 warning，檔案不動。"""
    import helpers.uploads as up
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep")
    bad = [str(victim), "../" + victim.name, "a/../../" + victim.name, str(victim).replace("/", "\\")]
    try:                                                    # 同磁碟時再加一個「相對上傳根目錄爬出去」的路徑
        bad.append(os.path.relpath(str(victim), os.path.realpath(up.UPLOADS_ROOT)).replace(os.sep, "/"))
    except ValueError:
        pass
    with caplog.at_level("WARNING"):
        for p in bad:
            up.remove_physical_file({"id": "x", "path": p})
            up._remove_physical({"id": "x", "path": p})
    assert victim.read_bytes() == b"keep"
    assert any("拒絕刪除" in r.getMessage() for r in caplog.records)


def test_remove_physical_still_removes_a_legit_upload(client, make_user):
    import helpers.uploads as up
    d = os.path.join(up.UPLOADS_ROOT, "t86_legit", "doc1")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, "a.bin")
    open(f, "wb").write(b"1")
    up.remove_physical_file({"id": "x", "path": "t86_legit/doc1/a.bin"})
    assert not os.path.exists(f)


def test_x_change_request_rejected_keeps_pending_files(change_draft):
    """送審 → 駁回：待核准附件的實體檔與紀錄都還在（駁回只改狀態；要刪得由申請人自己撤銷或刪附件）。"""
    client, h, eid, url, f = change_draft
    su = "t86_c"
    _exec("UPDATE case_extra_expenses SET change_status='待審核', change_approval_json=? WHERE id=?",
          (json.dumps({"requestedBy": "someone", "requestedAt": "2026-11-13T00:00:00", "currentTier": 0,
                       "tiers": [{"approvers": [{"username": su}]}]}), eid))
    r = client.post(url + "/change-request/reject", headers=h, json={"reason": "no"})
    assert r.status_code == 200, r.text
    st, chg = _chg(eid)
    assert st == "已駁回" and [x["id"] for x in chg["addFiles"]] == [f["id"]] and _on_disk([f]) == [f]


def test_x_change_file_upload_then_delete_after_reject_is_allowed_and_removes_after_commit(change_draft, monkeypatch):
    client, h, eid, url, f = change_draft
    _exec("UPDATE case_extra_expenses SET change_status='已駁回' WHERE id=?", (eid,))
    seen = _spy_os_remove(monkeypatch, lambda _p: {"listed": [x["id"] for x in _chg(eid)[1].get("addFiles", [])], "lock_free": _lock_free()})
    assert client.delete(url + "/change-request/files/" + f["id"], headers=h).status_code == 200
    assert seen == [{"listed": [], "lock_free": True}], seen


# ═════════════════════════ h12 審查補強（L1／L2／L3） ═════════════════════════

def test_x_delete_expense_rechecks_status_under_lock(expense, monkeypatch):
    """鎖外檢查是草稿、拿鎖之前被送審 ⇒ 鎖內重驗 409；單據與附件都在。"""
    client, h, eid = expense
    f = _x_upload(client, h, eid)
    from modules.case.api import case_extra_expenses as M
    real = M.begin_write

    def flip_then_lock(conn):
        _exec("UPDATE case_extra_expenses SET status='待審核' WHERE id=?", (eid,))
        monkeypatch.setattr(M, "begin_write", real)
        return real(conn)
    monkeypatch.setattr(M, "begin_write", flip_then_lock)
    r = client.delete(_x_url(eid), headers=h)
    assert r.status_code == 409, r.text
    assert _rows("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE id=?", (eid,))[0]["n"] == 1
    assert [x["id"] for x in _x_files(eid)] == [f["id"]] and _on_disk([f]) == [f]


def test_g_approve_copy_failure_leaves_no_half_written_destination(staged_request, monkeypatch):
    """複製到一半失敗（目的檔已寫了一半）：目的資料夾不留任何檔、暫存檔還在、申請仍是 pending。"""
    client, su, cid, qn, staged = staged_request
    from modules.case.api import quotations as Q
    real = Q.shutil.copy2

    def half_then_boom(src, dst, *a, **k):
        with open(dst, "wb") as fh:
            fh.write(b"half")
        raise OSError("disk full (test)")
    monkeypatch.setattr(Q.shutil, "copy2", half_then_boom)
    with pytest.raises(Exception):
        client.post("/api/case-changes/%s/approve" % cid, headers=su)
    monkeypatch.setattr(Q.shutil, "copy2", real)
    import helpers.uploads as up
    d = os.path.join(up.UPLOADS_ROOT, "quotation_materials", "%s_0" % qn)
    assert not os.path.isdir(d) or os.listdir(d) == []
    assert _status(cid) == "pending" and _on_disk(staged) == staged and _final_files(qn) == []


def test_g_staging_helpers_refuse_paths_outside_uploads(staged_request, tmp_path):
    """staged_files_json 裡的路徑指到上傳根目錄之外：核准不複製、駁回不刪（外面的檔案原封不動）。"""
    client, su, cid, qn, staged = staged_request
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"keep")
    bad = [{"id": "z", "filename": "z.png", "path": str(victim)}, {"id": "y", "filename": "y.png", "path": "../" + victim.name}]
    _exec("UPDATE case_change_requests SET staged_files_json=? WHERE id=?", (json.dumps(bad), cid))
    r = client.post("/api/case-changes/%s/reject" % cid, headers=su, json={"reason": "x"})
    assert r.status_code == 200, r.text
    assert victim.read_bytes() == b"keep"


def test_g_approve_with_bad_staged_path_adds_no_record_and_deletes_nothing(staged_request, tmp_path):
    client, su, cid, qn, staged = staged_request
    victim = tmp_path / "victim2.bin"
    victim.write_bytes(b"keep")
    _exec("UPDATE case_change_requests SET staged_files_json=? WHERE id=?",
          (json.dumps([{"id": "z", "filename": "z.png", "path": str(victim)}]), cid))
    r = client.post("/api/case-changes/%s/approve" % cid, headers=su)
    assert r.status_code == 200, r.text
    assert _final_files(qn) == [] and victim.read_bytes() == b"keep"
