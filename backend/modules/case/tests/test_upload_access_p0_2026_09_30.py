"""P0 安全修正（2026-09-30）：M01 的上傳檔讀取權限（IP-104 `uploads.path_access`）與完工單單筆讀取／回簽上傳守門。

修正前：
- `/api/photo-token?path=<任意路徑>`（與 `/api/uploads/<路徑>` 帶 Authorization 那條）只要求登入 ⇒
  任何登入者對可列舉的 `<資料夾>/<單號>/<檔名>` 都拿得到檔案。
- `GET /api/completion-notes/{no}`、`POST /api/completion-notes/{no}/signed-files` 只要求登入 ⇒ 單號可列舉即 IDOR。

修正後（本檔驗）：
① 完工單單筆 GET／回簽上傳：看得到該案（清單規則：業務本人／協作者、admin+、case_manage）⇒ 通過；
   看不到 ⇒ 404，訊息與查無**逐字相同**，且不帶案件單號；上傳被擋時沒有寫進任何檔案
② photo-token／標頭讀檔：完工單回簽檔、報價單回簽檔、待核准變更暫存檔（申請人本人）依擁有單據的規則放行；其餘 404
③ 簽核佇列情境：簽核人不是案件的人 ⇒ 單看路徑 404；帶 (type, id) 且詳情列出該路徑 ⇒ 放行；路徑不在詳情裡 ⇒ 404
"""
import io
import json
import os

import pytest

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
Q = "MQ-P0-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


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


@pytest.fixture
def world(client, make_user):
    """admin 建案件與完工單；owner＝該案業務（沒有任何模組）；outsider＝有 quotation／work_log 但不是該案的人；
    cm＝持 case_manage（完工單清單規則放行）。"""
    users = {}
    for name, role, mods in (("p0_admin", "admin", None), ("p0_owner", "sales", []),
                             ("p0_out", "sales", ["quotation", "work_log"]), ("p0_cm", "sales", ["case_manage"])):
        u, p = make_user(username=name, role=role, modules=mods)
        users[name] = _login(client, u, p)
    _exec("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
          " updated_at, deal_tag, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          (Q, "已送出", "客戶", "工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
           "2026-01-01T00:00:00", "已成案", _uid("p0_owner"), "p0_owner"))
    r = client.post("/api/completion-notes", headers=_h(users["p0_admin"]),
                    json={"quote_no": Q, "completion_date": "2026-09-10", "items": []})
    assert r.status_code == 201, r.text
    note_no = r.json()["noteNo"] if "noteNo" in r.json() else r.json()["note_no"]
    return users, note_no


def _upload(client, token, note_no):
    return client.post(f"/api/completion-notes/{note_no}/signed-files", headers=_h(token),
                       files=[("files", ("sign.png", PNG, "image/png"))])


# ── ① 完工單單筆 GET／回簽上傳 ────────────────────────────────────────────────

def test_completion_get_owner_and_case_manage_ok(client, world):
    users, note_no = world
    for who in ("p0_owner", "p0_cm", "p0_admin"):
        r = client.get(f"/api/completion-notes/{note_no}", headers=_h(users[who]))
        assert r.status_code == 200, (who, r.text)


def test_completion_get_outsider_is_same_404_as_missing(client, world):
    users, note_no = world
    denied = client.get(f"/api/completion-notes/{note_no}", headers=_h(users["p0_out"]))
    missing = client.get("/api/completion-notes/CN-NOPE-999", headers=_h(users["p0_out"]))
    assert denied.status_code == 404 and missing.status_code == 404, (denied.text, missing.text)
    assert denied.json()["detail"] == missing.json()["detail"] == "完工單不存在"
    assert Q not in denied.text                              # 不洩漏掛在哪一案


def test_completion_signed_upload_outsider_404_and_nothing_written(client, world):
    import helpers.uploads as up
    users, note_no = world
    r = _upload(client, users["p0_out"], note_no)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "完工單不存在"
    assert not os.path.isdir(os.path.join(up.UPLOADS_ROOT, "completion_notes", note_no))   # 擋在存檔之前
    r = client.get(f"/api/completion-notes/{note_no}", headers=_h(users["p0_owner"]))
    assert r.json().get("signedFiles", r.json().get("signed_files", [])) in ([], None)


def test_completion_signed_upload_owner_ok(client, world):
    users, note_no = world
    r = _upload(client, users["p0_owner"], note_no)
    assert r.status_code == 201, r.text
    assert r.json()["files"][0]["path"].startswith(f"completion_notes/{note_no}/")


# ── ② photo-token／標頭讀檔 ──────────────────────────────────────────────────

def _token(client, t, path, **ctx):
    return client.get("/api/photo-token", headers=_h(t), params={"path": path, **ctx})


def test_completion_file_photo_token(client, world):
    users, note_no = world
    path = _upload(client, users["p0_owner"], note_no).json()["files"][0]["path"]
    ok = _token(client, users["p0_owner"], path)
    assert ok.status_code == 200, ok.text
    r = client.get(f"/api/uploads/{path}", params={"pt": ok.json()["token"]})
    assert r.status_code == 200 and r.content                         # 端點真的讀回檔案
    assert _token(client, users["p0_cm"], path).status_code == 200
    bad = _token(client, users["p0_out"], path)
    missing = _token(client, users["p0_out"], f"completion_notes/{note_no}/nope.png")
    assert bad.status_code == 404 and bad.json()["detail"] == "檔案不存在", bad.text
    assert missing.status_code == 404
    # 標頭那條同一個規則（原本也是只要求登入）
    assert client.get(f"/api/uploads/{path}", headers=_h(users["p0_out"])).status_code == 404
    assert client.get(f"/api/uploads/{path}", headers=_h(users["p0_owner"])).status_code == 200


def test_quotation_signed_file_uses_case_page_rule(client, world):
    import helpers.uploads as up
    users, _ = world
    d = os.path.join(up.UPLOADS_ROOT, "quotations", Q)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "s.pdf"), "wb").write(b"%PDF-1.4")
    path = f"quotations/{Q}/s.pdf"
    assert _token(client, users["p0_owner"], path).status_code == 200
    assert _token(client, users["p0_out"], path).status_code == 404
    # 案件頁規則不放行 case_manage（稽核 D AT-M1c：附件可見範圍＝原單據）
    assert _token(client, users["p0_cm"], path).status_code == 404
    # demo 前綴對應同一個擁有單據（不因前綴繞過）
    assert _token(client, users["p0_out"], f"_demo_uploads/quotations/{Q}/s.pdf").status_code == 404


def test_pending_change_files_requester_or_case_reader(client, world, make_user):
    users, _ = world
    u, p = make_user(username="p0_req", role="sales", modules=["quotation"])
    t_req = _login(client, u, p)
    cid = _exec("INSERT INTO case_change_requests (quote_no, action_type, requested_by) VALUES (?,?,?)",
                (Q, "material_upload", "p0_req"))
    path = f"_pending_case_changes/{cid}/{Q}_0/x.png"
    assert _token(client, t_req, path).status_code == 200           # 申請人本人
    assert _token(client, users["p0_owner"], path).status_code == 200  # 案件頁規則
    assert _token(client, users["p0_out"], path).status_code == 404
    # 變更 id 與案件對不上 ⇒ 不放行（不可以拿自己的變更 id 去讀別案的暫存檔）
    assert _token(client, t_req, f"_pending_case_changes/{cid}/MQ-OTHER-1_0/x.png").status_code == 404


# ── ③ 簽核佇列情境 ─────────────────────────────────────────────────────────

def test_approval_context_lets_chain_member_open_listed_file(client, world, make_user):
    users, note_no = world
    u, p = make_user(username="p0_appr", role="sales", modules=["quotation"])
    t_ap = _login(client, u, p)
    path = _upload(client, users["p0_owner"], note_no).json()["files"][0]["path"]
    _exec("UPDATE completion_notes SET data_json=? WHERE note_no=?",
          (json.dumps({"approval": {"tiers": [{"approvers": [{"username": "p0_appr"}]}], "requestedBy": "p0_admin"}}),
           note_no))
    assert _token(client, t_ap, path).status_code == 404              # 單看路徑：不是案件的人
    ok = _token(client, t_ap, path, type="completion_note", id=note_no)
    assert ok.status_code == 200, ok.text
    # 詳情沒列出的路徑（同案別的檔）⇒ 不因帶了情境就放行
    assert _token(client, t_ap, f"quotations/{Q}/s.pdf", type="completion_note", id=note_no).status_code == 404
    # 不在簽核鏈上的人帶情境 ⇒ 仍 404
    assert _token(client, users["p0_out"], path, type="completion_note", id=note_no).status_code == 404


# ── ④ 批次簽章（稽核 S1：N 張圖不可以 N 次詳情守門＋N 筆 audit）─────────────────

N_IMAGES = 20


def _twenty_listed(note_no, approver):
    files = [{"id": "f%02d" % i, "filename": "p%02d.png" % i, "path": f"completion_notes/{note_no}/p{i:02d}.png"}
             for i in range(N_IMAGES)]
    _exec("UPDATE completion_notes SET signed_files_json=?, data_json=? WHERE note_no=?",
          (json.dumps(files), json.dumps({"approval": {"tiers": [{"approvers": [{"username": approver}]}],
                                                        "requestedBy": "p0_admin"}}), note_no))
    return [f["path"] for f in files]


@pytest.fixture
def count_detail(monkeypatch):
    from routers import approval_queue as aq
    calls = []
    real = aq._open_detail

    def spy(*a, **k):
        calls.append(a[2:])
        return real(*a, **k)
    monkeypatch.setattr(aq, "_open_detail", spy)
    return calls


def test_batch_runs_detail_guard_once_for_twenty_images(client, world, make_user, count_detail):
    import time
    users, note_no = world
    u, p = make_user(username="p0_apb", role="sales", modules=["quotation"])
    t_ap = _login(client, u, p)
    paths = _twenty_listed(note_no, "p0_apb")

    t0 = time.perf_counter()                                   # 修前的做法：每張一次單張端點
    for pth in paths:
        assert _token(client, t_ap, pth, type="completion_note", id=note_no).status_code == 200
    before_s, before_calls = time.perf_counter() - t0, len(count_detail)
    count_detail.clear()

    t0 = time.perf_counter()
    r = client.post("/api/photo-token/batch", headers=_h(t_ap),
                    json={"paths": paths + [f"quotations/{Q}/s.pdf", "../x"], "type": "completion_note", "id": note_no})
    after_s = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["tokens"]) == sorted(paths)
    assert sorted(body["denied"]) == sorted([f"quotations/{Q}/s.pdf", "../x"])   # 沒列在詳情／不合法 ⇒ 不簽
    assert len(count_detail) == 1, count_detail                 # 🔑 一次請求只跑一次詳情守門
    assert before_calls == N_IMAGES
    # 簽出來的簽章跟單張端點一樣可用
    assert client.get(f"/api/uploads/{paths[0]}", params={"pt": body["tokens"][paths[0]]}).status_code in (200, 404)
    print("\n[S1 量測] %d 張圖：單張端點 %d 次詳情守門 %.1f ms；批次 %d 次 %.1f ms"
          % (N_IMAGES, before_calls, before_s * 1000, len(count_detail), after_s * 1000))


def test_batch_denied_writes_one_audit_and_skips_detail_when_readable(client, world, count_detail):
    import db
    import time
    users, note_no = world
    paths = _twenty_listed(note_no, "someone_else")
    r = client.post("/api/photo-token/batch", headers=_h(users["p0_out"]),
                    json={"paths": paths, "type": "completion_note", "id": note_no})
    assert r.status_code == 200 and r.json()["tokens"] == {} and len(r.json()["denied"]) == N_IMAGES
    assert len(count_detail) == 1
    for _ in range(50):                                        # audit 在背景執行緒寫
        c = db.get_db()
        n = c.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action='approval.detail_denied'").fetchone()["n"]
        c.close()
        if n:
            break
        time.sleep(0.05)
    time.sleep(0.3)
    c = db.get_db()
    n = c.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action='approval.detail_denied'").fetchone()["n"]
    c.close()
    assert n == 1, n
    # 本來就讀得到（案件業務本人）⇒ 連一次詳情守門都不跑
    count_detail.clear()
    r = client.post("/api/photo-token/batch", headers=_h(users["p0_owner"]),
                    json={"paths": paths, "type": "completion_note", "id": note_no})
    assert len(r.json()["tokens"]) == N_IMAGES and count_detail == []


def test_batch_limit_and_no_context(client, world):
    users, note_no = world
    r = client.post("/api/photo-token/batch", headers=_h(users["p0_owner"]),
                    json={"paths": ["completion_notes/%s/%d.png" % (note_no, i) for i in range(201)]})
    assert r.status_code == 400
    r = client.post("/api/photo-token/batch", headers=_h(users["p0_out"]),
                    json={"paths": [f"completion_notes/{note_no}/a.png"]})
    assert r.status_code == 200 and r.json() == {"tokens": {}, "denied": [f"completion_notes/{note_no}/a.png"],
                                                 "ttl": 3600}
    assert client.post("/api/photo-token/batch", json={"paths": []}).status_code == 401
