# -*- coding: utf-8 -*-
"""自訂模組引擎總開關（P8，T78）：設定 `builder_custom_modules.enabled`（預設 0＝關；與其他 builder_* 功能「預設關、逐項開」同一慣例）。

[單位] helper:custom_module_switch    [層] L1    [穩定度] 實作
[公開介面] GROUP；creation_block(conn, kind, key, scope="company") → None｜(HTTP 狀態, 訊息)
[不變式] ①關著時**只擋「建立」**：這個 key 還沒有任何已發布版本的 `custom_module` 不能存草稿、發布、還原、核可；
            已發布模組的既有單據（`custom_records`）、查詢、輸出與它自己的草稿／發布／還原**完全不受影響**（關閉不是下架）。
         ②開關讀取走 `settings_strict`（讀不到 ⇒ 503 往嚴格方向收，不悄悄當成開著）。
         ③只管 `custom_module` 的 company 範圍（其他範圍本來就被 `_custom_module_scope_guard` 擋掉）。
[呼叫端] routers/definitions.py（存草稿／發布／還原）、routers/custom_records.py（核可送審中的定義版本）。
"""
import logging

from core import definitions as D

logger = logging.getLogger(__name__)

GROUP = "builder_custom_modules"
MSG = "尚未開放建立新的自訂模組：請最高管理者先到設定中心開啟「自訂模組引擎」（builder_custom_modules）。已發布的自訂模組不受影響。"


def creation_block(conn, kind, key, scope="company"):
    """⇒ None（放行）或 `(狀態碼, 訊息)`。"""
    if kind != "custom_module" or scope != "company":
        return None
    try:
        from helpers.settings_strict import strict_value
        val = strict_value(conn, GROUP, "enabled")
    except Exception:                                                                              # noqa: BLE001
        logger.exception("讀取 %s.enabled 失敗，暫不放行建立自訂模組", GROUP)
        return (503, "無法確認自訂模組引擎的開關狀態，暫不放行建立；請稍後再試或通知管理者。")
    if isinstance(val, int) and not isinstance(val, bool) and val == 1:
        return None
    try:
        if D.get(conn, kind, key, scope) is not None:                                              # 已有發布版本 ⇒ 不是建立
            return None
    except D.DefinitionError:                                                                      # 代號格式不對等：交給原本的流程回它自己的錯誤
        return None
    return (403, MSG)
