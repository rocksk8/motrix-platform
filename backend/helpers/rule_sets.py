# -*- coding: utf-8 -*-
"""規則集定義種類 `rule_set`（BP-2 R1；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §3）。

[單位] helper:rule_sets    [層] L1    [穩定度] 實驗（旗標 builder_rules 關閉時沒有任何呼叫端）
[公開介面] KIND, enabled, ensure_registered, published_rules, K01_ENTITY, K01_ID, k01_seed_on, k01_seed_rule, k01_warn_pct
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
    """規則功能是否有效：`builder_rules.enabled`＝1 **而且** `builder_governance.enabled`＝1（規則的放寬分類、核准、預覽都靠治理層；
    治理層關著卻讓規則可發布，會讓放寬變更繞過第二位核准）。任一讀不到 ⇒ 關（＝今天的行為）。"""
    try:
        from helpers import settings_registry as SR
        return int(SR.get(GROUP, FIELD, conn=conn)) == 1 and int(SR.get("builder_governance", "enabled", conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001
        return False


#: 專案毛利提醒（K01）作為種子規則（設計 BP2-K01-SEED-T62.md）：代號固定，其他規則不得使用。
K01_ID = "k01_project_margin"
K01_ENTITY = "case"


def k01_seed_on(conn=None) -> bool:
    """旗標 builder_rules.k01_seed（預設 0），而且規則功能本身有效。讀不到 ⇒ 關（＝今天的行為）。"""
    try:
        from helpers import settings_registry as SR
        return enabled(conn) and int(SR.get(GROUP, "k01_seed", conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001
        return False


def k01_seed_rule(warn_pct) -> dict:
    """把『現在的設定值』轉成種子規則：今天的判定是 `警示門檻 > 0 且 專案毛利% 不是 None 且 專案毛利% < 門檻`；
    門檻 0＝不提醒 ⇒ 規則停用（值先放 20 當編輯起點）。標示位置只有表單（今天的提醒只出現在報價單內部損益區，不出現在列表）。"""
    try:
        w = float(warn_pct or 0)
    except (TypeError, ValueError):
        w = 0.0
    on = w > 0
    return {"id": K01_ID, "name": "專案毛利過低", "enabled": on, "mode": "mark", "on_failure": "degrade_loud", "surfaces": ["form"],
            "when": {"op": "lt", "field": "projectMarginPct", "value": (int(w) if w == int(w) else w) if on else 20},
            "mark": {"level": "red", "text": "專案毛利低於提醒門檻", "target": "row"}}


def k01_warn_pct(conn=None):
    """報價單表單要用的提醒門檻：種子旗標關、或規則還沒發布／被刪／格式不是『專案毛利% 低於 數字』⇒ **None**（呼叫端沿用設定中心的值＝今天的行為）；
    規則已發布且啟用 ⇒ 該門檻；規則已發布但停用 ⇒ 0（不提醒）。"""
    if not k01_seed_on(conn):
        return None
    own = conn is None
    try:
        if own:
            from db import get_db
            conn = get_db()
        for r in published_rules(conn, K01_ENTITY):
            if isinstance(r, dict) and r.get("id") == K01_ID:
                w = r.get("when") or {}
                if r.get("enabled") is False:
                    return 0.0
                if r.get("enabled", True) is True and w.get("op") == "lt" and w.get("field") == "projectMarginPct"                         and isinstance(w.get("value"), (int, float)) and not isinstance(w.get("value"), bool):
                    return float(w["value"])
                return None                                            # 格式被改成別的形狀 ⇒ 不是單一門檻，表單回到設定中心的值
        return None
    except Exception:                                                  # noqa: BLE001  讀不到 ⇒ 沿用設定中心的值
        return None
    finally:
        if own and conn is not None:
            conn.close()


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
