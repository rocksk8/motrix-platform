# -*- coding: utf-8 -*-
"""T86 職責角色權限矩陣端點的金標案例。三條都用「不存在的角色編號」：計畫裡那個角色是 `skipped`（找不到這個職責角色），
所以三條都回 200 的**成功形狀**（roles／summary／planHash／applied／conflicts…）、而且**不寫任何東西**（套用＝空計畫、復原＝全部衝突 ⇒ rollback）。
真正的寫入、原因規則、版本、整批交易、復原 CAS 由 tests/test_duty_role_matrix_2026_11_14.py 逐項斷言。"""
import hashlib
import json

#: 套用要帶預覽的 planHash：不存在的角色 999999 的計畫雜湊（與 helpers/duty_role_matrix._plan 同一個算法）
_HASH = hashlib.sha256(json.dumps([[999999, 0, [], []]], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]

CASES = [
    {"key": "POST /api/duty-roles/matrix/preview", "url": "/api/duty-roles/matrix/preview",
     "body": {"changes": [{"roleId": 999999, "grant": ["map"]}]}},
    {"key": "POST /api/duty-roles/matrix/apply", "url": "/api/duty-roles/matrix/apply",
     "body": {"changes": [{"roleId": 999999, "grant": ["map"]}], "planHash": _HASH}},
    {"key": "POST /api/duty-roles/matrix/undo", "url": "/api/duty-roles/matrix/undo",
     "body": {"changes": [{"roleId": 999999, "adds": ["map"]}]}},
]
WAIVE = {}
