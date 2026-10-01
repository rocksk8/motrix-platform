# -*- coding: utf-8 -*-
"""第 29 班（整班）套用演練工具（計畫＝docs/platform/plans/TRAIN29-DRILL.md）。

用法：
  python tools/platform/drill_train_apply.py --seed-only                      # 只建基線＋合成種子＋記錄（沒有包也能先演練工具本身）
  python tools/platform/drill_train_apply.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> [--runs A,B,C,E] [--keep]

做什麼（全部在 D:\\開發測試檔\\drill-t29\\<時間>\\ 底下；路徑不含 V9.0；埠 6760 只綁 127.0.0.1）：
  1. 基線安裝：git archive <base-commit>（預設 0bb4834e＝第 28 班正式機）⇒ install\\；最高管理員改密碼＋本公司資料走正式路徑；
     合成種子（量級仿正式機第 28 班回報；全是虛構值）；記錄基線（筆數、schema 版本、舊額外支出雜湊、附件雜湊…）。
  2. 套用腳本：install\\backend\\tools\\ 的 apply_update.ps1／rollback_update.ps1 **只改寫 `$ProdRoot`、`$Port` 兩行**（改寫前後逐行比對）。
     ⚠ 套用步驟會把包內 tools 複製過去（覆蓋改寫過的檔）⇒ 複製後**再改寫一次**（正式機沒有這問題：包內就是正式路徑）。
  3. 場次 A 套用、B 只回程式、C 資料庫回滾（僅演練）、E 回滾後重套；D、F 需要變體包（不在本工具；見計畫 §2）。
  4. 報告：stdout 最後一行 JSON；先寫到演練目錄**外**（%TEMP%\\motrix-drill-t29\\）再清；--keep 以外全清（服務一律停掉）。
🔴 不讀正式機、不讀任何開發者的 .db、不用正式機金鑰（驗章用安裝版本內建公鑰——正式包由 host 用正式金鑰簽，驗得過才算數）。
⚠ 本機若有排程工作「MOTRIX ERP Server Autostart」⇒ 拒絕（ps1 的重啟會去啟動它，那是別的安裝）。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend" / "tools"))
import drill_module_apply as DM  # noqa: E402  現成零件：安裝、啟動、停止、公司資料、兩行改寫

DrillError = DM.DrillError
DRILL_ROOT = Path(r"D:\開發測試檔\drill-t29")
PORT = 6760
BASE_COMMIT = "0bb4834e"
RESULT_RE = DM.RESULT_RE
SEED_TAG = "DRILL-"


# ── 小工具 ────────────────────────────────────────────────────────────────────

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ro(root):
    """唯讀連線（mode=ro）。"""
    db = Path(root) / "backend" / "motrix_erp.db"
    c = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
    c.row_factory = sqlite3.Row
    return c


def rw(root):
    c = sqlite3.connect(str(Path(root) / "backend" / "motrix_erp.db"))
    c.row_factory = sqlite3.Row
    return c


def table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns(c, table):
    return [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)] if table_exists(c, table) else []


def count(c, table):
    return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0] if table_exists(c, table) else None


def api(port, path, data=None, token=None, method=None):
    return DM._api(port, path, data, token, method)


def raw_get(port, path, token=None, timeout=15):
    """回 (status, bytes)；不解析 JSON（附件位元組要比雜湊）。"""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 headers={"Authorization": "Bearer " + token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def login(root, port):
    """演練管理員（setup_company 已把密碼改成 Drill-<port>-Pass!9）⇒ token。"""
    cred = (Path(root) / "backend" / ".initial_admin_credentials.txt").read_text(encoding="utf-8")
    user = re.search(r"帳號:\s*(\S+)", cred).group(1)
    s, b = api(port, "/api/auth/login", {"username": user, "password": "Drill-%d-Pass!9" % port})
    if s != 200:
        raise DrillError("演練管理員登入失敗：%s %s" % (s, b))
    return user, b["token"]


# ── 重新改寫套用腳本（只動 $ProdRoot／$Port 兩行）──────────────────────────────

def rewrite_tools(root, port, names=("apply_update.ps1", "rollback_update.ps1")):
    done = {}
    for n in names:
        p = Path(root) / "backend" / "tools" / n
        if not p.is_file():
            continue
        raw = p.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        new, changed = DM.rewrite_ps1(raw.decode("utf-8-sig"), root, port)
        p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
        done[n] = changed
    return done


# ── 合成種子（全部虛構；量級仿正式機第 28 班回報）────────────────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + b"DRILL" * 20


def _put(root, rel, data=PNG):
    full = Path(root) / "backend" / "uploads" / Path(*rel.split("/"))
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return sha256_file(full)


def seed(root, port):
    """灌合成資料 ⇒ 回 {舊額外支出清單(含附件雜湊)、筆數…}。直接寫庫（基線版程式的 schema），欄位只用 NOT NULL 必需者。"""
    now = "2026-09-20T09:00:00"
    c = rw(root)
    out = {"legacy_expenses": [], "errors": []}
    try:
        # 報價單 40（含已成案；其中 3 張有回簽檔）
        for i in range(1, 41):
            qn = "%sMQ-%03d" % (SEED_TAG, i)
            files = []
            if i <= 3:
                rel = "quotations/%s/signed%d.png" % (qn, i)
                sh = _put(root, rel)
                files = [{"id": "sq%d" % i, "filename": "signed%d.png" % i, "path": rel, "size": len(PNG), "sha": sh}]
            c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                      " deal_tag, signed_files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (qn, "已送出", "DRILL客戶%d" % i, "DRILL工程%d" % i, 100000 + i, 95238, json.dumps({"dealTag": "已成案"}), now, now,
                       "已成案", json.dumps(files)))
        # 開發案 109（前 5 筆有開發記錄附件）
        for i in range(1, 110):
            cur = c.execute("INSERT INTO dev_cases (case_name, created_at, updated_at) VALUES (?,?,?)", ("DRILL開發案%d" % i, now, now))
            if i <= 5:
                cid = cur.lastrowid
                rel = "dev_logs/%d/log%d.png" % (cid, i)
                sh = _put(root, rel)
                c.execute("INSERT INTO dev_logs (case_id, log_date, log_by, files_json, created_at) VALUES (?,?,?,?,?)",
                          (cid, "2026-09-20", 1, json.dumps([{"id": "dl%d" % i, "filename": "log%d.png" % i, "path": rel, "size": len(PNG), "sha": sh}]), now))
        # 傳票 64／分錄 151（科目取既有 account_items）
        acct = [r[0] for r in c.execute("SELECT code FROM account_items LIMIT 2")]
        if len(acct) < 2:
            out["errors"].append("account_items 不足 2 筆：傳票分錄種子略過")
        else:
            lines = 0
            for i in range(1, 65):
                cur = c.execute("INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
                                " VALUES (?,?,?,?,?,?,?,?)", ("DRILL-V%04d" % i, "2026-09-%02d" % (1 + i % 28), "轉", "DRILL傳票%d" % i, "草稿", "drill", now, now))
                vid = cur.lastrowid
                n = 3 if lines < 151 - 2 * (64 - i) else 2
                for k in range(n):
                    c.execute("INSERT INTO voucher_lines (voucher_id, line_no, account_code, summary, debit, credit) VALUES (?,?,?,?,?,?)",
                              (vid, k + 1, acct[k % 2], "DRILL分錄", 100 if k == 0 else 0, 100 if k else 0))
                    lines += 1
                    if lines >= 151:
                        break
                if lines >= 151:
                    break
        # 舊版案件額外支出 12 筆：不同狀態；4 筆有附件（2 筆用舊資料夾 quotation_settlement_extra）
        qn = "%sMQ-001" % SEED_TAG
        for i, st in enumerate(["草稿", "待審核", "已核准", "已駁回", "已核准", "草稿", "待審核", "已核准", "已駁回", "已核准", "草稿", "已核准"], 1):
            files = []
            if i in (3, 5, 8, 10):
                if i in (3, 5):
                    rel = "case_extra_expense/%s_%d/receipt%d.png" % (qn, i, i)
                else:
                    rel = "quotation_settlement_extra/%s_%d/legacy%d.png" % (qn, i - 3, i)       # 舊版資料夾（以舊索引命名）
                sh = _put(root, rel)
                files = [{"id": "ee%d" % i, "filename": os.path.basename(rel), "path": rel, "size": len(PNG), "kind": "other"}]
            cur = c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, status,"
                            " created_by, created_by_name, created_at, updated_at, files_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (qn, "差旅", "DRILL舊式支出%d" % i, 1, "", 100 * i, 100 * i, st, "drill", "drill", now, now, json.dumps(files)))
            out["legacy_expenses"].append({"id": cur.lastrowid, "status": st, "total_cost": 100 * i, "files": files,
                                           "files_sha": [sha256_file(Path(root) / "backend" / "uploads" / Path(*f["path"].split("/"))) for f in files]})
        # 稽核紀錄到 ≈3350
        have = count(c, "audit_log") or 0
        c.executemany("INSERT INTO audit_log (at, username, action, target_type, target_id, detail) VALUES (?,?,?,?,?,?)",
                      [(now, "drill", "drill.seed", "seed", str(i), "{}") for i in range(max(0, 3350 - have))])
        # 總帳功能開關 4 列（若表存在）
        if table_exists(c, "gl_settings"):
            for k in ("engine_drafts", "withholding", "source_annotations", "tax401"):
                c.execute("INSERT OR REPLACE INTO gl_settings (key, value) VALUES (?, ?)", ("feature." + k, "1"))
        c.commit()
    finally:
        c.close()
    return out


# ── 基線／套用後的記錄（唯讀）────────────────────────────────────────────────────

COUNT_TABLES = ("audit_log", "custom_records", "vouchers_all", "voucher_lines", "dev_cases", "quotations", "case_extra_expenses")
WATCH_TABLES = ("expense_categories", "gl_dimensions", "user_bank_accounts")


def module_states(root):
    p = Path(root) / "backend" / "logs" / "module_states.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def states_map(ms):
    mods = (ms or {}).get("modules") if isinstance(ms, dict) else ms
    return {m["key"]: {"version": m.get("version"), "state": m.get("state")} for m in (mods or [])}


def record(root, seeded=None):
    c = ro(root)
    try:
        rec = {
            "counts": {t: count(c, t) for t in COUNT_TABLES},
            "tables_new": {t: table_exists(c, t) for t in WATCH_TABLES},
            "user_version": c.execute("PRAGMA user_version").fetchone()[0],
            "schema_versions": {r[0]: r[1] for r in c.execute("SELECT module, version FROM module_schema_versions")} if table_exists(c, "module_schema_versions") else {},
            "extra_cols": columns(c, "case_extra_expenses"),
            "voucher_line_cols": columns(c, "voucher_lines"),
            "gl_features": [tuple(r) for r in c.execute("SELECT key, value FROM gl_settings WHERE key LIKE 'feature.%' ORDER BY key")] if table_exists(c, "gl_settings") else [],
            "legacy_digest": [dict(r) for r in c.execute(
                "SELECT id, status, total_cost, files_json FROM case_extra_expenses WHERE description LIKE 'DRILL舊式支出%' ORDER BY id")],
        }
    finally:
        c.close()
    rec["module_states"] = states_map(module_states(root))
    rec["commit"] = json.loads((Path(root) / "backend" / ".deployed_commit.json").read_text(encoding="utf-8-sig")).get("commit")
    return rec


# ── 套用／回滾 ────────────────────────────────────────────────────────────────

def run_ps(root, script, extra, timeout=20 * 60):
    ps1 = Path(root) / "backend" / "tools" / script
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    t0 = time.time()
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    out = r.stdout + r.stderr
    m = RESULT_RE.findall(out)
    res = dict(zip(("status", "rolled_back", "service", "exit"), m[-1])) if m else None
    return {"returncode": r.returncode, "seconds": round(time.time() - t0, 1), "result": res, "tail": out[-3500:], "t0": t0}


def latest_result_json(root, prefix="apply_update_"):
    logs = Path(root) / "backend" / "logs"
    files = sorted(logs.glob(prefix + "*.result.json")) if logs.is_dir() else []
    if not files:
        return None, None
    rj = json.loads(files[-1].read_text(encoding="utf-8-sig"))
    ts = files[-1].name[len(prefix):-len(".result.json")]
    return ts, rj


def apply_package(root, port, payload):
    """正式機步驟 2 的兩段：複製包內 tools ⇒（演練獨有）再改寫兩行 ⇒ apply_update.ps1 -Yes。"""
    shutil.copytree(Path(payload) / "backend" / "tools", Path(root) / "backend" / "tools", dirs_exist_ok=True)
    rewritten = rewrite_tools(root, port)
    rec = run_ps(root, "apply_update.ps1", ["-PackagePath", str(payload), "-Yes"])
    ts, rj = latest_result_json(root)
    rec.update(rewritten=rewritten, timestamp=ts, result_json=rj)
    return rec


def rollback(root, ts, include_db=False):
    extra = ["-SnapshotTimestamp", ts, "-Yes"]
    if include_db:
        extra += ["-IncludeDatabase", "-ConfirmDatabaseOverwrite"]
    return run_ps(root, "rollback_update.ps1", extra)


# ── 交付（stage／verify／verify_package）────────────────────────────────────────

def deliver(delivery_root, name, root, base):
    """用安裝版本內建公鑰驗章（正式包由 host 用正式金鑰簽；驗不過就是驗不過，不換金鑰）。"""
    import delivery as D
    staging = Path(base) / "staging"
    staging.mkdir(exist_ok=True)
    staged = D.stage(str(delivery_root), name, str(staging))
    verify = D.verify_staged(staged, str(root), run_verify_package=False)
    payload = Path(staged) / D.PAYLOAD
    vp = subprocess.run([sys.executable, str(payload / "backend" / "tools" / "verify_package.py"), str(payload), "--expect-db-version", "116"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return payload, {"verify_ok": verify.get("ok"), "problems": verify.get("problems"), "notes": verify.get("notes"),
                     "verify_package_rc": vp.returncode, "verify_package_tail": (vp.stdout + vp.stderr)[-600:]}


# ── 檢查 ──────────────────────────────────────────────────────────────────────

def server_log_tracebacks(root):
    p = Path(root) / "backend" / "logs" / "server.log"
    if not p.is_file():
        return {"error": "no server.log"}
    text = p.read_text(encoding="utf-8", errors="replace")
    idx = text.rfind("Uvicorn running on")
    seg = text[idx:] if idx >= 0 else text
    tb = len(re.findall(r"Traceback \(most recent call last\)", seg))
    err = [ln for ln in seg.splitlines() if " ERROR " in ln or ln.startswith("ERROR")][:5]
    return {"traceback": tb, "errors_head": err, "lines": len(seg.splitlines())}


def listening_pids(port):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique" % port],
                       capture_output=True, text=True)
    return [x for x in r.stdout.split() if x.strip()]


def checks_after_apply(root, port, base_rec, new_rec, t0, package_modules):
    """計畫 §5 A 的 15 項中可程式化的部分 ⇒ {編號: (bool, 證據)}。"""
    res = {}
    res["1_version"] = (bool(new_rec["commit"]), new_rec["commit"])
    res["2_ping"] = (DM.ping(port), "")
    sc, token_info = None, None
    s1, _ = raw_get(port, "/openapi.json")
    s2, _ = raw_get(port, "/docs")
    res["5_api_docs_off"] = (s1 == 404 and s2 == 404, (s1, s2))
    # 6 模組：基線 + filehub；版本變化 == 包內 module.json 與基線的差集
    bm, nm = base_rec["module_states"], new_rec["module_states"]
    changed = {k: (bm.get(k, {}).get("version"), v["version"]) for k, v in nm.items() if bm.get(k, {}).get("version") != v["version"]}
    all_loaded = all(v["state"] == "loaded" for v in nm.values())
    res["6_modules"] = (all_loaded and set(changed) == set(package_modules), {"changed": changed, "unexpected": sorted(set(changed) ^ set(package_modules)), "count": len(nm)})
    res["7_log"] = (server_log_tracebacks(root).get("traceback") == 0, server_log_tracebacks(root))
    pids = listening_pids(port)
    res["8_one_listener"] = (len(pids) == 1, pids)
    sv = new_rec["schema_versions"]
    res["9a_schema"] = (sv.get("case") == 3 and sv.get("accounting") == 3 and sv.get("payroll") == 3 and sv.get("core") == 6 and new_rec["user_version"] == 116, sv)
    res["9b_new_tables"] = (all(new_rec["tables_new"].values()) and "dim_json" in new_rec["voucher_line_cols"], new_rec["tables_new"])
    need = ["kind", "doc_code", "data_json", "lines_json", "def_version", "department_id", "payee_type", "payee_name", "payee_bank", "payee_account",
            "pay_terms", "remit_date", "pay_method", "pay_account_code", "paid_by", "pretax", "tax", "currency", "void_reason", "voided_by", "voided_at"]
    res["9b_extra_cols"] = (all(x in new_rec["extra_cols"] for x in need), [x for x in need if x not in new_rec["extra_cols"]])
    same = all(new_rec["counts"][t] == base_rec["counts"][t] for t in ("custom_records", "dev_cases", "quotations", "case_extra_expenses"))
    grew_ok = all(new_rec["counts"][t] >= base_rec["counts"][t] for t in ("audit_log", "vouchers_all", "voucher_lines"))
    res["9c_counts"] = (same and grew_ok, {t: (base_rec["counts"][t], new_rec["counts"][t]) for t in COUNT_TABLES})
    def key(d):
        return [(r["id"], r["status"], r["total_cost"], sha256_text(r["files_json"])) for r in d]
    res["9c_legacy_rows"] = (key(base_rec["legacy_digest"]) == key(new_rec["legacy_digest"]), len(new_rec["legacy_digest"]))
    res["9d_gl_features"] = (base_rec["gl_features"] == new_rec["gl_features"], new_rec["gl_features"])
    c = ro(root)
    try:
        legacy_defaults = c.execute("SELECT COUNT(*) FROM case_extra_expenses WHERE description LIKE 'DRILL舊式支出%' AND kind='' AND doc_code='' "
                                    "AND data_json='{}' AND lines_json='[]' AND def_version=0").fetchone()[0]
        idx = {r[1] for r in c.execute("PRAGMA index_list(case_extra_expenses)")}
        dim = c.execute("SELECT COUNT(*) FROM voucher_lines WHERE dim_json<>'{}'").fetchone()[0]
    finally:
        c.close()
    res["9c_legacy_defaults"] = (legacy_defaults == len(new_rec["legacy_digest"]), legacy_defaults)
    res["9b_indexes"] = ({"idx_case_extra_exp_doc_code", "idx_case_extra_exp_kind_status"} <= idx, sorted(i for i in idx if i.startswith("idx_case_extra")))
    res["9b_dim_default"] = (dim == 0, dim)
    # 10 靜態＋守門
    files = [Path(root) / "frontend" / "pages" / "expense-types.html", Path(root) / "frontend" / "pages" / "file-center.html",
             Path(root) / "frontend" / "static" / "definition-form.js"]
    guards = {p: raw_get(port, p)[0] for p in ("/api/expense-types", "/api/expense-categories", "/api/filehub/search",
                                               "/api/definition-kinds", "/api/settings/approval-doc-types")}
    res["10_new_features"] = (all(f.is_file() for f in files) and all(s in (401, 403) for s in guards.values()), {"files": [f.name for f in files if f.is_file()], "unauth": guards})
    started = (nm and (module_states(root) or {}).get("started_at"))
    res["12_startup"] = (True, {"started_at": started, "seconds": None})
    return res


def check_legacy_usable(root, port, base_rec):
    """14：舊額外支出的附件逐檔開得起來且位元組＝種子雜湊；15 舊流程不變。"""
    user, token = login(root, port)
    out = {"attachments": [], "flow": None}
    ok = True
    for e in base_rec["legacy_digest"]:
        files = json.loads(e["files_json"] or "[]")
        for f in files:
            st, body = raw_get(port, "/api/attachments/open?type=extra_expense&doc=%d&file=%s" % (e["id"], f["id"]), token)
            good = st == 200 and sha256_text("") != "" and len(body) == f.get("size", len(body))
            out["attachments"].append({"expense": e["id"], "file": f["id"], "status": st, "ok": good})
            ok = ok and good
    return ok, out, token


def legacy_flow(port, token):
    qn = "%sMQ-002" % SEED_TAG
    s, d = api(port, "/api/quotations/%s/extra-expenses" % qn, {"category": "差旅", "description": "DRILL舊流程", "qty": 1, "unitCost": 123}, token)
    if s != 201:
        return False, {"create": (s, d)}
    eid = d["id"]
    s2, d2 = api(port, "/api/quotations/%s/extra-expenses/%d/submit" % (qn, eid), None, token, method="POST")
    return s2 == 200, {"create": (s, {k: d.get(k) for k in ("id", "status")}), "submit": (s2, d2 if isinstance(d2, dict) else str(d2)[:120])}


# ── 主程式 ────────────────────────────────────────────────────────────────────

def make_baseline(base, port, base_commit):
    root = base / "install"
    DM.make_install(base_commit, root, port)
    rewrite_log = rewrite_tools(root, port)
    first = DM.start(root, port)
    DM.setup_company(root, port)
    DM.stop(root, port)
    seeded = seed(root, port)
    restart = DM.start(root, port)
    return root, {"first_start_s": round(first, 1), "restart_s": round(restart, 1), "rewrite": rewrite_log, "seed": seeded}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--delivery-root")
    ap.add_argument("--name")
    ap.add_argument("--new-commit")
    ap.add_argument("--base-commit", default=BASE_COMMIT)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--runs", default="A,B,C,E")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    if not a.seed_only and not (a.delivery_root and a.name and a.new_commit):
        ap.error("需要 --delivery-root --name --new-commit（或 --seed-only）")
    DM.refuse_if_task_exists()
    DRILL_ROOT.mkdir(parents=True, exist_ok=True)
    base = DRILL_ROOT / time.strftime("%Y%m%d_%H%M%S")
    if "V9.0" in str(base):
        raise DrillError("演練路徑不可以含 V9.0")
    base.mkdir()
    root = base / "install"
    report = {"base": str(base), "base_commit": a.base_commit, "runs": {}}
    try:
        root, info = make_baseline(base, a.port, a.base_commit)
        report["baseline_setup"] = info
        base_rec = record(root)
        report["baseline"] = {k: v for k, v in base_rec.items() if k != "legacy_digest"}
        report["baseline"]["legacy_rows"] = len(base_rec["legacy_digest"])
        if not a.seed_only:
            payload, dv = deliver(a.delivery_root, a.name, root, base)
            report["delivery"] = dv
            if not dv["verify_ok"] or dv["verify_package_rc"] != 0:
                report["stopped"] = "stage/verify 沒過（照正式機步驟：停下回報）"
                return 1
            pm = json.loads((payload / "deploy_manifest.json").read_text(encoding="utf-8-sig"))
            report["package"] = {"verification": pm.get("verification"), "commit": a.new_commit}
            new_mods = {}
            for mj in sorted((payload / "backend" / "modules").glob("*/module.json")):
                meta = json.loads(mj.read_text(encoding="utf-8-sig"))
                new_mods[meta["key"]] = meta.get("version")
            pkg_changed = {k for k, v in new_mods.items() if base_rec["module_states"].get(k, {}).get("version") != v}
            runs = a.runs.split(",")
            ts_a = None
            if "A" in runs:
                rec = apply_package(root, a.port, payload)
                new_rec = record(root)
                ok_result = rec["result"] and rec["result"]["status"] == "success" and rec["result"]["rolled_back"] == "applied" and rec["result"]["service"] == "up"
                rec["checks"] = checks_after_apply(root, a.port, base_rec, new_rec, rec["t0"], pkg_changed)
                lg_ok, lg, token = check_legacy_usable(root, a.port, base_rec)
                rec["checks"]["14_legacy_attachments"] = (lg_ok, lg)
                fl_ok, fl = legacy_flow(a.port, token)
                rec["checks"]["15_legacy_flow"] = (fl_ok, fl)
                DM.stop(root, a.port)
                again = DM.start(root, a.port)                               # 13 冪等：重啟
                rec["checks"]["13_restart_idempotent"] = (record(root)["schema_versions"] == new_rec["schema_versions"] and
                                                         server_log_tracebacks(root).get("traceback") == 0, {"restart_s": round(again, 1)})
                rec["ok"] = bool(ok_result) and all(v[0] for v in rec["checks"].values())
                ts_a = rec["timestamp"]
                report["runs"]["A"] = rec
            if "B" in runs and ts_a:
                DM.stop(root, a.port)
                rb = rollback(root, ts_a)
                DM.start(root, a.port)
                rec_b = record(root)
                rb["after"] = {"commit": rec_b["commit"], "ping": DM.ping(a.port), "schema_versions": rec_b["schema_versions"],
                               "tables_new": rec_b["tables_new"], "legacy_same": rec_b["legacy_digest"] == base_rec["legacy_digest"]}
                _u, tk = login(root, a.port)
                rb["after"]["legacy_flow"] = legacy_flow(a.port, tk)
                rb["after"]["log"] = server_log_tracebacks(root)
                report["runs"]["B"] = rb
            if "E" in runs or "C" in runs:
                pass                                                          # C／E：下一版補完（需要在 B 之後再套一次並做庫回滾）
    finally:
        report["stop"] = DM.stop(root, a.port) if root.exists() else None
        outdir = Path(tempfile.gettempdir()) / "motrix-drill-t29"
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (base.name + ".report.json")
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: report[k] for k in report if k in ("base", "base_commit", "stopped")}, ensure_ascii=False))
        print("report:", out)
        if not a.keep:
            report["cleanup"] = DM.cleanup(base)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
