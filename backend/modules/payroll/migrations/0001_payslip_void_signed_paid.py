# -*- coding: utf-8 -*-
"""payroll v1（2026-09-29）：勞報單作廢、簽回、出納付款。

狀態：草稿 → 已匯出 → 已簽回（上傳對方簽回檔）→ 已付款（出納填付款日期＋既有傳票單號）；已作廢＝終結（只准從已匯出）。
- 作廢三欄：voided_at／voided_by／void_reason。
- 簽回：signed_files_json（檔案 metadata，實體檔在勞報單存檔目錄＝F2）／signed_at／signed_by。
- 付款：payment_date（營運報表成本歸月依據）／voucher_no（出納回填的既有傳票單號，不由勞報單開傳票）／paid_by／paid_at。
- 只新增欄位：回退到舊程式碼時，舊程式碼不讀它、照常運作（「只回程式」的回滾相容）。冪等：欄位已在就不加。
- 表不在（不該發生：V9 建）⇒ 回原因字串＝未完成（版號不前進、下次啟動再補）。不建表、不猜。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""

_COLUMNS = (
    ("voided_at", "TEXT NOT NULL DEFAULT ''"),
    ("voided_by", "TEXT NOT NULL DEFAULT ''"),
    ("void_reason", "TEXT NOT NULL DEFAULT ''"),
    ("signed_files_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("signed_at", "TEXT NOT NULL DEFAULT ''"),
    ("signed_by", "TEXT NOT NULL DEFAULT ''"),
    ("payment_date", "TEXT NOT NULL DEFAULT ''"),
    ("voucher_no", "TEXT NOT NULL DEFAULT ''"),
    ("paid_by", "TEXT NOT NULL DEFAULT ''"),
    ("paid_at", "TEXT NOT NULL DEFAULT ''"),
)


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()}
    if not cols:
        return "payslips 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    for name, ddl in _COLUMNS:
        if name not in cols:
            conn.execute("ALTER TABLE payslips ADD COLUMN %s %s" % (name, ddl))
    return None
