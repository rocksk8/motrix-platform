# -*- coding: utf-8 -*-
"""T85（feat/upload-files-txn-3，接在 T84 之後）：報價單 JSON 內嵌的附件刪除——先 commit、後刪實體檔。

範圍：款項發票（payment.items[].invoiceFiles）、叫料附件（materials[].files）、叫料發票（materials[].invoiceFiles）、
案件留言附件（case_updates.files_json），加上已結案半解鎖案件「刪除類變更」被最高管理者核准時的套用。
舊作法：`delete_document_file()` 先 `os.remove` 再寫庫 ⇒ 寫庫失敗留下「有紀錄、沒檔案」；刪檔還在寫鎖裡做。
新作法：鎖內重讀 → 只改清單 → commit → **commit 之後**才刪實體檔（`pop_document_file`／`remove_physical_file`、`remove_json_item`）。

觀測點一律在磁碟（檔還在不在）與資料表（紀錄還在不在）；「刪檔當下」的觀測用 `_remove_physical` 的包裝：
那一刻 ① 資料庫裡的紀錄必須已經是刪掉的狀態（已 commit），② 別條連線必須拿得到寫鎖（鎖已放掉）。
"""
import json
import os
import sqlite3

import pytest

from tests.test_payment_item_and_material_uploads import _make_quotation as _mk_q

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


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


def _spy_remove(monkeypatch, probe):
    """包住 helpers.uploads._remove_physical：真正刪檔「之前」先跑 probe(target)，記下它的回傳；回傳的 list 給測試看。"""
    import helpers.uploads as up
    real = up._remove_physical
    seen = []

    def wrapper(target):
        seen.append(probe(target))
        return real(target)
    monkeypatch.setattr(up, "_remove_physical", wrapper)
    return seen


def _lock_free_probe():
    """別條連線在 200ms 內拿得到寫鎖嗎（True＝鎖已放掉）。拿到就順手 ROLLBACK，不改任何資料。"""
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


# ───────────────────────────── 報價單內嵌三種附件 ─────────────────────────────

SITES = {
    "payment_invoice": ("/api/quotations/%s/payment/0/invoice-files", lambda cr: cr["payment"]["items"][0]["invoiceFiles"]),
    "material_files": ("/api/quotations/%s/materials/0/files", lambda cr: cr["materials"][0]["files"]),
    "material_invoice": ("/api/quotations/%s/materials/0/invoice-files", lambda cr: cr["materials"][0]["invoiceFiles"]),
}


def _listed(quote_no, getter):
    d = json.loads(_rows("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,))[0]["data_json"])
    return getter(d["caseRecord"])


@pytest.fixture(params=sorted(SITES))
def site(request, client, make_user):
    qn = "MQ-T85-" + request.param[:3].upper()
    _mk_q(qn)
    h = _login(client, make_user, "t85_" + request.param[:6])
    tmpl, getter = SITES[request.param]
    url = tmpl % qn
    r = client.post(url, headers=h, files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    assert _on_disk([f])
    return client, h, url, qn, getter, f


def test_normal_delete_removes_record_and_file(site):
    client, h, url, qn, getter, f = site
    r = client.delete(url + "/" + f["id"], headers=h)
    assert r.status_code == 200, r.text
    assert _listed(qn, getter) == [] and _on_disk([f]) == []


def test_delete_unknown_file_id_is_404_and_touches_nothing(site):
    client, h, url, qn, getter, f = site
    r = client.delete(url + "/no-such-id", headers=h)
    assert r.status_code == 404, r.text
    assert [x["id"] for x in _listed(qn, getter)] == [f["id"]] and _on_disk([f]) == [f]


def test_db_failure_keeps_record_and_file(site):
    """寫庫失敗（UPDATE quotations.data_json 被擋）：紀錄與實體檔都還在（舊程式先刪檔 ⇒ 有紀錄、沒檔案）。"""
    client, h, url, qn, getter, f = site
    _trigger("t85_blk", "UPDATE OF data_json", "quotations")
    try:
        with pytest.raises(Exception):
            client.delete(url + "/" + f["id"], headers=h)
    finally:
        _untrigger("t85_blk")
    assert [x["id"] for x in _listed(qn, getter)] == [f["id"]]
    assert _on_disk([f]) == [f]


def test_file_is_removed_only_after_commit_and_lock_release(site, monkeypatch):
    """刪實體檔的那一刻：紀錄已 commit 掉、寫鎖已放掉（別的請求可以寫）；並發寫入不被蓋掉。"""
    client, h, url, qn, getter, f = site

    def probe(_target):
        in_db = [x["id"] for x in _listed(qn, getter)]
        return {"listed": in_db, "lock_free": _lock_free_probe()}
    seen = _spy_remove(monkeypatch, probe)
    r = client.delete(url + "/" + f["id"], headers=h)
    assert r.status_code == 200, r.text
    assert len(seen) == 1
    assert seen[0] == {"listed": [], "lock_free": True}, seen


def test_concurrent_edit_during_file_removal_is_not_lost(site, client, monkeypatch):
    """刪檔（慢動作）進行時，別的請求改了同一張報價單 ⇒ 兩邊都保留（舊程式在鎖內刪檔，別人要等／被蓋）。"""
    client, h, url, qn, getter, f = site

    def probe(_target):
        import db
        c = db.get_db()
        try:
            c.execute("PRAGMA busy_timeout=200")
            row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()
            d = json.loads(row["data_json"])
            d["concurrentNote"] = "kept"
            c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), qn))
            c.commit()
            return "written"
        except sqlite3.OperationalError as e:
            return "locked: %s" % e
        finally:
            c.close()
    seen = _spy_remove(monkeypatch, probe)
    r = client.delete(url + "/" + f["id"], headers=h)
    assert r.status_code == 200, r.text
    assert seen == ["written"], seen
    d = json.loads(_rows("SELECT data_json FROM quotations WHERE quote_no=?", (qn,))[0]["data_json"])
    assert d.get("concurrentNote") == "kept" and getter(d["caseRecord"]) == []


# ───────────────────────────── 案件留言附件 ─────────────────────────────

@pytest.fixture()
def update_with_file(client, make_user):
    qn = "MQ-T85-U"
    _mk_q(qn)
    h = _login(client, make_user, "t85_upd")
    r = client.post("/api/quotations/%s/updates" % qn, headers=h, data={"content": "現場"},
                    files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    files = json.loads(_rows("SELECT files_json FROM case_updates WHERE id=?", (uid,))[0]["files_json"])
    assert len(files) == 1 and _on_disk(files)
    return client, h, qn, uid, files[0]


def _upd_url(qn, uid, fid):
    return "/api/quotations/%s/updates/%s/files/%s" % (qn, uid, fid)


def _upd_files(uid):
    return json.loads(_rows("SELECT files_json FROM case_updates WHERE id=?", (uid,))[0]["files_json"] or "[]")


def test_case_update_normal_delete(update_with_file):
    client, h, qn, uid, f = update_with_file
    r = client.delete(_upd_url(qn, uid, f["id"]), headers=h)
    assert r.status_code == 200 and r.json()["files"] == [], r.text
    assert _upd_files(uid) == [] and _on_disk([f]) == []


def test_case_update_unknown_file_or_comment_is_404(update_with_file):
    client, h, qn, uid, f = update_with_file
    assert client.delete(_upd_url(qn, uid, "no-such-id"), headers=h).status_code == 404
    assert client.delete(_upd_url(qn, uid + 999, f["id"]), headers=h).status_code == 404
    assert client.delete(_upd_url("MQ-OTHER", uid, f["id"]), headers=h).status_code in (403, 404)
    assert [x["id"] for x in _upd_files(uid)] == [f["id"]] and _on_disk([f]) == [f]


def test_case_update_db_failure_keeps_record_and_file(update_with_file):
    client, h, qn, uid, f = update_with_file
    _trigger("t85_u_blk", "UPDATE OF files_json", "case_updates")
    try:
        with pytest.raises(Exception):
            client.delete(_upd_url(qn, uid, f["id"]), headers=h)
    finally:
        _untrigger("t85_u_blk")
    assert [x["id"] for x in _upd_files(uid)] == [f["id"]] and _on_disk([f]) == [f]


def test_case_update_concurrent_edit_during_file_removal_is_not_lost(update_with_file, client, monkeypatch):
    client, h, qn, uid, f = update_with_file

    def probe(_target):
        import db
        c = db.get_db()
        try:
            c.execute("PRAGMA busy_timeout=200")
            c.execute("UPDATE case_updates SET content=? WHERE id=?", ("concurrent", uid))
            c.commit()
            return "written"
        except sqlite3.OperationalError as e:
            return "locked: %s" % e
        finally:
            c.close()
    seen = _spy_remove(monkeypatch, probe)
    r = client.delete(_upd_url(qn, uid, f["id"]), headers=h)
    assert r.status_code == 200, r.text
    assert seen == ["written"], seen
    row = _rows("SELECT content, files_json FROM case_updates WHERE id=?", (uid,))[0]
    assert row["content"] == "concurrent" and json.loads(row["files_json"]) == []


def test_case_update_file_removed_after_commit(update_with_file, monkeypatch):
    client, h, qn, uid, f = update_with_file
    seen = _spy_remove(monkeypatch, lambda _t: {"listed": [x["id"] for x in _upd_files(uid)], "lock_free": _lock_free_probe()})
    assert client.delete(_upd_url(qn, uid, f["id"]), headers=h).status_code == 200
    assert seen == [{"listed": [], "lock_free": True}], seen


# ───────────────────────────── 已結案半解鎖：刪除類變更核准後套用 ─────────────────────────────

APPLY_SITES = {
    "payment_invoice_delete": "payment_invoice",
    "material_file_delete": "material_files",
    "material_invoice_delete": "material_invoice",
}


@pytest.fixture(params=sorted(APPLY_SITES))
def approval(request, client, make_user, monkeypatch):
    key = APPLY_SITES[request.param]
    qn = "MQ-T85-G" + key[:3].upper()
    _mk_q(qn)
    h = _login(client, make_user, "t85_req_" + key[:6])
    tmpl, getter = SITES[key]
    url = tmpl % qn
    r = client.post(url, headers=h, files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    _exec("UPDATE quotations SET deal_tag='已結案', case_semi_unlocked=1 WHERE quote_no=?", (qn,))
    from modules.case.api import quotations as Q
    monkeypatch.setattr(Q, "spawn_bg_thread", lambda fn, *a, **k: None)
    r = client.delete(url + "/" + f["id"], headers=h)
    assert r.status_code == 200 and r.json().get("pending") is True, r.text
    cid = r.json()["changeRequestId"]
    su = _login(client, make_user, "t85_su_" + key[:6])
    return client, su, cid, qn, getter, f


def test_apply_delete_on_approve_removes_record_and_file(approval):
    client, su, cid, qn, getter, f = approval
    assert _on_disk([f]) == [f]                         # 申請階段檔案還在
    r = client.post("/api/case-changes/%s/approve" % cid, headers=su)
    assert r.status_code == 200, r.text
    assert _listed(qn, getter) == [] and _on_disk([f]) == []


def test_apply_delete_on_approve_db_failure_keeps_record_and_file(approval):
    """核准途中寫庫失敗（把申請列改成 approved 被擋 ⇒ 整筆 rollback）：紀錄與實體檔都還在、申請仍是 pending。"""
    client, su, cid, qn, getter, f = approval
    _trigger("t85_g_blk", "UPDATE OF status", "case_change_requests")
    try:
        with pytest.raises(Exception):
            client.post("/api/case-changes/%s/approve" % cid, headers=su)
    finally:
        _untrigger("t85_g_blk")
    assert [x["id"] for x in _listed(qn, getter)] == [f["id"]] and _on_disk([f]) == [f]
    assert _rows("SELECT status FROM case_change_requests WHERE id=?", (cid,))[0]["status"] == "pending"


def test_apply_delete_file_removed_after_commit_and_lock_release(approval, monkeypatch):
    client, su, cid, qn, getter, f = approval
    seen = _spy_remove(monkeypatch, lambda _t: {"listed": [x["id"] for x in _listed(qn, getter)],
                                                "status": _rows("SELECT status FROM case_change_requests WHERE id=?", (cid,))[0]["status"],
                                                "lock_free": _lock_free_probe()})
    assert client.post("/api/case-changes/%s/approve" % cid, headers=su).status_code == 200
    assert seen == [{"listed": [], "status": "approved", "lock_free": True}], seen


def test_apply_delete_file_already_gone_fails_cleanly_and_keeps_request_pending(approval):
    """申請之後同一個附件已被別人刪掉：核准回 404，不誤刪、申請維持 pending（沿用原行為）。"""
    client, su, cid, qn, getter, f = approval
    d = json.loads(_rows("SELECT data_json FROM quotations WHERE quote_no=?", (qn,))[0]["data_json"])
    getter(d["caseRecord"]).clear()
    _exec("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), qn))
    r = client.post("/api/case-changes/%s/approve" % cid, headers=su)
    assert r.status_code == 404, r.text
    assert _rows("SELECT status FROM case_change_requests WHERE id=?", (cid,))[0]["status"] == "pending"


# ───────────────────────────── helper 單元 ─────────────────────────────

def test_pop_document_file_does_not_touch_disk_and_404s_on_missing(tmp_path):
    import helpers.uploads as up
    from fastapi import HTTPException
    p = tmp_path / "x.bin"
    p.write_bytes(b"1")
    files = [{"id": "a", "path": "x"}, {"id": "b", "path": "y"}, "junk"]
    gone, rest = up.pop_document_file(files, "a")
    assert gone["id"] == "a" and [x for x in rest if isinstance(x, dict)] == [{"id": "b", "path": "y"}] and "junk" in rest
    assert p.exists()
    with pytest.raises(HTTPException) as e:
        up.pop_document_file(files, "zzz")
    assert e.value.status_code == 404
