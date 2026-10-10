# -*- coding: utf-8 -*-
"""M03 採購・庫存・出貨的刪除暫存區 adapter（第 53 班 P1；契約 helpers/recycle_bin.py、IP-RB1／IP-RB2）：出貨單 `shipping_note`。

規則（使用者 D1）：不放寬現行『只有草稿能刪』；已核准／簽核中的只走 superadmin 的『刪除已核可』（`can_delete_approved`）：
已核准且已扣庫存序號的出貨單**明確拒絕**（要先用『撤銷核准』歸還庫存序號，再刪）——不在暫存區裡悄悄放掉庫存扣帳。
本檔名為 `recycle_adapter.py`：裡面的 `DELETE FROM` 免進三道守門基線（就是 `delete_in_tx`）。
"""
import json
import sqlite3
from typing import List, Tuple

from helpers import recycle_bin as RB
from helpers.uploads import canonical_upload_path

#: 暫存區模組不在時，刪除端點的明說（IP-RB2「對方不在時」）
BIN_ABSENT_NOTICE = "刪除暫存區模組未安裝：這張出貨單已直接刪除，無法還原"


def _walk_paths(obj, out: list) -> None:
    if isinstance(obj, dict):
        p = obj.get("path")
        if isinstance(p, str):
            rel = canonical_upload_path(p)
            if rel:
                out.append(rel)
        for v in obj.values():
            _walk_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_paths(v, out)


def _paths_of(*raws) -> List[str]:
    out: list = []
    for raw in raws:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw else None
            except ValueError:
                raw = None
        _walk_paths(raw, out)
    return list(dict.fromkeys(out))


def _rm_empty_dirs(rels) -> None:
    """附件被搬進暫存區後，原本單據專屬的資料夾若已空就拿掉（與原本 purge_document_files 的行為相同；有別的檔就保留；還原時由 recyclebin 重建）。"""
    import os
    from helpers.uploads import UPLOADS_ROOT
    for d in {os.path.dirname(os.path.join(UPLOADS_ROOT, *r.split("/"))) for r in rels or []}:
        try:
            os.rmdir(d)
        except OSError:
            pass


def _remap_json(raw, ctx):
    def walk(o):
        if isinstance(o, dict):
            d = {k: walk(v) for k, v in o.items()}
            p = d.get("path")
            if isinstance(p, str) and ("uploads", p) in ctx.files:
                d["path"] = ctx.file_path("uploads", p)
            return d
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o
    try:
        return json.dumps(walk(json.loads(raw)), ensure_ascii=False) if raw else raw
    except ValueError:
        return raw


class ShippingNoteAdapter(RB.Adapter):
    entity_type = "shipping_note"
    label = "出貨單"

    def _row(self, conn, entity_id):
        return conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (str(entity_id),)).fetchone()

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "出貨單不存在"
        return (True, "") if r["status"] == "草稿" else (False, "僅草稿狀態可刪除")

    def _shipped_stock(self, conn, note_no) -> int:
        try:
            return conn.execute("SELECT COUNT(*) FROM stock_items WHERE shipping_note_no=? AND status='shipped'", (str(note_no),)).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def can_delete_approved(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "出貨單不存在"
        for it in self.impact(conn, entity_id):
            if it.get("blocking"):
                return False, it["label"]
        return True, ""

    def impact(self, conn, entity_id) -> List[dict]:
        r = self._row(conn, entity_id)
        if r is None:
            return []
        out = []
        n = self._shipped_stock(conn, entity_id)
        if n:
            out.append({"kind": "stock_deducted", "label": "已扣庫存序號 %d 個：請先用『撤銷核准』歸還庫存，再刪除" % n, "blocking": True})
        if r["is_signed"]:
            out.append({"kind": "signed_back", "label": "客戶已回簽（%s）；回簽檔會一併進暫存區" % (r["signed_at"] or "")[:10], "blocking": False})
        if r["status"] == "已核准":
            out.append({"kind": "approved", "label": "已核准的出貨單：刪除後材料申請的『已出貨量』會減少", "blocking": False})
        return out

    def snapshot(self, conn, entity_id) -> dict:
        r = self._row(conn, entity_id)
        if r is None:
            raise RB.BinError("出貨單不存在")
        row = dict(r)
        return {"rows": {"shipping_notes": [row]}, "files": [{"root": "uploads", "rel": p} for p in _paths_of(row.get("signed_files_json"), row.get("data_json"))],
                "label": "出貨單 %s（%s）" % (row["note_no"], row.get("customer_name") or ""), "parent": ("quotation", row["quote_no"]) if row.get("quote_no") else None,
                "meta": {"quote_no": row.get("quote_no") or "", "status": row.get("status") or ""}}

    def delete_in_tx(self, conn, entity_id) -> None:
        r = self._row(conn, entity_id)
        rels = _paths_of(r["signed_files_json"], r["data_json"]) if r is not None else []
        conn.execute("DELETE FROM shipping_notes WHERE note_no=?", (str(entity_id),))
        _rm_empty_dirs(rels)

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        row = dict(snap["rows"]["shipping_notes"][0])
        qn = row.get("quote_no") or ""
        if qn:
            try:
                has = conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (qn,)).fetchone() is not None
            except sqlite3.OperationalError:                      # 案件模組不在：沒有父層可檢查
                has = True
            if not has:
                raise RB.BinError("parent_missing: 報價單 %s 不在了（可能也在暫存區）：請先還原報價單" % qn)
        if self._row(conn, row["note_no"]) is not None:
            raise RB.BinError("conflict: 出貨單號 %s 已被占用" % row["note_no"])
        if "id" in row and conn.execute("SELECT 1 FROM shipping_notes WHERE id=?", (row["id"],)).fetchone():
            row.pop("id")
        for c in ("signed_files_json", "data_json"):
            if row.get(c):
                row[c] = _remap_json(row[c], ctx)
        have = {r[1] for r in conn.execute("PRAGMA table_info(shipping_notes)").fetchall()}
        cols = [k for k in row if k in have]
        try:
            conn.execute("INSERT INTO shipping_notes (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
        except sqlite3.IntegrityError as e:
            raise RB.BinError("conflict: 還原時資料衝突（%s）" % e)
        return {"entity_id": row["note_no"], "renumbered": False, "notes": []}


def adapters() -> dict:
    """`{entity_type: Adapter 類別}`——module 的 ModuleSpec.providers 用。"""
    return {ShippingNoteAdapter.entity_type: ShippingNoteAdapter}
