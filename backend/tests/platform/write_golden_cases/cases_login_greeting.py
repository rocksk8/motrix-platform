# -*- coding: utf-8 -*-
"""登入問候語句庫寫入端點的金標案例（UX P1.5）。記錄『錯誤形狀』（4xx，鍵集＝detail）：不存在的類別。
成功形狀與內容守門由 tests/test_login_greeting_2026_11_13.py 以真實使用者逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/login-greeting/phrases", "url": "/api/login-greeting/phrases",
     "body": {"category": "no_such_category", "style": "formal", "lines": []}, "expect": _E},
]
WAIVE = {}
