# -*- coding: utf-8 -*-
"""傳票附件開放 Word／Excel（使用者 2026-09-30 裁示）：docx／xlsx／doc／xls 可上傳；exe 等仍拒；大小上限沿用；
PDF 匯出時這些只列檔名、不嵌入（不崩）；下載時 Content-Disposition 是 attachment 且檔名正確。
放行範圍在 `helpers/uploads.py::_EXTRA_EXTS_BY_SUBFOLDER`（只有 voucher_attachments），其他單據的上傳白名單不變。
"""
import io
import pathlib
import urllib.parse

import pytest

from modules.accounting.tests.test_voucher_pdf_export_2026_09_23 import (
    _create, _export, _hdr, _one_page_pdf, _pdf_text, _sign_off)

OFFICE = [("報價明細.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
          ("對帳表.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
          ("舊版說明.doc", "application/msword"),
          ("舊版報表.xls", "application/vnd.ms-excel")]


def _post(client, hdr, vid, name, content=b"PK\x03\x04office-bytes", mime="application/octet-stream"):
    return client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                       files={"files": (name, io.BytesIO(content), mime)})


def test_word_and_excel_files_can_be_uploaded_and_listed(client, make_user):
    _u, hdr = _hdr(client, make_user, "off_up")
    vid = _create(client, hdr)
    for name, mime in OFFICE:
        r = _post(client, hdr, vid, name, mime=mime)
        assert r.status_code == 200 and r.json()["added"] == 1, (name, r.status_code, r.text[:200])
    atts = client.get("/api/vouchers/%s" % vid, headers=hdr).json()["attachments"]
    assert sorted(a["filename"] for a in atts) == sorted(n for n, _ in OFFICE)
    assert all(a["mergeKind"] == "unsupported" for a in atts), "Word／Excel 不併入 PDF，畫面要標出來"


def test_uppercase_extension_is_accepted_and_exe_is_still_rejected(client, make_user):
    _u, hdr = _hdr(client, make_user, "off_rej")
    vid = _create(client, hdr)
    assert _post(client, hdr, vid, "大寫.DOCX").status_code == 200
    for bad in ("惡意.exe", "腳本.js", "偽裝.docx.exe", "巨集.docm", "壓縮.zip", "無副檔名"):
        r = _post(client, hdr, vid, bad)
        assert r.status_code == 400, (bad, r.status_code)
        assert "不支援的檔案格式" in r.text
    assert len(client.get("/api/vouchers/%s" % vid, headers=hdr).json()["attachments"]) == 1


def test_size_limit_and_empty_file_still_apply_to_office_files(client, make_user, monkeypatch):
    import helpers.uploads as up
    _u, hdr = _hdr(client, make_user, "off_size")
    vid = _create(client, hdr)
    monkeypatch.setattr(up, "_MAX_FILE_SIZE", 10)
    assert _post(client, hdr, vid, "太大.xlsx", content=b"x" * 11).status_code == 400
    assert _post(client, hdr, vid, "空的.docx", content=b"").status_code == 400
    assert _post(client, hdr, vid, "剛好.xlsx", content=b"x" * 10).status_code == 200


def test_other_document_types_keep_the_old_whitelist():
    """放行只限傳票附件：直接呼叫共用存檔函式，別的 subfolder 傳 docx 仍是 400（反向控制：白名單表被加到別處會紅）。"""
    import asyncio
    from fastapi import HTTPException, UploadFile
    import helpers.uploads as up

    async def go(sub):
        f = UploadFile(filename="x.docx", file=io.BytesIO(b"abc"))
        return await up.save_document_files(sub, "OFF-1", [f], "tester")

    with pytest.raises(HTTPException) as e:
        asyncio.run(go("quotations"))
    assert e.value.status_code == 400 and "jpg/png/pdf" in e.value.detail and "/docx" not in e.value.detail   # 訊息只列 jpg/png/pdf（檔名 x.docx 本身會出現，所以比對「/docx」）
    assert up._EXTRA_EXTS_BY_SUBFOLDER.keys() == {"voucher_attachments", "case_extra_expense"}   # 第44班：支出申請另放行 HEIC／HEIF（只有它；傳票不收 HEIC）
    assert up._EXTRA_EXTS_BY_SUBFOLDER["case_extra_expense"] == {".heic", ".heif"}


def test_download_is_an_attachment_with_the_right_filename(client, make_user):
    _u, hdr = _hdr(client, make_user, "off_dl")
    vid = _create(client, hdr)
    body = b"PK\x03\x04docx-download-bytes"
    r = _post(client, hdr, vid, "報價明細.docx", content=body, mime=OFFICE[0][1])
    fid = r.json()["attachments"][0]["file_id"]
    d = client.get("/api/vouchers/%s/attachments/%s" % (vid, fid), headers=hdr)
    assert d.status_code == 200 and d.content == body
    cd = d.headers.get("content-disposition", "")
    assert cd.lower().startswith("attachment"), cd                 # 不可 inline：Word／Excel 不在頁內開
    assert urllib.parse.quote("報價明細.docx") in cd or "報價明細.docx" in cd, cd
    assert d.headers.get("content-type", "").startswith(OFFICE[0][1])


def test_pdf_export_with_attachments_lists_office_files_by_name(client, make_user):
    _u, hdr = _hdr(client, make_user, "off_pdf")
    vid = _create(client, hdr)
    assert _post(client, hdr, vid, "報價明細.docx", mime=OFFICE[0][1]).status_code == 200
    assert _post(client, hdr, vid, "對帳表.xlsx", mime=OFFICE[1][1]).status_code == 200
    r = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                    files={"files": ("正常憑證.pdf", io.BytesIO(_one_page_pdf()), "application/pdf")})
    assert r.status_code == 200
    _sign_off(client, hdr, vid)
    out = _export(client, hdr, vid, with_attachments=True)
    assert out.status_code == 200 and out.content[:5] == b"%PDF-" and len(out.content) > 0     # 不崩
    printed = _pdf_text(out.content)
    for name in ("報價明細.docx", "對帳表.xlsx"):
        assert name in printed, "PDF 最後一頁要列出未併入的 %s；抽出文字前 200 字：%s" % (name, printed[:200])
    assert "未能併入" in printed or "未併入" in printed


def test_every_upload_input_on_the_page_accepts_office_types():
    from core import source_tree
    page = source_tree.page_file("voucher.html")            # 頁面路徑集中在 source_tree（模組搬家也找得到）
    html = page.read_text(encoding="utf-8")
    inputs = [ln for ln in html.splitlines() if 'type="file"' in ln]
    assert len(inputs) >= 3, inputs
    assert all(".docx" in ln and ".xlsx" in ln and ".doc" in ln and ".xls" in ln for ln in inputs), inputs
