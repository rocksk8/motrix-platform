# -*- coding: utf-8 -*-
"""回應鍵集記錄器（U0a）：把『每條 GET 路由的 JSON 鍵路徑』與『匯出檔的表頭』記成基準，之後與基準比對。

不是測試檔（底線開頭）。用法見 test_response_keys_baseline.py。
- `seed_every_table(conn)`：每張表塞一列（NOT NULL 無預設的欄位按型別填），讓清單類路由回傳『有列』——空清單沒有鍵可比，基準會變成假綠燈。
- `key_paths(obj)`：遞迴鍵路徑（list 取聯集、元素型別抹去）。
- `record(client, headers, paths)`：逐路由 GET，記狀態與鍵路徑；csv／xlsx 記表頭列。
"""
import csv
import io
import re
import sqlite3

INTERNAL = ("owner_unit_id", "unit_id", "legal_entity_id")

#: 不由記錄器呼叫的 GET（副作用或很重）；其餘靜態 GET 一律記。理由寫在旁邊。
DENY = re.compile(r"logout|shutdown|restart|backup|restore|apply|upgrade|self.?test|health.?scan|/probe|/map|geo|tile", re.I)
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


def key_paths(obj, prefix="", out=None) -> list:
    """遞迴鍵路徑（排序、去重）；list 元素合併成 `prefix[]`。"""
    top = out is None
    out = set() if top else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            out.add(p)
            key_paths(v, p, out)
    elif isinstance(obj, list):
        for v in obj[:50]:
            key_paths(v, prefix + "[]", out)
    return sorted(out) if top else []


def static_get_paths(app) -> list:
    """app 的 GET 靜態路由（不含 `{}` 參數、只取 /api/）。"""
    out = set()
    for r in app.routes:
        methods = getattr(r, "methods", None) or ()
        p = getattr(r, "path", "")
        if "GET" in methods and p.startswith("/api/") and "{" not in p:
            out.add(p)
    return sorted(out)


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
    for p in paths:
        if DENY.search(p):
            continue
        try:
            r = client.get(p, headers=headers)
        except Exception:                                                    # noqa: BLE001
            out[p] = {"s": 0}
            continue
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            try:
                out[p] = {"s": r.status_code, "k": key_paths(r.json())}
            except ValueError:
                out[p] = {"s": r.status_code, "k": []}
        elif EXPORT.search(p) or "csv" in ct or "spreadsheetml" in ct:
            try:
                out[p] = {"s": r.status_code, "ct": ct.split(";")[0], "hdr": export_header(ct, r.content)}
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


def diff(base: dict, now: dict) -> dict:
    """{'missing': 基準有、現在沒有的路由, 'added': 現在才有的路由, 'changed': {路徑: (基準, 現在)}}（狀態類別或鍵集不同）。"""
    changed = {}
    for p in set(base) & set(now):
        b, n = base[p], now[p]
        if (b.get("s", 0) // 100) != (n.get("s", 0) // 100) or b.get("k") != n.get("k") or b.get("hdr") != n.get("hdr"):
            changed[p] = (b, n)
    return {"missing": sorted(set(base) - set(now)), "added": sorted(set(now) - set(base)), "changed": changed}
