# -*- coding: utf-8 -*-
"""「我的帳號」個人偏好寫入路由的金標案例（2026-11-13）。PUT /api/auth/preferences 只寫呼叫者自己的偏好（user_prefs），回應是整份偏好視圖。"""

CASES = [
    {"key": "PUT /api/auth/preferences", "url": "/api/auth/preferences", "body": {"theme": "light", "font_size": "normal"}},
]
WAIVE = {}
