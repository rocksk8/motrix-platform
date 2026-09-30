# -*- coding: utf-8 -*-
"""M05 應收應付的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：開票申請已開立檔案。
權限＝開票申請自己的讀取規則（`_voucher_readable`：案件層＋金額層，含本單簽核人例外），同 `attachments.for_document` 提供者。"""
import json
from urllib.parse import quote

from helpers.uploads import AttachmentSourceError, opened_upload_file, pick_file
from modules.arap.api.invoice_vouchers import _InvoiceVoucherAttachments, _voucher_readable


class _ArapCatalog:
    CATEGORIES = {
        "invoice_voucher": {"label": "開票申請已開立檔案", "doc": "開票申請", "module": "應收應付"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "invoice_voucher":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        files = _InvoiceVoucherAttachments.files(conn, source_type, doc_no, user)    # 看不到 ⇒ AttachmentNotVisible
        return opened_upload_file(pick_file(files, file_id))

    # ── 搜尋（附件目錄 P3）：權限＝開票申請自己的讀取規則 `_voucher_readable`（逐張）──
    @staticmethod
    def _collect(conn, user, crit):
        from helpers import attachment_search as S
        sql, args = "SELECT voucher_no, quote_no, data_json, issued_files_json FROM invoice_vouchers WHERE issued_files_json LIKE ?", ["%\"path\"%"]
        if crit["quote_no"]:
            sql += " AND quote_no = ?"
            args.append(crit["quote_no"])
        rows = conn.execute(sql, args).fetchall()
        names = S.case_names(conn, {r["quote_no"] for r in rows})
        items = []
        for r in rows:
            if not _voucher_readable(conn, r, user):
                continue
            try:
                files = json.loads(r["issued_files_json"] or "[]") or []
            except (TypeError, ValueError):
                continue
            cust, proj = names.get(r["quote_no"], ("", ""))
            for f in files:
                items.append(S.make_item("invoice_voucher", r["voucher_no"], "開票申請 %s" % r["voucher_no"], f, quote_no=r["quote_no"],
                                         customer=cust, project=proj, link="case-management.html?q=" + quote(r["quote_no"], safe="")))
        return items

    @staticmethod
    def search(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.finish(_ArapCatalog._collect(conn, user, c), c)

    @staticmethod
    def count(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.count_by_type(_ArapCatalog._collect(conn, user, c), c)
