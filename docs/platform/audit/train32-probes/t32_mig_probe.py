# -*- coding: utf-8 -*-
"""第 32 包稽核（c7）：真基準庫（prod/a5dea50c 的程式建庫）→ 第 32 包升級兩次。
第 32 班沒有任何 migration（`git diff a5dea50c..HEAD` 無 migrations 檔）⇒ 預期：**除 module_schema_versions 以外，每張表逐列雜湊相同**；
新功能（材料申請連結、尚未送審、舊單修改記號）只用既有欄位／JSON 鍵。另驗：
- 已發布的請款類型版本（ui_definitions v≥1，含舊的 applicant.help 英文字串）升級後位元不變（只有程式預設那份的字串改了）；
- 31-C 的舊資料（材料申請審核列、匯款申請含 snapshot_json 帳號與告知紀錄）不變；
- 舊派發單（approval_status=''）逐欄不變。
用法：python t32_mig_probe.py <第32包程式的 backend 路徑>（預設用整合樹）。"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
BASE = r"D:\開發測試檔\wt-prod-a5de\backend"
CUR = sys.argv[1] if len(sys.argv) > 1 else r"D:\開發測試檔\wt-t32pkg\backend"
tmp = os.path.join(tempfile.gettempdir(), "c7-t32-mig")
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


# 1) 基準庫：prod/a5dea50c 的程式＋loader（含 31-C 的 0004／0005）
print(run(BASE, "import db; from core import loader; loader.load_all(); db.init_db(%r); print('base init ok')" % db).strip())
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
now = "2026-10-02T10:00:00"
orders = [
    {"itemId": "M1", "itemName": "已核准材料", "quantity": 2, "unit": "台", "unitPrice": 5000, "totalPrice": 10000, "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": 1},
    {"itemId": "M2", "itemName": "草稿材料", "quantity": 1, "unit": "台", "unitPrice": 100, "totalPrice": 100, "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": 1},
    {"itemId": "L1", "itemName": "舊單材料", "quantity": 1, "unit": "式", "unitPrice": 3000, "totalPrice": 3000, "paidStatus": "paid", "paidAmount": 3000, "paidDate": "2026-08-01", "notes": ""},
]
cr = {"dealTag": "已成案", "caseRecord": {"materialOrders": orders, "materials": [{"id": 1, "name": "物流", "qty": 1, "ordered": True, "arrived": False, "devices": []}]}}
c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("MQ-A5-1", "已送出", "客", "案", 100000, 95238, json.dumps(cr, ensure_ascii=False), now, now, "已成案"))
c.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("MQ-A5-1", "M1", "MO-20261002-0001", "已核准", now, now))
c.execute("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)", ("MQ-A5-1", "M2", "MO-20261002-0002", "草稿", now, now))
c.execute("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", now, now))
snap = {"supplierName": "甲供應商", "bankAccountName": "甲有限公司", "bankAccountNumber": "28881234567890", "itemName": "已核准材料"}
c.execute("INSERT INTO case_material_payments (doc_code, quote_no, item_id, seq, supplier_id, amount_approved, snapshot_json, status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          ("MP-20261002-0001", "MQ-A5-1", "M1", 1, 1, 6000, json.dumps(snap, ensure_ascii=False), "已核准", "adm", now, now))
c.execute("INSERT INTO vendor_contractors (name) VALUES ('舊商')")
vid = c.execute("SELECT id FROM vendor_contractors").fetchone()[0]
c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, items_json, created_by, created_at, updated_at, approval_status) VALUES (?,?,?,?,?,?,?,?,?)",
          ("MQ-A5-1", vid, "accepted", 3000, json.dumps([{"description": "x", "amount": 3000}]), "old", now, now, ""))
c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, items_json, created_by, created_at, updated_at, approval_status, doc_code) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("MQ-A5-1", vid, "draft", 500, json.dumps([{"description": "y", "amount": 500}]), "new", now, now, "草稿", "DP-20261002-0001"))
# 卡住列（0004 的對象）：舊單申請完工待審核、doc_code=''；另放未卡住的舊單與已完成舊單
cols_cd = [r[1] for r in c.execute("PRAGMA table_info(contractor_dispatches)")]
def _cd(status, comp, approval, code, req):
    c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, total_amount, items_json, created_by, created_at, updated_at, approval_status, doc_code, completion_status, completion_requested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              ("MQ-A5-1", vid, status, 700, "[]", "old", now, now, approval, code, comp, req))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]
stuck_id = _cd("accepted", "待審核", "", "", "2026-09-20T09:00:00")
stuck2_id = _cd("accepted", "簽核中", "", "", "")
plain_id = _cd("completed", "", "", "", "")
c.commit()
# 已發布的請款類型（公司版，內含舊 help 英文字串）＋一份草稿
travel = json.loads(open(os.path.join(BASE, "helpers", "expense_type_defs", "travel.json"), encoding="utf-8").read())
c.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at, published_by, published_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ("expense_type", "travel", "company", 1, "published", json.dumps(travel, ensure_ascii=False), "sa", now, "sa", now))
c.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
          ("expense_type", "travel", "company", 0, "draft", json.dumps(dict(travel, name="草稿名"), ensure_ascii=False), "sa", now))
c.commit()
before = digests(c)
cd_before = {r[0]: dict(zip(cols_cd, r)) for r in c.execute("SELECT * FROM contractor_dispatches")}
print("baseline tables:", len(before))
c.close()

# 2) 第 32 包程式升級兩次
after = {}
for i in (1, 2):
    print("upgrade", i, run(CUR, "import db; from core import loader; loader.load_all(); db.init_db(%r); print('init ok')" % db).strip())
    c = sqlite3.connect(db)
    after[i] = digests(c)
    changed = [t for t in before if t in after[i] and before[t][1:] != after[i][t][1:] and t != "module_schema_versions"]
    newtabs = sorted(set(after[i]) - set(before))
    cols_changed = [t for t in before if t in after[i] and before[t][0] != after[i][t][0]]
    print(" changed pre-existing tables (rows):", changed, "| column set changed:", cols_changed, "| new tables:", newtabs)
    cd_after = {r[0]: dict(zip(cols_cd, r)) for r in c.execute("SELECT * FROM contractor_dispatches")}
    diffs = {k: sorted(f for f in cd_before[k] if cd_before[k][f] != cd_after[k][f]) for k in cd_before}
    print(" dispatch rows with changed fields:", {k: v for k, v in diffs.items() if v}, "| stuck codes:", cd_after[stuck_id]["doc_code"], cd_after[stuck2_id]["doc_code"], "| plain code:", repr(cd_after[plain_id]["doc_code"]))
    pub = c.execute("SELECT body_json FROM ui_definitions WHERE kind='expense_type' AND key='travel' AND version=1").fetchone()[0]
    print(" published travel v1 byte-identical:", pub == json.dumps(travel, ensure_ascii=False))
    print(" integrity:", c.execute("PRAGMA integrity_check").fetchone()[0], "| fk violations:", len(c.execute("PRAGMA foreign_key_check").fetchall()))
    c.close()
d = [t for t in after[1] if t in after[2] and after[1][t][1:] != after[2][t][1:]]
print("tables differing between upgrade 1 and 2:", d)
