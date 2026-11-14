# -*- coding: utf-8 -*-
"""自訂報表的「資料來源」登錄表（T87 B2 S0b：只登記與驗證、不執行查詢）。設計：D:\\Claude-pm\\t87-design\\B2-custom-reports.md §3、§4。

[單位] helper:report_catalog    [層] L1    [穩定度] 實驗（登記資料＋純函式；沒有路由、沒有資料表）
[公開介面] AGG_BY_TYPE, OPS_BY_TYPE, TYPES, field_of, field_visible, get_source, register_source, restore, snapshot, source_available, source_problems, sources, sources_for, visible_fields
[不變式] ①擁有模組以 `register_source()` 登記資料來源；核心不寫死任何來源或欄位。查詢的識別字與運算式**只取自這份登錄表**，使用者只能挑欄位代號，任何使用者文字都不會進入 SQL 識別字位置。
    ②欄位種類 `column`（識別字符合規則，且在擁有模組登記的表內）或 `expr`；`expr` 的運算式只能是擁有模組登錄於 `spec["exprs"]` 的常數，以 **`is`**（同一個物件）比對，不比字串——
      清單端點與報表引用同一個常數，才不會各寫一份而漂移。`sortExpr` 同規則。`reads` 宣告運算式讀哪些欄位（`data_json` 只允許出現在登錄常數裡，使用者無從指定路徑）。
    ③`money`／`percent` 欄位必須有 `catalogId`，且該目錄項 `moneyClass != none`；`catalogId` 指到 `protected`、或欄位名出現在 `core.internal_cols` ⇒ 該來源不登記。
    ④登記有問題 ⇒ 該來源**不登記**（fail closed）並記 warning，不丟例外（不讓一個模組的筆誤拖垮載入）；同一個來源代號只准同一個擁有者重複登記，不同擁有者搶 ⇒ ValueError。
    ⑤欄位可見＝`field_policy` 的天花板 ∧ 所有 `derivedFrom` 遞迴可見；任何例外 ⇒ 不可見。**每次呼叫重算，不存授權**。D7（自訂報表設定）只會在報價單層級天花板之外，
      多放行『`financial_mask.money_visible` 為真者』（＝既有報價單內頁的整份短路），不放寬任何其他天花板。
    ⑥能力不取代模組存取：`source_available` 另外要求擁有模組已載入、且使用者持有來源宣告的模組鍵（比對方式同既有端點；沒有 `execute` 的來源不列出）。
    ⑦別名來源（`extends`）沿用基底來源的表、列規則、欄位與 `execute`，只多一組預設篩選與自己的名稱；欄位不複製成第二份清單。
[契約題] backend/tests/platform/test_report_catalog_t87.py
"""
import copy
import logging
import re
import threading

from helpers import field_catalog as _FC

logger = logging.getLogger("motrix.report_catalog")

TYPES = ("text", "enum", "date", "number", "money", "percent")
AGG_BY_TYPE = {
    "text": ("count",), "enum": ("count",), "date": ("count", "min", "max"),
    "number": ("count", "sum", "avg", "min", "max"), "money": ("count", "sum", "avg", "min", "max"),
    "percent": ("count", "avg", "min", "max"),
}
OPS_BY_TYPE = {
    "text": ("eq", "neq", "contains", "in"), "enum": ("eq", "neq", "in"),
    "date": ("eq", "gte", "lte", "between", "relative"),
    "number": ("eq", "gte", "lte", "between"), "money": ("eq", "gte", "lte", "between"), "percent": ("eq", "gte", "lte", "between"),
}
_GROUPABLE = ("text", "enum", "date")                    # 金額／百分比不可分組（分組小計會變成逐筆明細的替身）
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_MINE_PARAMS = ("id", "display_name", "username")
_FLAGS = ("select", "filter", "group", "aggregate", "sort")

_SOURCES = {}                                            # source_id -> {"owner": str, "spec": dict}
_lock = threading.Lock()


def _internal(name) -> bool:
    try:
        from core.internal_cols import is_internal
        return bool(is_internal(name))
    except Exception:                                    # noqa: BLE001 — 取不到 ⇒ 保守視為內部
        return True


def _is_const(value, exprs) -> bool:
    return isinstance(value, str) and any(value is c for c in exprs)


def _field_problems(sid, f, exprs, ids) -> list:
    out = []
    if not isinstance(f, dict) or not _ID_RE.match(str(f.get("id") or "")):
        return ["%s：欄位 id 不合法：%r" % (sid, f)]
    fid = f["id"]
    p = "%s.%s" % (sid, fid)
    if fid in ids:
        out.append("%s：欄位 id 重複" % p)
    ids.append(fid)
    if not str(f.get("label") or "").strip():
        out.append("%s：沒有白話名稱" % p)
    typ = f.get("type")
    if typ not in TYPES:
        out.append("%s：type 必須是 %s" % (p, "／".join(TYPES)))
        return out
    kind = f.get("kind", "column")
    if kind == "column":
        col = f.get("column")
        if not isinstance(col, str) or not _COL_RE.match(col):
            out.append("%s：column 不合法" % p)
        elif _internal(col) or "data_json" in col:
            out.append("%s：column 不可是內部欄位或 data_json" % p)
    elif kind == "expr":
        if not _is_const(f.get("expr"), exprs):
            out.append("%s：expr 必須是擁有模組登錄於 exprs 的同一個常數（以 is 比對）" % p)
        reads = f.get("reads")
        if not isinstance(reads, (list, tuple)) or not reads or any(not isinstance(r, str) or not _COL_RE.match(r) or _internal(r) for r in reads):
            out.append("%s：expr 欄位必須宣告 reads（讀取的欄位名單，不可含內部欄位）" % p)
    else:
        out.append("%s：kind 必須是 column 或 expr" % p)
    se = f.get("sortExpr")
    if se is not None and not _is_const(se, exprs):
        out.append("%s：sortExpr 必須是登錄常數" % p)
    for k in _FLAGS:
        if k != "aggregate" and not isinstance(f.get(k, False), bool):
            out.append("%s：%s 必須是 True／False" % (p, k))
    agg = f.get("aggregate", ())
    if not isinstance(agg, (list, tuple)) or any(a not in AGG_BY_TYPE[typ] for a in agg):
        out.append("%s：aggregate 只能是 %s" % (p, "／".join(AGG_BY_TYPE[typ])))
    if f.get("group") and typ not in _GROUPABLE:
        out.append("%s：%s 欄位不可分組" % (p, typ))
    if f.get("group") and typ == "date":
        bk = f.get("bucket")
        if not isinstance(bk, (list, tuple)) or not bk or any(x not in ("month", "quarter", "year") for x in bk):
            out.append("%s：日期分組必須宣告 bucket（month／quarter／year 的非空清單）" % p)
    if typ == "enum" and not (callable(f.get("enum")) or (isinstance(f.get("enum"), (list, tuple)) and f.get("enum"))):
        out.append("%s：enum 欄位必須宣告選項（清單或回傳選項的函式；取自擁有模組）" % p)
    if f.get("isMe") and typ != "text":
        out.append("%s：isMe 只用在文字欄（業務）" % p)
    cid = f.get("catalogId")
    if typ in ("money", "percent") and not cid:
        out.append("%s：金額／百分比欄位必須有 catalogId" % p)
    if cid is not None:
        entry = _FC.by_id(cid)
        if entry is None:
            out.append("%s：catalogId 不在欄位目錄：%s" % (p, cid))
        elif entry.get("moneyClass") == "protected":
            out.append("%s：catalogId 指到 protected 欄位，不可進報表白名單" % p)
        elif typ in ("money", "percent") and entry.get("moneyClass") in (None, "none"):
            out.append("%s：金額欄位的目錄項 moneyClass 不可為 none" % p)
    return out


def _resolve(source_id, spec):
    """別名來源（extends）展開成完整規格（欄位物件與常數沿用基底，不複製字串）。展不開 ⇒ (None, 問題)。"""
    base_id = spec.get("extends")
    if base_id is None:
        return spec, []
    base = _SOURCES.get(base_id)
    if base is None:
        return None, ["%s：基底來源 %s 尚未登記" % (source_id, base_id)]
    full = dict(base["spec"])
    for k in ("label", "desc", "defaultFilters", "defaults", "modules"):
        if k in spec:
            full[k] = spec[k]
    full["extends"] = base_id
    return full, []


def source_problems(source_id, spec) -> list:
    """單一來源登記資料的問題（空＝合格）。"""
    if not isinstance(source_id, str) or not _ID_RE.match(source_id):
        return ["來源代號不合法：%r" % (source_id,)]
    if not isinstance(spec, dict):
        return ["%s：登記內容必須是物件" % source_id]
    spec, out = _resolve(source_id, spec)
    if spec is None:
        return out
    if not str(spec.get("label") or "").strip():
        out.append("%s：沒有白話名稱" % source_id)
    tbl = spec.get("table")
    if not isinstance(tbl, str) or not _COL_RE.match(tbl):
        out.append("%s：table 不合法" % source_id)
    mods = spec.get("modules")
    if not isinstance(mods, (list, tuple)) or not mods or any(not isinstance(m, str) or not m.strip() for m in mods):
        out.append("%s：modules 必須是非空的模組鍵清單（沒有模組存取 ⇒ 來源不列出）" % source_id)
    ra = spec.get("rowAccess")
    if not isinstance(ra, dict) or not str(ra.get("kind") or "").strip() or ra.get("scope") not in ("read", "owner"):
        out.append("%s：rowAccess 必須是 {kind, scope:'read'|'owner'}（列範圍必須併入每個查詢）" % source_id)
    sd = spec.get("softDelete")
    if sd is not None and (not isinstance(sd, str) or not _COL_RE.match(sd)):
        out.append("%s：softDelete 必須是欄位名" % source_id)
    exprs = spec.get("exprs") or ()
    if not isinstance(exprs, (list, tuple)) or any(not isinstance(c, str) for c in exprs):
        out.append("%s：exprs 必須是字串常數的清單" % source_id)
        exprs = ()
    fields = spec.get("fields")
    if not isinstance(fields, (list, tuple)) or not fields:
        return out + ["%s：沒有欄位" % source_id]
    ids = []
    for f in fields:
        out.extend(_field_problems(source_id, f, exprs, ids))
    by = {f["id"]: f for f in fields if isinstance(f, dict) and isinstance(f.get("id"), str)}
    mine = spec.get("mine")
    if mine is not None:
        ps = mine.get("params") if isinstance(mine, dict) else None
        if not isinstance(mine, dict) or not _is_const(mine.get("sql"), exprs) or not isinstance(ps, (list, tuple)) or any(x not in _MINE_PARAMS for x in ps) \
                or mine["sql"].count("?") != len(ps):
            out.append("%s：mine 必須是 {sql:登錄常數, params:id|display_name|username 的清單，個數同 ? 數}" % source_id)
    if any(f.get("isMe") for f in by.values()) and mine is None:
        out.append("%s：有 isMe 欄位就必須登記 mine（清單的「我負責的」語意）" % source_id)
    d = spec.get("defaults")
    if not isinstance(d, dict):
        out.append("%s：沒有 defaults" % source_id)
    else:
        dc = d.get("columns")
        if not isinstance(dc, (list, tuple)) or not dc or len(set(dc)) != len(dc) or any(x not in by or not by[x].get("select") for x in dc):
            out.append("%s：defaults.columns 必須是可顯示欄位的非空、不重複子集" % source_id)
        s = d.get("sort")
        if s is not None and (not isinstance(s, dict) or s.get("field") not in by or not by[s.get("field")].get("sort") or s.get("dir") not in ("asc", "desc")):
            out.append("%s：defaults.sort 必須指向可排序欄位且 dir 為 asc／desc" % source_id)
    for flt in spec.get("defaultFilters") or ():
        fld = by.get(flt.get("field")) if isinstance(flt, dict) else None
        if fld is None or not fld.get("filter") or flt.get("op") not in OPS_BY_TYPE.get(fld.get("type"), ()):
            out.append("%s：defaultFilters 項目不合法：%r" % (source_id, flt))
    ex = spec.get("execute")
    if ex is not None and not callable(ex):
        out.append("%s：execute 必須是函式（擁有模組自己的執行函式）" % source_id)
    return out


def register_source(source_id, owner, spec) -> list:
    """登記一個資料來源。回傳問題清單（空＝已登記）；有問題 ⇒ 不登記、記 warning。同代號不同擁有者 ⇒ ValueError。"""
    probs = source_problems(source_id, spec)
    if probs:
        logger.warning("report_catalog：%s 不登記：%s", source_id, "；".join(probs))
        return probs
    with _lock:
        cur = _SOURCES.get(source_id)
        if cur is not None and cur["owner"] != owner:
            raise ValueError("report source %s 已由 %s 登記" % (source_id, cur["owner"]))
        _SOURCES[source_id] = {"owner": owner, "spec": spec}
    return []


def sources() -> dict:
    """{source_id: 規格複本}（含別名展開；函式與常數不複製）。"""
    with _lock:
        items = list(_SOURCES.items())
    out = {}
    for sid, e in items:
        full, _ = _resolve(sid, e["spec"])
        if full is not None:
            out[sid] = _copy(full)
    return out


def _copy(spec):
    c = dict(spec)
    c["fields"] = [dict(f) for f in spec.get("fields", ())]
    return c


def get_source(source_id):
    with _lock:
        e = _SOURCES.get(source_id)
    if e is None:
        return None
    full, _ = _resolve(source_id, e["spec"])
    return _copy(full) if full is not None else None


def field_of(source_id, field_id):
    s = get_source(source_id)
    return next((f for f in (s or {}).get("fields", ()) if f["id"] == field_id), None)


def snapshot():
    with _lock:
        return dict(_SOURCES)


def restore(snap):
    with _lock:
        _SOURCES.clear()
        _SOURCES.update(snap)


# ── 可用與可見（每次呼叫重算，不存授權）──────────────────────────────────────

def source_available(source_id, user) -> bool:
    """來源是否對這位使用者列出：擁有模組已載入、有 `execute`、且使用者持有來源宣告的模組鍵。能力不取代模組存取。"""
    try:
        with _lock:
            e = _SOURCES.get(source_id)
        if e is None or not user:
            return False
        spec, _ = _resolve(source_id, e["spec"])
        if spec is None or not callable(spec.get("execute")):
            return False
        from core import registry
        if not registry.is_loaded(spec.get("ownerModule") or e["owner"]):
            return False
        role = user.get("role")
        if role == "superadmin":
            return True
        if spec.get("adminPass") and role == "admin":
            return True
        from helpers import auth
        return any(auth.user_has_module(user, k) for k in spec["modules"])
    except Exception:                                    # noqa: BLE001 — fail-closed
        logger.warning("report_catalog.source_available failed for %r; treating as unavailable", source_id, exc_info=True)
        return False


def sources_for(user) -> list:
    """這位使用者可用的來源代號（登記順序）。"""
    return [sid for sid in snapshot() if source_available(sid, user)]


def _cid_visible(cid, user, wide, depth=0) -> bool:
    from helpers import field_policy as FP
    entry = _FC.by_id(cid)
    if entry is None or depth > 4:
        return False
    ok = bool(FP.tier_allowed(entry["ceiling"], user))
    if not ok and wide and entry["ceiling"] == "quote_money":
        ok = bool(FP.tier_allowed("finance_money", user))   # D7：＝`financial_mask.money_visible`，既有報價單內頁的整份短路；只動報價單層級天花板
    if not ok:
        return False
    return all(_cid_visible(d, user, wide, depth + 1) for d in entry["derivedFrom"])


def field_visible(field, user, wide=None) -> bool:
    """這位使用者看不看得到這個欄位（`field` 為登記的欄位物件）。永不丟例外；不確定 ⇒ False。"""
    try:
        cid = field.get("catalogId")
        if cid is None:
            return True
        if wide is None:
            from helpers import report_policy as RP
            wide = RP.quote_money_wide()
        return _cid_visible(cid, user, bool(wide))
    except Exception:                                    # noqa: BLE001 — fail-closed
        logger.warning("report_catalog.field_visible failed for %r; treating as hidden", (field or {}).get("id"), exc_info=True)
        return False


def visible_fields(source_id, user) -> dict:
    """{field_id: bool}（設定值只讀一次）。來源不存在 ⇒ {}。"""
    s = get_source(source_id)
    if s is None:
        return {}
    try:
        from helpers import report_policy as RP
        wide = RP.quote_money_wide()
    except Exception:                                    # noqa: BLE001
        wide = False
    return {f["id"]: field_visible(f, user, wide) for f in s["fields"]}
