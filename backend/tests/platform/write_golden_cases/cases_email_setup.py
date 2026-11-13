# -*- coding: utf-8 -*-
"""批 3 寄信帳號精靈兩條寫入端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：欄位不合法就寄測試信 ⇒ 422（不會對外連線）；
還沒有寄過測試信（沒有有效的測試證明）就啟用 ⇒ 4xx。成功形狀、失敗分類與設定單、證明的時效與指紋比對，
由 tests/test_email_setup_2026_11_13.py 與 tests/test_e2e_email_setup_2026_11_13.py 逐項斷言（寄信一律換掉，不連任何信箱主機）。"""
_E = (4,)
CASES = [
    {"key": "POST /api/settings/email-notify/wizard/test-me", "url": "/api/settings/email-notify/wizard/test-me",
     "body": {"provider": "gmail", "smtp_user": "not-an-email", "smtp_password": "x"}, "expect": _E},
    {"key": "POST /api/settings/email-notify/wizard/activate", "url": "/api/settings/email-notify/wizard/activate", "body": {}, "expect": _E},
]
WAIVE = {}
