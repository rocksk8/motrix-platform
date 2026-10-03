# -*- coding: utf-8 -*-
r"""da：drill_train33 外包——每次 record() 都另存「全庫逐列雜湊」，結束後印出各階段差異（基準→A→重啟→C 回滾→E 重套→B 只回程式）。
用法（cwd 任意）：
  python drill33_full.py --drill-repo D:\開發測試檔\wt-da-drill -- --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> [其餘參數傳給 drill_train33]
輸出：stdout 摘要＋ %TEMP%\da_drill33_full.json。drill 本身的 PASS／FAIL 以 drill 報告為準（motrix-drill-t29\*.report.json）。"""
import hashlib, json, os, sqlite3, sys, tempfile
from pathlib import Path

argv = sys.argv[1:]
repo = r"D:\開發測試檔\wt-da-drill"
if "--drill-repo" in argv:
    i = argv.index("--drill-repo"); repo = argv[i + 1]; del argv[i:i + 2]
modname = "drill_train33"
if "--drill-module" in argv:
    i = argv.index("--drill-module"); modname = argv[i + 1]; del argv[i:i + 2]
if argv and argv[0] == "--":
    argv = argv[1:]
sys.path.insert(0, os.path.join(repo, "tools", "platform"))
import importlib
D33 = importlib.import_module(modname)  # noqa: E402
T = D33.T

# 變動本來就大的表：只報「有差」不展開
VOLATILE = {"audit_log", "notifications", "sessions", "login_attempts", "system_events", "request_log", "settings_history", "gl_source_events_log"}
SNAPS = []


def full_dump(root):
    c = T.ro(root)
    out = {}
    try:
        for (name, sql) in c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            rows = []
            try:
                for r in c.execute('SELECT rowid AS _rid, * FROM "%s" ORDER BY rowid' % name):
                    rows.append((r[0], hashlib.sha1(repr(tuple(r)[1:]).encode("utf-8", "replace")).hexdigest()[:12]))
            except sqlite3.Error as e:
                rows = [("ERR", str(e)[:60])]
            out[name] = {"sql": hashlib.sha1((sql or "").encode("utf-8")).hexdigest()[:12], "rows": rows}
        out["__indexes__"] = {"sql": "", "rows": [(n, hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:12]) for n, s in
                                                   c.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('index','trigger','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]}
    finally:
        c.close()
    return out


_orig_record = T.record


def record_with_dump(root, *a, **k):
    rec = _orig_record(root, *a, **k)
    try:
        SNAPS.append(full_dump(root))
    except Exception as e:  # noqa: BLE001
        SNAPS.append({"__error__": {"sql": "", "rows": [("ERR", str(e)[:100])]}})
    return rec


T.record = record_with_dump
import drill_train30 as _T30  # noqa: E402
_T30._orig_record = record_with_dump           # drill_train30.main 會把 T.record 換成包住 _orig_record 的版本，所以要換這個


def diff(a, b):
    res = {}
    for t in sorted(set(a) | set(b)):
        if t not in a:
            res[t] = {"table": "ADDED", "rows": len(b[t]["rows"])}; continue
        if t not in b:
            res[t] = {"table": "REMOVED", "rows": len(a[t]["rows"])}; continue
        ra, rb = dict(a[t]["rows"]), dict(b[t]["rows"])
        ch = sorted((k for k in ra if k in rb and ra[k] != rb[k]), key=str); ad = sorted((k for k in rb if k not in ra), key=str); rm = sorted((k for k in ra if k not in rb), key=str)
        schema = a[t]["sql"] != b[t]["sql"]
        if ch or ad or rm or schema:
            res[t] = {"schema_changed": schema, "changed": len(ch), "added": len(ad), "removed": len(rm), "sample": {"changed": ch[:3], "added": ad[:3], "removed": rm[:3]}}
    return res


def summarize():
    labels = ["baseline", "afterA", "afterA_restart", "afterC", "afterE", "B_migrated", "afterB"]
    out = {}
    pairs = [(0, 1, "baseline→A（預期差異：schema_version／module_schema_versions／新表新欄／audit；其餘應無）"), (1, 2, "A→A 重啟（應幾乎無差）"),
             (0, 3, "baseline→C 資料庫回滾（應無差）"), (1, 4, "A→E 回滾後重套（應與 A 同形）"), (4, 5, "E→B 前（應無差）"), (5, 6, "B 前→B 只回程式後（舊程式啟動可能補寫，逐項看）")]
    for i, j, msg in pairs:
        if j < len(SNAPS) and i < len(SNAPS):
            d = diff(SNAPS[i], SNAPS[j])
            vol = {k: v for k, v in d.items() if k in VOLATILE}
            main = {k: v for k, v in d.items() if k not in VOLATILE}
            out["%s→%s" % (labels[i], labels[j])] = {"說明": msg, "volatile_tables_changed": sorted(vol), "diff": main}
    p = Path(tempfile.gettempdir()) / "da_drill33_full.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n===== 全庫逐列差異摘要（詳見 %s）=====" % p)
    for k, v in out.items():
        print("\n%s\n  %s\n  volatile 有差：%s" % (k, v["說明"], v["volatile_tables_changed"]))
        for t, d in v["diff"].items():
            print("   - %s: %s" % (t, {x: y for x, y in d.items() if x != "sample"}))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    rc = 1
    try:
        rc = D33.main(argv)
    finally:
        summarize()
    sys.exit(rc)
