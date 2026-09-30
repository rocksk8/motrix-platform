"""P0 安全修正（2026-09-30）：`/api/photo-token` 與 `/api/uploads/…` 的讀取權限（L1；IP-104 `uploads.path_access`）。

修正前：photo-token 對任何路徑都簽（只要登入）；標頭那條讀檔也只要求登入 ⇒ 任何登入者讀得到任何單據附件。
修正後（本檔驗 L1 那一半，各模組的規則在各自的 tests/）：
① 路徑正規化：絕對路徑、`..`、反斜線、冒號、空段、連結跑出去 ⇒ 403；只有 photo-token 簽發過的正規路徑才驗得過
② 沒有提供者認領的資料夾（branding、voucher_attachments、亂寫的）⇒ 404（預設拒絕），連 superadmin 也一樣
③ L1 自己的工作日誌照片：模組規則（work_log／case_manage）放行，沒有模組 ⇒ 404；標頭那條同規則
④ 提供者契約：FOLDERS 兩兩不重疊；提供者丟例外 ⇒ 不放行（fail closed）
"""
import os

import pytest

from helpers import uploads as up

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


@pytest.mark.parametrize("raw", [
    "", "a", "/etc/passwd", "\\\\srv\\share\\x", "C:/Windows/win.ini", "C:\\x", "quotations/../../backend/main.py",
    "quotations/./Q/f.pdf", "quotations//f.pdf", "quotations/Q/f.pdf:stream", "quotations\\Q\\f.pdf",
    "quotations/Q/\x00.pdf", "../x", "quotations/Q/..",
])
def test_canonical_rejects(client, raw):
    assert up.canonical_upload_path(raw) is None, raw


def test_canonical_accepts_stored_shape(client):
    assert up.canonical_upload_path("quotations/MQ-1/ab.pdf") == "quotations/MQ-1/ab.pdf"
    assert up.canonical_upload_path("_demo_uploads/quotations/MQ-1/ab.pdf") == "_demo_uploads/quotations/MQ-1/ab.pdf"


@pytest.mark.parametrize("where", ["outside_root", "other_record_inside_root"])
def test_canonical_rejects_link_escaping_root(client, tmp_path, where):
    """uploads 底下一個連結（junction／symlink）：字面路徑是 A 單據，實際指到根目錄外、或根目錄內**別張單據**的資料夾
    ⇒ 拒絕。第二種只有「realpath 與字面不同」那一條擋得到（跑出根目錄的檢查擋不到）。"""
    if where == "outside_root":
        outside = tmp_path / "outside_secret"
    else:
        outside = type(tmp_path)(os.path.join(up.UPLOADS_ROOT, "shipping_notes", "SN-OTHER"))
    outside.mkdir(parents=True)
    (outside / "s.txt").write_text("secret")
    link = os.path.join(up.UPLOADS_ROOT, "quotations", "MQ-LINK")
    os.makedirs(os.path.dirname(link), exist_ok=True)
    try:
        if os.name == "nt":
            import subprocess
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, str(outside)], capture_output=True)
            if r.returncode != 0:
                pytest.skip("無法建立 junction：%r" % r.stderr)
        else:
            os.symlink(str(outside), link)
        assert up.canonical_upload_path("quotations/MQ-LINK/s.txt") is None
    finally:
        try:
            os.rmdir(link) if os.name == "nt" else os.unlink(link)
        except OSError:
            pass


def test_traversal_rejected_at_endpoints(client, make_user):
    u, p = make_user(username="pa_sa", role="superadmin")
    t = _login(client, u, p)
    for raw in ("../backend/main.py", "..\\backend\\main.py", "/etc/passwd", "C:/Windows/win.ini",
                "quotations/../../backend/main.py"):
        assert client.get("/api/photo-token", headers=_h(t), params={"path": raw}).status_code == 403, raw
    assert client.get("/api/uploads/..%5Cbackend%5Cmain.py", headers=_h(t)).status_code == 403


@pytest.mark.parametrize("path", ["branding/logo.png", "voucher_attachments/1/a.pdf", "nobody/x/y.png",
                                  "Quotations/MQ-1/a.pdf"])
def test_unowned_folder_denied_even_for_superadmin(client, make_user, path):
    u, p = make_user(username="pa_sa2", role="superadmin")
    t = _login(client, u, p)
    full = os.path.join(up.UPLOADS_ROOT, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(b"x")
    r = client.get("/api/photo-token", headers=_h(t), params={"path": path})
    assert r.status_code == 404 and r.json()["detail"] == "檔案不存在", r.text
    assert client.get(f"/api/uploads/{path}", headers=_h(t)).status_code == 404


def _work_log_photo(client, t, uid):
    wid = client.post("/api/work-logs", headers=_h(t),
                      json={"log_date": "2026-09-30", "user_id": uid, "content": "x"}).json()["id"]
    r = client.post(f"/api/work-logs/{wid}/photos", headers=_h(t), files=[("files", ("a.png", PNG, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["photos"][0]["path"]


def test_work_log_photo_module_rule(client, make_user):
    import db
    u, p = make_user(username="pa_wl", role="sales", modules=["work_log"])
    t = _login(client, u, p)
    c = db.get_db()
    uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    c.close()
    path = _work_log_photo(client, t, uid)
    assert path.startswith("projects/worklog_")
    ok = client.get("/api/photo-token", headers=_h(t), params={"path": path})
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/uploads/{path}", params={"pt": ok.json()["token"]}).status_code == 200
    u2, p2 = make_user(username="pa_nomod", role="sales", modules=["quotation"])
    t2 = _login(client, u2, p2)
    assert client.get("/api/photo-token", headers=_h(t2), params={"path": path}).status_code == 404
    assert client.get(f"/api/uploads/{path}", headers=_h(t2)).status_code == 404
    # 同資料夾、沒有任何日誌列出的檔 ⇒ 連有模組的人也 404（擁有單據要存在）
    other = path.rsplit("/", 1)[0] + "/not-listed.png"
    assert client.get("/api/photo-token", headers=_h(t), params={"path": other}).status_code == 404


def test_signed_token_is_bound_to_canonical_path(client, make_user):
    """簽章綁正規路徑：拿 A 的簽章讀 B（含大小寫、demo 前綴的變形）⇒ 403。"""
    import db
    u, p = make_user(username="pa_wl2", role="sales", modules=["work_log"])
    t = _login(client, u, p)
    c = db.get_db()
    uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    c.close()
    path = _work_log_photo(client, t, uid)
    pt = client.get("/api/photo-token", headers=_h(t), params={"path": path}).json()["token"]
    for other in ("_demo_projects/" + path.split("/", 1)[1], path.upper(), "branding/logo.png"):
        assert client.get(f"/api/uploads/{other}", params={"pt": pt}).status_code in (403, 404), other


def test_providers_folders_do_not_overlap(client):
    from core import registry
    seen = {}
    provs = registry.providers(up.PATH_ACCESS)
    assert "work_log" in provs                                # 正對照：L1 自己的提供者一定在
    for key, prov in provs.items():
        for f in prov.FOLDERS:
            assert f not in seen, f"{f} 同時由 {seen[f]} 與 {key} 認領"
            seen[f] = key
        assert callable(getattr(prov, "readable", None)), key


def test_provider_exception_fails_closed(client, monkeypatch):
    from core import registry

    class _Boom:
        FOLDERS = ("boom_folder",)

        @staticmethod
        def readable(conn, folder, rest, user):
            raise RuntimeError("壞掉")

    monkeypatch.setitem(registry._LEGACY_PROVIDERS, (up.PATH_ACCESS, "zz_boom"), _Boom)
    assert up.upload_readable(None, "boom_folder/x/y.png", {"role": "superadmin", "username": "x"}) is False
