# -*- coding: utf-8 -*-
"""analytics 的資源回收筒 adapter（T87 B2 D5）：`custom_report`（我的報表＋它的分享列）。

只有設定 `custom_reports.recycle_deleted` 開啟時，`report_store.delete` 才會呼叫 `recycle_bin.delete`；設定關閉時直接刪（不經這裡）。
規則：`can_delete` 沿用現行刪除規則——**只有擁有者能刪自己的報表**（`report_store.delete` 已先驗；這裡再擋一次，adapter 不信呼叫端）。
還原：同一個擁有者已有同名報表 ⇒ 還原成「名稱（已還原）」並說明（不覆蓋既有、不報衝突）；主鍵被占用 ⇒ 配新主鍵並把分享列接到新主鍵；擁有者帳號已不存在 ⇒ 仍還原（報表只是設定）。
本檔名為 `recycle_adapter.py`：裡面的 `DELETE FROM` 免進回收筒三道守門基線（它們就是 `delete_in_tx`）。報表不含附件。
"""
import sqlite3
from typing import List, Tuple

from helpers import recycle_bin as RB



def _cols(conn, table) -> List[str]:
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _insert(conn, table, row: dict, drop_id: bool = False) -> int:
    have = set(_cols(conn, table))
    cols = [k for k in row if k in have and not (drop_id and k == "id")]
    try:
        cur = conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
    except sqlite3.IntegrityError as e:
        raise RB.BinError("conflict: 還原時資料衝突（%s：%s）" % (table, e))
    return cur.lastrowid


class CustomReportBinAdapter(RB.Adapter):
    entity_type = "custom_report"
    label = "自訂報表"

    def _row(self, conn, entity_id):
        try:
            rid = int(entity_id)
        except (TypeError, ValueError):
            return None
        return conn.execute("SELECT %s FROM custom_reports WHERE id=?" % ",".join(_cols(conn, "custom_reports")), (rid,)).fetchone()

    def can_delete(self, conn, entity_id, user) -> Tuple[bool, str]:
        r = self._row(conn, entity_id)
        if r is None:
            return False, "報表不存在"
        if r["username"] != (user or {}).get("username"):
            return False, "只有擁有者可以刪除自己的報表"
        return True, ""

    def snapshot(self, conn, entity_id) -> dict:
        r = self._row(conn, entity_id)
        if r is None:
            raise RB.BinError("報表不存在")
        row = dict(r)
        shares = [dict(s) for s in conn.execute("SELECT %s FROM custom_report_shares WHERE report_id=?" % ",".join(_cols(conn, "custom_report_shares")), (row["id"],))]
        return {"rows": {"custom_reports": [row], "custom_report_shares": shares}, "files": [],
                "label": "自訂報表 %s" % row["name"], "parent": None, "meta": {"source_id": row["source_id"]}}

    def delete_in_tx(self, conn, entity_id) -> None:
        r = self._row(conn, entity_id)
        if r is None:
            return
        conn.execute("DELETE FROM custom_report_shares WHERE report_id=?", (r["id"],))
        conn.execute("DELETE FROM custom_reports WHERE id=?", (r["id"],))

    def restore_in_tx(self, conn, snap, ctx) -> dict:
        row = dict(snap["rows"]["custom_reports"][0])
        notes = []
        old_id = row["id"]
        if conn.execute("SELECT 1 FROM custom_reports WHERE username=? AND name=?", (row["username"], row["name"])).fetchone():
            row["name"] = (row["name"][:30] + "（已還原）")
            n = 2
            while conn.execute("SELECT 1 FROM custom_reports WHERE username=? AND name=?", (row["username"], row["name"])).fetchone():
                row["name"] = row["name"][:30] + "（已還原%d）" % n
                n += 1
            notes.append("同名的報表已存在，還原後的名稱是「%s」" % row["name"])
        taken = conn.execute("SELECT 1 FROM custom_reports WHERE id=?", (old_id,)).fetchone() is not None
        new_id = _insert(conn, "custom_reports", row, drop_id=taken)
        if not taken:
            new_id = old_id
        for s in snap["rows"].get("custom_report_shares", []):
            s = dict(s)
            s["report_id"] = new_id
            _insert(conn, "custom_report_shares", s, drop_id=True)
        return {"entity_id": str(new_id), "renumbered": taken, "notes": notes}
