# -*- coding: utf-8 -*-
"""工作日誌照片上傳：任何路徑都不留「磁碟上有檔、卻沒有紀錄指向它」的孤兒檔（fix/worklog-orphan-files；接在 image-bomb 之後）。

image-bomb 已處理「批次中途 400／503／斷線」（tests/test_image_guard_2026_11_13.py）。這裡補三條仍會留孤兒的路徑：
  ① 兩個請求同時往同一筆日誌上傳：各自讀到上傳前的 photos、整包寫回，後寫的蓋掉先寫的 ⇒ 先寫那一批的檔沒有紀錄（lost update）
  ② 日誌在上傳途中被刪掉：檔已寫、UPDATE 影響 0 列、回 201 卻什麼都沒存
  ③ 寫回 photos 時資料庫出錯：檔已寫、紀錄沒存
修法：慢動作（解碼、寫檔）做完才拿寫鎖、重讀目前的 photos、只加上自己這一批；任何失敗都回收這次剛寫入的檔。
"""
import json
import os

import pytest

from tests.test_image_guard_2026_11_13 import _auth, _real_png


def _files_under(path):
    out = []
    for root, _d, names in os.walk(path):
        out += [os.path.join(root, n) for n in names]
    return out


def _new_log(client, make_user, name):
    h = _auth(client, make_user, name)
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    conn.close()
    wid = client.post("/api/work-logs", headers=h, json={"log_date": "2026-11-13", "user_id": uid, "content": "x"}).json()["id"]
    return h, wid


def _upload(client, h, wid, n=1):
    return client.post(f"/api/work-logs/{wid}/photos", headers=h,
                       files=[("files", ("p%d.png" % i, _real_png(), "image/png")) for i in range(n)])


def _photos(wid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT photos FROM work_logs WHERE id=?", (wid,)).fetchone()
        return json.loads(row["photos"] or "[]") if row else None
    finally:
        conn.close()


def _dir(wid):
    from routers import system
    base, _prefix = system._photo_root()
    return os.path.join(base, "worklog_%s" % wid)


def test_concurrent_upload_does_not_overwrite_the_other_requests_photos(client, make_user, monkeypatch):
    """請求 A 解碼途中，另一個請求 B 已經把照片寫進同一筆日誌：A 寫回時要保留 B 的，不能整包蓋掉（蓋掉 ⇒ B 的檔成孤兒）。"""
    from routers import system
    h, wid = _new_log(client, make_user, "wo_conc")
    real = system.run_decode
    injected = {"id": "other001", "filename": "other.png", "path": "x/other.png", "uploaded_by": "B", "uploaded_at": "2026-11-13T00:00:00"}
    state = {"done": False}

    async def interleaved(fn, *a, **kw):
        if not state["done"]:
            state["done"] = True
            import db
            conn = db.get_db()
            conn.execute("UPDATE work_logs SET photos=? WHERE id=?", (json.dumps([injected]), wid))     # 請求 B 在 A 解碼期間完成
            conn.commit()
            conn.close()
        return await real(fn, *a, **kw)
    monkeypatch.setattr(system, "run_decode", interleaved)
    r = _upload(client, h, wid)
    assert r.status_code == 201, r.text
    ids = [p["id"] for p in _photos(wid)]
    assert "other001" in ids and len(ids) == 2, ids                      # B 的紀錄還在、A 的也加進去
    assert len(_files_under(_dir(wid))) == 1                              # A 寫的那一個檔有紀錄指向它


def test_log_deleted_mid_upload_leaves_no_files(client, make_user, monkeypatch):
    from routers import system
    h, wid = _new_log(client, make_user, "wo_del")
    real = system.run_decode

    async def delete_then_decode(fn, *a, **kw):
        import db
        conn = db.get_db()
        conn.execute("DELETE FROM work_logs WHERE id=?", (wid,))
        conn.commit()
        conn.close()
        return await real(fn, *a, **kw)
    monkeypatch.setattr(system, "run_decode", delete_then_decode)
    r = _upload(client, h, wid, n=2)
    assert r.status_code == 404, (r.status_code, r.text[:200])
    assert _files_under(_dir(wid)) == []


def test_db_error_when_saving_the_record_leaves_no_files(client, make_user):
    h, wid = _new_log(client, make_user, "wo_dberr")
    import db
    conn = db.get_db()
    conn.execute("CREATE TRIGGER wo_block_photos BEFORE UPDATE OF photos ON work_logs BEGIN SELECT RAISE(ABORT, 'blocked-by-test'); END")
    conn.commit()
    conn.close()
    try:
        with pytest.raises(Exception):
            _upload(client, h, wid, n=2)
    finally:
        conn = db.get_db()
        conn.execute("DROP TRIGGER IF EXISTS wo_block_photos")
        conn.commit()
        conn.close()
    assert _files_under(_dir(wid)) == []
    assert not (_photos(wid) or [])


def test_normal_upload_still_works_and_appends(client, make_user):
    """正對照：一般上傳照舊；第二次上傳是附加不是覆蓋。"""
    h, wid = _new_log(client, make_user, "wo_ok")
    assert _upload(client, h, wid, n=2).status_code == 201
    r = _upload(client, h, wid, n=1)
    assert r.status_code == 201 and r.json()["added"] == 1
    assert len(_photos(wid)) == 3 and len(_files_under(_dir(wid))) == 3
