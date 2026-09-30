# -*- coding: utf-8 -*-
"""上傳檔頭（magic bytes）檢查（NIGHT 計畫 line 161，2026-09-30）：副檔名白名單之外的第二道，**唯一關卡在 helpers/uploads.py**。

⚠️ 整檔標 `upload_magic`：conftest 一般把 `_magic_matches` 換成「一律符合」（既有題用假內容測業務流程），這裡要用真的。"""
import asyncio
import io
import zipfile

import pytest

from helpers import uploads as U

pytestmark = pytest.mark.upload_magic

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPG = b"\xff\xd8\xff\xe0" + b"0" * 32
GIF = b"GIF89a" + b"0" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"0" * 16
PDF = b"%PDF-1.7\n" + b"0" * 32
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 32
EXE = b"MZ\x90\x00" + b"0" * 64


def _zip(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


DOCX = _zip("[Content_Types].xml", "word/document.xml")
XLSX = _zip("[Content_Types].xml", "xl/workbook.xml")


@pytest.mark.parametrize("ext,raw", [
    (".png", PNG), (".jpg", JPG), (".jpeg", JPG), (".gif", GIF), (".webp", WEBP), (".pdf", PDF),
    (".doc", OLE), (".xls", OLE), (".docx", DOCX), (".xlsx", XLSX),
    (".PDF", PDF), (".pdf", b"junk\n" + PDF),                     # 大小寫；PDF 標頭前有少量雜訊
])
def test_real_headers_pass(ext, raw):
    assert U._magic_matches(ext, raw)


@pytest.mark.parametrize("ext,raw", [
    (".pdf", EXE), (".png", EXE), (".jpg", PNG), (".png", JPG), (".gif", PNG), (".webp", b"RIFF\x00\x00\x00\x00WAVE"),
    (".docx", XLSX), (".xlsx", DOCX),                             # zip 內容不是那一種 Office 檔
    (".docx", b"PK\x03\x04not really a zip"), (".docx", _zip("a.txt")), (".xlsx", PDF),
    (".doc", EXE), (".xls", DOCX),                                # 新版 zip 不可冒充舊版 OLE
    (".pdf", b"<html><script>alert(1)</script></html>"), (".png", b"<svg onload=alert(1)>"),
])
def test_mismatch_rejected(ext, raw):
    assert not U._magic_matches(ext, raw)


@pytest.mark.parametrize("ext", [".exe", ".svg", ".html", ".js", ".txt", ".csv", ""])
def test_extension_without_rule_is_fail_closed(ext):
    """白名單日後放行新副檔名卻忘了補檔頭規則 ⇒ 擋，不是「沒檢查」。"""
    assert not U._magic_matches(ext, PNG + PDF + b"PK\x03\x04")


class _Up:
    def __init__(self, name, data):
        self.filename, self._d, self.content_type = name, data, ""

    async def read(self):
        return self._d


@pytest.fixture()
def uploads_root(client, tmp_path, monkeypatch):
    monkeypatch.setattr(U, "UPLOADS_ROOT", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


def _save(name, data, sub="quotations"):
    return asyncio.run(U.save_document_files(sub, "MQ-202609-001", [_Up(name, data)], "tester"))


def test_save_document_files_accepts_real_and_rejects_disguised(uploads_root):
    from fastapi import HTTPException
    saved = _save("ok.png", PNG)
    assert len(saved) == 1 and (uploads_root / saved[0]["path"]).exists()
    before = sorted(p.name for p in uploads_root.rglob("*") if p.is_file())
    with pytest.raises(HTTPException) as e:
        _save("evil.pdf", EXE)
    assert e.value.status_code == 400 and "檔頭" in e.value.detail
    assert sorted(p.name for p in uploads_root.rglob("*") if p.is_file()) == before, "被擋下的檔案不可以落地"


def test_rejection_is_audited_without_content(uploads_root):
    from fastapi import HTTPException
    from db import get_db
    with pytest.raises(HTTPException):
        _save("evil.pdf", EXE)
    c = get_db()
    try:
        rows = c.execute("SELECT * FROM audit_log WHERE action='upload.rejected_magic'").fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    blob = " ".join(str(v) for v in dict(rows[0]).values())
    assert "evil.pdf" in blob and "tester" in blob and "MZ" not in blob


def test_whole_batch_rejected_when_one_file_is_bad(uploads_root):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(U.save_document_files("quotations", "MQ-202609-001", [_Up("a.png", PNG), _Up("b.pdf", EXE)], "t"))


def test_voucher_folder_office_files_checked_too(uploads_root):
    assert len(_save("a.docx", DOCX, "voucher_attachments")) == 1
    assert len(_save("a.xls", OLE, "voucher_attachments")) == 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _save("a.docx", EXE, "voucher_attachments")


def test_single_choke_point_no_per_module_copies():
    """自有存檔邏輯的兩處呼叫同一支函式；其他地方不得自己寫一份檔頭判斷。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    def src(rel):
        return open(os.path.join(root, rel), encoding="utf-8").read()
    assert "_check_upload_magic(" in src("modules/payroll/api/payslips.py")
    assert "_check_upload_magic(" in src("routers/system.py")
    assert "_check_upload_magic(" in src("helpers/uploads.py")
    offenders = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".venv", ".venv312", "logs", "node_modules")]
        for f in files:
            if f.endswith(".py") and f != "uploads.py":
                t = open(os.path.join(base, f), encoding="utf-8", errors="ignore").read()
                if '\\x89PNG' in t and "_magic" in t or "b\"%PDF-\"" in t:
                    offenders.append(os.path.relpath(os.path.join(base, f), root))
    assert not offenders, "檔頭判斷只准在 helpers/uploads.py：%s" % offenders


def test_payslip_signed_upload_rejects_disguised_file(client, make_user):
    """自有存檔邏輯（勞報單回簽檔）也走同一道：偽裝成 pdf 的 exe ⇒ 400（先過狀態檢查前的 404 也可接受＝沒有該單）。"""
    u, p = make_user(username="pay1", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/api/payslips/NOPE-1/signed-files", headers=h, files=[("files", ("x.pdf", EXE, "application/pdf"))])
    assert r.status_code in (400, 404, 409)


def test_work_log_photo_rejects_disguised_file(client, make_user):
    u, p = make_user(username="wl1", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/api/work-logs", headers=h, json={"log_date": "2026-09-30", "content": "x", "hours": 1})
    assert r.status_code in (200, 201), r.text
    wid = r.json().get("id")
    bad = client.post(f"/api/work-logs/{wid}/photos", headers=h, files=[("files", ("a.jpg", EXE, "image/jpeg"))])
    assert bad.status_code == 400 and "檔頭" in bad.text
    bad2 = client.post(f"/api/work-logs/{wid}/photos", headers=h, files=[("files", ("a.exe", PNG, "image/png"))])
    assert bad2.status_code == 400
