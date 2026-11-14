# -*- coding: utf-8 -*-
"""自訂報表的編譯與執行（T87 B2 S1：定義 → 驗證 → 套可見性 → 編譯成唯讀查詢 → 由擁有模組執行 → 組表）。設計：D:\\Claude-pm\\t87-design\\B2-custom-reports.md §4.4、§5。

[單位] helper:report_runner    [層] L1    [穩定度] 實驗（無路由、無資料表；不含任何業務表名字面值——表名／欄位／運算式全部取自 `report_catalog` 登錄表）
[公開介面] CompiledPlan, MAX_DEFINITION_BYTES, MAX_EXPORT_ROWS, PREVIEW_ROWS, TIME_LIMIT_SECONDS, ReportError, ReportRefused, SourceUnavailable, assemble, compile, describe_filters, preview, run_owned
[不變式] ①使用者只能提供**欄位代號**與**值**：識別字與運算式只來自登錄表（`expr` 是擁有模組的登錄常數），值一律走參數（LIKE 跳脫）；編譯後再斷言 `data_json` 只出現在登錄常數之內（授權器是欄位層級，分不出登錄運算式內的 `data_json` 與裸讀）。
    ②**不可見欄位**：用在顯示／彙總 ⇒ 拿掉並回報「已隱藏 N 欄」；用在篩選／分組／排序 ⇒ **422 拒絕執行**（不忽略；忽略會變成逐步逼近金額的探針）。可見性每次重算（`report_catalog.visible_fields`），定義裡只存欄位代號。
    ③列範圍＝`row_access.filter_sql(來源登記的 kind／scope)`，**無條件**併入每一支查詢（含計數與彙總）；來源有 `softDelete` 就併入 `<欄位> = 0`；未登錄列規則 ⇒ `AND 0`。
    ④`CompiledPlan` 不透明：只能由 `compile()` 產生（建構需內部權杖）；擁有模組的執行函式經 `run_owned(plan, accept)` 斷言型別與 `source_id`；沒有「執行任意計畫／任意 SQL」的入口。
    ⑤執行：獨立連線＋`PRAGMA query_only=ON`＋`set_authorizer`（只准 SELECT、對已登記表與欄位的 READ、白名單函式）＋`progress_handler` 時間上限；編譯內強制 LIMIT（預覽 50、匯出 10,001 ⇒ 超過 10,000 回 422，不截斷）。
    ⑥空值與零不混：加總略過空值；全空 ⇒ None（不是 0）；平均＝有值筆數的平均，金額四捨五入到元、百分比到小數兩位（四捨五入進位）。
    ⑦所有使用者可見的錯誤訊息是固定白話（原因＋怎麼處理），不回傳 SQL、不回傳例外文字。
[契約題] backend/tests/platform/test_report_runner_t87.py
"""
import json
import logging
import math
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from helpers import report_catalog as RC

logger = logging.getLogger("motrix.report_runner")

PREVIEW_ROWS = 50
MAX_EXPORT_ROWS = 10000
MAX_DEFINITION_BYTES = 8192
MAX_COLUMNS, MAX_FILTERS, MAX_GROUPS, MAX_AGGS, MAX_SORTS = 20, 6, 2, 6, 2
TIME_LIMIT_SECONDS = 8.0
_TOP_KEYS = {"version", "source", "columns", "filters", "groupBy", "aggregates", "layout", "sort"}
_PERIODS = ("this_month", "last_month", "this_quarter", "this_year", "last_year", "last_30_days")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AGG_LABEL = {"sum": "合計", "avg": "平均", "min": "最小", "max": "最大", "count": "筆數"}
_BUCKET_SQL = {
    "month": "strftime('%Y-%m', {d})",
    "quarter": "(strftime('%Y', {d}) || '-Q' || ((CAST(strftime('%m', {d}) AS INTEGER) + 2) / 3))",
    "year": "strftime('%Y', {d})",
}
_ALLOWED_FUNCS = frozenset({"coalesce", "nullif", "ifnull", "count", "sum", "avg", "min", "max", "json_extract", "json_type", "json_valid",
                            "like", "strftime", "substr", "round"})
_TOKEN = object()


class ReportError(Exception):
    """可顯示給使用者的錯誤：`status` 是 HTTP 狀態、`message` 是固定白話、`details` 是不含任何資料值的補充（欄位代號等）。"""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details or {}


class ReportRefused(ReportError):
    def __init__(self, message, details=None):
        super().__init__(422, message, details)


class SourceUnavailable(ReportError):
    def __init__(self):
        super().__init__(404, "找不到這個資料來源，或您沒有使用權限。")


class CompiledPlan:
    """不透明的編譯結果：只能由 `compile()` 建立。欄位唯讀。"""
    __slots__ = ("source_id", "table", "layout", "mode", "columns", "groups", "aggs", "hidden", "notices", "queries", "limit", "allowed", "enum_labels")

    def __init__(self, token, **kw):
        if token is not _TOKEN:
            raise TypeError("CompiledPlan 只能由 report_runner.compile() 建立")
        for k in self.__slots__:
            object.__setattr__(self, k, kw[k])

    def __setattr__(self, name, value):
        raise AttributeError("CompiledPlan 唯讀")


# ── 驗證與正規化 ─────────────────────────────────────────────────────────────

def _normalize(defn) -> dict:
    if not isinstance(defn, dict):
        raise ReportRefused("報表設定格式不正確，請重新建立。")
    try:
        size = len(json.dumps(defn, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ReportRefused("報表設定格式不正確，請重新建立。")
    if size > MAX_DEFINITION_BYTES:
        raise ReportRefused("報表設定過大，請減少欄位或條件。")
    if defn.get("version") != 1 or set(defn) - _TOP_KEYS:
        raise ReportRefused("報表設定的版本或內容不支援，請重新建立。")
    src = defn.get("source")
    if not isinstance(src, str):
        raise ReportRefused("請先選擇資料來源。")
    out = {"source": src, "layout": defn.get("layout", "detail")}
    if out["layout"] not in ("detail", "summary"):
        raise ReportRefused("版型只能是明細或彙總。")
    for key, cap, label in (("columns", MAX_COLUMNS, "欄位"), ("filters", MAX_FILTERS, "條件"), ("groupBy", MAX_GROUPS, "分組"),
                            ("aggregates", MAX_AGGS, "彙總"), ("sort", MAX_SORTS, "排序")):
        v = defn.get(key)
        if v is None:
            out[key] = None if key == "filters" else []
            continue
        if not isinstance(v, list) or len(v) > cap:
            raise ReportRefused("%s最多 %d 項，請減少後再執行。" % (label, cap))
        out[key] = v
    if any(not isinstance(c, str) for c in out["columns"]) or len(set(out["columns"])) != len(out["columns"]):
        raise ReportRefused("欄位清單格式不正確，請重新建立。")
    for key in ("filters", "groupBy", "aggregates", "sort"):
        if any(not isinstance(x, dict) for x in (out[key] or [])):
            raise ReportRefused("報表設定格式不正確，請重新建立。")
    return out


def _period(name, today):
    y, m = today.year, today.month
    if name == "this_month":
        s = date(y, m, 1)
        e = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    elif name == "last_month":
        e = date(y, m, 1) - timedelta(days=1)
        s = date(e.year, e.month, 1)
    elif name == "this_quarter":
        q0 = (m - 1) // 3 * 3 + 1
        s = date(y, q0, 1)
        e = date(y + (q0 == 10), (q0 + 3 - 1) % 12 + 1, 1) - timedelta(days=1)
    elif name == "this_year":
        s, e = date(y, 1, 1), date(y, 12, 31)
    elif name == "last_year":
        s, e = date(y - 1, 1, 1), date(y - 1, 12, 31)
    else:                                                                    # last_30_days
        s, e = today - timedelta(days=29), today
    return s.isoformat(), e.isoformat()


_NUM_LIMIT = 2 ** 53                                                           # 條件數字的上限（再大就不是合理金額；也避免 SQLite 64 位元溢位）


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)) or abs(v) > _NUM_LIMIT:
        raise ValueError
    return v


def _str(v, lo=0, hi=200):
    if not isinstance(v, str) or not (lo <= len(v) <= hi):
        raise ValueError
    return v


def _strs(v, hi=50):
    if not isinstance(v, list) or not v or len(v) > hi:
        raise ValueError
    return [_str(x, 0, 200) for x in v]


def _dt(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise ValueError
    datetime.strptime(v, "%Y-%m-%d")
    return v


def _like(s):
    return "%" + s.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _qi(name):
    return '"%s"' % name                                                       # 識別字只來自登錄表（已過正規式），這裡只加引號


def _fexpr(f):
    return f["expr"] if f.get("kind") == "expr" else _qi(f["column"])


def _filter_clause(f, op, value, today, spec, user):
    """單一條件 ⇒ (SQL 片段, 參數)。值不合法 ⇒ ValueError。"""
    e = _fexpr(f)
    typ = f["type"]
    if op == "is_me":
        mine = spec["mine"]
        vals = {"id": user.get("id"), "display_name": user.get("display_name"), "username": user.get("username")}
        return mine["sql"], [vals[p] for p in mine["params"]]
    if op == "empty":
        return "(%s IS NULL OR %s = '')" % (e, e) if typ in ("text", "enum", "date") else "%s IS NULL" % e, []
    if op == "not_empty":
        return "(%s IS NOT NULL AND %s <> '')" % (e, e) if typ in ("text", "enum", "date") else "%s IS NOT NULL" % e, []
    if typ in ("text", "enum"):
        if op == "eq":
            return "%s = ?" % e, [_str(value)]
        if op == "neq":
            return "(%s IS NULL OR %s <> ?)" % (e, e), [_str(value)]
        if op == "contains":
            return "%s LIKE ? ESCAPE '!' COLLATE NOCASE" % e, [_like(_str(value, 1, 100))]
        vs = _strs(value)                                                      # in
        return "%s IN (%s)" % (e, ",".join("?" * len(vs))), vs
    if typ == "date":
        d = "substr(%s,1,10)" % e
        if op == "eq":
            return "%s = ?" % d, [_dt(value)]
        if op == "gte":
            return "%s >= ?" % d, [_dt(value)]
        if op == "lte":
            return "%s <= ?" % d, [_dt(value)]
        if op == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError
            return "(%s >= ? AND %s <= ?)" % (d, d), [_dt(value[0]), _dt(value[1])]
        if value not in _PERIODS:                                              # relative
            raise ValueError
        s, en = _period(value, today)
        return "(%s >= ? AND %s <= ?)" % (d, d), [s, en]
    if op == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return "(%s >= ? AND %s <= ?)" % (e, e), [_num(value[0]), _num(value[1])]
    sym = {"eq": "=", "gte": ">=", "lte": "<="}[op]
    return "%s %s ?" % (e, sym), [_num(value)]


# ── 編譯 ─────────────────────────────────────────────────────────────────────

def _label_list(by, ids):
    return "、".join("「%s」" % by[i]["label"] for i in ids)


def compile(definition, user, mode="preview", today=None, conn=None) -> CompiledPlan:  # noqa: A001 — 與設計文件同名
    """定義 → CompiledPlan。來源不可用 ⇒ SourceUnavailable(404)；定義或權限問題 ⇒ ReportRefused(422)。
    使用者送來的定義型別不對造成的 TypeError／ValueError／KeyError／AttributeError／OverflowError 一律是 422（不准 500）。"""
    try:
        return _compile(definition, user, mode, today, conn)
    except ReportError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError, IndexError):
        logger.warning("report_runner：定義型別不合法（若不是使用者輸入錯誤就是程式錯誤）", exc_info=True)
        raise ReportRefused("報表設定格式不正確，請重新建立。", {"reason": "bad_definition"})


def _compile(definition, user, mode, today, conn) -> CompiledPlan:
    from helpers import row_access
    d = _normalize(definition)
    sid = d["source"]
    spec = RC.get_source(sid)
    if spec is None or not RC.source_available(sid, user):
        raise SourceUnavailable()
    today = today or date.today()
    by = {f["id"]: f for f in spec["fields"]}
    vis = RC.visible_fields(sid, user)
    notices, hidden = [], []

    def _known(fid):
        return fid in by

    # 篩選：不認得／不可見／不支援 ⇒ 拒絕（不忽略）
    filters = d["filters"] if d["filters"] is not None else list(spec.get("defaultFilters") or [])
    bad_unknown = [str(x.get("field")) for x in filters if not isinstance(x.get("field"), str) or not _known(x["field"])]
    if bad_unknown:
        raise ReportRefused("有條件使用的欄位已不存在，請移除該條件。", {"reason": "unknown_field", "action": "remove_conditions"})
    groups_in, sorts_in = d["groupBy"], d["sort"]
    for x in groups_in + sorts_in:
        if not isinstance(x.get("field"), str) or not _known(x["field"]):
            raise ReportRefused("分組或排序使用的欄位已不存在，請移除。", {"reason": "unknown_field"})
    denied = []
    for x in filters + groups_in + sorts_in:
        if not vis.get(x["field"]) and x["field"] not in denied:
            denied.append(x["field"])
    if denied:
        raise ReportRefused("條件、分組或排序使用了您無權限的欄位：%s。請移除後再執行。" % _label_list(by, denied),
                            {"reason": "no_permission", "fields": denied, "action": "remove_conditions"})

    where, params = ["1=1"], []
    if spec.get("softDelete"):
        where.append("%s = 0" % _qi(spec["softDelete"]))
    ra = spec["rowAccess"]
    frag, fparams = row_access.filter_sql(ra["kind"], user, scope=ra["scope"])
    if frag:
        where.append(frag.strip()[4:] if frag.strip().upper().startswith("AND ") else frag.strip())
        params.extend(fparams)
    for x in filters:
        f = by[x["field"]]
        op = x.get("op")
        legal = list(RC.OPS_BY_TYPE[f["type"]]) + ["empty", "not_empty"] + (["is_me"] if f.get("isMe") else [])
        if not f.get("filter") or op not in legal:
            raise ReportRefused("欄位「%s」不支援這種條件，請改用其他條件。" % f["label"], {"reason": "bad_operator", "fields": [f["id"]]})
        try:
            frag2, p2 = _filter_clause(f, op, x.get("value"), today, spec, user)
        except (ValueError, KeyError, TypeError):
            raise ReportRefused("欄位「%s」的條件值不正確，請重新輸入。" % f["label"], {"reason": "bad_value", "fields": [f["id"]]})
        where.append(frag2)
        params.extend(p2)
    where_sql = " AND ".join(where)

    # 分組
    groups = []
    for x in groups_in:
        f = by[x["field"]]
        if not f.get("group"):
            raise ReportRefused("欄位「%s」不能分組。" % f["label"], {"reason": "bad_group", "fields": [f["id"]]})
        ge = _fexpr(f)
        bucket = None
        if f["type"] == "date":
            bucket = x.get("bucket") or f["bucket"][0]
            if bucket not in f["bucket"]:
                raise ReportRefused("欄位「%s」不支援這種日期分組。" % f["label"], {"reason": "bad_bucket", "fields": [f["id"]]})
            ge = _BUCKET_SQL[bucket].format(d="substr(%s,1,10)" % ge)
        groups.append({"fieldId": f["id"], "label": f["label"] + ("（按%s）" % {"month": "月", "quarter": "季", "year": "年"}[bucket] if bucket else ""),
                       "type": f["type"], "expr": ge})
    if len({g["fieldId"] for g in groups}) != len(groups):
        raise ReportRefused("同一個欄位不能重複分組。")

    layout = d["layout"]
    # 顯示欄
    columns = []
    if layout == "detail":
        for cid in d["columns"]:
            f = by.get(cid)
            if f is None:
                notices.append("有一個顯示欄位已不存在，已略過。")
            elif not f.get("select"):
                notices.append("欄位「%s」不能顯示，已略過。" % f["label"])
            elif not vis.get(cid):
                hidden.append(f["label"])
            else:
                columns.append({"fieldId": cid, "label": f["label"], "type": f["type"], "expr": _fexpr(f)})
        if not columns:
            raise ReportRefused("沒有可顯示的欄位，請至少選擇一個您有權限的欄位。" if hidden else "請至少選擇一個要顯示的欄位。", {"reason": "no_columns"})
    # 彙總欄
    aggs = []
    for x in d["aggregates"]:
        fid, fn = x.get("field"), x.get("fn")
        if not isinstance(fid, str) or not isinstance(fn, str):
            raise ReportRefused("彙總設定的格式不正確，請重新設定。", {"reason": "bad_definition"})
        if fid == "*":
            if fn != "count":
                notices.append("「*」只能用於筆數，已略過。")
                continue
            aggs.append({"fieldId": "*", "fn": "count", "label": "筆數", "type": "number", "expr": "*"})
            continue
        f = by.get(fid) if isinstance(fid, str) else None
        if f is None:
            notices.append("有一個彙總欄位已不存在，已略過。")
        elif fn not in f.get("aggregate", ()):
            notices.append("欄位「%s」不支援這種彙總方式，已略過。" % f["label"])
        elif not vis.get(fid):
            hidden.append("%s（%s）" % (f["label"], _AGG_LABEL[fn]))
        else:
            aggs.append({"fieldId": fid, "fn": fn, "label": "%s（%s）" % (f["label"], _AGG_LABEL[fn]), "type": f["type"], "expr": _fexpr(f)})
    if layout == "summary" and not groups and not aggs:
        raise ReportRefused("彙總版型至少需要一個分組或彙總欄。", {"reason": "empty_summary"})

    # 排序
    order = []
    for x in sorts_in:
        f = by[x["field"]]
        if not f.get("sort"):
            raise ReportRefused("欄位「%s」不能排序。" % f["label"], {"reason": "bad_sort", "fields": [f["id"]]})
        if x.get("dir") not in ("asc", "desc"):
            raise ReportRefused("排序方向只能是由小到大或由大到小。")
        order.append("%s %s" % (f.get("sortExpr") or _fexpr(f), x["dir"].upper()))
    if layout == "summary":
        if order:
            notices.append("彙總版型依分組欄位排序，排序設定已略過。")
        order = []
    elif not order and spec["defaults"].get("sort"):
        s = spec["defaults"]["sort"]
        sf = by[s["field"]]
        if vis.get(s["field"]):
            order = ["%s %s" % (sf.get("sortExpr") or _fexpr(sf), s["dir"].upper())]

    limit = PREVIEW_ROWS if mode == "preview" else MAX_EXPORT_ROWS + 1
    t = _qi(spec["table"])
    gexprs = [g["expr"] for g in groups]
    gsel = ", ".join("%s AS g%d" % (e, i) for i, e in enumerate(gexprs))
    asel = ", ".join(("COUNT(*)" if a["expr"] == "*" else "%s(%s)" % (a["fn"].upper(), a["expr"])) + " AS a%d" % i for i, a in enumerate(aggs))
    q = {"where_params": list(params)}
    if layout == "detail":
        sel = ", ".join("%s AS c%d" % (c["expr"], i) for i, c in enumerate(columns))
        sel += (", " + gsel) if groups else ""
        ob = ", ".join(gexprs + order + ["rowid DESC"])
        q["rows"] = ("SELECT %s FROM %s WHERE %s ORDER BY %s LIMIT ?" % (sel, t, where_sql, ob), params + [limit])
        q["count"] = ("SELECT COUNT(*) FROM %s WHERE %s" % (t, where_sql), list(params))
        if aggs:
            q["total"] = ("SELECT %s FROM %s WHERE %s" % (asel, t, where_sql), list(params))
            if groups:
                q["groups"] = ("SELECT %s, %s FROM %s WHERE %s GROUP BY %s" % (gsel, asel, t, where_sql, ", ".join(gexprs)), list(params))
    else:
        sel = ", ".join(([gsel] if groups else []) + ([asel] if aggs else []))
        if groups:
            q["rows"] = ("SELECT %s FROM %s WHERE %s GROUP BY %s ORDER BY %s LIMIT ?" % (sel, t, where_sql, ", ".join(gexprs), ", ".join(gexprs)), params + [limit])
            q["count"] = ("SELECT COUNT(*) FROM (SELECT 1 FROM %s WHERE %s GROUP BY %s)" % (t, where_sql, ", ".join(gexprs)), list(params))
        else:
            q["rows"] = ("SELECT %s FROM %s WHERE %s" % (sel, t, where_sql), list(params))
            q["count"] = ("SELECT COUNT(*) FROM %s WHERE %s" % (t, where_sql), list(params))
        if groups and aggs:
            q["total"] = ("SELECT %s FROM %s WHERE %s" % (asel, t, where_sql), list(params))

    # `data_json` 只准出現在登錄常數之內（授權器是欄位層級，分不出裸讀）
    consts = sorted(spec.get("exprs") or (), key=len, reverse=True)
    for name, v in q.items():
        if name == "where_params":
            continue
        text = v[0]
        for c in consts:
            text = text.replace(c, " ")
        if "data_json" in text.lower():
            logger.error("report_runner：編譯結果在登錄常數之外讀取 data_json（來源 %s）", sid)
            raise ReportError(500, "報表暫時無法執行，請聯絡系統管理員。")

    allowed = {spec["table"]: set()}
    cols_ok = allowed[spec["table"]]
    cols_ok.update({"id", "rowid", ""})
    for f in spec["fields"]:
        if f.get("kind") == "expr":
            cols_ok.update(f.get("reads") or ())
        else:
            cols_ok.add(f["column"])
    if spec.get("softDelete"):
        cols_ok.add(spec["softDelete"])
    if spec.get("mine"):
        cols_ok.update(spec["mine"].get("reads") or ())
    rule = row_access.rule_for(ra["kind"])
    if rule is not None:
        cols_ok.update(c for c in (rule.owner_id_col, rule.legacy_name_col, rule.creator_col, *rule.id_list_cols) if c)
    enum_labels = {}
    shown = {c["fieldId"] for c in columns} | {g["fieldId"] for g in groups}
    for f in spec["fields"]:
        if f["type"] == "enum":
            en = f.get("enum")
            if f["id"] not in shown or getattr(en, "labels_are_values", False):  # 沒顯示、或選項＝資料本身（不必為了標籤掃表）
                enum_labels[f["id"]] = {}
                continue
            try:
                enum_labels[f["id"]] = {v: lab for v, lab in RC.enum_options(f, conn, user)}
            except Exception:                                                  # noqa: BLE001 — 取不到對照 ⇒ 顯示原值
                enum_labels[f["id"]] = {}
    return CompiledPlan(_TOKEN, source_id=sid, table=spec["table"], layout=layout, mode=mode, columns=columns, groups=groups, aggs=aggs,
                        hidden=hidden, notices=notices, queries=q, limit=limit, allowed={k: frozenset(v) for k, v in allowed.items()},
                        enum_labels=enum_labels)


# ── 執行（擁有模組的回呼經 run_owned 呼叫）────────────────────────────────────

def _authorizer(allowed):
    table, cols = next(iter(allowed.items()))

    def cb(action, a1, a2, dbname, src):
        if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if (a1 == table and a2 in cols) or (a1 == "json_each" and a2 == "value"):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (a2 or "").lower() in _ALLOWED_FUNCS else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY
    return cb


def run_owned(plan, accept) -> dict:
    """擁有模組的 `execute` 回呼呼叫這裡：斷言計畫型別與來源，再以唯讀連線＋授權器＋時間上限執行。回傳原始結果（尚未組表）。"""
    if not isinstance(plan, CompiledPlan) or plan.source_id not in tuple(accept):
        raise ReportError(500, "報表暫時無法執行，請聯絡系統管理員。")
    from db import get_db
    conn = get_db()
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_authorizer(_authorizer(plan.allowed))
        deadline = time.monotonic() + TIME_LIMIT_SECONDS
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
        raw = {}
        for name, v in plan.queries.items():
            if name == "where_params":
                continue
            cur = conn.execute(v[0], v[1])
            raw[name] = [tuple(r) for r in cur.fetchall()]
        return raw
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e).lower():
            raise ReportRefused("資料量過大，請縮小篩選範圍後再執行。", {"reason": "timeout"})
        logger.error("report_runner 執行失敗：%s", e)
        raise ReportError(500, "報表暫時無法執行，請稍後再試；若持續發生請聯絡系統管理員。")
    except (OverflowError, sqlite3.Error, ValueError) as e:                    # 條件值已在編譯時限制範圍；這裡是最後保險，不回 500 內部訊息
        logger.error("report_runner 執行失敗（%s）：%s", type(e).__name__, e)
        raise ReportRefused("報表條件的內容無法執行，請檢查條件值後再試。", {"reason": "bad_value"})
    finally:
        try:
            conn.set_authorizer(None)
        except Exception:                                                      # noqa: BLE001
            pass
        conn.close()


# ── 組表 ─────────────────────────────────────────────────────────────────────

def _fmt(v, typ, fn=None):
    if v is None:
        return None
    try:
        if fn == "count":
            return int(v)
        if typ == "money":
            return int(Decimal(str(v)).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if fn == "avg" else (int(v) if float(v).is_integer() else float(v))
        if typ == "percent":
            return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if fn == "avg" else v
    except (ValueError, TypeError, ArithmeticError):                           # 資料壞值：原樣顯示，不讓整份報表失敗
        return v
    return v


def _label_of(plan, field_id, v):
    if v is None or v == "":
        return "（未填）"
    return plan.enum_labels.get(field_id, {}).get(v, v)


def assemble(plan, raw) -> dict:
    """原始結果 → {columns, rows:[{k,v}], totalRows, truncated, hiddenFields, hiddenCount, notes}。`k` 是 row／subtotal／total。"""
    total_rows = raw["count"][0][0] if raw.get("count") else 0
    if plan.mode != "preview" and total_rows > MAX_EXPORT_ROWS:
        raise ReportRefused("資料超過 %s 列，請縮小篩選範圍。" % format(MAX_EXPORT_ROWS, ","), {"reason": "too_many_rows"})
    ng = len(plan.groups)
    agg_by_field = {}
    for i, a in enumerate(plan.aggs):
        agg_by_field.setdefault(a["fieldId"], (i, a))
    out, notes = [], list(plan.notices)
    if plan.layout == "detail":
        cols = [{"key": "c%d" % i, "label": c["label"], "type": c["type"]} for i, c in enumerate(plan.columns)]
        gtab = {r[:ng]: r[ng:] for r in raw.get("groups", [])} if ng else {}
        rows = raw["rows"]
        ncol = len(plan.columns)

        def sub_row(label, aggvals, first_label):
            cells = [None] * ncol
            for ci, c in enumerate(plan.columns):
                hit = agg_by_field.get(c["fieldId"])
                if hit is not None:
                    i, a = hit
                    cells[ci] = _fmt(aggvals[i], a["type"], a["fn"])
            for ci in range(ncol):
                if cells[ci] is None and plan.columns[ci]["fieldId"] not in agg_by_field:
                    cells[ci] = first_label
                    break
            return {"k": label, "v": cells}

        for idx, r in enumerate(rows):
            cells = [_label_of(plan, c["fieldId"], r[i]) if c["type"] == "enum" else _fmt(r[i], c["type"]) for i, c in enumerate(plan.columns)]
            out.append({"k": "row", "v": cells})
            if ng and plan.aggs:
                key = tuple(r[ncol:ncol + ng])
                nxt = tuple(rows[idx + 1][ncol:ncol + ng]) if idx + 1 < len(rows) else None
                if nxt != key and key in gtab:
                    gl = "、".join(str(_label_of(plan, plan.groups[j]["fieldId"], key[j])) for j in range(ng))
                    out.append(sub_row("subtotal", gtab[key], "小計：" + gl))
        if plan.aggs and raw.get("total"):
            out.append(sub_row("total", raw["total"][0], "總計"))
        unshown = [a["label"] for a in plan.aggs if a["fieldId"] != "*" and a["fieldId"] not in {c["fieldId"] for c in plan.columns}]
        if unshown:
            notes.append("彙總欄未列入顯示欄，小計與總計不列出：%s。" % "、".join(unshown))
        if any(a["fieldId"] == "*" for a in plan.aggs):
            notes.append("明細版型的筆數請看頂端的總筆數。")
    else:
        cols = ([{"key": "g%d" % i, "label": g["label"], "type": g["type"]} for i, g in enumerate(plan.groups)]
                + [{"key": "a%d" % i, "label": a["label"], "type": a["type"]} for i, a in enumerate(plan.aggs)])
        for r in raw["rows"]:
            cells = [_label_of(plan, g["fieldId"], r[i]) if g["type"] == "enum" else (r[i] if r[i] not in (None, "") else "（未填）") for i, g in enumerate(plan.groups)]
            cells += [_fmt(r[ng + i], a["type"], a["fn"]) for i, a in enumerate(plan.aggs)]
            out.append({"k": "row", "v": cells})
        tot = raw.get("total")
        if tot:
            out.append({"k": "total", "v": ["總計"] + [None] * (ng - 1) + [_fmt(tot[0][i], a["type"], a["fn"]) for i, a in enumerate(plan.aggs)]})
    if plan.aggs and any(a["type"] in ("money", "percent", "number") and a["fn"] in ("sum", "avg") for a in plan.aggs):
        notes.append("加總與平均不含空白的資料。")
    n_row = sum(1 for r in out if r["k"] == "row")
    return {"columns": cols, "rows": out, "totalRows": total_rows, "truncated": n_row < total_rows, "hiddenFields": list(plan.hidden),
            "hiddenCount": len(plan.hidden), "notes": notes}


_PERIOD_LABEL = {"this_month": "本月", "last_month": "上月", "this_quarter": "本季", "this_year": "今年", "last_year": "去年", "last_30_days": "近 30 天"}
_OP_LABEL = {"eq": "＝", "neq": "≠", "contains": "包含", "in": "屬於", "gte": "≥", "lte": "≤"}


def describe_filters(definition) -> list:
    """生效的篩選條件（含來源預設條件）寫成白話字串清單，給匯出檔的條件摘要用。只用欄位標籤與使用者自己填的條件值；
    定義必須已通過 `compile`（欄位都存在且可見）；不認得的欄位或值就略過，不丟例外。"""
    try:
        d = _normalize(definition)
        spec = RC.get_source(d["source"])
        if spec is None:
            return []
        by = {f["id"]: f for f in spec["fields"]}
        flts = d["filters"] if d["filters"] is not None else list(spec.get("defaultFilters") or [])
        out = []
        for x in flts:
            f = by.get(x.get("field"))
            if f is None:
                continue
            op, v = x.get("op"), x.get("value")
            opts = dict(o for o in (f.get("options") or ()) if isinstance(o, (list, tuple)) and len(o) == 2) if isinstance(f.get("options"), (list, tuple)) else {}

            def show(z):
                return str(opts.get(z, z))
            if op == "is_me":
                body = "是我"
            elif op == "empty":
                body = "未填"
            elif op == "not_empty":
                body = "有填"
            elif op == "between" and isinstance(v, list) and len(v) == 2:
                body = "介於 %s ～ %s" % (v[0], v[1])
            elif op == "relative":
                body = _PERIOD_LABEL.get(v, str(v))
            elif op == "in" and isinstance(v, list):
                body = "屬於 " + "、".join(show(z) for z in v)
            elif op in _OP_LABEL:
                body = "%s %s" % (_OP_LABEL[op], show(v))
            else:
                continue
            out.append("%s %s" % (f["label"], body) if op in ("is_me", "empty", "not_empty", "relative") else "%s%s" % (f["label"], (" " + body) if not body.startswith("＝") else body))
        return out
    except Exception:                                                          # noqa: BLE001 — 摘要只是說明文字
        return []


def preview(definition, user, today=None) -> dict:
    """預覽：編譯 → 擁有模組的 execute → 組表（不寫任何東西）。"""
    plan = compile(definition, user, "preview", today)
    spec = RC.get_source(plan.source_id)
    return assemble(plan, spec["execute"](plan))
