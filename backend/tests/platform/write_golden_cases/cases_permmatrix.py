# -*- coding: utf-8 -*-
"""T67 PM-S3 權限矩陣寫入端點的金標案例。正式資料庫沒有任何能力宣告（模組尚未接入，PM-S1 才開始宣告）、也沒有待生效項或版本，
所以每條都記錄『錯誤形狀』（4xx，鍵集＝detail）——狀態碼落在預期類別 4 才記錄，不會把非預期的 5xx 記成基準。
成功形狀（changed／version／pending／id…）由 modules/permmatrix/tests/test_permmatrix_s3_writes.py 以宣告過的能力逐項斷言。"""
_E = (4,)
CASES = [
    {"key": "POST /api/permmatrix/role-cap", "url": "/api/permmatrix/role-cap", "body": {"role": "sales", "cap": "zz.none.view", "granted": True}, "expect": _E},
    {"key": "POST /api/permmatrix/role-cap/preview", "url": "/api/permmatrix/role-cap/preview", "body": {"role": "sales", "cap": "zz.none.view", "granted": True}, "expect": _E},
    {"key": "POST /api/permmatrix/user-override", "url": "/api/permmatrix/user-override", "body": {"user_id": 1, "cap": "zz.none.view", "effect": "deny"}, "expect": _E},
    {"key": "POST /api/permmatrix/user-override/preview", "url": "/api/permmatrix/user-override/preview", "body": {"user_id": 1, "cap": "zz.none.view", "effect": "deny"}, "expect": _E},
    {"key": "DELETE /api/permmatrix/user-override", "url": "/api/permmatrix/user-override?user_id=1&cap=zz.none.view", "expect": _E},
    {"key": "POST /api/permmatrix/pending/{pid}/cancel", "url": "/api/permmatrix/pending/999999/cancel", "body": {"reason": "金標：不存在的項目"}, "expect": _E},
    {"key": "POST /api/permmatrix/pending/{pid}/approve", "url": "/api/permmatrix/pending/999999/approve", "body": {"reason": "金標：不存在的項目"}, "expect": _E},
    {"key": "POST /api/permmatrix/versions/{version_id}/restore", "url": "/api/permmatrix/versions/999999/restore", "body": {"reason": "金標：不存在的版本"}, "expect": _E},
    {"key": "POST /api/permmatrix/undo", "url": "/api/permmatrix/undo", "expect": _E},
]
WAIVE = {}
