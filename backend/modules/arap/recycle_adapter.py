# -*- coding: utf-8 -*-
"""M05 應收應付的刪除暫存區 adapter（第 53 班 P1；IP-RB1，契約 `helpers/recycle_bin.py`）：請款單、開票申請憑據。

兩種單據都是『對客戶的文件』：沒有總帳、收款、獎金的下游連結（總帳事件來自案件收款明細，不是這兩張單據），
所以影響清單只有資訊性項目（已匯出幾次、有幾個已開立附件、行事曆事件）——不擋刪除。
- 一般刪除：沿用現行規則（只准草稿；使用者 D1 不放寬）。
- 『刪除已核可』（superadmin 專用入口 POST /api/recycle-bin/delete-approved）：只支援『已核准』。
- 還原：單號被占用 ⇒ `conflict:`；案件（quote_no）不在 ⇒ `parent_missing:`；已開立附件已由暫存區搬回（路徑被占用時改寫）。
本檔只 import L1 契約 `helpers.recycle_bin`，不 import `modules.recyclebin`。
"""
import json

from helpers import recycle_bin as RB


def _cols(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _json_list(raw):
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def insert_row(conn, table, row):
    """把快照列放回 `table`：只放現在表裡還有的欄位；原 id 沒被占用就沿用（讓連結不斷），被占用就讓 AUTOINCREMENT 另給。"""
    cols = set(_cols(conn, table))
    row = {k: v for k, v in row.items() if k in cols}
    if "id" in row and conn.execute("SELECT 1 FROM %s WHERE id=?" % table, (row["id"],)).fetchone():
        row.pop("id")
    names = list(row)
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(names), ",".join("?" * len(names))), [row[n] for n in names])


class _ArapDocAdapter(RB.Adapter):
    table = ""
    key_col = ""
    id_cols = ("id",)
    noun = ""
    has_issued_files = False

    # ── 規則 ──
    def _status(self, conn, entity_id):
        r = conn.execute("SELECT status FROM %s WHERE %s=?" % (self.table, self.key_col), (entity_id,)).fetchone()
        return None if r is None else r["status"]

    def can_delete(self, conn, entity_id, user):
        st = self._status(conn, entity_id)
        if st is None:
            return False, "%s不存在" % self.noun
        if st != "草稿":
            return False, "僅草稿狀態可刪除"
        return True, ""

    def can_delete_approved(self, conn, entity_id, user):
        st = self._status(conn, entity_id)
        if st is None:
            return False, "%s不存在" % self.noun
        if st == "草稿":
            return False, "草稿請用一般刪除"
        if st != "已核准":
            return False, "『刪除已核可』只支援已核准的%s（目前「%s」；送審中的請先退回）" % (self.noun, st)
        return True, ""

    def impact(self, conn, entity_id):
        r = conn.execute("SELECT * FROM %s WHERE %s=?" % (self.table, self.key_col), (entity_id,)).fetchone()
        if r is None:
            return []
        out = [{"kind": "approved", "label": "此%s已核准（簽核紀錄會一併進暫存區，還原時恢復）" % self.noun, "blocking": False}]
        if (r["export_count"] or 0) > 0:
            out.append({"kind": "exported", "label": "已匯出 %d 次（既有匯出 PDF 存檔不會被刪除，留在原存檔目錄）" % r["export_count"], "blocking": False})
        n_files = len(self._files(r))
        if n_files:
            out.append({"kind": "files", "label": "已開立附件 %d 個（隨單據進暫存區，還原時搬回）" % n_files, "blocking": False})
        try:
            d = json.loads(r["data_json"] or "{}")
        except ValueError:
            d = {}
        if d.get("googleCalendarEventId"):
            out.append({"kind": "calendar", "label": "已建立行事曆事件（不會自動刪除，請自行處理）", "blocking": False})
        return out

    # ── 快照／刪除／還原 ──
    def _files(self, row):
        if not self.has_issued_files:
            return []
        out, seen = [], set()
        for f in _json_list(row["issued_files_json"]):
            p = f.get("path") if isinstance(f, dict) else None
            if p and p not in seen:
                seen.add(p)
                out.append({"root": "uploads", "rel": p})
        return out

    def snapshot(self, conn, entity_id):
        r = conn.execute("SELECT * FROM %s WHERE %s=?" % (self.table, self.key_col), (entity_id,)).fetchone()
        if r is None:
            raise RB.BinError("%s不存在" % self.noun)
        row = {k: r[k] for k in r.keys()}
        return {"rows": {self.table: [row]}, "files": self._files(r), "label": "%s %s" % (self.noun, entity_id),
                "parent": None, "meta": {"quote_no": r["quote_no"], "status": r["status"], "key": entity_id}}

    def delete_in_tx(self, conn, entity_id):
        conn.execute("DELETE FROM %s WHERE %s=?" % (self.table, self.key_col), (entity_id,))

    def restore_in_tx(self, conn, snap, ctx):
        rows = (snap.get("rows") or {}).get(self.table) or []
        if len(rows) != 1:
            raise RB.BinError("快照內容不完整（找不到%s本體）" % self.noun)
        row = dict(rows[0])
        key = row[self.key_col]
        if conn.execute("SELECT 1 FROM %s WHERE %s=?" % (self.table, self.key_col), (key,)).fetchone():
            raise RB.BinError("conflict: 單號 %s 已被占用（可能已有同號的新單據），不覆蓋" % key)
        if row.get("quote_no") and conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (row["quote_no"],)).fetchone() is None:
            raise RB.BinError("parent_missing: 案件 %s 已不存在，無法還原" % row["quote_no"])
        notes = []
        if self.has_issued_files:
            files = _json_list(row.get("issued_files_json"))
            moved = 0
            for f in files:
                if isinstance(f, dict) and f.get("path"):
                    new = ctx.file_path("uploads", f["path"])
                    if new != f["path"]:
                        f["path"] = new
                        moved += 1
            row["issued_files_json"] = json.dumps(files, ensure_ascii=False)
            if moved:
                notes.append("%d 個附件因原路徑被占用，已改用新路徑" % moved)
        insert_row(conn, self.table, row)
        return {"entity_id": key, "renumbered": False, "notes": notes}


class PaymentRequestBinAdapter(_ArapDocAdapter):
    entity_type = "payment_request"
    label = "請款單"
    table = "payment_requests"
    key_col = "request_no"
    noun = "請款單"


class InvoiceVoucherBinAdapter(_ArapDocAdapter):
    entity_type = "invoice_voucher"
    label = "開票申請憑據"
    table = "invoice_vouchers"
    key_col = "voucher_no"
    noun = "開票申請憑據"
    has_issued_files = True
