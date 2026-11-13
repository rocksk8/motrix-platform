# -*- coding: utf-8 -*-
"""S3b 信件矩陣批次端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：空本體缺 changes／expect／states。
成功形狀、409 衝突形狀、確認關閉的 400 形狀由 tests/test_s3b_mail_matrix_2026_11_13.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/settings/mail/batch", "url": "/api/settings/mail/batch", "body": {}, "expect": _E},
    {"key": "POST /api/settings/mail/batch-preview", "url": "/api/settings/mail/batch-preview", "body": {}, "expect": _E},
    {"key": "POST /api/settings/mail/batch-undo", "url": "/api/settings/mail/batch-undo", "body": {}, "expect": _E},
]
WAIVE = {}
