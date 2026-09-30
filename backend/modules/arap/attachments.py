# -*- coding: utf-8 -*-
"""M05 應收應付的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：開票申請已開立檔案。
權限＝開票申請自己的讀取規則（`_voucher_readable`：案件層＋金額層，含本單簽核人例外），同 `attachments.for_document` 提供者。"""
from helpers.uploads import AttachmentSourceError, opened_upload_file, pick_file, upload_path_key
from modules.arap.api.invoice_vouchers import _InvoiceVoucherAttachments


class _ArapCatalog:
    CATEGORIES = {
        "invoice_voucher": {"label": "開票申請已開立檔案", "doc": "開票申請", "module": "應收應付"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "invoice_voucher":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        files = _InvoiceVoucherAttachments.files(conn, source_type, doc_no, user)    # 看不到 ⇒ AttachmentNotVisible
        entry = pick_file(files, file_id)
        if entry is None or upload_path_key(entry, "invoice_vouchers") != str(doc_no):
            return None                                          # 路徑不屬於這張開票申請 ⇒ 當作沒有這個檔（W3）
        return opened_upload_file(entry)
