# -*- coding: utf-8 -*-
"""設定矩陣 S4c 簽核流程複製端點的金標案例（真成功形狀，不是錯誤形狀）。
setup 先把「統一流程」設成兩層、「出貨單」設成獨立且空的流程：預覽回每個目標的會不會變／進行中件數／planHash；套用的 planHash 在 setup 裡用同一支
`_plan` 算好填進請求（與伺服器重算的是同一份）。拒絕規則（空來源、跟隨統一流程的來源、planHash 過期）由 tests/test_approval_flow_copy_2026_11_14.py 逐項斷言。"""
import json

_SRC = {"tiers": [{"order": 1, "approvers": [{"sourceType": "user", "username": "wg_a"}]},
                  {"order": 2, "approvers": [{"sourceType": "user", "username": "wg_b"}]}], "includeSubmitterManagerTier": False}
_PREVIEW = {"source": "unified", "targets": ["shipping"]}
_APPLY = {"source": "unified", "targets": ["shipping"], "planHash": ""}


def _put(conn, key, value):
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, '2026-11-14T00:00:00') "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, json.dumps(value, ensure_ascii=False)))


def _state(conn):
    _put(conn, "unified_approval_flow", _SRC)
    _put(conn, "shipping_approval_flow", {"tiers": []})
    _put(conn, "approval_flow_scope", {"shipping": False})


def _setup_preview(conn):
    _state(conn)


def _setup_apply(conn):
    from helpers import approval_flow_copy as afc
    _state(conn)
    conn.commit()
    _APPLY["planHash"] = afc._plan(conn, afc.parse_request(dict(_PREVIEW)))["planHash"]


CASES = [
    {"key": "POST /api/approval/flows/copy/preview", "url": "/api/approval/flows/copy/preview", "body": _PREVIEW, "setup": _setup_preview},
    {"key": "POST /api/approval/flows/copy", "url": "/api/approval/flows/copy", "body": _APPLY, "setup": _setup_apply},
]
WAIVE = {}
