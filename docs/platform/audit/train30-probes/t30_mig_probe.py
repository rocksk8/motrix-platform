# -*- coding: utf-8 -*-
"""第 30 班 稽核（c7）：subcontract migration 0003 在「真的 47db5613 基底 DB」上升級的探針（兩次、比對舊列、完整性）。"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
BASE = r"D:\開發測試檔\wt-prod-47db\backend"
CUR = r"D:\開發測試檔\wt-t30-audit\backend"
tmp = os.path.join(tempfile.gettempdir(), "c7-t30-mig")
os.makedirs(tmp, exist_ok=True)
db = os.path.join(tmp, "base.db")
for f in os.listdir(tmp):
    os.remove(os.path.join(tmp, f))


def run(cwd, code):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", MOTRIX_TEST_DB=db)
    r = subprocess.run([PY, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print("STDERR", r.stderr[-1500:])
        sys.exit(1)
    return r.stdout


# 1) 用 47db5613 的程式建基底庫
print(run(BASE, "import db; db.init_db(%r); print('base init ok')" % db))
c = sqlite3.connect(db)
cols0 = [r[1] for r in c.execute("PRAGMA table_info(contractor_dispatches)")]
print("baseline columns:", cols0)
c.execute("INSERT INTO vendor_contractors (name) VALUES ('舊商')")
vid = c.execute("SELECT id FROM vendor_contractors").fetchone()[0]
rows = [("MQ-L1", vid, "draft", 1000), ("MQ-L2", vid, "sent", 2000), ("MQ-L3", vid, "accepted", 3000), ("MQ-L4", vid, "completed", 4000), ("MQ-L5", None, "cancelled", 0)]
for q, v, st, amt in rows:
    c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, items_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
              (q, v, st, amt, json.dumps([{"description": "x", "amount": amt}]), "old_user", "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
c.commit()
old_cols = [x for x in cols0]
dig = lambda cn: hashlib.sha256(json.dumps([list(r) for r in cn.execute("SELECT %s FROM contractor_dispatches ORDER BY id" % ",".join(old_cols))], ensure_ascii=False).encode()).hexdigest()
d0 = dig(c)
c.close()

# 2) 用現行程式升級兩次
for i in (1, 2):
    print("upgrade", i, run(CUR, "import db; from core import loader; loader.load_all(); db.init_db(%r); print('init ok')" % db).strip())
    c = sqlite3.connect(db)
    colsN = [(r[1], r[2], r[4]) for r in c.execute("PRAGMA table_info(contractor_dispatches)")]
    print(" digest unchanged:", dig(c) == d0, "| new col count:", len(colsN) - len(old_cols))
    leg = c.execute("SELECT approval_status, completion_status, doc_code, approval_json, approved_hash, cancel_reason FROM contractor_dispatches").fetchall()
    print(" all legacy markers blank:", all(tuple(r) == ("", "", "", "{}", "", "") for r in leg))
    print(" integrity:", c.execute("PRAGMA integrity_check").fetchone()[0], "| fk violations:", len(c.execute("PRAGMA foreign_key_check").fetchall()))
    print(" indexes:", sorted(r[1] for r in c.execute("PRAGMA index_list(contractor_dispatches)") if "dispatch_" in r[1] or "doc_code" in r[1]))
    mv = c.execute("SELECT * FROM schema_version").fetchall()
    print(" schema_version:", [tuple(x) for x in mv])
    try:
        print(" module versions:", [tuple(x) for x in c.execute("SELECT * FROM module_versions WHERE module LIKE 'subcontract%'")])
    except sqlite3.Error as e:
        print(" module_versions n/a:", e)
    c.close()
