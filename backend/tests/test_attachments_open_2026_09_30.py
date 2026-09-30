# -*- coding: utf-8 -*-
"""附件目錄 P2（設計 proposal-attachments-search-preview §4）：L1 `GET /api/attachments/open` ＋ `attachments.catalog` 提供者（契約 v1）。

驗：① 有權限的人打得開（octet-stream、位元組相同）；② 看不到＝查無＝同一句 404，未知 type／未知檔／壞 id 也是 404，未登入 401；
③ 與 `/api/photo-token`（擁有模組的 path_access）**同一個答案**——目錄不得比原端點寬（也不得窄到擁有者打不開）；
④ 端點自己的護欄：檔案必須落在 uploads 或提供者宣告的根之下、提供者例外＝404（fail closed）、來源資料壞＝400；
⑤ 沒有提供者認領（模組不在）＝404。反向控制見各題註解（拿掉根目錄檢查／忽略 user ⇒ 紅）。"""
import json
import os

import pytest

from core import registry
from helpers import uploads as up

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
Q = "MQ-CAT-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        c.close()


def _exec(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _open(client, h, type_, doc, file):
    return client.get("/api/attachments/open", headers=h, params={"type": type_, "doc": doc, "file": file})


@pytest.fixture
def world(client, make_user):
    """admin 建案件＋完工單；owner＝該案業務；out＝有 quotation／work_log 模組但不是該案的人；cm＝case_manage。"""
    H = {}
    for name, role, mods in (("ct_admin", "admin", None), ("ct_owner", "sales", []),
                             ("ct_out", "sales", ["quotation", "work_log"]), ("ct_cm", "sales", ["case_manage"]),
                             ("ct_none", "sales", [])):
        u, p = make_user(username=name, role=role, modules=mods)
        H[name] = _login(client, u, p)
    _exec("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
          " updated_at, deal_tag, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          (Q, "已送出", "客戶", "工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
           "2026-01-01T00:00:00", "已成案", _uid("ct_owner"), "ct_owner"))
    r = client.post("/api/completion-notes", headers=H["ct_admin"],
                    json={"quote_no": Q, "completion_date": "2026-09-10", "items": []})
    assert r.status_code == 201, r.text
    note_no = r.json().get("noteNo") or r.json().get("note_no")
    up_r = client.post(f"/api/completion-notes/{note_no}/signed-files", headers=H["ct_admin"],
                       files=[("files", ("sign.png", PNG, "image/png"))])
    assert up_r.status_code == 201, up_r.text
    f = up_r.json()["files"][0]
    return H, note_no, f


# ── ① 打得開 ─────────────────────────────────────────────────────────────────

def test_completion_note_file_opens_for_readers_with_same_bytes(client, world):
    H, note_no, f = world
    for who in ("ct_owner", "ct_cm", "ct_admin"):                  # 完工單清單規則：本人／case_manage／admin
        r = _open(client, H[who], "completion_note", note_no, f["id"])
        assert r.status_code == 200, (who, r.text)
        assert r.content == PNG and r.headers["content-type"].startswith("application/octet-stream")
        assert "sign.png" in r.headers.get("content-disposition", "")


def test_quotation_signed_file_opens_for_case_page_readers(client, world):
    H, _, _ = world
    r = client.post(f"/api/quotations/{Q}/signed-files", headers=H["ct_admin"], files=[("files", ("s.png", PNG, "image/png"))])
    assert r.status_code in (200, 201), r.text
    fid = r.json()["files"][0]["id"]
    assert _open(client, H["ct_owner"], "quotation_signed", Q, fid).content == PNG
    # 案件頁規則不放行 case_manage（AT-M1c）⇒ 目錄也不放行
    assert _open(client, H["ct_cm"], "quotation_signed", Q, fid).status_code == 404


# ── ② 看不到＝查無＝同一句 404 ───────────────────────────────────────────────

def test_hidden_equals_missing_and_nothing_leaks(client, world):
    H, note_no, f = world
    hidden = _open(client, H["ct_out"], "completion_note", note_no, f["id"])
    no_doc = _open(client, H["ct_out"], "completion_note", "CN-NOPE-1", f["id"])
    no_file = _open(client, H["ct_owner"], "completion_note", note_no, "deadbeef")
    unknown_type = _open(client, H["ct_owner"], "no_such_type", note_no, f["id"])
    for r in (hidden, no_doc, no_file, unknown_type):
        assert r.status_code == 404 and r.json()["detail"] == "檔案不存在", r.text
    assert Q not in hidden.text and "sign.png" not in hidden.text
    assert client.get("/api/attachments/open", params={"type": "completion_note", "doc": note_no, "file": f["id"]}).status_code == 401


def test_bad_doc_shapes_are_404_not_500(client, world):
    H, _, _ = world
    for t in ("work_log_photo", "dev_log", "contractor_dispatch", "contractor_invoice", "voucher", "payslip_signed",
              "shipping_note", "invoice_voucher", "extra_expense", "payment_item", "material", "case_update"):
        for doc in ("abc", "../../x", "9" * 30):
            r = _open(client, H["ct_admin"], t, doc, "zz")
            assert r.status_code in (404, 400), (t, doc, r.status_code, r.text)


# ── ③ 與 photo-token（擁有模組的 path_access）同一個答案 ─────────────────────

def test_catalog_answer_equals_photo_token_answer(client, world):
    """目錄不得比原端點寬；也不得窄到擁有者打不開。對每個使用者，`open` 成功 ⇔ `photo-token` 成功。"""
    H, note_no, f = world
    for who in H:
        via_catalog = _open(client, H[who], "completion_note", note_no, f["id"]).status_code == 200
        via_token = client.get("/api/photo-token", headers=H[who], params={"path": f["path"]}).status_code == 200
        assert via_catalog == via_token, who


def test_work_log_photo_follows_path_access(client, world):
    H, _, _ = world
    r = client.post("/api/work-logs", headers=H["ct_admin"], json={"log_date": "2026-09-30", "content": "x", "hours": 1, "case_no": Q})
    assert r.status_code in (200, 201), r.text
    wid = r.json()["id"]
    pr = client.post(f"/api/work-logs/{wid}/photos", headers=H["ct_admin"], files=[("files", ("a.png", PNG, "image/png"))])
    assert pr.status_code == 201, pr.text
    import db
    c = db.get_db()
    try:
        photos = json.loads(c.execute("SELECT photos FROM work_logs WHERE id=?", (wid,)).fetchone()["photos"])
    finally:
        c.close()
    pid, path = photos[0]["id"], photos[0]["path"]
    for who in H:
        via_catalog = _open(client, H[who], "work_log_photo", str(wid), pid).status_code == 200
        via_token = client.get("/api/photo-token", headers=H[who], params={"path": path}).status_code == 200
        assert via_catalog == via_token, who
    assert _open(client, H["ct_admin"], "work_log_photo", str(wid), pid).status_code == 200
    assert _open(client, H["ct_none"], "work_log_photo", str(wid), pid).status_code == 404


@pytest.mark.parametrize("t", ["voucher", "payslip_signed"])
def test_users_without_the_module_get_404_even_for_missing_docs(client, world, t):
    """傳票（cashier／finance）與勞報單簽回檔（superadmin／cashier）：沒有那個模組的人，存在與否看起來一樣。"""
    H, _, _ = world
    assert _open(client, H["ct_out"], t, "1", "x").status_code == 404
    assert _open(client, H["ct_out"], t, "PS-202609-001" if t == "payslip_signed" else "999", "x").status_code == 404


# ── ④ 端點自己的護欄（合成提供者）─────────────────────────────────────────────

class _Synth:
    CATEGORIES = {"zz_synth": {"label": "合成", "doc": "合成單", "module": "測試"}}
    result = None
    roots = ()

    @classmethod
    def ROOTS(cls):
        return list(cls.roots)

    @classmethod
    def open(cls, conn, user, source_type, doc_no, file_id):
        if isinstance(cls.result, Exception):
            raise cls.result
        return cls.result


@pytest.fixture
def synth(client):
    snap = registry.snapshot()
    saved = dict(registry._LEGACY_PROVIDERS)
    registry._LEGACY_PROVIDERS[(up.ATTACHMENTS_CATALOG, "zz")] = _Synth
    _Synth.result, _Synth.roots = None, ()
    yield _Synth
    registry._LEGACY_PROVIDERS.clear()
    registry._LEGACY_PROVIDERS.update(saved)
    registry.restore(snap)


def _admin(client, make_user):
    u, p = make_user(username="syn_admin", role="superadmin", modules=[])
    return _login(client, u, p)


def test_file_outside_the_allowed_roots_is_404(client, make_user, synth, tmp_path):
    """**反向控制**：拿掉端點的根目錄檢查 ⇒ 這題紅（提供者回了 uploads 之外的檔，端點照送）。"""
    h = _admin(client, make_user)
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret")
    synth.result = up.OpenedFile(str(outside), "secret.txt", "text/plain", outside.stat().st_size)
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404
    synth.roots = (str(tmp_path),)                                   # 提供者宣告了這個根 ⇒ 放行（勞報單封存目錄的形狀）
    r = _open(client, h, "zz_synth", "1", "1")
    assert r.status_code == 200 and r.content == b"top secret"


def test_traversal_through_declared_root_is_still_404(client, make_user, synth, tmp_path):
    h = _admin(client, make_user)
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "escape.txt").write_text("x")
    synth.roots = (str(root),)
    synth.result = up.OpenedFile(str(root / ".." / "escape.txt"), "e.txt", "text/plain", 1)
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404


def test_provider_exception_fails_closed_and_source_error_is_400(client, make_user, synth):
    h = _admin(client, make_user)
    synth.result = RuntimeError("boom")
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404
    synth.result = up.AttachmentSourceError("資料壞了")
    r = _open(client, h, "zz_synth", "1", "1")
    assert r.status_code == 400 and "資料壞了" in r.text
    synth.result = up.AttachmentNotVisible()
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404
    synth.result = None                                              # 單據／檔案不存在
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404


def test_missing_physical_file_is_404(client, make_user, synth, tmp_path):
    h = _admin(client, make_user)
    synth.roots = (str(tmp_path),)
    synth.result = up.OpenedFile(str(tmp_path / "gone.bin"), "gone.bin", "", 0)
    assert _open(client, h, "zz_synth", "1", "1").status_code == 404


def test_no_provider_claims_the_type_is_404(client, make_user):
    """模組不在 ⇒ 沒有提供者認領該 type ⇒ 404（安全的方向）。"""
    h = _admin(client, make_user)
    assert _open(client, h, "quotation_signed_absent_xyz", "1", "1").status_code == 404


# ── ⑤ 契約形狀 ──────────────────────────────────────────────────────────────

def test_every_registered_provider_has_the_contract_shape(client):
    provs = registry.providers(up.ATTACHMENTS_CATALOG)
    assert provs
    seen = {}
    for key, p in provs.items():
        assert callable(getattr(p, "open", None)), key
        for c, info in p.CATEGORIES.items():
            assert c not in seen, "%s 被 %s 與 %s 重複認領" % (c, seen.get(c), key)
            seen[c] = key
            assert {"label", "doc", "module"} <= set(info) and all(isinstance(v, str) and v for v in info.values())
    # 不含待核准暫存檔（設計 Q6）：沒有任何 category 以 pending 命名
    assert not any("pending" in c for c in seen)
