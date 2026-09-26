# -*- coding: utf-8 -*-
"""M04 外包工班的附件來源（`attachments.for_document` 提供者；主持裁示 M06-b，2026-09-26）。

| 來源類型 | 位置 | `doc_no` |
|---|---|---|
| contractor_dispatch | `contractor_dispatches.files_json` | 派工單 id |
| contractor_invoice | `contractor_dispatches.invoice_files_json` | 派工單 id（與上一類同鍵，取用方以 `(type, docNo)` 區分） |
"""
from helpers.uploads import AttachmentSourceError, files_from_json_column

_COLUMNS = {"contractor_dispatch": "files_json", "contractor_invoice": "invoice_files_json"}


class _SubcontractAttachments:
    LABEL = "外包工班"
    SOURCE_TYPES = tuple(_COLUMNS)

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no):
        if source_type not in _COLUMNS:
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        return [str(r["k"]) for r in conn.execute(
            "SELECT id AS k FROM contractor_dispatches WHERE quote_no = ? ORDER BY id", (quote_no,))]

    @staticmethod
    def files(conn, source_type, doc_no):
        if source_type not in _COLUMNS:
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        return files_from_json_column(conn, "contractor_dispatches", "id", doc_no, _COLUMNS[source_type])
