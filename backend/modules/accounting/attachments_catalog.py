# -*- coding: utf-8 -*-
"""M06 會計的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：傳票附件（`voucher_attachments` 表）。
`doc_no`＝傳票 id、`file_id`＝附件的 file_id。權限＝傳票各端點的閘門（`cashier`／`finance` 模組；看不到 ⇒ 與查無同一句 404），
附件必須屬於**這一張**傳票且未刪（同 `GET /api/vouchers/{id}/attachments/{file_id}`）。作廢傳票的附件照列（稽核要看得到）。"""
from helpers.auth import user_has_module
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, opened_upload_file

_VOUCHER_MODULES = ("cashier", "finance")         # 與 api/vouchers.py 的 _VOUCHER_MODULES 同；守門：tests 逐字比對


class _AccountingCatalog:
    CATEGORIES = {
        "voucher": {"label": "傳票附件", "doc": "傳票", "module": "會計"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "voucher":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        if not (user.get("role") == "superadmin" or any(user_has_module(user, k) for k in _VOUCHER_MODULES)):
            raise AttachmentNotVisible()
        if not str(doc_no).isdigit():
            return None
        att = conn.execute(
            "SELECT a.* FROM voucher_attachments a JOIN vouchers_all v ON v.id = a.voucher_id "
            "WHERE a.voucher_id = ? AND a.file_id = ? AND a.deleted_at = ''", (int(doc_no), str(file_id))).fetchone()
        if att is None:
            return None
        return opened_upload_file({"path": att["path"], "filename": att["filename"], "mime": att["mime"]})
