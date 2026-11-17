# -*- coding: utf-8 -*-
"""2026-11-17 備註事項範本寫入端點的金標案例（feat/quote-extra-notes-page）。
範本名稱空白 ⇒ 400（錯誤形狀 `detail`）；正常儲存 ⇒ 200 `{templates:[…]}`（key 由伺服器派，案例用固定 key 讓回應可重現）。
驗證規則、權限、稽核與通知由 tests/test_quote_extra_notes_2026_11_17.py 逐項斷言。"""
CASES = [
    {"key": "PUT /api/settings/quote-notes-templates", "url": "/api/settings/quote-notes-templates",
     "body": {"templates": [{"key": "wg1", "name": "金標範本", "category": "AGV", "text": "備註事項：\n一、金標"}]}},
]
WAIVE = {}
