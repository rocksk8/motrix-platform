# -*- coding: utf-8 -*-
"""附件上傳／刪除：整份 JSON 清單「讀舊值 → 慢動作 → 整份寫回」的 lost update 與孤兒檔（T83，feat/upload-files-txn）。

審計（2026-11-13，19 個 save_document_files 呼叫點）的 C 組六處——上傳前先讀出 existing、存檔（數秒）、再以 existing+new 整份寫回：
  ① 兩個請求同時上傳 ⇒ 後寫的蓋掉先寫的紀錄（先寫那批的檔沒有紀錄、請求卻早已回 201）
  ② 寫庫失敗／單據在上傳途中被刪 ⇒ 檔留在磁碟上沒有紀錄
對應的 DELETE 端點同樣是「讀 → 先刪實體檔 → 整份寫回」：lost update，而且寫庫失敗時紀錄還在、檔已不見。
修法（helpers/uploads.py：files_txn／append_json_list／remove_json_item）：慢動作做完才拿寫鎖、重讀、只加自己這批（刪除只濾掉那一筆）；
失敗一律回收這次剛存的檔；刪除在 commit 之後才刪實體檔。

六處：發票憑據已開立附件、完工單回簽附件、出貨單回簽附件、報價單客戶回簽單、承攬商報價附件、承攬商發票附件。
每處四題：①上傳途中別人寫進同一列 ⇒ 兩邊都在 ②寫庫失敗 ⇒ 不留檔 ③單據上傳途中被刪 ⇒ 404 且不留檔 ④刪除途中別人寫進同一列 ⇒ 別人的還在；
外加刪除時寫庫失敗 ⇒ 紀錄與檔都還在。
"""
import importlib
import json
import os

import pytest

from tests.test_signed_upload_files import _auth, _login, _make_invoice_voucher, _make_quotation, _png_file

INJECTED = {"id": "other001", "filename": "other.png", "path": "x/other.png", "uploaded_by": "B", "uploaded_at": "2026-11-13T00:00:00"}


def _exec(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _seed_invoice(no):
    _make_quotation("MQ-T83-IV")
    _make_invoice_voucher(no, "MQ-T83-IV")


def _seed_completion(no):
    _make_quotation("MQ-T83-CN")
    _exec("INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, created_at, updated_at, site_address, "
          "work_summary, items_json, warranty_months) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (no, "MQ-T83-CN", "待審核", "{}", "t83", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "台中", "x", "[]", 12))


def _seed_shipping(no):
    _make_quotation("MQ-T83-SN")
    _exec("INSERT INTO shipping_notes (note_no, quote_no, signed_files_json) VALUES (?,?,?)", (no, "MQ-T83-SN", "[]"))


def _seed_quotation(no):
    _make_quotation(no)


def _seed_dispatch(no):
    _make_quotation("MQ-T83-DP")
    _exec("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, "
          "tax_rate, status, notes, created_by, created_at, updated_at, accepted_at, accepted_by, files_json, invoice_files_json) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (int(no), "MQ-T83-DP", None, "2026-09-01", "測試", "[]", "[]", 500, 0, "已完成", "", "x",
           "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "", "[]", "[]"))


#  name: (router module, table, column, key column, key value, seed, upload url, delete url (含 {fid}))
SITES = {
    "invoice": ("modules.arap.api.invoice_vouchers", "invoice_vouchers", "issued_files_json", "voucher_no", "IV-T83-1", _seed_invoice,
                "/api/invoice-vouchers/IV-T83-1/issued-files", "/api/invoice-vouchers/IV-T83-1/issued-files/{fid}"),
    "completion": ("modules.case.api.completion_notes", "completion_notes", "signed_files_json", "note_no", "CN-T83-1", _seed_completion,
                   "/api/completion-notes/CN-T83-1/signed-files", "/api/completion-notes/CN-T83-1/signed-files/{fid}"),
    "shipping": ("modules.supply.api.shipping_notes", "shipping_notes", "signed_files_json", "note_no", "SN-T83-1", _seed_shipping,
                 "/api/shipping-notes/SN-T83-1/signed-files", "/api/shipping-notes/SN-T83-1/signed-files/{fid}"),
    "quotation": ("modules.case.api.quotations", "quotations", "signed_files_json", "quote_no", "MQ-T83-QT", _seed_quotation,
                  "/api/quotations/MQ-T83-QT/signed-files", "/api/quotations/MQ-T83-QT/signed-files/{fid}"),
    "dispatch_quote": ("modules.subcontract.api.vendor_contractors", "contractor_dispatches", "files_json", "id", 83001, _seed_dispatch,
                       "/api/contractor-dispatches/83001/files", "/api/contractor-dispatches/83001/files/{fid}"),
    "dispatch_invoice": ("modules.subcontract.api.vendor_contractors", "contractor_dispatches", "invoice_files_json", "id", 83001, _seed_dispatch,
                         "/api/contractor-dispatches/83001/invoice-files", "/api/contractor-dispatches/83001/invoice-files/{fid}"),
}


class _Site:
    def __init__(self, name):
        (self.modname, self.table, self.col, self.keycol, self.key, seed, self.up, self.dele) = SITES[name]
        self.mod = importlib.import_module(self.modname)
        self.name = name
        seed(str(self.key))

    def items(self):
        import db
        conn = db.get_db()
        try:
            row = conn.execute("SELECT %s AS v FROM %s WHERE %s=?" % (self.col, self.table, self.keycol), (self.key,)).fetchone()
            return json.loads(row["v"] or "[]") if row else None
        finally:
            conn.close()

    def inject(self):
        import db
        conn = db.get_db()
        try:
            cur = json.loads(conn.execute("SELECT %s AS v FROM %s WHERE %s=?" % (self.col, self.table, self.keycol), (self.key,)).fetchone()["v"] or "[]")
            conn.execute("UPDATE %s SET %s=? WHERE %s=?" % (self.table, self.col, self.keycol), (json.dumps(cur + [INJECTED]), self.key))
            conn.commit()
        finally:
            conn.close()

    def drop_row(self):
        _exec("DELETE FROM %s WHERE %s=?" % (self.table, self.keycol), (self.key,))

    def block_updates(self):
        _exec("CREATE TRIGGER t83_block BEFORE UPDATE OF %s ON %s BEGIN SELECT RAISE(ABORT, 'blocked-by-test'); END" % (self.col, self.table))

    def unblock(self):
        _exec("DROP TRIGGER IF EXISTS t83_block")


def _on_disk(entries):
    import helpers.uploads as up
    return [e for e in entries if os.path.isfile(os.path.join(up.UPLOADS_ROOT, e["path"]))]


@pytest.fixture(params=sorted(SITES))
def site(request, client, make_user):
    s = _Site(request.param)
    username, password = make_user(role="superadmin")
    s.h = _auth(_login(client, username, password))
    s.client = client
    return s


def _spy_save(site, monkeypatch, after=None):
    """包住該 router 的 save_document_files：記下存了哪些檔；存完（＝慢動作剛結束）再執行 after()（模擬別的請求這時剛好寫庫）。"""
    saved = []
    real = site.mod.save_document_files

    async def wrapper(*a, **kw):
        out = await real(*a, **kw)
        saved.extend(out)
        if after is not None:
            after()
        return out
    monkeypatch.setattr(site.mod, "save_document_files", wrapper)
    return saved


def _post(site):
    return site.client.post(site.up, headers=site.h, files={"files": _png_file("a.png")})


def test_upload_keeps_entry_written_by_another_request(site, monkeypatch):
    """上傳（存檔）途中，另一個請求已把一筆附件寫進同一列：寫回要保留它，不能整份蓋掉。"""
    saved = _spy_save(site, monkeypatch, after=site.inject)
    r = _post(site)
    assert r.status_code == 201, r.text
    items = site.items()
    ids = [x["id"] for x in items]
    assert "other001" in ids and len(items) == 2, ids
    assert len(saved) == 1 and saved[0]["id"] in ids
    assert len(_on_disk(saved)) == 1                                       # 自己這批的檔有紀錄指向它


def test_upload_db_error_leaves_no_files(site, monkeypatch):
    """寫庫失敗：這次剛存的檔要回收，不留「磁碟上有檔、沒有紀錄」。"""
    saved = _spy_save(site, monkeypatch)
    site.block_updates()
    try:
        with pytest.raises(Exception):
            _post(site)
    finally:
        site.unblock()
    assert saved and _on_disk(saved) == []
    assert (site.items() or []) == []


def test_upload_row_deleted_midway_is_404_and_leaves_no_files(site, monkeypatch):
    """單據在上傳途中被刪掉：回 404、不留檔（舊寫法 UPDATE 影響 0 列卻回 201）。"""
    saved = _spy_save(site, monkeypatch, after=site.drop_row)
    r = _post(site)
    assert r.status_code == 404, (r.status_code, r.text[:200])
    assert saved and _on_disk(saved) == []


def test_delete_keeps_entry_written_by_another_request(site, monkeypatch):
    """刪除途中別人剛把一筆附件寫進同一列：刪除只濾掉自己那一筆，不能整份寫回蓋掉別人的。"""
    r = _post(site)
    assert r.status_code == 201, r.text
    target = r.json()["files"][0]
    real_remove = os.remove
    state = {"n": 0}

    def remove_and_interleave(p, *a, **kw):
        if state["n"] == 0:
            state["n"] = 1
            site.inject()
        return real_remove(p, *a, **kw)
    monkeypatch.setattr(os, "remove", remove_and_interleave)
    d = site.client.delete(site.dele.format(fid=target["id"]), headers=site.h)
    assert d.status_code == 200, d.text
    assert [x["id"] for x in site.items()] == ["other001"]
    assert state["n"] == 1
    assert _on_disk([target]) == []                                        # 目標的實體檔確實刪了


def test_delete_db_error_keeps_record_and_file(site):
    """刪除時寫庫失敗：紀錄與實體檔都要還在（舊寫法先刪檔 ⇒ 紀錄還在、檔已不見）。"""
    r = _post(site)
    assert r.status_code == 201, r.text
    target = r.json()["files"][0]
    site.block_updates()
    try:
        with pytest.raises(Exception):
            site.client.delete(site.dele.format(fid=target["id"]), headers=site.h)
    finally:
        site.unblock()
    assert [x["id"] for x in site.items()] == [target["id"]]
    assert len(_on_disk([target])) == 1


def test_normal_upload_appends_and_delete_removes(site):
    """正對照：第二次上傳是附加不是覆蓋；刪除只刪指定那一筆（紀錄與檔都沒了），不存在的附件回 404。"""
    a = _post(site).json()["files"][0]
    b = _post(site).json()["files"][0]
    assert [x["id"] for x in site.items()] == [a["id"], b["id"]]
    assert site.client.delete(site.dele.format(fid=a["id"]), headers=site.h).status_code == 200
    assert [x["id"] for x in site.items()] == [b["id"]]
    assert _on_disk([a]) == [] and len(_on_disk([b])) == 1
    assert site.client.delete(site.dele.format(fid=a["id"]), headers=site.h).status_code == 404


# ── 承攬商報價附件：刪除申請核可（走完簽核才真的刪）：刪附件與「申請列改已核可」同一個寫交易 ──

def _dispatch_request_then_approve(client, make_user, monkeypatch, interleave):
    _seed_dispatch("83001")
    su, sp = make_user(username="t83_su", role="superadmin")
    hs = _auth(_login(client, su, sp))
    au, ap = make_user(username="t83_ad", role="admin")
    ha = _auth(_login(client, au, ap))
    up = client.post("/api/contractor-dispatches/83001/files", headers=hs, files={"files": _png_file("q.png")})
    assert up.status_code == 201, up.text
    target = up.json()["files"][0]
    r = client.request("DELETE", "/api/contractor-dispatches/83001/files/%s" % target["id"], headers=ha, json={"reason": "t83"})
    assert r.status_code == 200 and r.json().get("pending") is True, r.text          # 沒簽核層、申請人不是最高管理者 ⇒ 待審
    if interleave:
        real_remove = os.remove
        state = {"n": 0}

        def remove_and_interleave(p, *a, **kw):
            if state["n"] == 0:
                state["n"] = 1
                import db
                conn = db.get_db()
                cur = json.loads(conn.execute("SELECT files_json FROM contractor_dispatches WHERE id=83001").fetchone()[0] or "[]")
                conn.execute("UPDATE contractor_dispatches SET files_json=? WHERE id=83001", (json.dumps(cur + [INJECTED]),))
                conn.commit()
                conn.close()
            return real_remove(p, *a, **kw)
        monkeypatch.setattr(os, "remove", remove_and_interleave)
    a = client.post("/api/contractor-dispatches/83001/files/%s/delete-approve" % target["id"], headers=hs)
    assert a.status_code == 200, a.text
    return target, a.json()


def test_dispatch_delete_approve_removes_file_and_closes_request(client, make_user, monkeypatch):
    target, out = _dispatch_request_then_approve(client, make_user, monkeypatch, interleave=False)
    assert out["deleted"] is True
    import db
    conn = db.get_db()
    try:
        assert json.loads(conn.execute("SELECT files_json FROM contractor_dispatches WHERE id=83001").fetchone()[0]) == []
        assert conn.execute("SELECT status FROM dispatch_file_delete_requests WHERE dispatch_id=83001").fetchone()[0] == "已核可"
    finally:
        conn.close()
    assert _on_disk([target]) == []


def test_dispatch_delete_approve_keeps_entry_written_by_another_request(client, make_user, monkeypatch):
    target, out = _dispatch_request_then_approve(client, make_user, monkeypatch, interleave=True)
    import db
    conn = db.get_db()
    try:
        ids = [x["id"] for x in json.loads(conn.execute("SELECT files_json FROM contractor_dispatches WHERE id=83001").fetchone()[0])]
    finally:
        conn.close()
    assert ids == ["other001"], ids


def test_upload_lock_timeout_leaves_no_files(site, monkeypatch):
    """拿寫鎖失敗（BEGIN IMMEDIATE：database is locked，正是爭用時會發生的事）：with 不會呼叫 __exit__，
    所以 files_txn.__enter__ 自己要回收剛存的檔（審查 hichan-12 M1）。"""
    import sqlite3
    import core.txn as ctxn
    saved = _spy_save(site, monkeypatch)

    def locked(conn):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ctxn, "begin_write", locked)
    with pytest.raises(Exception):
        _post(site)
    assert saved and _on_disk(saved) == []
    assert (site.items() or []) == []


def test_files_txn_releases_lock_before_purging(client, monkeypatch):
    """失敗路徑：先 rollback＋關連線（放掉寫鎖）再刪檔——刪檔時不可還握著寫鎖。"""
    import db
    import helpers.uploads as up
    conn = db.get_db()
    order = []
    real_purge = up.purge_document_files

    def spy_purge(files):
        try:
            conn.execute("SELECT 1")
            order.append("purge-with-open-conn")
        except Exception:
            order.append("purge-after-close")
        return real_purge(files)
    monkeypatch.setattr(up, "purge_document_files", spy_purge)
    with pytest.raises(RuntimeError):
        with up.files_txn(conn, []):
            raise RuntimeError("boom")
    assert order == ["purge-after-close"], order
