# -*- coding: utf-8 -*-
"""M03 採購・庫存・出貨的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：出貨單回簽附件。
權限＝出貨單自己的讀取規則（`case_documents_readable`，同 `shipping_notes._ShippingPathAccess` 與單筆端點 `_readable_note`）。"""
import json

from helpers.case_access import case_documents_readable
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, opened_upload_file, pick_file


class _SupplyCatalog:
    CATEGORIES = {
        "shipping_note": {"label": "出貨單回簽", "doc": "出貨單", "module": "採購・庫存・出貨"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "shipping_note":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        row = conn.execute("SELECT quote_no, signed_files_json FROM shipping_notes WHERE note_no = ?", (doc_no,)).fetchone()
        if row is None:
            return None
        if not case_documents_readable(conn, row["quote_no"], user):
            raise AttachmentNotVisible()
        try:
            files = json.loads(row["signed_files_json"] or "[]") or []
        except (TypeError, ValueError):
            raise AttachmentSourceError("出貨單「%s」的附件資料格式不正確。" % doc_no)
        return opened_upload_file(pick_file(files, file_id))
