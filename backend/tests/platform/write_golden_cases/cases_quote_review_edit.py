# -*- coding: utf-8 -*-
"""簽核二擇一 S4：複查編輯端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：金標跑的是超管，超管一律被導去解鎖編輯（403）。
成功形狀、權限、對帳順序、重簽規則由 modules/case/tests/test_review_edit_s4_2026_11_07.py 以真實使用者逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/quotations/{quote_no}/review-edit", "url": "/api/quotations/MQ-GOLDEN-NONE/review-edit",
     "body": {"data": {}, "expectedFp": "1:golden"}, "expect": _E},
]
WAIVE = {}
