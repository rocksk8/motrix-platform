# -*- coding: utf-8 -*-
"""accounting v2（2026-09-30）：總帳申請表 `gl_action_requests`（會計規定 C 類：結帳／重開期間／年度決算／期初批次，
一般財務人員送申請、最高管理者（會計主管）核准後自動執行）。

只新增、冪等；回退程式碼時舊程式不讀這張表。申請只增不刪（撤回／退回／核准都是改狀態並留紀錄）。
"""
_TABLES = (
    """CREATE TABLE IF NOT EXISTS gl_action_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_no TEXT NOT NULL UNIQUE,
        action TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        params_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT '待審核',
        requested_by TEXT NOT NULL DEFAULT '',
        requested_by_display TEXT NOT NULL DEFAULT '',
        requested_at TEXT NOT NULL DEFAULT '',
        decided_by TEXT NOT NULL DEFAULT '',
        decided_at TEXT NOT NULL DEFAULT '',
        decision_note TEXT NOT NULL DEFAULT '',
        result_json TEXT NOT NULL DEFAULT '{}',
        approval_json TEXT NOT NULL DEFAULT '{}')""",       # 簽核佇列共用格式（requestedBy／tiers…），佇列提供者讀它

)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_gl_action_requests_status ON gl_action_requests(status, id)",
    "CREATE INDEX IF NOT EXISTS idx_gl_action_requests_user ON gl_action_requests(requested_by, id)",
)


def up(conn):
    for ddl in _TABLES + _INDEXES:
        conn.execute(ddl)
