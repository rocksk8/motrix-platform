# -*- coding: utf-8 -*-
"""「備份與監控」頁（2026-11-13）寫入端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：沒帶確認、參數型別不對、不存在的申請。
這些端點的成功形狀、權限、限流、備份互斥、停用雙人核准由 tests/test_backup_monitor_2026_11_13.py 與
tests/test_backup_monitor_review_fixes_2026_11_13.py 逐項斷言（備份、對外打卡、寄信一律換成假的，不碰真的備份與網路）。"""
_E = (4,)
CASES = [
    {"key": "POST /api/system/backup-monitor/backup-now", "url": "/api/system/backup-monitor/backup-now", "body": {}, "expect": _E},
    {"key": "PUT /api/system/backup-monitor/heartbeat-url", "url": "/api/system/backup-monitor/heartbeat-url", "body": {"pingUrl": 123}, "expect": _E},
    {"key": "POST /api/system/backup-monitor/heartbeat-test", "url": "/api/system/backup-monitor/heartbeat-test", "body": {}, "expect": _E},
    {"key": "POST /api/system/backup-monitor/heartbeat-disable", "url": "/api/system/backup-monitor/heartbeat-disable", "body": {}, "expect": _E},
    {"key": "POST /api/system/backup-monitor/heartbeat-disable/{change_id}/approve", "url": "/api/system/backup-monitor/heartbeat-disable/999999/approve",
     "body": {"confirm": True}, "expect": _E},
    {"key": "POST /api/system/backup-monitor/heartbeat-disable/{change_id}/cancel", "url": "/api/system/backup-monitor/heartbeat-disable/999999/cancel",
     "body": {}, "expect": _E},
    {"key": "POST /api/system/backup-monitor/heartbeat-disable/{change_id}/reject", "url": "/api/system/backup-monitor/heartbeat-disable/999999/reject",
     "body": {"confirm": True, "reason": "不認得這個申請"}, "expect": _E},
]
WAIVE = {}
