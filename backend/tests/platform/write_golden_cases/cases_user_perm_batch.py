# -*- coding: utf-8 -*-
"""設定矩陣 S3a 使用者權限批次端點的金標案例。三條都用「不存在的使用者編號」：計畫裡那個人是 `skipped`（找不到這位使用者），
所以三條都回 200 的**成功形狀**（people／summary／lists／applied／conflicts…）、而且**不寫任何東西**（套用＝空計畫、復原＝全員衝突 ⇒ rollback）。
真正的寫入、略過、原因規則、復原 CAS 由 tests/test_user_perm_batch_2026_11_13.py 逐項斷言。"""
CASES = [
    {"key": "POST /api/users/permissions/batch/preview", "url": "/api/users/permissions/batch/preview",
     "body": {"userIds": [999999], "grant": ["map"]}},
    {"key": "POST /api/users/permissions/batch", "url": "/api/users/permissions/batch",
     "body": {"userIds": [999999], "grant": ["map"]}},
    {"key": "POST /api/users/permissions/batch/undo", "url": "/api/users/permissions/batch/undo",
     "body": {"changes": [{"userId": 999999, "adds": ["map"]}]}},
]
WAIVE = {}
