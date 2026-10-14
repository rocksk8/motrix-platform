# -*- coding: utf-8 -*-
"""規則文法與驗證器（BP-2 R0；設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §4）。

[單位] helper:rule_grammar    [層] L1    [穩定度] 實驗（旗標 builder_rules 關閉時沒有任何呼叫端）
[公開介面] validate_rule_set, fields_used, OPS_BY_TYPE, LIMITS
[不變式] ①宣告式：沒有運算式字串、沒有函式呼叫、沒有欄位對欄位的算式（只有『欄位 vs 常數』）；
    ②任何不在文法內的輸入一律回問題清單（不丟例外、不靜默丟掉）；
    ③本檔只 import 標準函式庫的 json／math／re／datetime，不 import 其他本專案模組（純函式，可單獨測）；
    ④先檢長度與型別再往下走；節點數、深度、規則數、文字長度皆有上限；
    ⑤第一版只開放 `mode=mark`、`on_failure=degrade_loud`（API 已帶這兩個欄位，之後開 block／fail_closed 不必改形狀）。
[契約題] backend/tests/test_rule_engine_2026_10_14.py

`fields`＝欄位目錄 `{欄位代號: {type, options?, ...}}`（由 `helpers.rule_catalog` 提供）。規則、簽核條件、浮水印占位日後共用這一份驗證器。
"""
import datetime
import json
import math
import re

LIMITS = {"nodes": 200, "depth": 8, "rules": 50, "name": 30, "text": 40, "in_values": 30, "str": 100, "bytes": 65536}
LEVELS = ("red", "yellow", "info")
TARGETS = ("row", "field")
RULE_KEYS = ("id", "name", "enabled", "mode", "on_failure", "when", "mark", "surfaces")
#: 標示出現在哪裡：list＝列表／卡片疊加層（預設）；form＝單筆表單內的提示（由表單自己讀門檻，例如專案毛利提醒）
SURFACES = ("list", "form")
MARK_KEYS = ("level", "text", "target", "field")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ORDER = ("lt", "le", "gt", "ge")
_NOVAL = ("empty", "not_empty")
#: 每種欄位型別可用的比較（日期以 ISO 字串字典序比；缺值＝unknown，見 rule_engine）
OPS_BY_TYPE = {
    "number": ("lt", "le", "gt", "ge", "eq", "ne", "between", "empty", "not_empty"),
    "text": ("eq", "ne", "in", "empty", "not_empty"),
    "enum": ("eq", "ne", "in", "empty", "not_empty"),
    "date": ("lt", "le", "gt", "ge", "between", "empty", "not_empty"),
    "bool": ("eq", "ne"),
}
_BOOL_OPS = ("and", "or", "not")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1e12


def _value_problem(f, v):
    """常數 v 對欄位 f 的型別是否合法 ⇒ 問題字串或 None。"""
    t = f.get("type")
    if t == "number":
        return None if _is_num(v) else "必須是數字"
    if t == "bool":
        return None if isinstance(v, bool) else "必須是 true／false"
    if t == "date":
        if isinstance(v, str) and _DATE_RE.match(v):
            try:
                datetime.date.fromisoformat(v)
                return None
            except ValueError:
                pass
        return "必須是日期（YYYY-MM-DD）"
    if not isinstance(v, str) or not 0 < len(v) <= LIMITS["str"]:
        return "必須是 1～%d 字的文字" % LIMITS["str"]
    if t == "enum" and isinstance(f.get("options"), list) and f["options"] and v not in f["options"]:
        return "不在這個欄位的選項內"
    return None


class _Walk:
    def __init__(self, fields, path):
        self.fields, self.path, self.nodes, self.problems = fields, path, 0, []

    def bad(self, p, msg):
        self.problems.append({"path": p, "message": msg})

    def node(self, n, p, depth):
        self.nodes += 1
        if self.nodes > LIMITS["nodes"]:
            if self.nodes == LIMITS["nodes"] + 1:
                self.bad(p, "條件太複雜（最多 %d 個節點）" % LIMITS["nodes"])
            return
        if depth > LIMITS["depth"]:
            self.bad(p, "條件巢狀太深（最多 %d 層）" % LIMITS["depth"])
            return
        if not isinstance(n, dict):
            self.bad(p, "條件必須是物件")
            return
        op = n.get("op")
        if op in ("and", "or"):
            extra = set(n) - {"op", "args"}
            if extra:
                self.bad(p, "不認得的設定：%s" % "、".join(sorted(map(str, extra))))
            args = n.get("args")
            if not isinstance(args, list) or not 1 <= len(args) <= LIMITS["nodes"]:
                self.bad(p + ".args", "必須是至少 1 項的清單")
                return
            for i, a in enumerate(args):
                self.node(a, "%s.args[%d]" % (p, i), depth + 1)
            return
        if op == "not":
            extra = set(n) - {"op", "arg"}
            if extra:
                self.bad(p, "不認得的設定：%s" % "、".join(sorted(map(str, extra))))
            self.node(n.get("arg"), p + ".arg", depth + 1)
            return
        self.cmp(n, p, op)

    def cmp(self, n, p, op):
        allowed = {"op", "field"} | ({"value"} if op in ("lt", "le", "gt", "ge", "eq", "ne") else {"min", "max"} if op == "between"
                                      else {"values"} if op == "in" else set())
        for k in n:
            if k not in allowed:
                self.bad("%s.%s" % (p, k), "不認得的設定：%s" % k)
        fid = n.get("field")
        f = self.fields.get(fid) if isinstance(fid, str) else None
        if f is None:
            self.bad(p + ".field", "不在欄位目錄內：%s" % (fid if isinstance(fid, str) else "（未填）"))
            return
        if not isinstance(op, str) or op not in OPS_BY_TYPE.get(f.get("type"), ()):
            self.bad(p + ".op", "這個欄位不能用這種比較：%s" % (op if isinstance(op, str) else "（未填）"))
            return
        if op in _NOVAL:
            return
        if op == "between":
            before = len(self.problems)
            for k in ("min", "max"):
                msg = _value_problem(f, n.get(k)) if k in n else "必須填寫"
                if msg:
                    self.bad("%s.%s" % (p, k), msg)
            if len(self.problems) == before and n["min"] > n["max"]:
                self.bad(p, "下限不能大於上限")
            return
        if op == "in":
            vs = n.get("values")
            if not isinstance(vs, list) or not 1 <= len(vs) <= LIMITS["in_values"]:
                self.bad(p + ".values", "必須是 1～%d 項的清單" % LIMITS["in_values"])
                return
            for i, v in enumerate(vs):
                msg = _value_problem(f, v)
                if msg:
                    self.bad("%s.values[%d]" % (p, i), msg)
            return
        msg = _value_problem(f, n["value"]) if "value" in n else "必須填寫"
        if msg:
            self.bad(p + ".value", msg)


def validate_rule_set(body, fields) -> list:
    """規則集 body ⇒ `[{path, message}]`（空＝合法）。永不丟例外。"""
    try:
        return _validate(body, fields or {})
    except Exception as e:                                             # noqa: BLE001  驗證器自己壞了 ⇒ 當不合法，不放行
        return [{"path": "", "message": "規則集無法驗證：%s" % type(e).__name__}]


def _validate(body, fields):
    if not isinstance(body, dict):
        return [{"path": "", "message": "規則集必須是 JSON 物件"}]
    try:
        if len(json.dumps(body, ensure_ascii=False)) > LIMITS["bytes"]:
            return [{"path": "", "message": "規則集太大（最多 %d 位元組）" % LIMITS["bytes"]}]
    except (TypeError, ValueError):
        return [{"path": "", "message": "規則集必須是可存成 JSON 的內容"}]
    out = []
    for k in body:
        if k != "rules":
            out.append({"path": k, "message": "不認得的設定：%s" % k})
    rules = body.get("rules", [])
    if not isinstance(rules, list):
        return out + [{"path": "rules", "message": "rules 必須是清單"}]
    if len(rules) > LIMITS["rules"]:
        out.append({"path": "rules", "message": "規則太多（最多 %d 條）" % LIMITS["rules"]})
        return out
    seen = set()
    total = _Walk(fields, "")
    for i, r in enumerate(rules):
        p = "rules[%d]" % i
        if not isinstance(r, dict):
            out.append({"path": p, "message": "規則必須是物件"})
            continue
        for k in r:
            if k not in RULE_KEYS:
                out.append({"path": "%s.%s" % (p, k), "message": "不認得的設定：%s" % k})
        rid = r.get("id")
        if not isinstance(rid, str) or not _ID_RE.match(rid):
            out.append({"path": p + ".id", "message": "代號要 2～40 個小寫英數字或底線，且以英文字母開頭"})
        elif rid in seen:
            out.append({"path": p + ".id", "message": "代號重複：%s" % rid})
        else:
            seen.add(rid)
        name = r.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= LIMITS["name"]:
            out.append({"path": p + ".name", "message": "名稱要 1～%d 字" % LIMITS["name"]})
        if not isinstance(r.get("enabled", True), bool):
            out.append({"path": p + ".enabled", "message": "必須是 true／false"})
        sf = r.get("surfaces")
        if sf is not None and (not isinstance(sf, list) or not 1 <= len(sf) <= len(SURFACES) or len(set(map(str, sf))) != len(sf) or any(x not in SURFACES for x in sf)):
            out.append({"path": p + ".surfaces", "message": "標示位置只能是：列表、表單（list／form），至少選一個且不重複"})
        if r.get("mode", "mark") != "mark":
            out.append({"path": p + ".mode", "message": "這一版只開放『標示』類規則，阻擋類尚未開放"})
        if r.get("on_failure", "degrade_loud") != "degrade_loud":
            out.append({"path": p + ".on_failure", "message": "這一版只支援『故障時降級並提醒』"})
        w = _Walk(fields, p)
        w.node(r.get("when"), p + ".when", 1)
        out += w.problems
        total.nodes += w.nodes
        mk = r.get("mark")
        if not isinstance(mk, dict):
            out.append({"path": p + ".mark", "message": "必須設定標示"})
            continue
        for k in mk:
            if k not in MARK_KEYS:
                out.append({"path": "%s.mark.%s" % (p, k), "message": "不認得的設定：%s" % k})
        if mk.get("level") not in LEVELS:
            out.append({"path": p + ".mark.level", "message": "顏色只能是：紅、黃、灰（red／yellow／info）"})
        t = mk.get("text")
        if not isinstance(t, str) or not 1 <= len(t.strip()) <= LIMITS["text"]:
            out.append({"path": p + ".mark.text", "message": "提示文字要 1～%d 字" % LIMITS["text"]})
        elif any(c in t for c in "{}<>") or "\n" in t:
            out.append({"path": p + ".mark.text", "message": "提示文字只能是單行純文字（不支援占位符或標籤）"})
        tg = mk.get("target", "row")
        if tg not in TARGETS:
            out.append({"path": p + ".mark.target", "message": "標示位置只能是：整列、欄位（row／field）"})
        elif tg == "field" and mk.get("field") not in fields:
            out.append({"path": p + ".mark.field", "message": "標示到欄位時，必須選一個目錄內的欄位"})
        elif tg == "row" and "field" in mk:
            out.append({"path": p + ".mark.field", "message": "標示整列時不能指定欄位"})
    if total.nodes > LIMITS["nodes"] * 5:
        out.append({"path": "rules", "message": "整份規則集的條件總量太大"})
    return out


def fields_used(when) -> set:
    """條件用到的欄位代號（走訪；未知節點略過）。供引擎判斷『檢視者看不到其中任一欄 ⇒ 不評估』。"""
    out, stack = set(), [when]
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        if n.get("op") in ("and", "or"):
            stack.extend(a for a in (n.get("args") or []) if isinstance(a, dict))
        elif n.get("op") == "not":
            stack.append(n.get("arg"))
        elif isinstance(n.get("field"), str):
            out.add(n["field"])
    return out
