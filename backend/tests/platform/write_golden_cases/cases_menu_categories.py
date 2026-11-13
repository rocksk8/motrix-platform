# -*- coding: utf-8 -*-
"""選單分類／設定說明覆寫端點的金標案例（批次 9）。記錄『錯誤形狀』（4xx，鍵集＝detail）：不存在的分類、不存在的設定欄位（兩個都在寫入前就被拒，不碰資料）。
成功形狀（有效分類與覆寫筆數）與內容守門由 tests/test_settings_center_b9_2026_11_13.py 以真實使用者逐項斷言；
PUT /api/menu/categories/override 成功時回整份有效分類（含每個設定群組一組鍵，約 440 行），資料長出來的鍵不適合進金標。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/menu/categories/override", "url": "/api/menu/categories/override",
     "body": {"categories": {"no_such_category": {"name": "x"}}}, "expect": _E},
    {"key": "PUT /api/menu/settings-help/override", "url": "/api/menu/settings-help/override",
     "body": {"no_such_group.no_such_field": None}, "expect": _E},
]
WAIVE = {}
