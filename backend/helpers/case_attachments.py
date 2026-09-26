# -*- coding: utf-8 -*-
"""M01 案件的附件來源（`attachments.for_document` 提供者；主持裁示 M06-b，2026-09-26）。

案件底下六類已上傳檔案的位置只有 M01 知道（其中三類在 `quotations.data_json` 的 caseRecord 陣列裡）：

| 來源類型 | 位置 | `doc_no` |
|---|---|---|
| quotation_signed | `quotations.signed_files_json` | 案件編號 |
| case_update | `case_updates.files_json`（一個案件多列，併起來） | 案件編號 |
| payment_item | caseRecord.payment.items[i].invoiceFiles | `案件編號_i` |
| material | caseRecord.materials[i].files | `案件編號_i` |
| material_invoice | caseRecord.materials[i].invoiceFiles | `案件編號_i` |
| extra_expense | `case_extra_expenses.files_json` | id |

M01 尚未搬進 modules/ ⇒ 以 `registry.provide()` 在匯入時登記（同 `helpers/quotations.py` 的 case.access）；
M01 搬遷時改寫進 `ModuleSpec.providers`（M01-PLAN，同 CA-O3）。
"""
import json

from helpers.uploads import AttachmentSourceError, files_from_json_column


def _quote_and_index(doc_no):
    """`{quote_no}_{idx}` 拆成 `(quote_no, idx)`。拆不出來回 `(doc_no, None)`。
    ⚠️ 從**右邊**切：報價單號本身含 `-` 不含 `_`，而索引一定在最後一段。"""
    base, sep, tail = (doc_no or "").rpartition("_")
    if sep and tail.isdigit():
        return base, int(tail)
    return doc_no, None


def _case_record(conn, quote_no):
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone()
    if row is None:
        return {}
    try:
        return (json.loads(row["data_json"] or "{}") or {}).get("caseRecord") or {}
    except (TypeError, ValueError):
        raise AttachmentSourceError("案件「%s」的資料格式不正確，無法帶入。" % quote_no)


#: `doc_no` 是 `{案件編號}_{索引}` 的那幾類（項目在 caseRecord 的陣列裡）：(外層鍵, 陣列鍵, 檔案鍵)
_INDEXED = {
    "payment_item": ("payment", "items", "invoiceFiles"),
    "material": (None, "materials", "files"),
    "material_invoice": (None, "materials", "invoiceFiles"),
}


def _items(cr, outer, key):
    return ((cr.get(outer) or {}).get(key) if outer else cr.get(key)) or []


class _CaseAttachments:
    LABEL = "案件"
    SOURCE_TYPES = ("quotation_signed", "case_update", "payment_item", "material", "material_invoice",
                    "extra_expense")

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no):
        if source_type in ("quotation_signed", "case_update"):
            return [quote_no]
        if source_type in _INDEXED:
            outer, key, _ = _INDEXED[source_type]
            return ["%s_%d" % (quote_no, i) for i in range(len(_items(_case_record(conn, quote_no), outer, key)))]
        if source_type == "extra_expense":
            return [str(r["k"]) for r in conn.execute(
                "SELECT id AS k FROM case_extra_expenses WHERE quote_no = ? ORDER BY id", (quote_no,))]
        raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)

    @staticmethod
    def files(conn, source_type, doc_no):
        if source_type == "quotation_signed":
            return files_from_json_column(conn, "quotations", "quote_no", doc_no, "signed_files_json")
        if source_type == "case_update":
            out = []
            for row in conn.execute("SELECT files_json FROM case_updates WHERE quote_no = ?", (doc_no,)):
                try:
                    out += json.loads(row["files_json"] or "[]") or []
                except (TypeError, ValueError):
                    raise AttachmentSourceError("案件動態的附件資料格式不正確，無法帶入。")
            return out
        if source_type in _INDEXED:
            quote_no, idx = _quote_and_index(doc_no)
            if idx is None:
                raise AttachmentSourceError("來源編號「%s」缺少項目索引（應為「案件編號_序號」）。" % doc_no)
            outer, key, fkey = _INDEXED[source_type]
            arr = _items(_case_record(conn, quote_no), outer, key)
            if idx < 0 or idx >= len(arr):
                return []
            return (arr[idx] or {}).get(fkey) or []
        if source_type == "extra_expense":
            return files_from_json_column(conn, "case_extra_expenses", "id", doc_no, "files_json")
        raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)


from core import registry as _registry  # noqa: E402
_registry.provide("attachments.for_document", "case", _CaseAttachments)
