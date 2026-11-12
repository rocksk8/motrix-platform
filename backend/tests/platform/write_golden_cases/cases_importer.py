# -*- coding: utf-8 -*-
"""T85 匯入精靈的金標案例。員工匯入記錄的是『預覽』（dryRun 不是 false ⇒ 只回計畫、不寫入、不含密碼）；
解析端點是 multipart，金標的 JSON 請求只會得到 4xx，記錄錯誤形狀（設定預設關 ⇒ 404）；成功形狀由 modules/importer/tests/test_importer_t85.py 斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/users/import-rows", "url": "/api/users/import-rows",
     "body": {"rows": [{"row": 2, "username": "gold_import_user", "displayName": "金標預覽", "role": "業務"}], "dryRun": True}},
    {"key": "POST /api/importer/parse", "url": "/api/importer/parse", "body": {"kind": "customers"}, "expect": _E},
]
WAIVE = {}
