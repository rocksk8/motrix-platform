# -*- coding: utf-8 -*-
"""payroll v2（2026-09-30，使用者核准：已發放獎金的「獎金更正單」）：新增 `bonus_corrections`、`bonus_correction_log`。

- 更正單對象＝已發放的獎金分潤單（`bonus_case_awards.status='已發放'`）；原單與原名單**不改**（歷史），更正的每人差額存在更正單自己的 `lines_json`。
- 狀態：草稿 → 待審核 → 待補發（有人要補發時）／已完成 → 已完成；草稿可作廢。同一張原單同時只有一張未結案的更正單（部分唯一索引）。
- 連到傳票的四個 id（沖轉、重開應付、補發、追回應收）預設 0；由程式經 `voucher.draft` 提供者開立草稿，不在這裡碰會計表。
- 只新增表：回退到舊程式碼時舊程式碼不讀它、照常運作（「只回程式」的回滾相容）。冪等：`IF NOT EXISTS`。
- 原單表不在（不該發生：V9 建）⇒ 回原因字串＝未完成（版號不前進、下次啟動再補）。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bonus_case_awards'").fetchone():
        return "bonus_case_awards 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    conn.execute("""CREATE TABLE IF NOT EXISTS bonus_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        corr_no TEXT NOT NULL UNIQUE,
        quote_no TEXT NOT NULL,
        award_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT '草稿' CHECK (status IN ('草稿','待審核','待補發','已完成','已作廢')),
        reason TEXT NOT NULL DEFAULT '',
        old_total INTEGER NOT NULL DEFAULT 0,
        new_total INTEGER NOT NULL DEFAULT 0,
        supplement_total INTEGER NOT NULL DEFAULT 0,
        clawback_total INTEGER NOT NULL DEFAULT 0,
        lines_json TEXT NOT NULL DEFAULT '[]',
        approval_json TEXT NOT NULL DEFAULT '{}',
        reversal_voucher_id INTEGER NOT NULL DEFAULT 0,
        rebook_voucher_id INTEGER NOT NULL DEFAULT 0,
        supplement_voucher_id INTEGER NOT NULL DEFAULT 0,
        clawback_voucher_id INTEGER NOT NULL DEFAULT 0,
        voucher_notice TEXT NOT NULL DEFAULT '',
        approved_by TEXT NOT NULL DEFAULT '',
        approved_at TEXT NOT NULL DEFAULT '',
        paid_by TEXT NOT NULL DEFAULT '',
        paid_at TEXT NOT NULL DEFAULT '',
        deductions_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        UNIQUE (award_id, seq))""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bonus_corr_one_open ON bonus_corrections(award_id)"
                 " WHERE status IN ('草稿','待審核','待補發')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bonus_corr_status ON bonus_corrections(status)")
    conn.execute("""CREATE TABLE IF NOT EXISTS bonus_correction_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        corr_id INTEGER NOT NULL,
        changed_by TEXT NOT NULL DEFAULT '',
        changed_at TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bonus_corr_log ON bonus_correction_log(corr_id)")
    return None
