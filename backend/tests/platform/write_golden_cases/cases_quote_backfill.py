# -*- coding: utf-8 -*-
"""T69 補登歷史案件 L1 寫入端點的金標案例。預設開關是關的，所以記錄『被拒絕的形狀』（4xx，鍵集＝detail）；
成功形狀（quote_no／created_at／quote_date／status／dealTag）與各項規則由 tests/test_quote_backfill_l1_t69.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/quotations/historical", "url": "/api/quotations/historical",
     "body": {"data": {"customerName": "金標", "quoteDate": "2026-07-15", "items": []}, "reason": "金標：開關預設關"}, "expect": _E},
]
WAIVE = {}
