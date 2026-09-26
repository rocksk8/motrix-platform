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

權限（稽核 D AT-M1，主持裁示 (b)）：每一類都先確認使用者看得到那張案件（`case_documents_readable`），
看不到 ⇒ raise `AttachmentNotVisible`（取用方：列清單時不列、帶入／預覽 403）。
"""
import json

from helpers.case_access import case_documents_readable, case_owner_readable, case_page_readable
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, files_from_json_column


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


def _quote_of(conn, source_type, doc_no):
    """這一筆來源屬於哪一張案件；來源不存在 ⇒ None。"""
    if source_type in ("quotation_signed", "case_update"):
        return doc_no
    if source_type in _INDEXED:
        return _quote_and_index(doc_no)[0]
    if source_type == "extra_expense":
        row = conn.execute("SELECT quote_no FROM case_extra_expenses WHERE id = ?", (doc_no,)).fetchone()
        return row["quote_no"] if row else None
    raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)


#: 每一類用**原單據自己的讀取規則**（稽核 D AT-M1b：附件的可見範圍不可以比原單據寬）
#:   extra_expense ⇒ 額外支出各端點的 `_guard_case` ＝ `case_owner_readable`（不放行 case_manage）
#:   存在報價單上的四類 ⇒ 案件頁 `get_quotation` 的 `case_page_readable`（scope="read"：放行 cashier、不放行 case_manage；AT-M1c）
#:   case_update   ⇒ 案件動態端點的 `guard_case_access(allow_module="case_manage")` ＝ `case_documents_readable`
_READ_RULE = {"extra_expense": case_owner_readable,
              "quotation_signed": case_page_readable, "payment_item": case_page_readable,
              "material": case_page_readable, "material_invoice": case_page_readable}


def _require_readable(conn, source_type, quote_no, user):
    if not _READ_RULE.get(source_type, case_documents_readable)(conn, quote_no, user):
        raise AttachmentNotVisible()


class _CaseAttachments:
    LABEL = "案件"
    SOURCE_TYPES = ("quotation_signed", "case_update", "payment_item", "material", "material_invoice",
                    "extra_expense")

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no, user):
        docs = _CaseAttachments._docs(conn, source_type, quote_no)
        if not _READ_RULE.get(source_type, case_documents_readable)(conn, quote_no, user):
            # 看不到：只回「沒列出幾個附件」（數字），不帶單號與內容（主持裁示 2026-09-26）
            raise AttachmentNotVisible(hidden=sum(_count(conn, source_type, d) for d in docs))
        return docs

    @staticmethod
    def _docs(conn, source_type, quote_no):
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
    def files(conn, source_type, doc_no, user):
        quote_no = _quote_of(conn, source_type, doc_no)
        if quote_no is None or conn.execute("SELECT 1 FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone() is None:
            return []                                     # 來源不存在（契約：[]）
        _require_readable(conn, source_type, quote_no, user)
        return _read(conn, source_type, doc_no)


def _count(conn, source_type, doc_no):
    """看不到的那一筆有幾個附件（只給 hidden 的數字用；壞資料算 1：至少有東西沒列出）。"""
    try:
        return len(_read(conn, source_type, doc_no) or [])
    except AttachmentSourceError:
        return 1


def _read(conn, source_type, doc_no):
    """讀一筆來源的附件 metadata（**不查權限**：只給已查過權限的 `files()` 與只算數字的 `_count()` 用）。"""
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
