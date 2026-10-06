# -*- coding: utf-8 -*-
"""附件上限是 check-then-act（稽核 hichan-68）：上傳前讀到的數量，與寫回時的清單可能已被同時進來的另一批改掉。
修法：檔案存好後才拿寫鎖、重讀、重驗數量與狀態，只把自己這批併進最新清單；超過就刪掉剛存的檔並 400。
"""
import io
import json
import os

import pytest

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01 額外支出的附件端點")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
NO = "MQ-XAR-001"


def _setup(client, make_user, seed_extra_expense):
    u, p = make_user(username="xar_user", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "測客", "測專", 1, 1, json.dumps({"dealTag": "已成案"}),
                                                       "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()
    return h, seed_extra_expense(NO, total_cost=1000, description="競態題", status="草稿")


def _files(eid):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT files_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["files_json"] or "[]")
    finally:
        conn.close()


def _concurrent(monkeypatch, eid, n):
    """在「存檔」這個 await 期間，另一批已經把 n 個附件寫進 files_json。"""
    from modules.case.api import case_extra_expenses as M
    real = M.save_document_files

    async def wrapped(*a, **k):
        out = await real(*a, **k)
        import db
        conn = db.get_db()
        try:
            conn.execute("UPDATE case_extra_expenses SET files_json=? WHERE id=?",
                         (json.dumps([{"id": "cc%d" % i, "filename": "c%d.pdf" % i, "kind": "other"} for i in range(n)]), eid))
            conn.commit()
        finally:
            conn.close()
        return out
    monkeypatch.setattr(M, "save_document_files", wrapped)


def _up(client, h, eid):
    return client.post("/api/quotations/%s/extra-expenses/%s/files" % (NO, eid), headers=h,
                       files=[("files", ("mine.pdf", io.BytesIO(b"%PDF-1.4\n" + b"0" * 32), "application/pdf"))])


def test_concurrent_batch_filling_the_cap_makes_this_one_fail_without_orphans(client, make_user, seed_extra_expense, monkeypatch):
    h, eid = _setup(client, make_user, seed_extra_expense)
    _concurrent(monkeypatch, eid, 10)
    r = _up(client, h, eid)
    assert r.status_code == 400 and "10" in r.json()["detail"], r.text
    assert len(_files(eid)) == 10, "另一批的 10 個沒被蓋掉、也沒多出第 11 個"
    from helpers import uploads as U
    d = os.path.join(U.UPLOADS_ROOT, "case_extra_expense", "%s_%s" % (NO, eid))
    assert not os.path.isdir(d) or os.listdir(d) == [], "被擋的這批已存的實體檔案要刪掉"


def test_concurrent_batch_is_merged_not_overwritten(client, make_user, seed_extra_expense, monkeypatch):
    h, eid = _setup(client, make_user, seed_extra_expense)
    _concurrent(monkeypatch, eid, 1)
    r = _up(client, h, eid)
    assert r.status_code == 201, r.text
    names = sorted(f["filename"] for f in _files(eid))
    assert names == ["c0.pdf", "mine.pdf"], "從過期的列整包寫回會丟掉同時進來的那一批"


def test_status_changed_during_upload_purges_new_files(client, make_user, seed_extra_expense, monkeypatch):
    h, eid = _setup(client, make_user, seed_extra_expense)
    from modules.case.api import case_extra_expenses as M
    real = M.save_document_files

    async def wrapped(*a, **k):
        out = await real(*a, **k)
        import db
        conn = db.get_db()
        try:
            conn.execute("UPDATE case_extra_expenses SET status='已作廢' WHERE id=?", (eid,))
            conn.commit()
        finally:
            conn.close()
        return out
    monkeypatch.setattr(M, "save_document_files", wrapped)
    r = _up(client, h, eid)
    assert r.status_code == 409, r.text
    from helpers import uploads as U
    d = os.path.join(U.UPLOADS_ROOT, "case_extra_expense", "%s_%s" % (NO, eid))
    assert not os.path.isdir(d) or os.listdir(d) == [], "上傳途中單據被作廢 ⇒ 剛存的檔不留孤兒"
