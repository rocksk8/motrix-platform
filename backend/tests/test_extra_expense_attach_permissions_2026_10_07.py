# -*- coding: utf-8 -*-
"""支出申請附件的增刪權限與狀態規則、HEIC（第44班，使用者 2026-10-07 裁示）：
申請人本人與管理員只能在 草稿／待審核（含簽核中）／已駁回 增刪；簽核人（非申請人）唯讀；核准後上鎖（只剩發票補上傳）；
作廢保留檔案不可動；HEIC 收原檔（檔頭要對）、下載時一律 attachment。
"""
import io
import json

import pytest

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01 額外支出的附件端點")

NO = "MQ-XAP-001"
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"0" * 32


def _login(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    finally:
        conn.close()
    return u, uid, {"Authorization": "Bearer " + r.json()["token"]}


def _case(uids):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "測客", "測專", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已成案", "", json.dumps(uids)))
        conn.commit()
    finally:
        conn.close()


def _set(eid, **cols):
    import db
    conn = db.get_db()
    try:
        for k, v in cols.items():
            conn.execute("UPDATE case_extra_expenses SET %s=? WHERE id=?" % k, (v, eid))
        conn.commit()
    finally:
        conn.close()


def _up(client, h, eid, name="a.pdf", data=b"%PDF-1.4\n" + b"0" * 32, kind="other"):
    return client.post("/api/quotations/%s/extra-expenses/%s/files" % (NO, eid), headers=h,
                       files=[("files", (name, io.BytesIO(data), "application/octet-stream"))], data={"kind": kind})


def _del(client, h, eid, fid):
    return client.delete("/api/quotations/%s/extra-expenses/%s/files/%s" % (NO, eid, fid), headers=h)


@pytest.fixture
def world(client, make_user, seed_extra_expense):
    owner, oid, ho = _login(client, make_user, "xap_owner", "sales")
    _, aid, ha = _login(client, make_user, "xap_approver", "sales")
    _, _, hs = _login(client, make_user, "xap_admin", "superadmin")
    _case([oid, aid])

    def mk(status):
        eid = seed_extra_expense(NO, total_cost=1000, description="權限題", status=status)
        _set(eid, created_by=owner)
        return eid
    return client, ho, ha, hs, mk


@pytest.mark.parametrize("status", ["草稿", "待審核", "簽核中", "已駁回"])
def test_applicant_and_admin_can_add_and_delete_in_editable_statuses(world, status):
    client, ho, ha, hs, mk = world
    eid = mk(status)
    r = _up(client, ho, eid, "mine.pdf")
    assert r.status_code == 201, r.text
    fid = r.json()["files"][0]["id"]
    r = _up(client, hs, eid, "admin.pdf")
    assert r.status_code == 201, r.text
    assert _del(client, ho, eid, fid).status_code == 200
    assert _del(client, hs, eid, r.json()["files"][0]["id"]).status_code == 200


@pytest.mark.parametrize("status", ["草稿", "待審核", "簽核中", "已駁回"])
def test_non_applicant_non_admin_is_read_only(world, status):
    client, ho, ha, hs, mk = world
    eid = mk(status)
    fid = _up(client, ho, eid).json()["files"][0]["id"]
    assert _up(client, ha, eid, "x.pdf").status_code == 403
    assert _del(client, ha, eid, fid).status_code == 403
    assert _del(client, ho, eid, fid).status_code == 200, "申請人本人仍可刪（上面的 403 沒有誤動檔案）"


def test_approved_is_locked_except_invoice_supplement(world):
    client, ho, ha, hs, mk = world
    eid = mk("已核准")
    assert _up(client, ho, eid, "o.pdf", kind="other").status_code == 409, "核准後其他類不可加"
    r = _up(client, ho, eid, "inv.pdf", kind="invoice")
    assert r.status_code == 201, r.text
    assert _del(client, ho, eid, r.json()["files"][0]["id"]).status_code == 409, "核准後不可刪（含自己補的發票）"
    assert _del(client, hs, eid, r.json()["files"][0]["id"]).status_code == 409, "管理員也一樣上鎖"
    assert _up(client, ha, eid, "inv2.pdf", kind="invoice").status_code == 403, "核准後補發票限填寫人／管理員／出納"


def test_voided_keeps_files_and_refuses_changes(world):
    client, ho, ha, hs, mk = world
    eid = mk("草稿")
    fid = _up(client, ho, eid).json()["files"][0]["id"]
    _set(eid, status="已作廢")
    assert _up(client, ho, eid, "x.pdf").status_code == 409
    assert _del(client, hs, eid, fid).status_code == 409
    import db
    conn = db.get_db()
    try:
        assert len(json.loads(conn.execute("SELECT files_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["files_json"])) == 1
    finally:
        conn.close()


@pytest.mark.upload_magic
def test_heic_original_is_accepted_and_served_as_download(world):
    client, ho, ha, hs, mk = world
    eid = mk("草稿")
    r = _up(client, ho, eid, "IMG_0001.HEIC", HEIC)
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    assert f["path"].lower().endswith(".heic")
    g = client.get("/api/uploads/" + f["path"], headers=ho)
    assert g.status_code == 200 and g.content == HEIC
    assert g.headers.get("content-disposition", "").lower().startswith("attachment"), "HEIC 檢視＝下載"
    assert _up(client, ho, eid, "b.heif", HEIC).status_code == 201


@pytest.mark.upload_magic
def test_fake_heic_is_refused_by_magic_check(world):
    client, ho, ha, hs, mk = world
    eid = mk("草稿")
    r = _up(client, ho, eid, "fake.heic", b"this is not heic at all")
    assert r.status_code == 400 and "檔頭" in r.json()["detail"], r.text


def test_heic_is_not_allowed_for_other_document_folders():
    """放行只限支出申請資料夾；傳票附件等其他資料夾不因此多收 HEIC。"""
    from helpers import uploads as U
    assert {".heic", ".heif"} <= U._EXTRA_EXTS_BY_SUBFOLDER["case_extra_expense"]
    assert not ({".heic", ".heif"} & U._EXTRA_EXTS_BY_SUBFOLDER["voucher_attachments"])
