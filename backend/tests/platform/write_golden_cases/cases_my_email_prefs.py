# -*- coding: utf-8 -*-
"""S6（2026-11-13）我的帳號「我要收的 Email 通知」寫入端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：
`changes` 為空 ⇒ 400。成功形狀、confirm 閘、CAS、最後一位超管（U15）與稽核由 tests/test_my_email_prefs_s6_2026_11_13.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/mail-types/mine", "url": "/api/mail-types/mine", "body": {"changes": {}}, "expect": _E},
]
WAIVE = {}
