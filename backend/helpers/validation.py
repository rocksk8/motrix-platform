# -*- coding: utf-8 -*-
"""請求本文的共用驗證（第 49 班 W1c-P2）。

[單位] helper:validation    [層] L1    [穩定度] 實作
[公開介面] body_flag、strict_bool
[契約題] tests/test_strict_bool_helper_t49.py

🔴 為什麼有這一支：`bool(body.get("flag"))` 與 `1 if body.get("flag") else 0` 會把 JSON 字串 `"false"`、`"0"`、`""` 當成 **true**。
前端送真正的布林所以平時無事，但 API 直打、舊用戶端或腳本只要多帶一個引號，**關卡（確認旗標、`accept_warnings`、緊急開關…）就被繞過**。
規則：旗標只收 `true`／`false`（或整數 `0`／`1`）；其他型別一律 **422**，什麼都不寫。
守門：`tests/platform/test_no_truthy_request_flags.py` 禁止在端點裡對請求本文用 `bool(...)`／真值三元式取旗標。
"""
from fastapi import HTTPException


def strict_bool(value, field: str = "value") -> bool:
    """`True`／`False`（或整數 0／1）⇒ 布林；其他（字串 "false"／"0"／""、None、list、dict、2…）⇒ 422。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise HTTPException(422, "%s 必須是 true 或 false" % field)


def body_flag(body, key: str, default: bool = False) -> bool:
    """請求本文裡的旗標：沒帶（或本文是 None）、或值是 JSON null ⇒ `default`；帶了就必須是真布林（見 `strict_bool`），否則 422。"""
    if not isinstance(body, dict) or key not in body or body[key] is None:
        return default
    return strict_bool(body[key], key)
