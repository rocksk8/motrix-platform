"""P0 安全修正（2026-09-30）：`/api/photo-token` 與 `/api/uploads/…` 的讀取權限（L1；IP-104 `uploads.path_access`）。

修正前：photo-token 對任何路徑都簽（只要登入）；標頭那條讀檔也只要求登入 ⇒ 任何登入者讀得到任何單據附件。
修正後（本檔驗 L1 那一半，各模組的規則在各自的 tests/）：
① 路徑正規化：絕對路徑、`..`、反斜線、冒號、空段、連結跑出去 ⇒ 403；只有 photo-token 簽發過的正規路徑才驗得過
② 沒有提供者認領的資料夾（branding、voucher_attachments、亂寫的）⇒ 404（預設拒絕），連 superadmin 也一樣
③ L1 自己的工作日誌照片：模組規則（work_log／case_manage）放行，沒有模組 ⇒ 404；標頭那條同規則
④ 提供者契約：FOLDERS 兩兩不重疊；提供者丟例外 ⇒ 不放行（fail closed）
⑤ （稽核 S3）Windows 檔名變體：尾端點號／空白、8.3 短檔名、ADS、大小寫、%2e%2e —— **有權限的人**打變體也不可以 200
"""
import os
from urllib.parse import quote

import pytest

from helpers import uploads as up
from tests._requires import requires_module

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


# ── ⑤ 稽核 S3：Windows 檔名變體（有權限者打變體也不可以讀到；簽章綁的只有正規那一個）──────────────

S3_Q = "MQ-S3-1"
S3_OK = f"quotations/{S3_Q}/a.pdf"
S3_VARIANTS = [
    f"quotations/{S3_Q}./a.pdf",            # 尾端點號（Windows 會去掉 ⇒ 實際是同一個資料夾）
    f"quotations./{S3_Q}/a.pdf",
    f"quotations/{S3_Q}/a.pdf.",
    f"quotations/{S3_Q} /a.pdf",            # 尾端空白
    f"quotations/{S3_Q}/a.pdf ",
    f"QUOTAT~1/{S3_Q}/a.pdf",               # 8.3 短檔名
    f"quotations/MQ-S3~1/a.pdf",
    f"quotations/{S3_Q}/a.pdf::$DATA",      # ADS
    f"quotations/{S3_Q}/a.pdf:x",
    f"Quotations/{S3_Q}/a.pdf",             # 大小寫變體（NTFS 不分大小寫）
    f"quotations/mq-s3-1/a.pdf",
    f"QUOTATIONS/{S3_Q}/A.PDF",
    "%2e%2e/backend/main.py",               # 編碼過的 ..（伺服器不可以再解一次）
    "quotations/%2e%2e/%2e%2e/backend/main.py",
    f"quotations/{S3_Q}/..%2fa.pdf",
]


@pytest.fixture
def s3_world(client, make_user):
    import db
    u, p = make_user(username="s3_sa", role="superadmin")
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at) VALUES (?,?,?,?,?)",
                  (S3_Q, "已送出", "{}", "2026-09-30", "2026-09-30"))
        c.commit()
    finally:
        c.close()
    full = os.path.join(up.UPLOADS_ROOT, *S3_OK.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(b"%PDF-1.4 s3")
    return _login(client, u, p)


@requires_module("case", "正對照的擁有單據是 M01 報價單回簽檔（有權限者 200 才證明變體被擋是因為變體本身）")
def test_s3_positive_control_exact_path_ok(client, s3_world):
    t = s3_world
    r = client.get("/api/photo-token", headers=_h(t), params={"path": S3_OK})
    assert r.status_code == 200, r.text
    assert client.get("/api/uploads/" + S3_OK, params={"pt": r.json()["token"]}).content == b"%PDF-1.4 s3"
    assert client.get("/api/uploads/" + S3_OK, headers=_h(t)).status_code == 200


@requires_module("case", "同上：有權限的人打變體")
@pytest.mark.parametrize("variant", S3_VARIANTS)
def test_s3_variant_never_served(client, s3_world, variant):
    t = s3_world
    r = client.get("/api/photo-token", headers=_h(t), params={"path": variant})
    if r.status_code == 200:
        # 只有「在有權限的單據資料夾裡、字面上是另一個檔名」（例 `..%2fa.pdf` 是一個合法的檔名段，伺服器不再解碼）
        # 才可能簽出來；那個簽章讀不到任何東西（字面檔案不存在），更讀不到 a.pdf
        assert variant.startswith(f"quotations/{S3_Q}/"), (variant, r.text)
        got = client.get("/api/uploads/" + quote(variant, safe="/"), params={"pt": r.json()["token"]})
        assert got.status_code in (403, 404), (variant, got.status_code)
    else:
        assert r.status_code in (403, 404), (variant, r.status_code, r.text)
    r = client.get("/api/uploads/" + quote(variant, safe="/"), headers=_h(t))
    assert r.status_code in (403, 404), (variant, r.status_code)
    r = client.get("/api/uploads/" + variant, headers=_h(t))            # 不再編碼：由伺服器端解碼一次
    assert r.status_code in (403, 404, 405), (variant, r.status_code)
    # 正規路徑的簽章不可以拿來讀變體
    pt = client.get("/api/photo-token", headers=_h(t), params={"path": S3_OK}).json()["token"]
    assert client.get("/api/uploads/" + quote(variant, safe="/"), params={"pt": pt}).status_code in (403, 404), variant
