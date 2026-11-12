# -*- coding: utf-8 -*-
"""T83 授權匯入的寫入端點金標案例。記錄『錯誤形狀』（4xx）：內容不是授權檔 ⇒ 400（鍵集＝detail／reason／message 等白話欄位）。
成功形狀、預覽、換檔、備份、還原、頻率限制與權限由 tests/test_license_import_2026_11_13.py 逐項斷言（每題都把授權檔換到自己的暫存目錄；
這裡不可以真的換掉測試共用的授權檔，所以只記驗證不通過的形狀，不會寫任何東西）。"""
_E = (4,)
CASES = [
    {"key": "POST /api/license/import", "url": "/api/license/import", "body": {"content": "AAAA"}, "expect": _E},
]
WAIVE = {}
