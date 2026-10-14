# -*- coding: utf-8 -*-
"""規則評估器（BP-2 R0；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §6）。

[單位] helper:rule_engine    [層] L1    [穩定度] 實驗（旗標 builder_rules 關閉時沒有任何呼叫端）
[公開介面] evaluate, Result 欄位說明見 evaluate
[不變式] ①純函式：不碰資料庫、不寫任何東西、不 import 本專案其他模組（只用 rule_grammar 的上限與走訪）、不執行任何字串；
    ②三態：true／false／unknown；缺值＝unknown；標記型 unknown＝不標記；
    ③遮蔽優先：條件用到任何『檢視者看不到』的欄位 ⇒ 該規則對這位檢視者**不評估**（不是 false：結果裡不出現、不計命中），
       因此無權限者不能由『紅／不紅』推得來源欄位；評估時只讀 `visible` 內的欄位；
    ④故障（逾時、超預算、例外）＝該條規則本次整條丟棄並回報 degraded，絕不丟例外給呼叫端、絕不影響其他規則；
    ⑤只有 mode=mark（block／fail_closed 之後再開；呼叫端傳入的規則若是別的 mode 一律略過並回報 not_applicable）。
[契約題] backend/tests/test_rule_engine_2026_10_14.py
"""
import time

from helpers import rule_grammar as G

_ABSENT = object()
DEFAULT_BUDGET_MS = 300


class _Budget(Exception):
    pass


def _kind(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    return None


def _cmp(n, vals):
    """比較節點 ⇒ True／False／None(unknown)。型別對不上也是 unknown（缺值或髒資料不是故障）。"""
    op = n["op"]
    v = vals.get(n["field"], _ABSENT)
    if op in ("empty", "not_empty"):
        if v is _ABSENT:
            return None
        e = v is None or v == ""
        return e if op == "empty" else not e
    if v is _ABSENT or v is None or v == "":
        return None
    k = _kind(v)
    if k is None:
        return None
    if op == "between":
        lo, hi = n["min"], n["max"]
        if _kind(lo) != k or _kind(hi) != k:
            return None
        return lo <= v <= hi
    if op == "in":
        vs = n["values"]
        return v in vs if all(_kind(x) == k for x in vs) else None
    c = n["value"]
    if _kind(c) != k:
        return None
    if op == "eq":
        return v == c
    if op == "ne":
        return v != c
    if k == "bool":
        return None
    return {"lt": v < c, "le": v <= c, "gt": v > c, "ge": v >= c}[op]


def _tri(n, vals):
    op = n["op"]
    if op == "and":
        res = [_tri(a, vals) for a in n["args"]]
        return False if False in res else None if None in res else True
    if op == "or":
        res = [_tri(a, vals) for a in n["args"]]
        return True if True in res else None if None in res else False
    if op == "not":
        r = _tri(n["arg"], vals)
        return None if r is None else not r
    return _cmp(n, vals)


def evaluate(rules, records, visible, *, budget_ms=DEFAULT_BUDGET_MS, clock=time.perf_counter, surface=None) -> dict:
    """`rules`＝已驗證的規則清單；`records`＝`[{"id": 識別, "values": {欄位代號: 值}}]`；`visible`＝檢視者看得到的欄位代號集合。
    ⇒ `{"marks": {紀錄id: [{ruleId, level, text, target, field?}]}, "hits": {規則id: 命中筆數}, "degraded": [{ruleId, reason}],
        "notApplicable": [規則id]}`；`surface`（list｜form）給了就只評估標示在該位置的規則（規則沒寫 `surfaces` ＝ 只在 list）；`reason` ∈ timeout｜budget｜error。`notApplicable` 只供最高管理者的畫面使用（一般檢視者的 API 不回）。"""
    out = {"marks": {}, "hits": {}, "degraded": [], "notApplicable": []}
    try:
        visible = frozenset(visible or ())
        deadline = clock() + max(1, int(budget_ms)) / 1000.0
        recs = [r for r in (records or []) if isinstance(r, dict) and isinstance(r.get("values"), dict)]
    except Exception:                                                  # noqa: BLE001  連入參都壞 ⇒ 什麼都不標
        return out
    for rule in list(rules or [])[: G.LIMITS["rules"]]:
        try:
            if not isinstance(rule, dict) or rule.get("enabled", True) is not True and rule.get("enabled") is not None:
                continue
            if rule.get("enabled") is False:
                continue
            if surface is not None and surface not in (rule.get("surfaces") or ["list"]):
                continue
            rid = rule["id"]
            if rule.get("mode", "mark") != "mark" or rule.get("on_failure", "degrade_loud") != "degrade_loud":
                out["notApplicable"].append(rid)
                continue
            needed = G.fields_used(rule["when"])
            mk = rule["mark"]
            if mk.get("target") == "field" and mk.get("field"):
                needed.add(mk["field"])
            if not needed <= visible:                                  # 遮蔽優先：看不到就不評估
                out["notApplicable"].append(rid)
                continue
        except Exception:                                              # noqa: BLE001
            out["degraded"].append({"ruleId": str(rule.get("id") if isinstance(rule, dict) else "?"), "reason": "error"})
            continue
        found = []
        try:
            for i, rec in enumerate(recs):
                if (i & 63) == 0 and clock() > deadline:
                    raise _Budget()
                if _tri(rule["when"], rec["values"]) is True:
                    found.append(rec["id"])
        except _Budget:
            out["degraded"].append({"ruleId": rid, "reason": "budget"})
            continue
        except Exception:                                              # noqa: BLE001
            out["degraded"].append({"ruleId": rid, "reason": "error"})
            continue
        out["hits"][rid] = len(found)
        m = {"ruleId": rid, "level": mk["level"], "text": mk["text"], "target": mk.get("target", "row")}
        if m["target"] == "field":
            m["field"] = mk["field"]
        for rec_id in found:
            out["marks"].setdefault(rec_id, []).append(dict(m))
    return out
