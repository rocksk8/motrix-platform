# -*- coding: utf-8 -*-
"""T69 總帳設定寫入端點的金標案例。記錄『錯誤形狀』（4xx，鍵集＝detail）：不存在的待核准項、缺欄位的申請、不合法的起始月份。
成功形狀與雙人核准流程由 modules/accounting/tests/test_ledger_settings_t69.py 以真實使用者逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/ledger/roles", "url": "/api/ledger/roles", "body": {"role": "", "account_code": ""}, "expect": _E},
    {"key": "POST /api/ledger/roles/pending/{pid}/approve", "url": "/api/ledger/roles/pending/999999/approve", "body": {"reason": "金標：不存在的項目"}, "expect": _E},
    {"key": "POST /api/ledger/roles/pending/{pid}/cancel", "url": "/api/ledger/roles/pending/999999/cancel", "body": {"reason": "金標：不存在的項目"}, "expect": _E},
    {"key": "PUT /api/ledger/settings", "url": "/api/ledger/settings", "body": {"fiscal_year_start_month": 13}, "expect": _E},
]
WAIVE = {}
