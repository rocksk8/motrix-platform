# -*- coding: utf-8 -*-
"""U0a 回滾演練腳本（FRAMEWORK-ORG-UNITS-T57 §14.10；規格由 98 寫、本檔實作、5c 只負責執行）。

[單位] tools:u0a_rollback_drill    [層] 工具    [穩定度] 內部

用法（Python 一律用主工作樹 .venv312；在任一目錄）：
  python tools/platform/u0a_rollback_drill.py --db <MS1c 狀態的資料庫副本> --new-tree <含 U0a 的 repo 根> --old-tree <MS1c repo 根>
         [--work D:\\開發測試檔\\u0a-drill] [--expect-db-version 118] [--package <建好的包目錄>] [--json-out F] [--keep]
結束碼：0 全過；1 有 FAIL；2 工具本身出錯（路徑不對…）。**不修改 --db 指向的來源檔**（全程在 --work 底下的副本操作）。

流程（每一步印 PASS／FAIL 一行；全部通過才 exit 0）：
  P0 預檢        來源庫可讀、兩棵樹存在、--work 不在系統暫存；複製來源庫（含 -wal/-shm）成 before.db
  P1 基準快照    表／VIEW／索引／欄位（型別、NOT NULL、預設、主鍵）／每表列數／schema_version／module_schema_versions／各序列表內容／整庫健檢
  P2 升級        用 **新樹自己的啟動規則**（`tools/migrate_like_startup.py`：先載入模組 ⇒ `db.init_db`：V9 基準、core 與各模組 migration，含未取號的 U0a 與 permmatrix v2；
                 該工具不在的舊樹退回只跑 `db.init_db`）升級 before.db 的副本
  P3 計時        U0a 遷移本身單獨計時（--max-migration-sec，預設 5 秒）＋啟動式升級總耗時；配合放大庫（u0a_seed_synthetic --bulk）證明 ADD COLUMN 不隨列數成長
  P3 差異檢查    只准 ① 多出 U0a 的 5 張新表 ② 既有表多出 owner_unit_id／unit_id／legal_entity_id／scope_json（型別、NOT NULL、預設＝1 與清單一致）；
                 不得有表／欄／索引／VIEW 被刪或改；既有每表列數相同；每表「原有欄位」的內容雜湊相同；`vouchers` VIEW 與 `quote_seq` 的 SQL 逐字相同；
                 schema_version 仍是 --expect-db-version；其他模組的 module_schema_versions 不變；`core` 的版號報告（未取號＝不記，取號後 9→10）
  P4 序列等價    quote_seq／payslip_seq 內容相同；各單據號碼的現存最大值（傳票日流水、PS、CN、DN…的取最大值來源）相同 ⇒ 下一個號碼不變
  P4b 全新安裝同形  新樹在空庫上跑完所有 migration ⇒ 與 P2 升級後的副本比：表集合、每表欄位（不看順序）、索引、VIEW、觸發器完全相同（D3b）
  P5 舊程式回滾  分 core=9（未取號）與 core=10（模擬取號後：把 module_schema_versions.core 改成 10）兩種各做一次：用 **舊樹自己的啟動規則** 打開已升級的副本——
                 不得丟例外、`migrations.incomplete` 空、舊程式不得改動／降低任何版號、表欄位與升級後逐一相同、資料未變；
                 **舊樹的真實配號函式**（客戶碼、完工單號、傳票號、報價單號、薪資單號）的結果與升級前相同；
                 **舊式 INSERT（完全不帶新欄位）對每一張清單內的表真的寫入**（SAVEPOINT 內、最後 ROLLBACK），新欄位落在根單位（=1）
  P6 重新升級    把兩種回滾後的副本各再用新樹升級一次：與 P2 的結果相同（冪等；MS1c→U0a→回滾→U0a 的完整流程）
  P8 demo 重置   在升級後的副本上真的跑新樹的 `db.reset_demo_db()`：根單位與閉包被重種、業務表清空、新欄位與新表仍在
  P7 驗包（選）  給了 --package 才跑：新樹的 `backend/tools/verify_package.py <包> --expect-db-version N`，exit 0 才算過
所有報告寫到 --work/report.json（或 --json-out）。純函式 `snapshot`／`diff_upgrade`／`check_old_inserts` 有單元測試（tests/platform/test_u0a_rollback_drill.py），
含正對照：故意刪欄、改列數、漏新欄預設 ⇒ 差異檢查必須報 FAIL。
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NEW_TABLES = {"org_units", "org_unit_closure", "user_units", "system_settings_unit", "seq_by_entity"}
INTERNAL = ("owner_unit_id", "unit_id", "legal_entity_id", "scope_json")
#: 取最大值配號的來源（表, 欄）：升級前後最大值相同 ⇒ 下一個號碼不變
NUMBER_SOURCES = (("vouchers_all", "voucher_no"), ("payslips", "slip_no"), ("completion_notes", "note_no"), ("shipping_notes", "note_no"),
                  ("invoice_vouchers", "voucher_no"), ("payment_requests", "request_no"), ("contractor_payment_vouchers", "voucher_no"),
                  ("quotations", "quote_no"), ("customers", "code"), ("suppliers", "code"))
#: 授權帶範圍的欄位屬 permmatrix 自己的 migration v2（不在 core 清單裡）
PERM_SCOPE_TABLES = ("perm_role_caps", "perm_user_overrides")
SEQ_TABLES = ("quote_seq", "payslip_seq", "custom_record_counters")


# ── 快照（純讀）────────────────────────────────────────────────────────────────

def _q(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def snapshot(path, digest_cols=None):
    """資料庫 → dict。`digest_cols`＝{表: [欄]}：只對這些欄算內容雜湊（升級後用升級前的欄位清單，排除新增欄位）。"""
    conn = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True)
    try:
        out = {"tables": {}, "views": {}, "indexes": {}, "triggers": {}, "digests": {}, "seqs": {}, "numbers": {}, "msv": {}}
        for name, typ, sql, tbl in _q(conn, "SELECT name, type, sql, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"):
            if typ == "table":
                cols = [tuple(r[1:6]) for r in _q(conn, 'PRAGMA table_info("%s")' % name)]       # name,type,notnull,dflt,pk
                out["tables"][name] = {"cols": cols, "count": conn.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0], "sql": sql}
            elif typ == "view":
                out["views"][name] = sql
            elif typ == "index":
                out["indexes"][name] = (tbl, sql)
            elif typ == "trigger":
                out["triggers"][name] = sql
        names = list(out["tables"])
        for t, cols in (digest_cols or {}).items():
            if t in out["tables"]:
                use = [c for c in cols if c in {x[0] for x in out["tables"][t]["cols"]}]
                if use:
                    rows = sorted(repr(tuple(r)) for r in _q(conn, 'SELECT %s FROM "%s"' % (",".join('"%s"' % c for c in use), t)))
                    h = hashlib.sha256()
                    for r in rows:
                        h.update(r.encode("utf-8", "replace"))
                    out["digests"][t] = h.hexdigest()
        for t in SEQ_TABLES:
            if t in names:
                out["seqs"][t] = [tuple(r) for r in _q(conn, 'SELECT * FROM "%s" ORDER BY 1,2' % t)]
        for t, c in NUMBER_SOURCES:
            if t in names and c in {x[0] for x in out["tables"][t]["cols"]}:
                out["numbers"]["%s.%s" % (t, c)] = conn.execute('SELECT MAX("%s") FROM "%s"' % (c, t)).fetchone()[0]
        out["schema_version"] = conn.execute("SELECT version FROM schema_version").fetchone()[0] if "schema_version" in names else None
        if "module_schema_versions" in names:
            out["msv"] = {r[0]: r[1] for r in _q(conn, "SELECT module, version FROM module_schema_versions")}
        out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        out["fk_violations"] = len(_q(conn, "PRAGMA foreign_key_check"))
        return out
    finally:
        conn.close()


def old_cols(snap):
    return {t: [c[0] for c in v["cols"]] for t, v in snap["tables"].items()}


# ── 差異檢查（純函式；測試以合成快照驅動）──────────────────────────────────────────────

#: 這一包預期會前進的模組 migration 版號（模組 → 升級後的版號）；其餘模組不得動
EXPECTED_MODULE_BUMPS = {"permmatrix": 2}
#: 內容本來就會隨升級改變的表（版號與套用時間）：不比內容雜湊，版號另行檢查
DIGEST_EXEMPT = ("module_schema_versions",)


def diff_upgrade(before, after, lists, expect_version=118, bumps=None):
    """升級前後快照 → [(名稱, 通過?, 說明)]。`lists`＝{"owner":[…], "unit":[…], "legal":[…], "scope":[…]}（來自新樹的 U0A_*）。"""
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
    added_tables = set(after["tables"]) - set(before["tables"])
    removed_tables = set(before["tables"]) - set(after["tables"])
    chk("新增的表只有 U0a 的五張", added_tables <= NEW_TABLES and (NEW_TABLES - added_tables) <= set(before["tables"]),
        "多出：%s；缺少：%s" % (sorted(added_tables - NEW_TABLES), sorted(NEW_TABLES - added_tables - set(before["tables"]))))
    chk("沒有表被刪", not removed_tables, "被刪：%s" % sorted(removed_tables))
    expected = {}
    for key, col in (("owner", "owner_unit_id"), ("unit", "unit_id"), ("legal", "legal_entity_id"), ("scope", "scope_json")):
        for t in lists.get(key, ()):
            if t in before["tables"]:
                expected.setdefault(t, set()).add(col)
    bad_added, bad_removed, bad_def, missing = [], [], [], []
    for t, b in before["tables"].items():
        if t not in after["tables"]:
            continue
        bc, ac = {c[0]: c for c in b["cols"]}, {c[0]: c for c in after["tables"][t]["cols"]}
        for c in bc:
            if c not in ac:
                bad_removed.append("%s.%s" % (t, c))
            elif bc[c] != ac[c]:
                bad_def.append("%s.%s 定義被改：%r → %r" % (t, c, bc[c], ac[c]))
        new = set(ac) - set(bc)
        if new - expected.get(t, set()):
            bad_added.append("%s 多出非預期欄位 %s" % (t, sorted(new - expected.get(t, set()))))
        for c in expected.get(t, set()) - set(bc):
            if c not in ac:
                missing.append("%s.%s" % (t, c))
            else:
                col = ac[c]                                   # (name,type,notnull,dflt,pk)
                want_null = 0 if c == "scope_json" else 1
                if col[2] != want_null or (c != "scope_json" and str(col[3]) != "1") or col[4]:
                    bad_def.append("%s.%s 型態／預設不對：%r" % (t, c, col))
    chk("既有欄位沒有被刪", not bad_removed, "；".join(bad_removed))
    chk("既有欄位定義逐項相同", not [x for x in bad_def if "定義被改" in x], "；".join(x for x in bad_def if "定義被改" in x))
    chk("只多出清單上的新欄位", not bad_added, "；".join(bad_added))
    chk("清單上的欄位都已補上", not missing, "缺：%s" % missing)
    chk("新欄位 NOT NULL DEFAULT 1（scope_json 可為空）", not [x for x in bad_def if "型態" in x], "；".join(x for x in bad_def if "型態" in x))
    chk("既有每表列數相同", all(after["tables"][t]["count"] == b["count"] for t, b in before["tables"].items() if t in after["tables"]),
        "；".join("%s %d→%d" % (t, b["count"], after["tables"][t]["count"]) for t, b in before["tables"].items()
                  if t in after["tables"] and after["tables"][t]["count"] != b["count"]))
    bd = {t: h for t, h in before["digests"].items() if t not in DIGEST_EXEMPT}
    ad = {t: h for t, h in after["digests"].items() if t not in DIGEST_EXEMPT}
    chk("原有欄位的內容雜湊相同（排除新欄位）", bd == ad and bool(bd), "不同的表：%s" % sorted(t for t in bd if bd[t] != ad.get(t)))
    lost_idx = {k: v for k, v in before["indexes"].items() if after["indexes"].get(k) != v}
    chk("既有索引逐字相同", not lost_idx, "變動：%s" % sorted(lost_idx))
    chk("觸發器逐字相同", all(after["triggers"].get(k) == v for k, v in before["triggers"].items()))
    chk("VIEW 逐字相同（vouchers 不重建）", before["views"] == {k: after["views"].get(k) for k in before["views"]},
        "變動：%s" % sorted(k for k in before["views"] if before["views"][k] != after["views"].get(k)))
    qs = lambda s: (s["tables"].get("quote_seq") or {}).get("sql")            # noqa: E731
    chk("quote_seq 的 DDL 逐字相同", qs(before) == qs(after) and qs(before) is not None)
    chk("schema_version 不變", before["schema_version"] == after["schema_version"] == expect_version,
        "前 %r／後 %r／期待 %r" % (before["schema_version"], after["schema_version"], expect_version))
    bumps = EXPECTED_MODULE_BUMPS if bumps is None else bumps
    other = {m: v for m, v in before["msv"].items() if m != "core"}
    got = {m: v for m, v in after["msv"].items() if m != "core"}
    unexpected = sorted(m for m in set(other) | set(got) if other.get(m) != got.get(m) and not (m in bumps and got.get(m) == bumps[m]))
    chk("其他模組的 migration 版號不變（預期前進：%s）" % (bumps or "無"), not unexpected,
        "非預期的變動：%s" % {m: (other.get(m), got.get(m)) for m in unexpected})
    chk("序列表內容相同（下一個號碼不變）", before["seqs"] == after["seqs"])
    chk("各單據號碼的現存最大值相同", before["numbers"] == after["numbers"],
        "不同：%s" % sorted(k for k in before["numbers"] if before["numbers"][k] != after["numbers"].get(k)))
    chk("整庫健檢 ok、外鍵違規數沒有增加", after["integrity"] == "ok" and after["fk_violations"] <= before["fk_violations"],
        "%s／fk %s（升級前 %s；合成資料本身可能有違規，只要求不增加）" % (after["integrity"], after["fk_violations"], before["fk_violations"]))
    return res


def parity(fresh, upgraded):
    """全新安裝（新樹從空庫跑完所有 migration）與「升級後的正式庫副本」必須同形：表集合、每表欄位（名稱→型別／NOT NULL／預設／主鍵，不看順序）、索引（名稱與 SQL）、
    VIEW、觸發器。ADD COLUMN 會把欄位排在最後，所以欄位順序不比（SQLite 以名稱取值）。回 [(名稱, 通過?, 說明)]。"""
    res = []
    ft, ut = set(fresh["tables"]), set(upgraded["tables"])
    res.append(("全新安裝與升級庫的表集合相同", ft == ut, "只在全新：%s；只在升級庫：%s" % (sorted(ft - ut), sorted(ut - ft))))
    diff = []
    for t in sorted(ft & ut):
        fc, uc = {c[0]: c for c in fresh["tables"][t]["cols"]}, {c[0]: c for c in upgraded["tables"][t]["cols"]}
        if fc != uc:
            names = sorted(set(fc) ^ set(uc)) or sorted(c for c in fc if fc[c] != uc.get(c))
            diff.append("%s：%s" % (t, names))
    res.append(("每表欄位（名稱／型別／NOT NULL／預設／主鍵）相同", not diff, "；".join(diff[:12])))
    fi, ui = fresh["indexes"], upgraded["indexes"]
    res.append(("索引（名稱與 SQL）相同", fi == ui, "只在全新：%s；只在升級庫：%s；SQL 不同：%s" % (
        sorted(set(fi) - set(ui)), sorted(set(ui) - set(fi)), sorted(k for k in set(fi) & set(ui) if fi[k] != ui[k]))))
    res.append(("VIEW 相同", fresh["views"] == upgraded["views"], "不同：%s" % sorted(k for k in set(fresh["views"]) | set(upgraded["views"])
                                                                 if fresh["views"].get(k) != upgraded["views"].get(k))))
    res.append(("觸發器相同", fresh["triggers"] == upgraded["triggers"], ""))
    return res


def _seeder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_u0a_seed", Path(__file__).with_name("u0a_seed_synthetic.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def probe_old_style_inserts(path, tables):
    """舊程式式 INSERT（完全不帶新欄位）真的寫進每一張表，並確認新欄位落在根單位（owner_unit_id／unit_id／legal_entity_id＝1）；在 SAVEPOINT 內做、最後 ROLLBACK。
    與 `check_old_inserts` 不同：不靠複製既有列（會撞唯一鍵），而是依欄位定義組一列全新的值（表空著也能測）。回 [(表, 通過?, 說明)]。"""
    seeder = _seeder()
    out = []
    conn = sqlite3.connect(str(path))
    try:
        for t in tables:
            info = conn.execute('PRAGMA table_info("%s")' % t).fetchall()
            if not info:
                out.append((t, False, "表不存在"))
                continue
            names = [r[1] for r in info]
            cols, vals = seeder.build_row(info, t, 987654)
            conn.execute("SAVEPOINT p")
            try:
                if cols:
                    cur = conn.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (t, ",".join(cols), ",".join("?" * len(cols))), vals)
                else:
                    cur = conn.execute('INSERT INTO "%s" DEFAULT VALUES' % t)
                want = [c for c in ("owner_unit_id", "unit_id", "legal_entity_id") if c in names]
                row = conn.execute('SELECT %s FROM "%s" WHERE rowid=?' % (",".join(want), t), (cur.lastrowid,)).fetchone()
                bad = [c for c, v in zip(want, row) if v != 1]
                out.append((t, not bad and bool(want), ("真的寫入，%s 皆為 1" % "／".join(want)) if not bad else "欄位不是根單位：%s" % bad))
            except sqlite3.Error as e:
                out.append((t, False, "舊式 INSERT 被擋：%s: %s" % (type(e).__name__, e)))
            finally:
                conn.execute("ROLLBACK TO p")
                conn.execute("RELEASE p")
    finally:
        conn.close()
    return out


def check_old_inserts(path, tables):
    """舊程式的 INSERT 不帶新欄位：逐表 `INSERT … SELECT`（只含原有欄位）在 SAVEPOINT 內試，撞唯一鍵可接受，但不得是新欄位的 NOT NULL 錯誤。回 [(表, 通過?, 說明)]。"""
    out = []
    conn = sqlite3.connect(str(path))
    try:
        for t in tables:
            try:
                cols = [r[1] for r in conn.execute('PRAGMA table_info("%s")' % t)]
            except sqlite3.Error:
                continue
            if not cols:
                continue
            old = [c for c in cols if c not in INTERNAL and c != "id"]
            if not old or conn.execute('SELECT 1 FROM "%s" LIMIT 1' % t).fetchone() is None:
                continue
            col_sql = ",".join('"%s"' % c for c in old)
            conn.execute("SAVEPOINT s")
            try:
                conn.execute('INSERT INTO "%s" (%s) SELECT %s FROM "%s" LIMIT 1' % (t, col_sql, col_sql, t))
                out.append((t, True, "ok"))
            except sqlite3.IntegrityError as e:
                msg = str(e)
                bad = any(c in msg for c in INTERNAL)
                out.append((t, not bad, "撞約束（可接受）：%s" % msg if not bad else "新欄位拒絕了舊式 INSERT：%s" % msg))
            except sqlite3.Error as e:
                out.append((t, False, "%s: %s" % (type(e).__name__, e)))
            finally:
                conn.execute("ROLLBACK TO s")
                conn.execute("RELEASE s")
    finally:
        conn.close()
    return out


# ── 子行程：用某一棵樹自己的程式升級／讀清單 ─────────────────────────────────────────────

_UPGRADE = r"""
import importlib.util, json, os, sys
tree, path = sys.argv[1], sys.argv[2]
license_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
import db
from core import migrations
problems = []
tool = os.path.join(tree, "backend", "tools", "migrate_like_startup.py")
if os.path.isfile(tool) and os.path.isfile(os.path.join(tree, "backend", "helpers", "module_startup.py")):
    # 照服務啟動的規則：先載入模組（含各模組自己的 migration）、再 init_db（含 core 與模組 migration）
    spec = importlib.util.spec_from_file_location("_mls", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    problems = list(mod.run([path], license_path))
else:
    db.init_db(path)
inc = migrations.incomplete(path)
print("@@" + json.dumps({"incomplete": {k: list(v) for k, v in (inc or {}).items()}, "problems": problems,
                         "pending": len(getattr(migrations, "_PENDING", []))}))
"""
_LISTS = r"""
import json, os, sys
tree = sys.argv[1]
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
from core import migrations as M
print("@@" + json.dumps({"owner": list(getattr(M, "U0A_OWNER_UNIT_TABLES", ())), "unit": list(getattr(M, "U0A_UNIT_ID_TABLES", ())),
                         "legal": list(getattr(M, "U0A_LEGAL_ENTITY_TABLES", ())), "scope": list(getattr(M, "U0A_SCOPE_JSON_TABLES", ()))}))
"""


_ALLOC = r"""
import json, os, sqlite3, sys
tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
out = {}
conn = sqlite3.connect(path)
conn.row_factory = sqlite3.Row
def attempt(name, fn):
    try:
        out[name] = fn()
    except Exception as e:
        out[name] = "ERROR %s: %s" % (type(e).__name__, e)
import db
attempt("entity_code_customers", lambda: db.next_entity_code(conn, "customers", "C"))
attempt("entity_code_completion", lambda: db.next_entity_code(conn, "completion_notes", "CN", code_col="note_no"))
def v():
    from modules.accounting import voucher
    return voucher.next_voucher_no(conn, "2026-10-14")
attempt("voucher_no", v)
def q():
    from modules.case.api import quotations
    return quotations._peek_next_no(conn, "202610")
attempt("quote_no", q)
def p():
    from modules.payroll.api import payslips
    return payslips._peek_next_slip_no(conn, "202610")
attempt("slip_no", p)
print("@@" + json.dumps(out, ensure_ascii=False))
"""
_U0A_ONLY = r"""
import json, os, sqlite3, sys, time
tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
from core import migrations as M
conn = sqlite3.connect(path)
t0 = time.perf_counter()
res = M._core_next_org_units(conn)
dt = time.perf_counter() - t0
print("@@" + json.dumps({"seconds": dt, "result": res}))
"""
_DEMO_RESET = r"""
import json, os, sys, time
tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
import db
db.DEMO_DB_PATH = path
t0 = time.perf_counter()
db.reset_demo_db()
print("@@" + json.dumps({"seconds": time.perf_counter() - t0}))
"""


def _run(code, tree, path=None, timeout=900, license_path=None):
    args = [sys.executable, "-c", code, str(tree)] + ([str(path)] if path else []) + ([str(license_path)] if (path and license_path) else [])
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    payload = None
    for line in (p.stdout or "").splitlines():
        if line.startswith("@@"):
            payload = json.loads(line[2:])
    return p.returncode, payload, (p.stderr or "")[-1500:]


# ── 主流程 ────────────────────────────────────────────────────────────────────

class Report:
    def __init__(self):
        self.rows = []

    def add(self, phase, name, ok, detail=""):
        self.rows.append({"phase": phase, "name": name, "ok": bool(ok), "detail": detail})
        print("%s  [%s] %s%s" % ("PASS" if ok else "FAIL", phase, name, ("  —  " + detail) if (detail and not ok) else ""))

    @property
    def ok(self):
        return all(r["ok"] for r in self.rows)


def _copy_db(src, dst):
    shutil.copyfile(src, dst)
    for ext in ("-wal", "-shm"):
        if Path(str(src) + ext).exists():
            shutil.copyfile(str(src) + ext, str(dst) + ext)


def main(argv=None):
    ap = argparse.ArgumentParser(description="U0a 回滾演練")
    ap.add_argument("--db", required=True)
    ap.add_argument("--new-tree", required=True)
    ap.add_argument("--old-tree", required=True)
    ap.add_argument("--work", default=None)
    ap.add_argument("--expect-db-version", type=int, default=118)
    ap.add_argument("--package", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--license", default=None, help="授權金鑰檔（照啟動規則載入模組用；省略 ⇒ 預設位置）")
    ap.add_argument("--max-migration-sec", type=float, default=5.0, help="U0a 遷移本身（單獨計時）的上限秒數；ADD COLUMN 不隨列數成長")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--allow-temp-work", action="store_true", help="測試用：允許 --work 在系統暫存下")
    a = ap.parse_args(argv)
    rep = Report()
    db, new_tree, old_tree = Path(a.db), Path(a.new_tree), Path(a.old_tree)
    for label, p in (("--db", db), ("--new-tree", new_tree / "backend" / "db.py"), ("--old-tree", old_tree / "backend" / "db.py")):
        if not Path(p).exists():
            print("ERROR: %s 不存在：%s" % (label, p))
            return 2
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="u0a-drill-", dir="D:/開發測試檔" if os.path.isdir("D:/開發測試檔") else None))
    work.mkdir(parents=True, exist_ok=True)
    if not a.allow_temp_work and str(work.resolve()).lower().startswith(os.path.normcase(tempfile.gettempdir()).lower()):
        rep.add("P0", "--work 不在系統暫存（下載與暫存以 D 槽為主）", False, str(work))
    before, upgraded, rolled, again = (work / n for n in ("before.db", "upgraded.db", "rolled_back.db", "reupgraded.db"))
    _copy_db(db, before)
    rep.add("P0", "來源庫已複製（來源檔不動）", before.exists() and before.stat().st_size > 0)

    snap0 = snapshot(before)
    rep.add("P1", "基準快照（表 %d／VIEW %d）" % (len(snap0["tables"]), len(snap0["views"])), snap0["integrity"] == "ok" and bool(snap0["tables"]),
            "健檢：%s" % snap0["integrity"])
    rep.add("P1", "基準庫的 schema_version＝%d" % a.expect_db_version, snap0["schema_version"] == a.expect_db_version, "實際 %r" % snap0["schema_version"])
    digest_cols = old_cols(snap0)
    snap0 = snapshot(before, digest_cols)

    rc, lists, err = _run(_LISTS, new_tree)
    rep.add("P2", "讀得到新樹的 U0A 清單", rc == 0 and bool(lists and lists["owner"]), err)
    lists = dict(lists or {})
    lists["scope"] = list(PERM_SCOPE_TABLES)
    _copy_db(before, upgraded)
    t0 = time.perf_counter()
    rc, info, err = _run(_UPGRADE, new_tree, upgraded, license_path=a.license)
    startup_sec = time.perf_counter() - t0
    rep.add("P2", "新樹 init_db 升級成功（未丟例外）", rc == 0 and info is not None, err)
    rep.add("P2", "啟動式升級總耗時 %.1f 秒（含載入模組、V9 基準檢查、所有 migration）" % startup_sec, True)
    rep.add("P2", "沒有未完成的 migration、模組都載入", bool(info) and not info["incomplete"] and not info.get("problems"),
            json.dumps({"incomplete": (info or {}).get("incomplete"), "problems": (info or {}).get("problems")}, ensure_ascii=False))
    snap1 = snapshot(upgraded, digest_cols)
    for name, ok, detail in diff_upgrade(snap0, snap1, lists, a.expect_db_version):
        rep.add("P3/P4", name, ok, detail)
    rep.add("P3", "core 版號報告（未取號＝不記；取號後 9→10）：前 %r 後 %r（未取號 migration %s 支）" % (
        snap0["msv"].get("core"), snap1["msv"].get("core"), (info or {}).get("pending")),
        snap1["msv"].get("core") in (snap0["msv"].get("core"), (snap0["msv"].get("core") or 0) + 1))

    timing_db = work / "timing.db"
    _copy_db(before, timing_db)
    rc, tinfo, err = _run(_U0A_ONLY, new_tree, timing_db)
    big = sorted(((v["count"], t) for t, v in snap0["tables"].items()), reverse=True)[:3]
    total_rows = sum(v["count"] for v in snap0["tables"].values())
    rep.add("P3", "U0a 遷移本身單獨耗時 %.3f 秒（庫內共 %d 列；最大表 %s；上限 %.1f 秒）" % (
        (tinfo or {}).get("seconds", -1), total_rows, big, a.max_migration_sec),
        rc == 0 and tinfo is not None and tinfo.get("result") is None and tinfo["seconds"] <= a.max_migration_sec, err or str(tinfo))

    fresh = work / "fresh.db"
    for ext in ("", "-wal", "-shm"):
        try:
            Path(str(fresh) + ext).unlink()
        except OSError:
            pass
    rc, infof, err = _run(_UPGRADE, new_tree, fresh, license_path=a.license)
    rep.add("P4b", "新樹在空庫上建出全新安裝（D3b 同形檢查的對照）", rc == 0 and infof is not None and not infof["incomplete"], err)
    for name, ok, detail in parity(snapshot(fresh), snap1):
        rep.add("P4b", name, ok, detail)

    # D7：舊樹的真實配號函式在「升級前」的庫上先跑一次當基準
    base_alloc_db = work / "alloc_base.db"
    _copy_db(before, base_alloc_db)
    rc, base_alloc, err = _run(_ALLOC, old_tree, base_alloc_db)
    rep.add("P5", "舊樹配號函式在升級前的庫上可執行（基準）：%s" % json.dumps(base_alloc, ensure_ascii=False),
            rc == 0 and base_alloc is not None and not any(str(v).startswith("ERROR") for v in (base_alloc or {}).values()), err or "")

    def rollback_variant(label, core_version):
        db_ = work / ("rolled_back_%s.db" % label)
        _copy_db(upgraded, db_)
        if core_version is not None:                                   # 模擬『取號後 core=10』：領先舊程式所知的版號
            c = sqlite3.connect(str(db_))
            c.execute("UPDATE module_schema_versions SET version=? WHERE module='core'", (core_version,))
            c.commit()
            c.close()
        expect_msv = dict(snap1["msv"])
        if core_version is not None:
            expect_msv["core"] = core_version
        rc_, i2, e2 = _run(_UPGRADE, old_tree, db_, license_path=a.license)
        tag = "core=%s" % (core_version if core_version is not None else snap1["msv"].get("core"))
        rep.add("P5", "[%s] 舊樹啟動規則打開已升級的庫：不丟例外" % tag, rc_ == 0 and i2 is not None, e2)
        rep.add("P5", "[%s] 舊樹 migrations.incomplete 為空、模組都載入" % tag, bool(i2) and not i2["incomplete"] and not i2.get("problems"),
                json.dumps({"incomplete": (i2 or {}).get("incomplete"), "problems": (i2 or {}).get("problems")}, ensure_ascii=False))
        sn = snapshot(db_, digest_cols)
        rep.add("P5", "[%s] 舊程式沒有改動／降低任何 migration 版號" % tag, sn["msv"] == expect_msv, "預期 %r／實際 %r" % (expect_msv, sn["msv"]))
        rep.add("P5", "[%s] 回滾後表欄位與升級後逐一相同（舊程式不刪新欄位）" % tag,
                {t: v["cols"] for t, v in sn["tables"].items()} == {t: v["cols"] for t, v in snap1["tables"].items()})
        rep.add("P5", "[%s] 回滾後資料未變（列數、內容雜湊）" % tag, {k: v for k, v in sn["digests"].items() if k not in DIGEST_EXEMPT} ==
                {k: v for k, v in snap1["digests"].items() if k not in DIGEST_EXEMPT} and
                {t: v["count"] for t, v in sn["tables"].items()} == {t: v["count"] for t, v in snap1["tables"].items()})
        rcA, alloc, eA = _run(_ALLOC, old_tree, db_)
        rep.add("P5", "[%s] 舊樹真實配號函式（客戶碼、完工單號、傳票號、報價單號、薪資單號）與升級前相同" % tag,
                rcA == 0 and alloc == base_alloc and not any(str(v).startswith("ERROR") for v in (alloc or {}).values()),
                "升級前 %r／回滾後 %r %s" % (base_alloc, alloc, eA))
        probes = probe_old_style_inserts(db_, list(lists.get("owner", [])) + list(lists.get("unit", [])))
        bad = [(t, d) for t, ok, d in probes if not ok]
        rep.add("P5", "[%s] 舊式 INSERT（完全不帶新欄位）逐表真的寫入，新欄位落在根單位：%d／%d 張" % (tag, len(probes) - len(bad), len(probes)),
                not bad and len(probes) >= 38, "；".join("%s：%s" % b for b in bad[:8]))
        return db_

    rolled = rollback_variant("c9", None)
    rolled10 = rollback_variant("c10", 10)

    for label, src_ in (("c9", rolled), ("c10", rolled10)):
        again_ = work / ("reupgraded_%s.db" % label)
        _copy_db(src_, again_)
        rc, info3, err = _run(_UPGRADE, new_tree, again_, license_path=a.license)
        rep.add("P6", "[%s] 回滾後再升級成功" % label, rc == 0 and info3 is not None and not info3["incomplete"], err)
        snap3 = snapshot(again_, digest_cols)
        rep.add("P6", "[%s] 再升級結果與第一次升級相同（冪等）" % label, {t: v["cols"] for t, v in snap3["tables"].items()} == {t: v["cols"] for t, v in snap1["tables"].items()}
                and {k: v for k, v in snap3["digests"].items() if k not in DIGEST_EXEMPT} == {k: v for k, v in snap1["digests"].items() if k not in DIGEST_EXEMPT}
                and snap3["seqs"] == snap1["seqs"])
    again = work / "reupgraded_c9.db"

    # P8 展示庫重置（真的跑 db.reset_demo_db）：清單內的表被清空、根單位與閉包由 init_db 重種、欄位與新表完好
    demo = work / "demo_reset.db"
    _copy_db(upgraded, demo)
    t0 = time.perf_counter()
    rc, dinfo, err = _run(_DEMO_RESET, new_tree, demo)
    rep.add("P8", "demo 重置（新樹 db.reset_demo_db）成功，耗時 %.1f 秒" % (time.perf_counter() - t0), rc == 0 and dinfo is not None, err)
    sd = snapshot(demo)
    conn = sqlite3.connect("file:%s?mode=ro" % demo.as_posix(), uri=True)
    try:
        root = conn.execute("SELECT id, parent_id, is_legal_entity FROM org_units").fetchall()
        clos = conn.execute("SELECT ancestor_id, descendant_id, depth FROM org_unit_closure").fetchall()
        n_q = conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] if "quotations" in sd["tables"] else 0
        n_seq = conn.execute("SELECT COUNT(*) FROM seq_by_entity").fetchone()[0]
    finally:
        conn.close()
    rep.add("P8", "重置後根單位與閉包被重種（id=1、法人、(1,1,0)）", [tuple(r) for r in root] == [(1, None, 1)] and [tuple(r) for r in clos] == [(1, 1, 0)], "%r %r" % (root, clos))
    rep.add("P8", "重置後業務表已清空、seq_by_entity 空", n_q == 0 and n_seq == 0, "quotations=%s seq_by_entity=%s" % (n_q, n_seq))
    missing = [t for t in lists.get("owner", []) if t in sd["tables"] and "owner_unit_id" not in [c[0] for c in sd["tables"][t]["cols"]]]
    rep.add("P8", "重置後新欄位仍在、新表仍在", not missing and NEW_TABLES <= set(sd["tables"]), "缺：%s" % missing)

    if a.package:
        vp = new_tree / "backend" / "tools" / "verify_package.py"
        p = subprocess.run([sys.executable, str(vp), str(a.package), "--expect-db-version", str(a.expect_db_version)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        rep.add("P7", "verify_package --expect-db-version %d" % a.expect_db_version, p.returncode == 0, (p.stdout or "")[-800:])

    out = Path(a.json_out) if a.json_out else work / "report.json"
    out.write_text(json.dumps({"ok": rep.ok, "rows": rep.rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n演練結果：%s（%d 項，FAIL %d）；報告 %s" % ("全過" if rep.ok else "有紅", len(rep.rows), sum(1 for r in rep.rows if not r["ok"]), out))
    if not a.keep and rep.ok:
        for f in (upgraded, rolled, rolled10, again):
            for ext in ("", "-wal", "-shm"):
                try:
                    Path(str(f) + ext).unlink()
                except OSError:
                    pass
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
