# -*- coding: utf-8 -*-
"""subcontract v1（2026-09-30，W1 出納匯款手續費）：`contractor_payment_vouchers` 加匯款實付／手續費／差額審核欄位。

- remit_actual：實付金額（NULL＝沒記錄過，舊資料；報表與比對一律回退用應付金額）
- remit_fee：匯款手續費（公司自付的額外支出，不從受款方扣；0＝沒有）
- remit_review：差額審核狀態（''＝不需審核／舊資料、'pending'＝實付≠應付待核可、'approved'＝已核可）
- remit_review_by／remit_review_at／remit_review_note：核可人、時間、備註（退回＝回未匯款，欄位一併清空，紀錄留在稽核與 paid_log）
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
"""

_COLS = (
    ("remit_actual", "REAL"),
    ("remit_fee", "REAL NOT NULL DEFAULT 0"),
    ("remit_review", "TEXT NOT NULL DEFAULT ''"),
    ("remit_review_by", "TEXT NOT NULL DEFAULT ''"),
    ("remit_review_at", "TEXT NOT NULL DEFAULT ''"),
    ("remit_review_note", "TEXT NOT NULL DEFAULT ''"),
)


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_payment_vouchers)").fetchall()}
    if not cols:
        return "contractor_payment_vouchers 表不存在，匯款手續費欄位這次不補、下次啟動再試"
    for name, ddl in _COLS:
        if name not in cols:
            conn.execute("ALTER TABLE contractor_payment_vouchers ADD COLUMN %s %s" % (name, ddl))
    return None
