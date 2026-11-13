# -*- coding: utf-8 -*-
"""「開始使用」清單寫入端點的金標案例（2026-11-13）：記錄『錯誤形狀』（4xx，鍵集＝detail）：動作不認得 ⇒ 400。
成功形狀、權限（只限最高管理者）、略過／手動確認規則由 tests/test_getting_started_2026_11_13.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/getting-started/steps/{step_id}", "url": "/api/getting-started/steps/email", "body": {"action": "explode"}, "expect": _E},
]
WAIVE = {}
