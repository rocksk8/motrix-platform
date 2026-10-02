# -*- coding: utf-8 -*-
"""第 31 班 31-C 稽核（c7）：用「真的 prod/6b5d2865 基底庫」升級到 a5dea50c 兩次——全表逐列雜湊比對（舊列逐位不變）、新表為空、冪等、完整性。"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
BASE = r"D:\開發測試檔\wt-prod-6b5d\backend"
CUR = r"D:\開發測試檔\wt-t31p\backend"
tmp = os.path.join(tempfile.gettempdir(), "c7-t31c-mig")
os.makedirs(tmp, exist_ok=True)
db = os.path.join(tmp, "base.db")
for f in os.listdir(tmp):
    os.remove(os.path.join(tmp, f))


def run(cwd, code):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print("STDERR", r.stderr[-2000:])
        sys.exit(1)
    return r.stdout


def digests(conn):
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        cols = [r[1] for r in conn.execute('PRAGMA table_info("%s")' % t)]
        rows = conn.execute('SELECT * FROM "%s" ORDER BY 1' % t).fetchall()
        out[t] = (cols, len(rows), hashlib.sha256(json.dumps([list(map(str, r)) for r in rows], ensure_ascii=False).encode()).hexdigest())
    return out


# 1) 基底庫（47db→6b5d2865 的程式）：用 loader 跑完該版全部模組 migration
print(run(BASE, "import db; from core import loader; loader.load_all(); db.init_db(%r); print('base init ok')" % db).strip())
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
c.execute("INSERT INTO vendor_contractors (name) VALUES ('舊商')")
vid = c.execute("SELECT id FROM vendor_contractors").fetchone()[0]
orders = [{"itemId": "L%d" % i, "itemName": "舊叫料%d" % i, "quantity": 2, "unit": "台", "unitPrice": 1000 * i, "totalPrice": 2000 * i,
           "paidStatus": ("paid" if i == 2 else "pending"), "paidAmount": (4000 if i == 2 else 0), "paidDate": ("2026-09-01" if i == 2 else ""), "notes": ""} for i in (1, 2, 3)]
mats = [{"id": 101, "name": "舊物料", "qty": 2, "ordered": True, "arrived": True, "devices": ["SN1"]}]
cr = {"dealTag": "已成案", "caseRecord": {"materialOrders": orders, "materials": mats}}
c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("MQ-OLD-1", "已送出", "舊客", "舊案", 100000, 95238, json.dumps(cr, ensure_ascii=False), "2026-08-01T00:00:00", "2026-08-01T00:00:00", "已成案"))
c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, items_json, created_by, created_at, updated_at, approval_status) VALUES (?,?,?,?,?,?,?,?,?)",
          ("MQ-OLD-1", vid, "accepted", 3000, json.dumps([{"description": "x", "amount": 3000}]), "old", "2026-08-02T00:00:00", "2026-08-02T00:00:00", ""))
c.commit()
before = digests(c)
print("baseline tables:", len(before), "| has case_material_*:", [t for t in before if t.startswith("case_material")])
c.close()

# 2) 現行程式升級兩次
after = {}
for i in (1, 2):
    print("upgrade", i, run(CUR, "import db; from core import loader; loader.load_all(); db.init_db(%r); print('init ok')" % db).strip())
    c = sqlite3.connect(db)
    after[i] = digests(c)
    changed = [t for t in before if t in after[i] and (before[t][1:] != after[i][i][1:] if False else before[t][1:] != after[i][t][1:])]
    newtabs = sorted(set(after[i]) - set(before))
    print(" changed pre-existing tables:", changed)
    print(" new tables:", newtabs, "| new tables empty:", all(after[i][t][1] == 0 for t in newtabs if t.startswith("case_material")))
    print(" case_material_* rows:", {t: after[i][t][1] for t in newtabs if t.startswith("case_material")})
    mo = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-OLD-1'").fetchone()[0])["caseRecord"]["materialOrders"]
    print(" legacy orders json unchanged:", mo == orders)
    print(" integrity:", c.execute("PRAGMA integrity_check").fetchone()[0], "| fk violations:", len(c.execute("PRAGMA foreign_key_check").fetchall()))
    print(" schema_version:", [tuple(x) for x in c.execute("SELECT * FROM schema_version")])
    c.close()
print("run1==run2 (no change on 2nd upgrade):", {t: v[1:] for t, v in after[1].items()} == {t: v[1:] for t, v in after[2].items()})
d = [t for t in after[1] if t in after[2] and after[1][t][1:] != after[2][t][1:]]
print("tables differing between upgrade 1 and 2:", d)
