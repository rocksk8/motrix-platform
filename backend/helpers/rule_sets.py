# -*- coding: utf-8 -*-
"""規則集定義種類 `rule_set`（BP-2 R1；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §3）。

[單位] helper:rule_sets    [層] L1    [穩定度] 實驗（旗標 builder_rules 關閉時沒有任何呼叫端）
[公開介面] KIND, enabled, ensure_registered, published_rules
[不變式] ①旗標 `builder_rules.enabled` 關（預設）⇒ 不登記定義種類（`/api/definition-kinds` 與今天逐位元相同）、通用定義路由對 rule_set 一律『未知種類』或 404；
    ②**登記是懶登記**：只有旗標開時的規則路由會呼叫 `ensure_registered()`（匯入本檔不登記任何東西）；
    ③key＝規則主題（`rule_catalog.ENTITIES`），一個主題一份規則集；內容由 `rule_grammar.validate_rule_set` 驗證（同一份驗證器）；
    ④評估只讀**已發布版**（`published_rules`），不受功能狀態閘門影響（T57 §3.9b-1：閘門只管編輯／發布／顯示）；讀不到 ⇒ 空清單（不標記）。
[契約題] backend/tests/test_rule_catalog_2026_10_14.py
"""
import logging

from core import definitions as D
from core import spine as _spine
from helpers import rule_catalog as C
from helpers import rule_grammar as G

KIND = "rule_set"
GROUP, FIELD = "builder_rules", "enabled"
_log = logging.getLogger(__name__)


def enabled(conn=None) -> bool:
    """旗標 builder_rules.enabled（預設 0）。讀不到 ⇒ 關（＝今天的行為）。"""
    try:
        from helpers import settings_registry as SR
        return int(SR.get(GROUP, FIELD, conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001
        return False


def _validator(body, key):
    if key not in C.ENTITIES:
        return [{"path": "", "message": "未知的規則主題：%s（可用：%s）" % (key, "、".join(C.ENTITIES))}]
    return G.validate_rule_set(body, C.all_fields(key))


def _default(key):
    return {"rules": []}


def ensure_registered() -> None:
    """登記定義種類與功能閘門（可重複呼叫）。**只有旗標開時的規則路由會呼叫**。"""
    try:
        if KIND not in D.kinds():
            D.register_kind(KIND, label="規則集（標示）", validator=_validator, default=_default)
        if not _spine.has_kind_gate(KIND):
            _spine.register_kind_gate(KIND, _gate)
    except ValueError:                                                 # 兩個請求同時登記：另一個已經登記完成
        pass


def _gate(key):
    """通用定義路由對 rule_set 的功能狀態：旗標關 ⇒ hidden（404）；開 ⇒ open。"""
    return "open" if enabled() else "hidden"


def published_rules(conn, entity) -> list:
    """該主題最新已發布版的規則（停用的也在內；由引擎略過）。沒有／讀不到 ⇒ []。"""
    try:
        r = D.get(conn, KIND, entity, "company")
        rules = ((r or {}).get("body") or {}).get("rules")
        return rules if isinstance(rules, list) else []
    except Exception:                                                  # noqa: BLE001  規則讀不到不可影響任何畫面
        _log.warning("rule_sets: 讀取 %s 的已發布規則失敗，視為沒有規則", entity, exc_info=True)
        return []
