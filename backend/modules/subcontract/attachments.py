# -*- coding: utf-8 -*-
"""M04 外包工班的附件來源（`attachments.for_document` 提供者；主持裁示 M06-b，2026-09-26）。

| 來源類型 | 位置 | `doc_no` |
|---|---|---|
| contractor_dispatch | `contractor_dispatches.files_json` | 派工單 id |
| contractor_invoice | `contractor_dispatches.invoice_files_json` | 派工單 id（與上一類同鍵，取用方以 `(type, docNo)` 區分） |
"""
from helpers.case_access import case_documents_readable
from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, files_from_json_column

_COLUMNS = {"contractor_dispatch": "files_json", "contractor_invoice": "invoice_files_json"}


class _SubcontractAttachments:
    LABEL = "外包工班"
    SOURCE_TYPES = tuple(_COLUMNS)

    @staticmethod
    def doc_nos_for_case(conn, source_type, quote_no, user):
        if source_type not in _COLUMNS:
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        docs = [str(r["k"]) for r in conn.execute(
            "SELECT id AS k FROM contractor_dispatches WHERE quote_no = ? ORDER BY id", (quote_no,))]
        if not case_documents_readable(conn, quote_no, user):        # 同派工單清單的讀取規則（AT-M1）
            # 只回「沒列出幾個附件」（數字），不帶單號與內容（主持裁示 2026-09-26）
            raise AttachmentNotVisible(hidden=sum(_count(conn, source_type, d) for d in docs))
        return docs

    @staticmethod
    def files(conn, source_type, doc_no, user):
        if source_type not in _COLUMNS:
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        row = conn.execute("SELECT quote_no FROM contractor_dispatches WHERE id = ?", (doc_no,)).fetchone()
        if row is None:
            return []
        if not case_documents_readable(conn, row["quote_no"], user):
            raise AttachmentNotVisible()
        return files_from_json_column(conn, "contractor_dispatches", "id", doc_no, _COLUMNS[source_type])


class _SubcontractCatalog:
    """`attachments.catalog`（契約 v1，2026-09-30 P2）：派工單報價單附件與承攬商發票。
    權限＝派工單單筆端點的規則（模組 ∨ 看得到該案的單據），同 `_SubcontractPathAccess`（不用 for_document 那條較窄的：
    單筆端點本來就讓這些模組看到檔案路徑）。"""
    CATEGORIES = {
        "contractor_dispatch": {"label": "派工單附件", "doc": "承攬派工單", "module": "外包工班"},
        "contractor_invoice": {"label": "承攬商發票", "doc": "承攬派工單", "module": "外包工班"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        from helpers.uploads import opened_upload_file, pick_file, upload_path_key
        if source_type not in _COLUMNS:
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        if not str(doc_no).isdigit():
            return None
        row = conn.execute("SELECT id FROM contractor_dispatches WHERE id = ?", (int(doc_no),)).fetchone()
        if row is None:
            return None
        if not _SubcontractPathAccess.readable(conn, "contractor_dispatches", (str(int(doc_no)), "-"), user):
            raise AttachmentNotVisible()
        files = files_from_json_column(conn, "contractor_dispatches", "id", int(doc_no), _COLUMNS[source_type])
        entry = pick_file(files, file_id)
        folder = "contractor_dispatches" if source_type == "contractor_dispatch" else "contractor_dispatch_invoices"
        if entry is None or upload_path_key(entry, folder) != str(int(doc_no)):
            return None                                          # 路徑不屬於這張派工單 ⇒ 當作沒有這個檔（W3）
        return opened_upload_file(entry)

    # ── 搜尋（附件目錄 P3）：權限＝open() 同一支 `_SubcontractPathAccess.readable`（逐派工單）──
    @staticmethod
    def _collect(conn, user, crit):
        import json
        from urllib.parse import quote
        from helpers import attachment_search as S
        sql = ("SELECT id, quote_no, files_json, invoice_files_json FROM contractor_dispatches "
               "WHERE (files_json LIKE ? OR invoice_files_json LIKE ?)")
        args = ["%\"path\"%", "%\"path\"%"]
        if crit["quote_no"]:
            sql += " AND quote_no = ?"
            args.append(crit["quote_no"])
        rows = conn.execute(sql, args).fetchall()
        names = S.case_names(conn, {r["quote_no"] for r in rows})
        items = []
        for r in rows:
            if not _SubcontractPathAccess.readable(conn, "contractor_dispatches", (str(r["id"]), "-"), user):
                continue
            cust, proj = names.get(r["quote_no"], ("", ""))
            for st, col in _COLUMNS.items():
                try:
                    files = json.loads(r[col] or "[]") or []
                except (TypeError, ValueError):
                    continue
                folder = "contractor_dispatches" if st == "contractor_dispatch" else "contractor_dispatch_invoices"
                for f in files:
                    if not S.owned(f, folder, r["id"]):
                        continue                                     # 與 open() 同一道：路徑不在這張派工單的資料夾 ⇒ 不列
                    items.append(S.make_item(st, r["id"], "%s #%s" % (_SubcontractCatalog.CATEGORIES[st]["doc"], r["id"]), f,
                                             quote_no=r["quote_no"], customer=cust, project=proj,
                                             link="case-management.html?q=" + quote(r["quote_no"] or "", safe="")))
        return items

    @staticmethod
    def search(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.finish(_SubcontractCatalog._collect(conn, user, c), c)

    @staticmethod
    def count(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.count_by_type(_SubcontractCatalog._collect(conn, user, c), c)


#: 派工單單筆 `GET /api/contractor-dispatches/{did}` 的模組（回應含 files_json／invoice_files_json 的路徑）
DISPATCH_READ_MODULES = ('procurement', 'case_manage', 'contractor_list', 'quotation')


class _SubcontractPathAccess:
    """`uploads.path_access`（IP-104，2026-09-30 P0）：`contractor_dispatches|contractor_dispatch_invoices/<派工id>/<檔名>`
    ⇒ 派工單存在，且（派工單單筆端點的模組規則 ∨ 看得到該案的單據 `case_documents_readable`，同 IP-21 提供者）。"""
    FOLDERS = ("contractor_dispatches", "contractor_dispatch_invoices")

    @staticmethod
    def readable(conn, folder, rest, user):
        from helpers.auth import user_has_module
        if len(rest) != 2 or not rest[0].isdigit():
            return False
        row = conn.execute("SELECT quote_no FROM contractor_dispatches WHERE id = ?", (int(rest[0]),)).fetchone()
        if row is None:
            return False
        if user.get("role") == "superadmin" or any(user_has_module(user, k) for k in DISPATCH_READ_MODULES):
            return True
        return bool(row["quote_no"]) and case_documents_readable(conn, row["quote_no"], user)


def _count(conn, source_type, doc_no):
    """看不到的那一筆有幾個附件（只給 hidden 的數字用；壞資料算 1）。"""
    try:
        return len(files_from_json_column(conn, "contractor_dispatches", "id", doc_no, _COLUMNS[source_type]) or [])
    except AttachmentSourceError:
        return 1
