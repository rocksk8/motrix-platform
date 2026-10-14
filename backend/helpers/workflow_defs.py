# -*- coding: utf-8 -*-
"""流程定義種類 `workflow` 與『有效定義』解析（BP-5 P1；設計 BP5-WORKFLOW-BUILDER-DESIGN-T62.md §3、§4、§10）。

[單位] helper:workflow_defs    [層] L1    [穩定度] 實驗（第一期：沒有任何端點呼叫 `effective()`；沒有路由呼叫 `ensure_registered()`）
[公開介面] KIND, flag_on, enabled, ensure_registered, effective
[不變式] ①旗標 `builder_workflow.enabled` 的設定群組在第一期**尚未登記**（登記時機＝第一個會呼叫引擎的路由，P2）⇒ `enabled()` 一律 False，
    不會有一個『開了也沒作用』的開關出現在設定中心，設定基準檔與 API 回應都與今天逐位元相同；
    ②登記是懶登記（匯入本檔不登記任何東西）；key＝單據類型，只收有內建定義的 plain 類單據；
    ③`effective()`：旗標關／沒有已發布公司版／讀不到 ⇒ 內建 v1（＝今天的行為）；絕不丟例外；
    ④旗標有效需要同時開啟建構器治理（`def_pipeline.enabled`），否則放寬無法走待核准，不可編輯。
[契約題] backend/tests/test_workflow_grammar_2026_10_14.py
"""
import logging

from core import definitions as D
from core import spine as _spine
from helpers import workflow_defaults as W
from helpers import workflow_grammar as G

KIND = "workflow"
GROUP, FIELD = "builder_workflow", "enabled"
_log = logging.getLogger(__name__)


def flag_on(conn=None) -> bool:
    """旗標本身。設定群組沒登記（第一期）或讀不到 ⇒ 關。"""
    try:
        from helpers import settings_registry as SR
        return int(SR.get(GROUP, FIELD, conn=conn)) == 1
    except Exception:                                                  # noqa: BLE001  KeyError（群組未登記）也在這裡 ⇒ 關
        return False


def enabled(conn=None) -> bool:
    """流程建構器是否有效：旗標開 **且** 建構器治理開。"""
    if not flag_on(conn):
        return False
    try:
        from routers import def_pipeline as P
        return bool(P.enabled(conn))
    except Exception:                                                  # noqa: BLE001
        return False


def _validator(body, key):
    if key not in W.doc_types():
        return [{"path": "", "message": "這種單據尚未開放流程建構：%s（可用：%s）" % (key, "、".join(W.doc_types()))}]
    problems = G.validate_workflow(body, key)
    if problems:
        return problems
    removed = G.removed_write_callbacks(W.builtin(key), body)
    out = [{"path": "transitions", "message": "不可拿掉寫入類回呼：轉換 %s 的 %s" % x} for x in removed]
    from helpers import tiered_approval as T
    if T.doc_class(key) == "stock":                                   # 核准會動庫存的單據：所有回呼都只能保留（可以加，不能拿掉）
        have = {t["id"]: set(t.get("callbacks") or []) for t in body.get("transitions") or []}
        for t in W.builtin(key)["transitions"]:
            for cb in t["callbacks"]:
                if cb not in have.get(t["id"], set()) and (t["id"], cb) not in removed:
                    out.append({"path": "transitions", "message": "此單據的核准會異動庫存，回呼只能保留：轉換 %s 的 %s" % (t["id"], cb)})
    return out


def _default(key):
    return W.builtin(key) or {}


def _gate(key):
    return "open" if enabled() else "hidden"


def ensure_registered() -> None:
    """登記定義種類與功能閘門（可重複呼叫）。第一期沒有任何呼叫端。"""
    try:
        if KIND not in D.kinds():
            D.register_kind(KIND, label="單據流程", validator=_validator, default=_default)
        if not _spine.has_kind_gate(KIND):
            _spine.register_kind_gate(KIND, _gate)
    except ValueError:
        pass


def effective(doc_type, conn=None):
    """⇒ 這種單據現在生效的流程定義（dict）；沒有內建版的單據 ⇒ None。**只讀、永不丟例外。**"""
    base = W.builtin(doc_type)
    if base is None:
        return None
    try:
        if not enabled(conn):
            return base
        if conn is None:
            import db
            c = db.get_db()
            try:
                return effective(doc_type, c)
            finally:
                c.close()
        r = D.get(conn, KIND, doc_type, "company")
        body = (r or {}).get("body")
        if isinstance(body, dict) and not _validator(body, doc_type):            # 與發布同一個驗證器（含不可拿掉的回呼、stock 類規則）
            return body
    except Exception:                                                  # noqa: BLE001
        _log.warning("workflow_defs: 讀取 %s 的已發布流程失敗，使用內建版", doc_type, exc_info=True)
    return base
