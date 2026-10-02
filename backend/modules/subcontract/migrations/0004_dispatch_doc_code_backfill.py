# -*- coding: utf-8 -*-
"""subcontract v4（2026-10-02，修正：舊單申請完工進不了簽核佇列）：幫「已卡住」的派發補單號 `doc_code`。

背景：簽核佇列、簽核詳情、轉簽都以 `doc_code`（DP-YYYYMMDD-NNNN）為鍵；第 31-A 之前建立的舊單 `doc_code=''`。舊單申請完工時
（`dispatch_review_submit`）原本只把 `completion_status` 改成待審核、沒有補單號 ⇒ `_queue_for` 對空單號直接略過，該筆完工審核**永遠不顯示**
（正式機 2026-10-02 使用者回報）。程式已改成送審當下補號（`dispatch_review_submit`）；這支 migration 修**已經卡住**的資料。
**只補 `doc_code`，不動任何其他欄位**：對象＝任一段審核在「待審核／簽核中」而 `doc_code=''` 的列；單號日期取該筆送審的日期
（完工審核＝`completion_requested_at`、派發審核＝`submitted_at`，都沒有就取 `updated_at`，再沒有才用今天），流水號接在同日最大號之後。
冪等（補過就不再是空單號）；舊單沒卡住（沒有審核中）的不動、doc_code 維持空；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）。
不自己 commit、不 import 會演進的程式碼；SQL 與編號規則寫在這裡（與 `dispatch_flow.next_dispatch_code` 同格式）。"""
from datetime import datetime

_IN_REVIEW = ("待審核", "簽核中")


def _day(candidates):
    """單號用的日期（YYYYMMDD）：該筆送審的日期；取不到才用更新日、建立日、最後用今天。"""
    for v in candidates:
        v = (v or "")[:10]
        if len(v) == 10 and v[4] == "-" and v[7] == "-":
            return v.replace("-", "")
    return datetime.now().strftime("%Y%m%d")


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_dispatches)").fetchall()}
    if not cols:
        return "contractor_dispatches 表不存在，單號補號這次不做、下次啟動再試"
    need = {"doc_code", "approval_status", "completion_status", "completion_requested_at", "submitted_at", "updated_at", "created_at"}
    if not need <= cols:
        return "contractor_dispatches 還沒有審核欄位（0003 未完成），單號補號這次不做、下次啟動再試"
    rows = conn.execute(                                         # 一律用位置取值（不依賴連線的 row_factory）
        "SELECT id, completion_requested_at, submitted_at, updated_at, created_at FROM contractor_dispatches "
        "WHERE doc_code='' AND (approval_status IN (?,?) OR completion_status IN (?,?)) ORDER BY id", _IN_REVIEW + _IN_REVIEW).fetchall()
    for r in rows:
        stem = "DP-%s-" % _day((r[1], r[2], r[3], r[4]))
        last = conn.execute("SELECT MAX(doc_code) FROM contractor_dispatches WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                            (stem + "%", len(stem) + 4)).fetchone()
        n = int(last[0][-4:]) if last and last[0] else 0
        conn.execute("UPDATE contractor_dispatches SET doc_code=? WHERE id=? AND doc_code=''", ("%s%04d" % (stem, n + 1), r[0]))
    return None
