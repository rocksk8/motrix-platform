# -*- coding: utf-8 -*-
"""fix/excel-import-dataloss（2026-11-13）：Excel 匯入兩個批次端點的金標案例。記錄的是『預覽』（dryRun 不是 false ⇒ 只回計畫、不寫入）的回應鍵集；
寫入形狀與各項規則由 tests/test_excel_import_review_fixes_2026_11_13.py、tests/test_e2e_excel_import_dataloss_2026_11_13.py 逐項斷言。"""
CASES = [
    {"key": "POST /api/customers/import-rows", "url": "/api/customers/import-rows",
     "body": {"rows": [{"row": 2, "name": "金標預覽公司", "taxId": "", "phone": "", "data": {}}], "dryRun": True}},
    {"key": "POST /api/parts/import-rows", "url": "/api/parts/import-rows",
     "body": {"rows": [{"row": 2, "partNo": "GOLD-001", "name": "金標預覽料號"}], "dryRun": True}},
]
WAIVE = {}
