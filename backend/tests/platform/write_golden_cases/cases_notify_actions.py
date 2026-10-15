# -*- coding: utf-8 -*-
"""BP-4 額外通知動作的寫入類路由金標案例（旗標『開』的狀態）：POST /api/notify-actions/{key}/preview（唯讀試跑；只留一筆稽核）。
旗標『關』（404、什麼都不寫）由 tests/platform/test_notify_actions_t63.py 的 test_preview_route_is_404_when_off_403_for_others_422_when_invalid 守——
同一條路由在 CASES 裡只能有一個鍵，所以金標記的是有資料的那一邊。
setup(conn) 直接用設定引擎發布旗標（SR.publish，與設定中心同一個寫入口）。"""

_BODY = {"version": 1, "label": "金標通知", "enabled": True, "event": "custom_module.transitioned",
         "when": [{"field": "新狀態", "in": ["已送出"]}], "channels": ["in_app"], "recipients": [{"kind": "role", "value": "admin"}],
         "template": {"title": "單據 {單據號} 已送出", "body": "{操作人} 把 {單據號} 從 {原狀態} 改成 {新狀態}"},
         "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}


def _setup(conn):
    from helpers import settings_registry as SR
    from helpers import notify_actions as NA
    SR.publish("builder_governance", {"enabled": 1}, user="golden", reason="golden", conn=conn)
    SR.publish(NA.GROUP, {"enabled": 1}, user="golden", reason="golden", conn=conn)
    SR.invalidate()
    assert NA.enabled(conn), "金標前置：旗標沒有打開"


CASES = [
    {"key": "POST /api/notify-actions/{key}/preview", "url": "/api/notify-actions/wg_notice/preview", "body": {"template": _BODY}, "setup": _setup},
]
WAIVE = {}
