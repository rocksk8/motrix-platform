# -*- coding: utf-8 -*-
"""M07 薪資獎金的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：勞報單簽回檔。
實體檔在**勞報單封存目錄**（可設定，不在 uploads/）⇒ 宣告 `ROOTS`，由 L1 `/api/attachments/open` 驗檔案落在該根之下。
權限＝`GET /api/payslips/{no}/signed-files/{id}`：superadmin 或出納（`cashier` 模組）；看不到 ⇒ 404。"""
import json
import mimetypes
import os

from helpers.auth import user_has_module
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, OpenedFile, pick_file
from modules.payroll.api import payslips as _p


class _PayrollCatalog:
    CATEGORIES = {
        "payslip_signed": {"label": "勞報單簽回檔", "doc": "勞報單", "module": "薪資獎金"},
    }

    @staticmethod
    def ROOTS():
        return [_p._archive_dir()]

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "payslip_signed":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        if user.get("role") != "superadmin" and not user_has_module(user, "cashier"):
            raise AttachmentNotVisible()
        row = conn.execute("SELECT signed_files_json FROM payslips WHERE slip_no = ?", (doc_no,)).fetchone()
        if row is None:
            return None
        try:
            files = json.loads(row["signed_files_json"] or "[]") or []
        except (TypeError, ValueError):
            raise AttachmentSourceError("勞報單「%s」的簽回檔資料格式不正確。" % doc_no)
        meta = pick_file(files, file_id)
        if meta is None:
            return None
        try:
            path = _p._signed_path(doc_no, str(meta.get("id")), meta.get("ext", ""))
        except ValueError:
            return None
        if not os.path.isfile(path):
            return None
        name = str(meta.get("filename") or os.path.basename(path))
        return OpenedFile(path, name, mimetypes.guess_type(name)[0] or "application/octet-stream", os.path.getsize(path))
