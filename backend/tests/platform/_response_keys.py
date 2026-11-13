# -*- coding: utf-8 -*-
"""回應鍵集記錄器（U0a）：把『每條 GET 路由的 JSON 鍵路徑』與『匯出檔的表頭』記成基準，之後與基準比對。

不是測試檔（底線開頭）。用法見 test_response_keys_baseline.py。
- `seed_every_table(conn)`：每張表塞一列（NOT NULL 無預設的欄位按型別填），讓清單類路由回傳『有列』——空清單沒有鍵可比，基準會變成假綠燈。
- `key_paths(obj)`：遞迴鍵路徑（list 取聯集、元素型別抹去）。
- `record(client, headers, paths)`：逐路由 GET，記狀態與鍵路徑；csv／xlsx 記表頭列。
- `norm_keys(keys)`：動態月份鍵（`…otherBreakdown.2026-11`）正規化成 `<月>`；`record` 與 `diff` 都走它，所以滾動視窗不會讓基準無故轉紅。
"""
import csv
import io
import re
import sqlite3

INTERNAL = ("owner_unit_id", "unit_id", "legal_entity_id")

#: 不由記錄器呼叫的 GET（副作用或很重）；其餘靜態 GET 一律記。理由寫在旁邊。
DENY = re.compile(r"logout|shutdown|restart|backup|restore|apply|upgrade|self.?test|health.?scan|/probe|/map|geo|tile|company/tax", re.I)
EXPORT = re.compile(r"export|download|\.xlsx|\.csv", re.I)


def seed_every_table(conn) -> int:
    """每張表插一列；失敗（CHECK、觸發器…）的表略過。回成功張數。"""
    conn.execute("PRAGMA foreign_keys=OFF")
    ok = 0
    for name, sql in conn.execute("SELECT name, COALESCE(sql,'') FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        if sql.upper().startswith("CREATE VIRTUAL") or "_fts" in name:
            continue
        cols = conn.execute('PRAGMA table_info("%s")' % name).fetchall()
        if conn.execute('SELECT 1 FROM "%s" LIMIT 1' % name).fetchone():
            continue
        names, vals = [], []
        for _cid, cname, ctype, notnull, default, pk in cols:
            if pk and "INT" in (ctype or "").upper():
                continue
            if notnull and default is None:
                t = (ctype or "").upper()
                names.append('"%s"' % cname)
                vals.append(1 if "INT" in t else 1.0 if any(x in t for x in ("REAL", "FLOA", "DOUB", "NUM")) else "x")
        try:
            if names:
                conn.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (name, ", ".join(names), ", ".join("?" * len(vals))), vals)
            else:
                conn.execute('INSERT INTO "%s" DEFAULT VALUES' % name)
            ok += 1
        except sqlite3.Error:
            continue
    conn.commit()
    return ok


#: 動態月份鍵：回應用「年-月」當物件鍵（例：`/api/dashboard/bundle` 的 `expenses.otherBreakdown.<YYYY-MM>`、`/api/dashboard/expenses-monthly` 的
#: `otherBreakdown.<YYYY-MM>`；視窗＝最近 12 個月，隨『今天』滾動）。不正規化的話基準錄在 11 月，12/1 起鍵集就變（2025-12 掉出、2026-12 進來）而無故轉紅。
#: 只認「整段」是 YYYY-MM（前後是 `.`、`[`、頭尾）；`2026-01-05`（日）、`x2026-01`、`2026-13` 都不算。
_MONTH_SEG = re.compile(r"(?<![\w-])(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?![\w-])")
MONTH_TOKEN = "<月>"


def norm_keys(keys):
    """鍵路徑清單 ⇒ 月份段換成 `<月>`、去重、排序。None 原樣回（沒有 `k` 的匯出／非 JSON 項目）。冪等。"""
    if keys is None:
        return None
    return sorted({_MONTH_SEG.sub(MONTH_TOKEN, k) for k in keys})


def key_paths(obj, prefix="", out=None) -> list:
    """遞迴鍵路徑（排序、去重）；list 元素合併成 `prefix[]`，**所有**元素的鍵取聯集、不設筆數上限。
    （曾經只取前 50 筆：設定中心群組加到第 51 個後，排在後面的群組——tender_closing 的 closing_soon_days——掉出取樣，
    基準「少了」一個其實還在的鍵；更糟的是陣列後段新增／消失的鍵會被靜默漏看。T84 修。種子每表一列，清單都很短，全掃的成本可忽略。）"""
    top = out is None
    out = set() if top else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            out.add(p)
            key_paths(v, p, out)
    elif isinstance(obj, list):
        for v in obj:
            key_paths(v, prefix + "[]", out)
    return sorted(out) if top else []


_INT_NAME = re.compile(r"^(id|year|seq|rid|month|page|limit|offset)$|_id$|_seq$", re.I)


def _is_int(field) -> bool:
    for ann in (getattr(field, "annotation", None), getattr(getattr(field, "field_info", None), "annotation", None),
                getattr(field, "type_", None), getattr(field, "outer_type_", None)):
        if ann is int:
            return True
    return bool(_INT_NAME.search(getattr(field, "name", "") or ""))     # 型別取不到（Path()／Annotated）時按名稱猜


_QUERY_DEFAULTS = (
    (re.compile(r"year", re.I), "2026"), (re.compile(r"month", re.I), "10"),
    (re.compile(r"(from|start|begin).*|.*_(from|start)$", re.I), "2026-01-01"),
    (re.compile(r"(to|end).*|.*_(to|end)$", re.I), "2026-12-31"),
    (re.compile(r"date|day", re.I), "2026-10-01"),
    (re.compile(r"^(fmt|format)$", re.I), "xlsx"),
    (re.compile(r"(^|_)id$|^id", re.I), "1"),
)


def _query_default(name: str, field) -> str:
    for rx, v in _QUERY_DEFAULTS:
        if rx.search(name):
            return v
    return "1" if _is_int(field) else "x"


def iter_routes(app):
    """app 的所有端點路由（攤平）：委派給專案共用的 `tests/_routes.all_routes`（新舊 FastAPI 都適用；0.14x 的 `include_router`
    放 `_IncludedRouter`，只有 `effective_route_contexts()`）。不另寫一份：這個坑 2026-09-25 就記過一次。"""
    from tests._routes import all_routes
    for _path, _methods, r in all_routes(app):
        yield r


def get_targets(app) -> list:
    """[(鍵, 實際網址)]：GET 路由；路徑參數用種子值填（整數 1、字串 'x'——種子的 NOT NULL 文字欄位就是 'x'，所以字串主鍵也對得上），
    必填查詢參數用 `_QUERY_DEFAULTS` 的合理預設。鍵是路由樣板（含 `{}`），所以基準不依賴填入的值。"""
    from urllib.parse import quote
    out = {}
    for r in iter_routes(app):
        methods = getattr(r, "methods", None) or ()
        tpl = getattr(r, "path", "")
        if "GET" not in methods or not tpl.startswith("/api/"):
            continue
        dep = getattr(r, "dependant", None)
        url = tpl
        for f in (getattr(dep, "path_params", None) or []):
            url = url.replace("{%s}" % f.name, "1" if _is_int(f) else "x")
            url = re.sub(r"\{%s:[^}]*\}" % re.escape(f.name), "1" if _is_int(f) else "x", url)
        if "{" in url:
            continue
        q = ["%s=%s" % (f.name, quote(_query_default(f.name, f))) for f in (getattr(dep, "query_params", None) or []) if getattr(f, "required", False)]
        out[tpl] = url + ("?" + "&".join(q) if q else "")
    return sorted(out.items())


def static_get_paths(app) -> list:
    """舊介面：只回鍵（保留給舊呼叫者）。"""
    return [k for k, _u in get_targets(app)]


def export_header(content_type: str, body: bytes) -> list:
    """csv／xlsx 的表頭（第一個非空列）；其他型別回 []。"""
    ct = (content_type or "").lower()
    if "csv" in ct:
        text = body.decode("utf-8-sig", "replace")
        for row in csv.reader(io.StringIO(text)):
            if any(c.strip() for c in row):
                return [c.strip() for c in row]
        return []
    if "spreadsheetml" in ct or "excel" in ct or "xlsx" in ct:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True)
        heads = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c not in (None, "")]
                if cells:
                    heads.append("%s|%s" % (ws.title, ",".join(cells)))
                    break
        return heads
    return []


def record(client, headers, paths) -> dict:
    """{路徑: {"s": 狀態碼, "k": [鍵路徑]} 或 {"s":…, "ct":…, "hdr":[表頭]}}。呼叫失敗的路由記 {"s": 0}。"""
    out = {}
    for item in paths:
        p, url = item if isinstance(item, tuple) else (item, item)
        if DENY.search(p):
            continue
        try:
            r = client.get(url, headers=headers)
        except Exception:                                                    # noqa: BLE001
            out[p] = {"s": 0}
            continue
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            try:
                out[p] = {"s": r.status_code, "k": norm_keys(key_paths(r.json()))}
            except ValueError:
                out[p] = {"s": r.status_code, "k": []}
        elif EXPORT.search(p) or "csv" in ct or "spreadsheetml" in ct:
            try:
                out[p] = {"s": r.status_code, "ct": ct.split(";")[0], "hdr": _mask_dates(export_header(ct, r.content))}
            except Exception:                                                # noqa: BLE001
                out[p] = {"s": r.status_code, "ct": ct.split(";")[0], "hdr": ["<unreadable>"]}
        else:
            out[p] = {"s": r.status_code}
    return out


def leaks(rec: dict) -> list:
    """記錄裡出現內部欄位名的位置：[(路徑, 鍵／表頭)]。"""
    bad = []
    for p, e in rec.items():
        for k in e.get("k", []):
            if k.split(".")[-1].replace("[]", "") in INTERNAL:
                bad.append((p, k))
        for h in e.get("hdr", []):
            if any(i in h.split("|")[-1].split(",") for i in INTERNAL):
                bad.append((p, h))
    return bad


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: 『2026-11 當月收支明細』『2026 年 11 月』『2026年度收支總表』：表頭帶『執行當下的年月／年』，換月（12/1）、換年（1/1）就變；只遮數字段，欄位名與結構照比。
_YM = re.compile(r"(?<![A-Za-z\d-])(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?![A-Za-z\d-])")
_ZH_YM = re.compile(r"(?<!\d)(?:19|20)\d{2} ?年(?: ?\d{1,2} ?月)?")


def _mask_dates(hdr):
    """匯出表頭裡隨執行日變動的日期／年月（『截至 2026-10-13』『2026-11 當月…』『2026 年 11 月』『2026年度』）；比對與記錄都先遮掉。冪等。"""
    if hdr is None:
        return None
    return [_ZH_YM.sub("<年月>", _YM.sub("YYYY-MM", _DATE.sub("YYYY-MM-DD", h))) for h in hdr]


# 有套限流的匯出／PDF 路由（基準裡記到 429 的那幾條）；新增項目要有證據（基準裡真的記到 429）
RATE_LIMITED = frozenset({"/api/contractors/export/pdf", "/api/reports/financial/pdf", "/api/reports/tax-export", "/api/reports/tax-export/pdf"})


def diff(base: dict, now: dict) -> dict:
    """{'missing': 基準有、現在沒有的路由, 'added': 現在才有的路由, 'changed': {路徑: (基準, 現在)}}（狀態類別或鍵集不同）。"""
    changed = {}
    for p in set(base) & set(now):
        b, n = base[p], now[p]
        if p in RATE_LIMITED and {b.get("s"), n.get("s")} == {429, 200}:      # 限流器的命中順序隨請求順序挪動（新增路由會挪動）；只放行清單內路由的 429↔200，其餘（403／404／500、鍵集變動）照報
            continue
        if (b.get("s", 0) // 100) != (n.get("s", 0) // 100) or norm_keys(b.get("k")) != norm_keys(n.get("k")) or _mask_dates(b.get("hdr")) != _mask_dates(n.get("hdr")):
            changed[p] = (b, n)
    return {"missing": sorted(set(base) - set(now)), "added": sorted(set(now) - set(base)), "changed": changed}
