# -*- coding: utf-8 -*-
"""支出申請附件的數量／大小上限與孤兒檔清除（第44班，使用者 2026-10-07 裁示）：
每張單據最多 10 個附件、單檔 20MB、一次送出合計 50MB；整批全存或全不存（不留孤兒檔）；草稿／已駁回刪除時一併刪實體檔案。
上限寫在 `helpers/uploads.py::UPLOAD_LIMITS_BY_SUBFOLDER`（只有 case_extra_expense 有；其他資料夾行為不變）。
"""
import asyncio
import io
import os

import pytest

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01 額外支出的附件端點")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
NO = "MQ-XAC-001"
MB = 1024 * 1024


def _auth(client, make_user, name="xac_user"):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _case():
    import db
    import json
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "測客", "測專", 100000, 95238, json.dumps({"dealTag": "已成案"}),
                                                       "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _pdf(n=64):
    return b"%PDF-1.4\n" + b"0" * max(0, n - 9)


def _upload(client, h, eid, parts):
    files = [("files", (name, io.BytesIO(data), "application/pdf")) for name, data in parts]
    return client.post("/api/quotations/%s/extra-expenses/%s/files" % (NO, eid), headers=h, files=files)


def _dir(eid):
    from helpers import uploads as U
    return os.path.join(U.UPLOADS_ROOT, "case_extra_expense", "%s_%s" % (NO, eid))


def _files_on_disk(eid):
    d = _dir(eid)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _files_json(eid):
    import db
    import json
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT files_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["files_json"] or "[]")
    finally:
        conn.close()


@pytest.fixture
def doc(client, make_user, seed_extra_expense):
    h = _auth(client, make_user)
    _case()
    eid = seed_extra_expense(NO, total_cost=1000, description="附件上限題", status="草稿")
    return client, h, eid


def test_ten_files_are_accepted_and_the_eleventh_is_refused(doc):
    client, h, eid = doc
    r = _upload(client, h, eid, [("a%d.pdf" % i, _pdf()) for i in range(10)])
    assert r.status_code == 201 and r.json()["added"] == 10, r.text
    r = _upload(client, h, eid, [("one-more.pdf", _pdf())])
    assert r.status_code == 400 and "10" in r.json()["detail"], r.text
    assert len(_files_json(eid)) == 10 and len(_files_on_disk(eid)) == 10, "被擋的那個沒有存到磁碟"


def test_eleven_files_in_one_request_are_refused_as_a_whole(doc):
    client, h, eid = doc
    r = _upload(client, h, eid, [("b%d.pdf" % i, _pdf()) for i in range(11)])
    assert r.status_code == 400, r.text
    assert _files_json(eid) == [] and _files_on_disk(eid) == [] and not os.path.isdir(_dir(eid)), "整批擋下：不留檔案也不留空目錄"


def test_cap_counts_files_already_attached_across_requests(doc):
    client, h, eid = doc
    assert _upload(client, h, eid, [("c%d.pdf" % i, _pdf()) for i in range(6)]).status_code == 201
    r = _upload(client, h, eid, [("d%d.pdf" % i, _pdf()) for i in range(5)])
    assert r.status_code == 400 and "目前已有 6 個" in r.json()["detail"], r.text
    assert len(_files_json(eid)) == 6 and len(_files_on_disk(eid)) == 6
    assert _upload(client, h, eid, [("e%d.pdf" % i, _pdf()) for i in range(4)]).status_code == 201, "6 + 4 剛好 10 個"


def test_request_total_over_50mb_is_refused_and_nothing_is_stored(doc):
    client, h, eid = doc
    big = _pdf(18 * MB)
    r = _upload(client, h, eid, [("p1.pdf", big), ("p2.pdf", big), ("p3.pdf", big)])        # 54MB（每個都在 20MB 以內）
    assert r.status_code == 400 and "50MB" in r.json()["detail"], r.text
    assert _files_json(eid) == [] and not os.path.isdir(_dir(eid))
    assert _upload(client, h, eid, [("p1.pdf", big), ("p2.pdf", big)]).status_code == 201, "兩個 36MB 可以"


def test_single_file_over_20mb_is_still_refused(doc):
    client, h, eid = doc
    r = _upload(client, h, eid, [("huge.pdf", _pdf(21 * MB))])
    assert r.status_code == 400 and "20MB" in r.json()["detail"], r.text


@pytest.mark.upload_magic          # 這一題要驗真的檔頭判定（conftest 預設把 _magic_matches 換成一律符合）
def test_a_bad_file_in_the_batch_leaves_no_orphans_from_the_good_ones(doc):
    client, h, eid = doc
    r = _upload(client, h, eid, [("ok1.pdf", _pdf()), ("ok2.pdf", _pdf()), ("evil.exe", b"MZ" + b"0" * 30)])
    assert r.status_code == 400, r.text
    assert _files_json(eid) == [] and _files_on_disk(eid) == [] and not os.path.isdir(_dir(eid)), "前面兩個好檔也不能留在磁碟上（原本會成孤兒檔）"
    r = _upload(client, h, eid, [("ok1.pdf", _pdf()), ("fake.pdf", b"not really a pdf at all")])        # 檔頭不符
    assert r.status_code == 400, r.text
    assert _files_on_disk(eid) == []


def test_other_folders_are_not_capped_by_this_table():
    """上限表只列 case_extra_expense：別的資料夾（例：報價單回簽）沒有數量上限，行為與之前相同。"""
    from fastapi import UploadFile
    from helpers import uploads as U
    assert set(U.UPLOAD_LIMITS_BY_SUBFOLDER) == {"case_extra_expense"}
    ups = [UploadFile(filename="s%d.pdf" % i, file=io.BytesIO(_pdf())) for i in range(12)]
    import tempfile
    old = U.UPLOADS_ROOT
    with tempfile.TemporaryDirectory() as td:
        U.UPLOADS_ROOT = td
        try:
            saved = asyncio.run(U.save_document_files("quotations", "Q-CAP-1", ups, "tester"))
        finally:
            U.UPLOADS_ROOT = old
    assert len(saved) == 12


def test_deleting_a_draft_deletes_its_files_and_folder(doc):
    client, h, eid = doc
    assert _upload(client, h, eid, [("x1.pdf", _pdf()), ("x2.pdf", _pdf())]).status_code == 201
    assert len(_files_on_disk(eid)) == 2
    r = client.delete("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h)
    assert r.status_code == 200, r.text
    assert _files_on_disk(eid) == [] and not os.path.isdir(_dir(eid)), "草稿刪除後實體檔案與資料夾都清掉（原本會留成孤兒檔）"


def test_deleting_a_rejected_doc_also_purges_but_other_docs_keep_their_files(doc, seed_extra_expense):
    client, h, eid = doc
    other = seed_extra_expense(NO, total_cost=2000, description="別張單據", status="草稿")
    assert _upload(client, h, eid, [("y1.pdf", _pdf())]).status_code == 201
    assert _upload(client, h, other, [("z1.pdf", _pdf())]).status_code == 201
    import db
    conn = db.get_db()
    conn.execute("UPDATE case_extra_expenses SET status='已駁回' WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    assert client.delete("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h).status_code == 200
    assert _files_on_disk(eid) == []
    assert len(_files_on_disk(other)) == 1, "只清這一張的檔案，別張單據的不受影響"


def test_approved_docs_cannot_be_deleted_so_their_files_stay(doc):
    client, h, eid = doc
    assert _upload(client, h, eid, [("k1.pdf", _pdf())]).status_code == 201
    import db
    conn = db.get_db()
    conn.execute("UPDATE case_extra_expenses SET status='已核准' WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    r = client.delete("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h)
    assert r.status_code == 409
    assert len(_files_on_disk(eid)) == 1


def test_purge_helper_ignores_paths_outside_uploads(tmp_path):
    """purge_document_files 只認 uploads 根目錄底下的正規路徑：`../` 與絕對路徑一律略過，不刪任何東西。"""
    from helpers import uploads as U
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    n = U.purge_document_files([{"path": "../../" + victim.name}, {"path": str(victim)}, {"path": ""}, {"nopath": 1}, "junk"])
    assert n == 0 and victim.exists()


def test_change_request_upload_counts_official_plus_pending_files(doc):
    """核准後的變更申請：待核准附件核准後會併進正式清單 ⇒ 正式（8）＋待核准（2）合計不可超過 10。"""
    client, h, eid = doc
    import db
    import json
    official = [{"id": "o%d" % i, "filename": "old%d.pdf" % i, "path": "case_extra_expense/%s_%s/old%d.pdf" % (NO, eid, i), "size": 1, "kind": "other"} for i in range(8)]
    conn = db.get_db()
    conn.execute("UPDATE case_extra_expenses SET status='已核准', files_json=? WHERE id=?", (json.dumps(official), eid))
    conn.commit()
    conn.close()
    r = client.put("/api/quotations/%s/extra-expenses/%s/change-request" % (NO, eid), headers=h,
                   json={"category": "其他", "description": "補憑證", "qty": 1, "unit": "", "unitCost": 1000})
    assert r.status_code in (200, 201), r.text
    url = "/api/quotations/%s/extra-expenses/%s/change-request/files" % (NO, eid)
    ok = client.post(url, headers=h, files=[("files", ("n%d.pdf" % i, io.BytesIO(_pdf()), "application/pdf")) for i in range(2)])
    assert ok.status_code == 201, ok.text
    over = client.post(url, headers=h, files=[("files", ("n9.pdf", io.BytesIO(_pdf()), "application/pdf"))])
    assert over.status_code == 400 and "目前已有 10 個" in over.json()["detail"], over.text
