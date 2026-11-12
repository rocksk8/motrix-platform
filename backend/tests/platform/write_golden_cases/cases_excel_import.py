# -*- coding: utf-8 -*-
"""T81 整合者補：Excel 匯入防資料遺失（fix/excel-import-dataloss）新增的兩條批次寫入端點的金標案例。
記錄『錯誤形狀』（4xx）：空 body 不是合法的匯入請求。成功形狀、合併規則、planHash／409 plan_changed 由
tests/test_excel_import_review_fixes_2026_11_13.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/customers/import-rows", "url": "/api/customers/import-rows", "body": {}, "expect": _E},
    {"key": "POST /api/parts/import-rows", "url": "/api/parts/import-rows", "body": {}, "expect": _E},
]
WAIVE = {}
