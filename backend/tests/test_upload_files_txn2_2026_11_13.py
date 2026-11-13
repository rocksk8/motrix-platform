# -*- coding: utf-8 -*-
"""T84（feat/upload-files-txn-2，接在 T83 之後）：審計 19 個 save_document_files 呼叫點裡 A／G／D 三組的孤兒檔與鬼申請。

A 組（已是「先存檔、再拿鎖重讀」，只缺「失敗回收剛存的檔」）：款項發票附件、叫料附件、叫料發票附件、案件留言補附件
G 組（已結案半解鎖案件的上傳類變更）：舊作法先建 pending 申請（立刻通知）再存檔 ⇒ 存檔失敗留下沒有檔案的「鬼申請」
D 組（INSERT 型，沒有整份寫回）：傳票附件（上傳／帶入）、案件留言、業務開發記錄、自訂模組暫存附件
  傳票另有 TOCTOU：「只有草稿能加附件」的檢查在上傳之前，上傳途中被送審／作廢仍會加進去（加了也刪不掉）⇒ 鎖內重查

觀測點一律在磁碟上（檔還在不在）與資料表（列有沒有），不看回應。
"""
import json
import os

import pytest

from tests.test_payment_item_and_material_uploads import _make_quotation as _mk_q

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _login(client, make_user, name, role="superadmin", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
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


def _spy(monkeypatch, mod, attr="save_document_files", after=None):
    """包住 mod.<attr>：記下存了哪些檔；存完（＝慢動作剛結束）再執行 after()（模擬那一刻別的請求／狀態變化）。"""
    saved = []
    real = getattr(mod, attr)

    async def wrapper(*a, **kw):
        out = await real(*a, **kw)
        saved.extend(out)
        if after is not None:
            after()
        return out
    monkeypatch.setattr(mod, attr, wrapper)
    return saved


def _trigger(name, event, table):
    _exec("CREATE TRIGGER %s BEFORE %s ON %s BEGIN SELECT RAISE(ABORT, 'blocked-by-test'); END" % (name, event, table))


def _untrigger(name):
    _exec("DROP TRIGGER IF EXISTS %s" % name)


# ───────────────────────────── A 組：叫料／款項附件 ─────────────────────────────

A_SITES = {
    "payment_invoice": ("/api/quotations/MQ-T84-A/payment/0/invoice-files", "payment"),
    "material_files": ("/api/quotations/MQ-T84-A/materials/0/files", "materials"),
    "material_invoice": ("/api/quotations/MQ-T84-A/materials/0/invoice-files", "materials"),
}


@pytest.fixture(params=sorted(A_SITES))
def a_site(request, client, make_user):
    _mk_q("MQ-T84-A")
    h = _login(client, make_user, "t84_a")
    url, kind = A_SITES[request.param]
    return client, h, url, kind


def _post_png(client, h, url, name="a.png"):
    return client.post(url, headers=h, files={"files": (name, PNG, "image/png")})


def test_a_db_error_leaves_no_files(a_site, monkeypatch):
    client, h, url, kind = a_site
    from modules.case.api import quotations as Q
    saved = _spy(monkeypatch, Q)
    _trigger("t84_a_blk", "UPDATE OF data_json", "quotations")
    try:
        with pytest.raises(Exception):
            _post_png(client, h, url)
    finally:
        _untrigger("t84_a_blk")
    assert saved and _on_disk(saved) == []


def test_a_item_removed_midway_is_rejected_and_leaves_no_files(a_site, monkeypatch):
    client, h, url, kind = a_site
    from modules.case.api import quotations as Q

    def drop_items():
        d = json.loads(_rows("SELECT data_json FROM quotations WHERE quote_no='MQ-T84-A'")[0]["data_json"])
        cr = d["caseRecord"]
        if kind == "payment":
            cr["payment"]["items"] = []
        else:
            cr["materials"] = []
        _exec("UPDATE quotations SET data_json=? WHERE quote_no='MQ-T84-A'", (json.dumps(d),))
    saved = _spy(monkeypatch, Q, after=drop_items)
    r = _post_png(client, h, url)
    assert r.status_code in (400, 404), (r.status_code, r.text[:200])
    assert saved and _on_disk(saved) == []


def test_a_normal_upload_still_works(a_site):
    client, h, url, kind = a_site
    r = _post_png(client, h, url)
    assert r.status_code == 201, r.text
    assert _on_disk(r.json()["files"]) and len(r.json()["files"]) == 1


# ───────────────────────────── A 組：案件留言補附件 ─────────────────────────────

def _case_update(client, h, q="MQ-T84-U"):
    _mk_q(q)
    r = client.post("/api/quotations/%s/updates" % q, headers=h, data={"content": "現場"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_case_update_add_files_db_error_leaves_no_files(client, make_user, monkeypatch):
    h = _login(client, make_user, "t84_u")
    uid = _case_update(client, h)
    from modules.case.api import quotations as Q
    saved = _spy(monkeypatch, Q)
    _trigger("t84_u_blk", "UPDATE OF files_json", "case_updates")
    try:
        with pytest.raises(Exception):
            client.post("/api/quotations/MQ-T84-U/updates/%s/files" % uid, headers=h, files={"files": ("a.png", PNG, "image/png")})
    finally:
        _untrigger("t84_u_blk")
    assert saved and _on_disk(saved) == []


def test_a_case_update_add_files_comment_deleted_midway_is_404_no_files(client, make_user, monkeypatch):
    h = _login(client, make_user, "t84_u2")
    uid = _case_update(client, h, "MQ-T84-U2")
    from modules.case.api import quotations as Q
    saved = _spy(monkeypatch, Q, after=lambda: _exec("DELETE FROM case_updates WHERE id=?", (uid,)))
    r = client.post("/api/quotations/MQ-T84-U2/updates/%s/files" % uid, headers=h, files={"files": ("a.png", PNG, "image/png")})
    assert r.status_code == 404, r.text
    assert saved and _on_disk(saved) == []


# ───────────────────────────── D 組：案件留言（INSERT） ─────────────────────────────

def test_d_post_case_update_insert_error_leaves_no_files(client, make_user, monkeypatch):
    h = _login(client, make_user, "t84_p")
    _mk_q("MQ-T84-P")
    from modules.case.api import quotations as Q
    saved = _spy(monkeypatch, Q)
    _trigger("t84_p_blk", "INSERT", "case_updates")
    try:
        with pytest.raises(Exception):
            client.post("/api/quotations/MQ-T84-P/updates", headers=h, data={"content": "x"}, files={"files": ("a.png", PNG, "image/png")})
    finally:
        _untrigger("t84_p_blk")
    assert saved and _on_disk(saved) == []
    assert _rows("SELECT COUNT(*) AS n FROM case_updates WHERE quote_no='MQ-T84-P'")[0]["n"] == 0


def test_d_post_case_update_bad_file_closes_connection_and_adds_no_row(client, make_user):
    """存檔失敗（400）：不留留言列、也不再漏關連線（舊寫法 save 丟例外時 conn 沒關）。"""
    h = _login(client, make_user, "t84_p2")
    _mk_q("MQ-T84-P2")
    r = client.post("/api/quotations/MQ-T84-P2/updates", headers=h, data={"content": "x"}, files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert _rows("SELECT COUNT(*) AS n FROM case_updates WHERE quote_no='MQ-T84-P2'")[0]["n"] == 0


# ───────────────────────────── G 組：已結案半解鎖案件的上傳類變更 ─────────────────────────────

G_SITES = {
    "payment_invoice_upload": "/api/quotations/MQ-T84-G/payment/0/invoice-files",
    "material_file_upload": "/api/quotations/MQ-T84-G/materials/0/files",
    "material_invoice_upload": "/api/quotations/MQ-T84-G/materials/0/invoice-files",
}


@pytest.fixture(params=sorted(G_SITES))
def g_site(request, client, make_user, monkeypatch):
    _mk_q("MQ-T84-G")
    _exec("UPDATE quotations SET deal_tag='已結案', case_semi_unlocked=1 WHERE quote_no='MQ-T84-G'")
    h = _login(client, make_user, "t84_g")
    from modules.case.api import quotations as Q
    announced = []          # 「通知最高管理者」的背景工作被排了幾次（新舊程式都是經 spawn_bg_thread；這裡只計數、不真的寄）
    monkeypatch.setattr(Q, "spawn_bg_thread", lambda fn, *a, **k: announced.append(fn.__name__))
    return client, h, request.param, G_SITES[request.param], announced, Q


def _ccr():
    return _rows("SELECT id, status, action_type, staged_files_json FROM case_change_requests ORDER BY id")


def test_g_normal_upload_creates_one_pending_request_with_staged_files_and_notifies_once(g_site):
    client, h, action, url, announced, Q = g_site
    r = _post_png(client, h, url)
    assert r.status_code == 201 and r.json().get("pending") is True, r.text
    rows = _ccr()
    assert len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["action_type"] == action
    staged = json.loads(rows[0]["staged_files_json"])
    assert len(staged) == 1 and _on_disk(staged) and ("_pending_case_changes/%s/" % rows[0]["id"]) in staged[0]["path"]
    assert len(announced) == 1


def test_g_rejected_file_leaves_no_request_and_no_notification(g_site):
    """存檔被擋（副檔名 400）：不可以留下 pending 的鬼申請，也不可以已經通知過最高管理者。"""
    client, h, action, url, announced, Q = g_site
    r = client.post(url, headers=h, files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert [x for x in _ccr() if x["status"] == "pending"] == []
    assert announced == []


def test_g_db_error_when_promoting_leaves_no_files_no_pending_request_no_notification(g_site, monkeypatch):
    client, h, action, url, announced, Q = g_site
    saved = _spy(monkeypatch, Q)
    _trigger("t84_g_blk", "UPDATE OF staged_files_json", "case_change_requests")
    try:
        with pytest.raises(Exception):
            _post_png(client, h, url)
    finally:
        _untrigger("t84_g_blk")
    assert saved and _on_disk(saved) == []
    assert [x for x in _ccr() if x["status"] == "pending"] == []
    assert announced == []


def test_g_staging_row_cannot_be_approved_or_listed(client, make_user, monkeypatch):
    """預留編號用的 staging 列：簽核佇列看不到、核准回 409（不是 pending）。"""
    _mk_q("MQ-T84-G2")
    _exec("UPDATE quotations SET deal_tag='已結案', case_semi_unlocked=1 WHERE quote_no='MQ-T84-G2'")
    h = _login(client, make_user, "t84_g2")
    from modules.case.api import quotations as Q
    seen = {}

    def peek():
        rows = _ccr()
        seen["status"] = rows[-1]["status"]
        su = _login(client, make_user, "t84_g2_other", role="superadmin")
        seen["approve"] = client.post("/api/case-changes/%s/approve" % rows[-1]["id"], headers=su).status_code
    _spy(monkeypatch, Q, after=peek)
    r = _post_png(client, h, "/api/quotations/MQ-T84-G2/materials/0/files")
    assert r.status_code == 201, r.text
    assert seen["status"] == "staging" and seen["approve"] == 409, seen


# ───────────────────────────── D 組：傳票附件 ─────────────────────────────

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0}, {"account_code": "4111", "debit": 0, "credit": 1000}]


@pytest.fixture()
def voucher(client, make_user):
    h = _login(client, make_user, "t84_v", modules=["cashier"])
    r = client.post("/api/vouchers", headers=h, json={"summary": "T84", "lines": _LINES})
    assert r.status_code == 200, r.text
    return client, h, r.json()["id"]


def _vpost(client, h, vid):
    return client.post("/api/vouchers/%s/attachments" % vid, headers=h, files={"files": ("a.png", PNG, "image/png")})


def _vatt(vid):
    return _rows("SELECT COUNT(*) AS n FROM voucher_attachments WHERE voucher_id=?", (vid,))[0]["n"]


def test_d_voucher_normal_upload_still_works(voucher):
    client, h, vid = voucher
    r = _vpost(client, h, vid)
    assert r.status_code in (200, 201), r.text
    assert _vatt(vid) == 1


def test_d_voucher_left_draft_midway_is_rejected_and_leaves_no_files(voucher, monkeypatch):
    """上傳途中傳票被送審（離開草稿）：鎖內重查要擋下，不能把附件加到「加了也刪不掉」的傳票上；實體檔也不留。"""
    client, h, vid = voucher
    from modules.accounting.api import vouchers as V
    saved = _spy(monkeypatch, V, after=lambda: _exec("UPDATE vouchers_all SET status='待審核' WHERE id=?", (vid,)))
    r = _vpost(client, h, vid)
    assert r.status_code == 400, r.text
    assert saved and _on_disk(saved) == [] and _vatt(vid) == 0


def test_d_voucher_voided_midway_is_rejected_and_leaves_no_files(voucher, monkeypatch):
    client, h, vid = voucher
    from modules.accounting.api import vouchers as V
    saved = _spy(monkeypatch, V, after=lambda: _exec("UPDATE vouchers_all SET voided_at='2026-11-13T00:00:00' WHERE id=?", (vid,)))
    r = _vpost(client, h, vid)
    assert r.status_code == 400, r.text
    assert saved and _on_disk(saved) == [] and _vatt(vid) == 0


def test_d_voucher_insert_error_leaves_no_files(voucher, monkeypatch):
    client, h, vid = voucher
    from modules.accounting.api import vouchers as V
    saved = _spy(monkeypatch, V)
    _trigger("t84_v_blk", "INSERT", "voucher_attachments")
    try:
        with pytest.raises(Exception):
            _vpost(client, h, vid)
    finally:
        _untrigger("t84_v_blk")
    assert saved and _on_disk(saved) == [] and _vatt(vid) == 0


def test_d_voucher_pick_copy_failing_midway_removes_the_copies_already_made(voucher, monkeypatch, tmp_path):
    """帶入（複製）：第二筆複製失敗 ⇒ 第一筆已落地的複本要回收（舊寫法留孤兒）。"""
    client, h, vid = voucher
    from modules.accounting.api import vouchers as V
    import helpers.uploads as up
    src = tmp_path / "src.png"
    src.write_bytes(PNG)
    item = {"meta": {"filename": "a.png"}, "src": str(src), "source_type": "payment_item", "source_doc_no": "X", "source_file_id": "f", "missing": []}
    monkeypatch.setattr(V, "resolve_picks", lambda conn, picks, user: [dict(item), dict(item)])
    real_copy = V.copy_into
    made = []

    def flaky(vid_, src_, name):
        if made:
            raise RuntimeError("boom-second-copy")
        out = real_copy(vid_, src_, name)
        made.append({"path": out[1]})
        return out
    monkeypatch.setattr(V, "copy_into", flaky)
    with pytest.raises(RuntimeError):
        client.post("/api/vouchers/%s/attachments" % vid, headers=h, json={"picks": [{"type": "payment_item", "docNo": "X", "fileId": "f"}] * 2})
    assert made and _on_disk(made) == []
    assert _vatt(vid) == 0
    assert up.UPLOADS_ROOT


# ───────────────────────────── D 組：業務開發記錄 ─────────────────────────────

@pytest.fixture()
def dev_case(client, make_user):
    h = _login(client, make_user, "t84_c")
    r = client.post("/api/dev-cases", headers=h, json={"case_name": "T84 案件"})
    assert r.status_code in (200, 201), r.text
    uid = _rows("SELECT id FROM users WHERE username='t84_c'")[0]["id"]
    return client, h, r.json()["id"], uid


def _dlog(client, h, cid, uid):
    return client.post("/api/dev-cases/%s/logs" % cid, headers=h, data={"log_date": "2026-11-13", "log_by": uid, "content": "拜訪"},
                       files=[("files", ("a.png", PNG, "image/png"))])


def _dlogs(cid):
    return _rows("SELECT COUNT(*) AS n FROM dev_logs WHERE case_id=?", (cid,))[0]["n"]


def test_d_devlog_normal_upload_still_works(dev_case):
    client, h, cid, uid = dev_case
    r = _dlog(client, h, cid, uid)
    assert r.status_code == 201, r.text
    assert _dlogs(cid) == 1 and _on_disk(r.json()["files"])


def test_d_devlog_insert_error_leaves_no_files(dev_case, monkeypatch):
    client, h, cid, uid = dev_case
    from modules.crm import api as C
    saved = _spy(monkeypatch, C)
    _trigger("t84_c_blk", "INSERT", "dev_logs")
    try:
        with pytest.raises(Exception):
            _dlog(client, h, cid, uid)
    finally:
        _untrigger("t84_c_blk")
    assert saved and _on_disk(saved) == [] and _dlogs(cid) == 0


def test_d_devlog_case_deleted_midway_is_404_and_leaves_no_files(dev_case, monkeypatch):
    client, h, cid, uid = dev_case
    from modules.crm import api as C
    saved = _spy(monkeypatch, C, after=lambda: _exec("UPDATE dev_cases SET is_deleted=1 WHERE id=?", (cid,)))
    r = _dlog(client, h, cid, uid)
    assert r.status_code == 404, r.text
    assert saved and _on_disk(saved) == [] and _dlogs(cid) == 0


# ───────────────────────────── D 組：自訂模組暫存附件 ─────────────────────────────

def test_d_custom_staged_register_error_leaves_no_files(client, make_user, monkeypatch):
    from tests.test_builder3_files_2026_09_30 import KEY, _body, _publish
    hb = _login(client, make_user, "t84_cb")
    hs = _login(client, make_user, "t84_cs", role="user", modules=["custom." + KEY])
    assert _publish(client, hb, _body()) == []
    import helpers.uploads as up
    import helpers.custom_files as CF
    saved = _spy(monkeypatch, up)

    def boom(*a, **k):
        raise RuntimeError("boom-register")
    monkeypatch.setattr(CF, "register_staged", boom)
    with pytest.raises(RuntimeError):
        client.post("/api/custom/%s/files/pics" % KEY, headers=hs, files=[("files", ("a.png", PNG))])
    assert saved and _on_disk(saved) == []
