# -*- coding: utf-8 -*-
"""2026-11-17 報價單規格 PDF 上傳／刪除端點的金標案例（feat/quote-spec-pdf-merge）。
setup 種一張草稿報價單（最高管理者可存取）；POST 上傳一個 1 頁 PDF ⇒ 200 `{specFiles, mergeFiles, …}`；
DELETE 先於本檔的 POST（案例依檔內順序、DELETE 排最後）上傳的檔，所以用固定 id 的 setup 種一筆規格檔再刪。
狀態鎖、格式／大小／數量限制、單筆壞檔不拖垮整批等規則由 tests/test_quote_spec_files_2026_11_17.py 逐項斷言。"""
import io
import json

_NO = "MQ-WG-SPEC"


def _blank_pdf():
    import pypdf
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _seed(conn):
    if conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (_NO,)).fetchone():
        return
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at)"
                 " VALUES (?,?,?,?,?,?,?,?,?)",
                 (_NO, "草稿", "金標客戶", "金標案", 0, 0, json.dumps({"quoteNo": _NO}), "2026-11-17T00:00:00", "2026-11-17T00:00:00"))


def _seed_with_file(conn):
    _seed(conn)
    conn.execute("UPDATE quotations SET spec_files_json=? WHERE quote_no=?",
                 (json.dumps([{"id": "wgspec1", "name": "金標規格.pdf", "path": "quotation_specs/%s/wgspec1.pdf" % _NO,
                               "size": 10, "pages": 1, "status": "ok", "uploadedAt": "2026-11-17T00:00:00", "uploadedBy": "wg_admin"}]), _NO))


CASES = [
    {"key": "POST /api/quotations/{quote_no}/spec-files", "url": "/api/quotations/%s/spec-files" % _NO, "setup": _seed,
     "files": [("files", ("金標.pdf", _blank_pdf(), "application/pdf"))]},
    {"key": "POST /api/quotations/{quote_no}/spec-files/discard-staged", "url": "/api/quotations/%s/spec-files/discard-staged" % _NO, "setup": _seed},
    {"key": "DELETE /api/quotations/{quote_no}/spec-files/{file_id}", "url": "/api/quotations/%s/spec-files/wgspec1" % _NO,
     "setup": _seed_with_file},
]
WAIVE = {}
