# -*- coding: utf-8 -*-
"""T79 LINE 通知設定寫入端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：沒有 token 就要啟用、沒有 token 就驗證。
成功形狀、遮罩與保留規則由 tests/platform/test_line_notify_t79.py 逐項斷言（對外呼叫一律換掉，不連 LINE）。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/settings/line-notify", "url": "/api/settings/line-notify", "body": {"enabled": True}, "expect": _E},
    {"key": "POST /api/settings/line-notify/verify", "url": "/api/settings/line-notify/verify", "body": {}, "expect": _E},
    {"key": "PUT /api/settings/line-notify/events/{key}", "url": "/api/settings/line-notify/events/approval_review_edit", "body": {"enabled": "yes"}, "expect": _E},
    # LINE Login 綁定：沒設 Login channel／對外網址就發起 ⇒ 400；解除綁定（沒綁過）⇒ 200 {ok, unlinked}。完整流程見 test_line_login_t79.py
    {"key": "POST /api/line/binding/start", "url": "/api/line/binding/start", "body": {}, "expect": _E},
    {"key": "DELETE /api/line/binding", "url": "/api/line/binding"},
    {"key": "DELETE /api/line/binding/{username}", "url": "/api/line/binding/nobody"},
]
WAIVE = {}
