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
  P2 升級        用 **新樹自己的 `db.init_db(path)`**（＝啟動路徑：V9 基準 migration ＋ core 模組 migration，含未取號的 U0a）升級 before.db 的副本
  P3 差異檢查    只准 ① 多出 U0a 的 5 張新表 ② 既有表多出 owner_unit_id／unit_id／legal_entity_id／scope_json（型別、NOT NULL、預設＝1 與清單一致）；
                 不得有表／欄／索引／VIEW 被刪或改；既有每表列數相同；每表「原有欄位」的內容雜湊相同；`vouchers` VIEW 與 `quote_seq` 的 SQL 逐字相同；
                 schema_version 仍是 --expect-db-version；其他模組的 module_schema_versions 不變；`core` 的版號報告（未取號＝不記，取號後 9→10）
  P4 序列等價    quote_seq／payslip_seq 內容相同；各單據號碼的現存最大值（傳票日流水、PS、CN、DN…的取最大值來源）相同 ⇒ 下一個號碼不變
  P4b 全新安裝同形  新樹在空庫上跑完所有 migration ⇒ 與 P2 升級後的副本比：表集合、每表欄位（不看順序）、索引、VIEW、觸發器完全相同（D3b）
  P5 舊程式回滾  用 **舊樹自己的 `db.init_db(path)`** 打開已升級的副本（`module_schema_versions.core` 領先舊程式所知的版號）：不得丟例外、
                 `migrations.incomplete` 空、舊程式不得改動／降低任何版號、表欄位與升級後逐一相同；再以「舊程式的 INSERT 不帶新欄位」模擬寫入
                 （逐表 INSERT … SELECT 既有列，容許撞唯一鍵，但不得出現新欄位的 NOT NULL 錯誤）
  P6 重新升級    把回滾後的副本再用新樹升級一次：與 P2 的結果相同（冪等；MS1c→U0a→回滾→U0a 的完整流程）
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
from pathlib import Path

NEW_TABLES = {"org_units", "org_unit_closure", "user_units", "system_settings_unit", "seq_by_entity"}
INTERNAL = ("owner_unit_id", "unit_id", "legal_entity_id", "scope_json")
#: 取最大值配號的來源（表, 欄）：升級前後最大值相同 ⇒ 下一個號碼不變
NUMBER_SOURCES = (("vouchers_all", "voucher_no"), ("payslips", "slip_no"), ("completion_notes", "note_no"), ("shipping_notes", "note_no"),
                  ("invoice_vouchers", "voucher_no"), ("payment_requests", "request_no"), ("contractor_payment_vouchers", "voucher_no"),
                  ("quotations", "quote_no"), ("customers", "code"), ("suppliers", "code"))
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

def diff_upgrade(before, after, lists, expect_version=118):
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
    chk("原有欄位的內容雜湊相同（排除新欄位）", before["digests"] == after["digests"] and bool(before["digests"]),
        "不同的表：%s" % sorted(t for t in before["digests"] if before["digests"][t] != after["digests"].get(t)))
    lost_idx = {k: v for k, v in before["indexes"].items() if after["indexes"].get(k) != v}
    chk("既有索引逐字相同", not lost_idx, "變動：%s" % sorted(lost_idx))
    chk("觸發器逐字相同", all(after["triggers"].get(k) == v for k, v in before["triggers"].items()))
    chk("VIEW 逐字相同（vouchers 不重建）", before["views"] == {k: after["views"].get(k) for k in before["views"]},
        "變動：%s" % sorted(k for k in before["views"] if before["views"][k] != after["views"].get(k)))
    qs = lambda s: (s["tables"].get("quote_seq") or {}).get("sql")            # noqa: E731
    chk("quote_seq 的 DDL 逐字相同", qs(before) == qs(after) and qs(before) is not None)
    chk("schema_version 不變", before["schema_version"] == after["schema_version"] == expect_version,
        "前 %r／後 %r／期待 %r" % (before["schema_version"], after["schema_version"], expect_version))
    other = {m: v for m, v in before["msv"].items() if m != "core"}
    chk("其他模組的 migration 版號不變", other == {m: v for m, v in after["msv"].items() if m != "core"})
    chk("序列表內容相同（下一個號碼不變）", before["seqs"] == after["seqs"])
    chk("各單據號碼的現存最大值相同", before["numbers"] == after["numbers"],
        "不同：%s" % sorted(k for k in before["numbers"] if before["numbers"][k] != after["numbers"].get(k)))
    chk("整庫健檢 ok、外鍵無違規", after["integrity"] == "ok" and after["fk_violations"] == 0, "%s／fk %s" % (after["integrity"], after["fk_violations"]))
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
    res.append(("觸發器相同", fresh["triggers"] == upgraded["triggers"]))
    return res


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
import json, os, sys
tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, "backend"))
os.chdir(os.path.join(tree, "backend"))
import db
from core import migrations
db.init_db(path)
inc = migrations.incomplete(path)
print("@@" + json.dumps({"incomplete": {k: list(v) for k, v in (inc or {}).items()}, "pending": len(getattr(migrations, "_PENDING", []))}))
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


def _run(code, tree, path=None, timeout=900):
    args = [sys.executable, "-c", code, str(tree)] + ([str(path)] if path else [])
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
    lists = lists or {}
    _copy_db(before, upgraded)
    rc, info, err = _run(_UPGRADE, new_tree, upgraded)
    rep.add("P2", "新樹 init_db 升級成功（未丟例外）", rc == 0 and info is not None, err)
    rep.add("P2", "沒有未完成的 migration", bool(info) and not info["incomplete"], json.dumps((info or {}).get("incomplete")))
    snap1 = snapshot(upgraded, digest_cols)
    for name, ok, detail in diff_upgrade(snap0, snap1, lists, a.expect_db_version):
        rep.add("P3/P4", name, ok, detail)
    rep.add("P3", "core 版號報告（未取號＝不記；取號後 9→10）：前 %r 後 %r（未取號 migration %s 支）" % (
        snap0["msv"].get("core"), snap1["msv"].get("core"), (info or {}).get("pending")),
        snap1["msv"].get("core") in (snap0["msv"].get("core"), (snap0["msv"].get("core") or 0) + 1))

    fresh = work / "fresh.db"
    for ext in ("", "-wal", "-shm"):
        try:
            Path(str(fresh) + ext).unlink()
        except OSError:
            pass
    rc, infof, err = _run(_UPGRADE, new_tree, fresh)
    rep.add("P4b", "新樹在空庫上建出全新安裝（D3b 同形檢查的對照）", rc == 0 and infof is not None and not infof["incomplete"], err)
    for name, ok, detail in parity(snapshot(fresh), snap1):
        rep.add("P4b", name, ok, detail)

    _copy_db(upgraded, rolled)
    rc, info2, err = _run(_UPGRADE, old_tree, rolled)
    rep.add("P5", "舊樹 init_db 打開已升級的庫：不丟例外（core 版號領先舊程式所知）", rc == 0 and info2 is not None, err)
    rep.add("P5", "舊樹 migrations.incomplete 為空", bool(info2) and not info2["incomplete"], json.dumps((info2 or {}).get("incomplete")))
    snap2 = snapshot(rolled, digest_cols)
    rep.add("P5", "舊程式沒有改動／降低任何 migration 版號", snap2["msv"] == snap1["msv"], "升級後 %r／回滾後 %r" % (snap1["msv"], snap2["msv"]))
    rep.add("P5", "回滾後表欄位與升級後逐一相同（舊程式不刪新欄位）", {t: v["cols"] for t, v in snap2["tables"].items()} == {t: v["cols"] for t, v in snap1["tables"].items()})
    rep.add("P5", "回滾後資料未變（列數、內容雜湊）", snap2["digests"] == snap1["digests"] and
            {t: v["count"] for t, v in snap2["tables"].items()} == {t: v["count"] for t, v in snap1["tables"].items()})
    for t, ok, detail in check_old_inserts(rolled, list(lists.get("owner", [])) + list(lists.get("unit", []))):
        rep.add("P5", "舊式 INSERT（不帶新欄位）：%s" % t, ok, detail)

    _copy_db(rolled, again)
    rc, info3, err = _run(_UPGRADE, new_tree, again)
    rep.add("P6", "回滾後再升級成功", rc == 0 and info3 is not None and not info3["incomplete"], err)
    snap3 = snapshot(again, digest_cols)
    rep.add("P6", "再升級結果與第一次升級相同（冪等）", {t: v["cols"] for t, v in snap3["tables"].items()} == {t: v["cols"] for t, v in snap1["tables"].items()}
            and snap3["digests"] == snap1["digests"] and snap3["seqs"] == snap1["seqs"])

    if a.package:
        vp = new_tree / "backend" / "tools" / "verify_package.py"
        p = subprocess.run([sys.executable, str(vp), str(a.package), "--expect-db-version", str(a.expect_db_version)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
        rep.add("P7", "verify_package --expect-db-version %d" % a.expect_db_version, p.returncode == 0, (p.stdout or "")[-800:])

    out = Path(a.json_out) if a.json_out else work / "report.json"
    out.write_text(json.dumps({"ok": rep.ok, "rows": rep.rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n演練結果：%s（%d 項，FAIL %d）；報告 %s" % ("全過" if rep.ok else "有紅", len(rep.rows), sum(1 for r in rep.rows if not r["ok"]), out))
    if not a.keep and rep.ok:
        for f in (upgraded, rolled, again):
            for ext in ("", "-wal", "-shm"):
                try:
                    Path(str(f) + ext).unlink()
                except OSError:
                    pass
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
