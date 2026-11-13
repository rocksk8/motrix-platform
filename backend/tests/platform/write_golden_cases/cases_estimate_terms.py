# -*- coding: utf-8 -*-
"""2026-11-13 估價單自己的條款設定寫入端點的金標案例（feat/estimate-own-terms）。
條款組名稱空白 ⇒ 400（錯誤形狀 `detail`）；預設付款條件任何文字都收 ⇒ 200 `{ok}`。
兩邊獨立、遷移複製、送審比對基準由 tests/test_estimate_own_terms_2026_11_13.py 逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "PUT /api/settings/estimate-terms-presets", "url": "/api/settings/estimate-terms-presets",
     "body": {"presets": [{"name": ""}], "defaultKey": ""}, "expect": _E},
    {"key": "PUT /api/settings/estimate-payment-terms", "url": "/api/settings/estimate-payment-terms",
     "body": {"text": "金標：估價單預設付款條件"}},
]
WAIVE = {}
