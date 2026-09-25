# -*- coding: utf-8 -*-
"""料件分類代碼表（L1；DEPENDENCY-MAP §3 #17）。

原本定義在 `routers/parts.py`，M06 accounting_export 為了這張表 import 那支 router。
料號主檔已下沉 L1（CORE-SPEC 使用者裁示），代碼表跟著放在 L1 的 helper，
router 與各模組都從這裡取。
"""

# 固定分類清單：新增分類時可在此增列（顯示順序＝清單順序）
PART_CATEGORIES = [
    {"name": "網通設備", "prefix": "NET"},
    {"name": "監控設備", "prefix": "CCTV"},
    {"name": "交換器",   "prefix": "SW"},
    {"name": "伺服器/工控", "prefix": "SVR"},
    {"name": "線材配件", "prefix": "CAB"},
    {"name": "其他",     "prefix": "OTH"},
]
PART_CATEGORY_PREFIX = {c["name"]: c["prefix"] for c in PART_CATEGORIES}
