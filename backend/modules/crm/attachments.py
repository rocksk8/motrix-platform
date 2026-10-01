# -*- coding: utf-8 -*-
"""M02 業務開發的附件目錄提供者（`attachments.catalog`，契約 v1，2026-09-30 P2）：開發記錄（dev_logs）附件。
`doc_no`＝開發記錄 id。權限＝`GET /dev-cases/{id}/logs` 的規則（`_require_dev` 模組規則＋row_access `dev_case`），
直接用 `_DevLogPathAccess`（同一支判斷，不寫第二份）。"""
import json

from helpers.uploads import AttachmentNotVisible, AttachmentSourceError, opened_upload_file, pick_file, upload_path_key
from modules.crm.api import _DevLogPathAccess


class _CrmCatalog:
    CATEGORIES = {
        "dev_log": {"label": "開發記錄附件", "doc": "業務開發記錄", "module": "業務開發"},
    }

    @staticmethod
    def open(conn, user, source_type, doc_no, file_id):
        if source_type != "dev_log":
            raise AttachmentSourceError("不支援的附件來源「%s」。" % source_type)
        if not str(doc_no).isdigit():
            return None
        row = conn.execute("SELECT case_id, files_json FROM dev_logs WHERE id = ?", (int(doc_no),)).fetchone()
        if row is None:
            return None
        if not _DevLogPathAccess.readable(conn, "dev_logs", (str(row["case_id"]), "-"), user):
            raise AttachmentNotVisible()
        try:
            files = json.loads(row["files_json"] or "[]") or []
        except (TypeError, ValueError):
            raise AttachmentSourceError("開發記錄「%s」的附件資料格式不正確。" % doc_no)
        entry = pick_file(files, file_id)
        if entry is None or upload_path_key(entry, "dev_logs") != str(row["case_id"]):
            return None                                          # 路徑不屬於這個開發案 ⇒ 當作沒有這個檔（W3）
        return opened_upload_file(entry)

    # ── 搜尋（附件目錄 P3）：權限＝open() 同一支 `_DevLogPathAccess.readable`（逐開發案，快取）──
    @staticmethod
    def _collect(conn, user, crit):
        from helpers import attachment_search as S
        sql = ("SELECT l.id, l.case_id, l.files_json, c.case_name, c.customer_name FROM dev_logs l "
               "JOIN dev_cases c ON c.id = l.case_id WHERE l.files_json LIKE ?")
        args = ["%\"path\"%"]
        if crit["quote_no"]:
            sql += " AND c.converted_quote_no = ?"
            args.append(crit["quote_no"])
        ok, items = {}, []
        for r in conn.execute(sql, args).fetchall():
            cid = r["case_id"]
            if cid not in ok:
                ok[cid] = bool(_DevLogPathAccess.readable(conn, "dev_logs", (str(cid), "-"), user))
            if not ok[cid]:
                continue
            try:
                files = json.loads(r["files_json"] or "[]") or []
            except (TypeError, ValueError):
                continue
            for f in files:
                if not S.owned(f, "dev_logs", cid):
                    continue                                         # 與 open() 同一道：路徑不在這個開發案的資料夾 ⇒ 不列
                items.append(S.make_item("dev_log", r["id"], "業務開發記錄 #%s" % r["id"], f, quote_no=crit["quote_no"],
                                         customer=r["customer_name"], project=r["case_name"], link="dev-crm.html?case=%s" % cid))
        return items

    @staticmethod
    def search(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.finish(_CrmCatalog._collect(conn, user, c), c)

    @staticmethod
    def count(conn, user, crit):
        from helpers import attachment_search as S
        c = S.normalize_crit(crit)
        return S.count_by_type(_CrmCatalog._collect(conn, user, c), c)
