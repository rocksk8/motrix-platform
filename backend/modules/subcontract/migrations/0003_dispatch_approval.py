# -*- coding: utf-8 -*-
"""subcontract v3（2026-10-01，第 31 班 31-A：承攬商派發審核）：`contractor_dispatches` 加審核欄位（設計 docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md）。

兩段審核與既有「作業狀態」（status：draft／sent／confirmed／pending_acceptance／accepted／completed／cancelled）**分開**，下游讀者照舊讀 status：
- 第一段（派發審核）：approval_status＝''（舊單，不溯及既往；migration 預設）／草稿（新單尚未送審）／待審核／簽核中／已核准／已退回；approval_json＝簽核鏈與歷程（形狀同各單據 approval：requestedBy、tiers、currentTier、history…）；
  doc_code＝人看的單號 DP-YYYYMMDD-NNNN（新單才有；舊單維持空字串，不受唯一限制）；submitted_by／submitted_at／approved_at；approved_hash＝核准當下「實質欄位」（承攬商、品項、人員、稅率）的雜湊，之後不同 ⇒ 需重新送審
- 第二段（完工審核）：completion_status（同上五值）、completion_approval_json、completion_requested_by／_at、completion_approved_at
  ——`completed` 只能由完工審核通過這個事件設定
- 取消：cancel_reason／cancelled_by／cancelled_at（已核准的派發取消要理由）
- 只新增欄位與索引、冪等；舊列全部維持原值（approval_status／completion_status 預設空字串＝舊單）；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；
  不自己 commit、不 import 會演進的程式碼；SQL 寫在這裡。
"""

_COLS = (
    ("approval_status", "TEXT NOT NULL DEFAULT ''"),
    ("approval_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("doc_code", "TEXT NOT NULL DEFAULT ''"),
    ("submitted_by", "TEXT NOT NULL DEFAULT ''"),
    ("submitted_at", "TEXT NOT NULL DEFAULT ''"),
    ("approved_at", "TEXT NOT NULL DEFAULT ''"),
    ("approved_hash", "TEXT NOT NULL DEFAULT ''"),
    ("completion_status", "TEXT NOT NULL DEFAULT ''"),
    ("completion_approval_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("completion_requested_by", "TEXT NOT NULL DEFAULT ''"),
    ("completion_requested_at", "TEXT NOT NULL DEFAULT ''"),
    ("completion_approved_at", "TEXT NOT NULL DEFAULT ''"),
    ("cancel_reason", "TEXT NOT NULL DEFAULT ''"),
    ("cancelled_by", "TEXT NOT NULL DEFAULT ''"),
    ("cancelled_at", "TEXT NOT NULL DEFAULT ''"),
)


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_dispatches)").fetchall()}
    if not cols:
        return "contractor_dispatches 表不存在，派發審核欄位這次不補、下次啟動再試"
    for name, ddl in _COLS:
        if name not in cols:
            conn.execute("ALTER TABLE contractor_dispatches ADD COLUMN %s %s" % (name, ddl))
    # doc_code 有值時必須唯一（舊單是空字串，不受限）
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_doc_code ON contractor_dispatches(doc_code) WHERE doc_code <> ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_approval ON contractor_dispatches(approval_status, completion_status)")
    return None
