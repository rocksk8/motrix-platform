# -*- coding: utf-8 -*-
"""A29 升級／回滾演練 v2（合成資料；用應用程式啟動路徑跑模組 migration）：
A 0bb4834e 啟動建庫 → 塞舊資料 → B 47db5613 啟動（升級）→ C 再啟動一次（冪等）→ D 0bb4834e 在升級後的庫上啟動（回滾相容）。"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess

PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
OLD = r"D:\開發測試檔\wt-a29-prod\backend"
NEW = r"D:\開發測試檔\wt-a29-pkg\backend"
CHILD = r"""
import os, sys
sys.path.insert(0, '.')
from fastapi.testclient import TestClient
import main
with TestClient(main.app) as c:
    r = c.get('/api/ping')
    print('PING', r.status_code)
"""


def dbfile(tree):
    return os.path.join(tree, "motrix_erp.db")


def run(tree, label, create=False):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", MOTRIX_DISABLE_SCHEDULERS="1")
    if create:
        env["MOTRIX_CREATE_NEW_DB"] = "1"
    for k in ("MOTRIX_CLOUD_ARCHIVE", "MOTRIX_API_DOCS"):
        env.pop(k, None)
    r = subprocess.run([PY, "-c", CHILD], cwd=tree, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    ping = [l for l in r.stdout.splitlines() if l.startswith("PING")]
    print("%-38s rc=%s %s" % (label, r.returncode, ping[-1] if ping else "(no ping)"))
    if r.returncode != 0:
        print("   STDERR tail:", r.stderr.strip()[-500:])
    return r.returncode == 0 and ping and ping[-1].endswith("200")


def snap(path):
    c = sqlite3.connect(path)
    out = {}
    for t, cols in (("quotations", "quote_no,status,total,data_json"), ("case_extra_expenses", "quote_no,category,description,total_cost,status,created_by")):
        rows = c.execute("SELECT %s FROM %s ORDER BY 1,2" % (cols, t)).fetchall()
        out[t] = (len(rows), hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()[:12])
    schema = c.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    msv = dict(c.execute("SELECT module, version FROM module_schema_versions").fetchall()) if c.execute("SELECT 1 FROM sqlite_master WHERE name='module_schema_versions'").fetchone() else {}
    ver = c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone() else None
    c.close()
    return out, hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest()[:12], {s[1] for s in schema}, msv, ver


for t in (OLD, NEW):
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(dbfile(t) + ext):
            os.remove(dbfile(t) + ext)
try:
    assert run(OLD, "A. 0bb4834e 啟動建庫", create=True)
    c = sqlite3.connect(dbfile(OLD))
    c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) VALUES ('MQ-DR-1','已送出','客','案',1000,'{\"dealTag\":\"已成案\"}','2026-09-01','2026-09-01')")
    c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json, change_status, change_json)"
              " VALUES ('MQ-DR-1','材料','舊支出',1,'式',500,500,'','2026-09-01','','[]','u','U',0,'u','U','2026-09-01T00:00:00','2026-09-01T00:00:00','U','已核准','{}','','{}')")
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    b_data, b_schema, b_names, b_msv, b_ver = snap(dbfile(OLD))
    print("   prod 狀態: schema_version=%s module_versions=%s legacy=%s" % (b_ver, b_msv, b_data))
    shutil.copy(dbfile(OLD), dbfile(NEW))
    assert run(NEW, "B. 47db5613 啟動（升級）")
    a_data, a_schema, a_names, a_msv, a_ver = snap(dbfile(NEW))
    print("   升級後: schema_version=%s module_versions=%s" % (a_ver, {k: v for k, v in a_msv.items() if b_msv.get(k) != v}))
    print("   新增物件:", sorted(a_names - b_names)[:14])
    print("   舊資料逐列相同:", a_data == b_data)
    assert run(NEW, "C. 47db5613 再啟動一次（冪等）")
    c_data, c_schema, c_names, c_msv, c_ver = snap(dbfile(NEW))
    print("   冪等：schema 相同=%s 版號相同=%s 資料相同=%s" % (c_schema == a_schema, (c_msv, c_ver) == (a_msv, a_ver), c_data == a_data))
    cn = sqlite3.connect(dbfile(NEW))
    print("   integrity_check:", cn.execute("PRAGMA integrity_check").fetchone()[0], "| foreign_key_check rows:", len(cn.execute("PRAGMA foreign_key_check").fetchall()))
    cn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cn.close()
    shutil.copy(dbfile(NEW), dbfile(OLD))
    ok = run(OLD, "D. 0bb4834e 在升級後的庫上啟動（回滾相容）")
    d_data = snap(dbfile(OLD))[0]
    print("   回滾後舊資料相同:", d_data == b_data)
finally:
    for t in (OLD, NEW):
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(dbfile(t) + ext)
            except OSError:
                pass
