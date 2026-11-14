# -*- coding: utf-8 -*-
"""正式機半自動套用（T87 A1 M1）——把「步驟檔裡人工做的記錄與驗收」做成程式。

[單位] tool:auto_apply    [層] 部署工具（正式機本機；由 deploy_dashboard 呼叫，不開網路端點）
[公開介面] capture_state, diff_state, compare_diffs, integrity_check, precheck, rehearse, consent_digest,
    verify_after, apply_with_verification, estimate_downtime, render_report, write_report, audit_event, audit_chain_problems,
    structure_hash, finish, finish_crashed, build_notice, notify_result, load_expectations, is_loopback_url, python_exe
[不變式]
  - **不碰 apply_update.ps1／rollback_update.ps1／delivery.py**：套用本身仍是 delivery.apply_staged（它的備份、
    預演、停服、健檢、**內建自動回滾**都照舊）。本檔只在它前後加「記錄」與「驗收」。
  - **事後驗證只停下來報告，不自動回滾**（PM 裁示 2026-11-14 D1）；報告附回滾指令的文字，**本檔永遠不執行**它。
  - 預演在「正式庫的線上備份副本」上跑新包的 migrate_like_startup（`python -B`＋PYTHONDONTWRITEBYTECODE，
    **不得在暫存包裡留下 .pyc／__pycache__**，否則套用前的重驗會判成「暫存被改過」）；副本用完一定刪（含 -wal／-shm）。
  - 預期變更＝預演前後的結構差異（sqlite_master／欄位／模組 schema 版本／設定鍵名）；**不比資料列、不存設定值**
    （只存被指定「不得變動」的鍵的雜湊）。
  - 報告與稽核不含密碼、token、設定值、個資；稽核另寫一份雜湊鏈 JSONL。
  - 預演是一次性（儀表板在套用一開始就作廢它）；套用前再比一次正式庫的結構雜湊；稽核寫不進去就不套用；套用程序丟例外也補 apply_end。
  - 套用結果（成功、驗證未通過或沒做、失敗、被擋、中斷）一律由 `notify_result` 請安裝目錄裡的後端（`a1_notify.py`）寫 ERP 稽核列、
    站內通知，並走 `email_notify.send_registered` 發 Email／LINE；本檔不 import ERP 的 helpers。
[契約題] tests/platform/test_a1_auto_apply_2026_11_14.py
[文件] docs/platform/prod-tasks/A1-AUTO-APPLY.md（設計全文：D:\\Claude-pm\\t87-design\\A1-auto-apply.md；M2 不在這一版）
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

STATE_SCHEMA = 1
EXPECT_REL = os.path.join("backend", "a1_expectations.json")       # 隨包出貨的選用檔（見 load_expectations）
REHEARSAL_MAX_AGE_SEC = 12 * 3600       # 預演距離套用太久 ⇒ 正式庫已漂移，重做
MIN_FREE_FACTOR = 3                     # 可用空間 ≥ 主庫大小 × 3（預演副本＋套用前快照＋緩衝）
PING_POLL_SEC = 2.0
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SUCCESS_STATE = "applied"               # apply_update.ps1 成功出口的 rolled_back 值（$script:ProdState，:1285）

#: 預期差異比對時，「設定鍵」多出的鍵若符合這個樣式 ⇒ 視為失敗（一次性遷移標記不可憑空出現）；其餘多出的鍵只警告。
_MIGRATION_MARK = re.compile(r"^migration_")
_SKIP_TABLE = re.compile(r"^sqlite_")


# ══════════════════════════════════════════════════════════════════
# 狀態擷取與差異（唯讀；只記結構與鍵名）
# ══════════════════════════════════════════════════════════════════

def _connect_ro(path, timeout=10):
    uri = "file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    return sqlite3.connect(uri, uri=True, timeout=timeout)


def _quote_ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def _rows(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise


#: 每個行程一把隨機鹽：受監看設定的值雜湊即使被存下來，也不能拿字典反推低熵的值（同一行程內前後比對不受影響）。
_SALT = os.urandom(16)


def _value_hash(text):
    return hashlib.sha256(_SALT + ("" if text is None else str(text)).encode("utf-8")).hexdigest()[:16]


def structure_hash(state):
    """資料庫「結構」的雜湊（schema_version、模組版號、物件、欄位）。**不含**設定鍵名與監看值：執行中服務會寫設定，納入會誤擋。
    預演時記下副本的值；套用時與正式庫目前的值比，不同＝預演之後結構變動過，預演預期已不適用。"""
    blob = json.dumps({k: state.get(k) for k in ("schema_version", "modules", "objects", "columns")},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def capture_state(db_path, watch_keys=()):
    """只讀擷取（`mode=ro`；服務在跑也可讀）。⇒ dict（可 json 化）。讀不到庫就丟例外——呼叫端當「驗不到」，不可吞成空狀態。

    內容：schema_version、module_schema_versions（不含 applied_at）、sqlite_master 每項的 type／tbl／sql 雜湊、
    每張表的欄位（名稱／型別／notnull／預設值／pk）、system_settings 的鍵名、watch_keys 的值雜湊。**不含任何資料列內容。**
    """
    conn = _connect_ro(db_path)
    try:
        st = {"schema": STATE_SCHEMA}
        rows = _rows(conn, "SELECT version FROM schema_version WHERE id=1")
        st["schema_version"] = int(rows[0][0]) if rows else None
        rows = _rows(conn, "SELECT module, version FROM module_schema_versions")
        st["modules"] = {m: int(v) for m, v in (rows or [])}
        objs = {}
        tables = []
        for typ, name, tbl, sql in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"):
            objs["%s:%s" % (typ, name)] = {"tbl": tbl, "sql": _value_hash(sql)}
            if typ == "table" and not _SKIP_TABLE.match(name):
                tables.append(name)
        st["objects"] = objs
        cols = {}
        for t in tables:
            cols[t] = {r[1]: [r[2], r[3], r[4], r[5]] for r in conn.execute("PRAGMA table_info(%s)" % _quote_ident(t))}
        st["columns"] = cols
        rows = _rows(conn, "SELECT key FROM system_settings ORDER BY key")
        st["settings_keys"] = [r[0] for r in rows] if rows is not None else None
        watch = {}
        for k in watch_keys or ():
            r = _rows(conn, "SELECT value_json FROM system_settings WHERE key=?", (k,))
            watch[k] = _value_hash(r[0][0]) if r else None
        st["watch"] = watch
        return st
    finally:
        conn.close()


def integrity_check(db_path, timeout=120):
    """⇒ 'ok' 或錯誤文字（第一行）。唯讀。"""
    conn = _connect_ro(db_path, timeout=timeout)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    first = str(rows[0][0]) if rows else "（沒有結果）"
    return "ok" if first == "ok" and len(rows) == 1 else first


def diff_state(before, after):
    """兩份 capture_state 的結構差異。⇒ dict；全空＝沒有變化（`diff_is_empty`）。"""
    out = {"schema_version": None, "modules": {"added": {}, "changed": {}, "removed": []},
           "objects": {"added": [], "removed": [], "changed": []}, "columns": {},
           "settings": {"added": [], "removed": []}, "watch": {}}
    if before.get("schema_version") != after.get("schema_version"):
        out["schema_version"] = [before.get("schema_version"), after.get("schema_version")]
    bm, am = before.get("modules") or {}, after.get("modules") or {}
    out["modules"]["added"] = {k: v for k, v in am.items() if k not in bm}
    out["modules"]["changed"] = {k: [bm[k], am[k]] for k in bm if k in am and bm[k] != am[k]}
    out["modules"]["removed"] = sorted(k for k in bm if k not in am)
    bo, ao = before.get("objects") or {}, after.get("objects") or {}
    out["objects"]["added"] = sorted(k for k in ao if k not in bo)
    out["objects"]["removed"] = sorted(k for k in bo if k not in ao)
    out["objects"]["changed"] = sorted(k for k in bo if k in ao and bo[k] != ao[k])
    bc, ac = before.get("columns") or {}, after.get("columns") or {}
    for t in sorted(set(bc) & set(ac)):
        b, a = bc[t], ac[t]
        d = {"added": sorted(c for c in a if c not in b), "removed": sorted(c for c in b if c not in a),
             "changed": sorted(c for c in b if c in a and b[c] != a[c])}
        if d["added"] or d["removed"] or d["changed"]:
            out["columns"][t] = d
    bs, as_ = before.get("settings_keys"), after.get("settings_keys")
    if bs is not None and as_ is not None:
        out["settings"]["added"] = sorted(set(as_) - set(bs))
        out["settings"]["removed"] = sorted(set(bs) - set(as_))
    bw, aw = before.get("watch") or {}, after.get("watch") or {}
    out["watch"] = {k: [bw.get(k), aw.get(k)] for k in set(bw) | set(aw) if bw.get(k) != aw.get(k)}
    return out


def diff_is_empty(d):
    return not (d["schema_version"] or d["modules"]["added"] or d["modules"]["changed"] or d["modules"]["removed"]
                or d["objects"]["added"] or d["objects"]["removed"] or d["objects"]["changed"] or d["columns"]
                or d["settings"]["added"] or d["settings"]["removed"] or d["watch"])


def summarize_diff(d):
    """給人看的一行一項（同意畫面／報告用）。"""
    lines = []
    if d["schema_version"]:
        lines.append("schema_version：%s → %s" % tuple(d["schema_version"]))
    for k, v in sorted(d["modules"]["added"].items()):
        lines.append("模組 %s 遷移版號：新增 %s" % (k, v))
    for k, (b, a) in sorted(d["modules"]["changed"].items()):
        lines.append("模組 %s 遷移版號：%s → %s" % (k, b, a))
    for k in d["modules"]["removed"]:
        lines.append("模組 %s 遷移版號：移除" % k)
    for k in d["objects"]["added"]:
        lines.append("資料庫新增：%s" % k)
    for k in d["objects"]["removed"]:
        lines.append("資料庫移除：%s" % k)
    for k in d["objects"]["changed"]:
        lines.append("資料庫定義變更：%s" % k)
    for t, c in sorted(d["columns"].items()):
        if c["added"]:
            lines.append("資料表 %s 新增欄位：%s" % (t, "、".join(c["added"])))
        if c["removed"]:
            lines.append("資料表 %s 移除欄位：%s" % (t, "、".join(c["removed"])))
        if c["changed"]:
            lines.append("資料表 %s 欄位定義變更：%s" % (t, "、".join(c["changed"])))
    if d["settings"]["added"]:
        lines.append("設定鍵新增：%s" % "、".join(d["settings"]["added"]))
    if d["settings"]["removed"]:
        lines.append("設定鍵移除：%s" % "、".join(d["settings"]["removed"]))
    for k in sorted(d["watch"]):
        lines.append("受監看設定 %s 的值有變動" % k)
    return lines


def _set_problems(label, expected, actual, fails, warns=None, soft=False):
    """expected／actual：集合。多出（預演沒預見）與少了（預期卻沒發生）分開報。soft ⇒ 多出只警告。"""
    for x in sorted(actual - expected):
        msg = "%s：實際多出預演沒有預見的項目 %s" % (label, x)
        (warns if soft and warns is not None else fails).append(msg)
    for x in sorted(expected - actual):
        fails.append("%s：預演預期有、實際沒有 %s" % (label, x))


def compare_diffs(expected, actual):
    """預演預期差異 vs 正式機實際差異。⇒ (fails, warns)；兩者都空＝完全相符。
    設定鍵：多出的鍵若是 `migration_*` ⇒ 失敗，其餘多出的鍵只警告（服務啟動時的一次性寫入不在預演範圍）；
    少了鍵、預期有而沒發生、其他結構差異一律失敗。"""
    fails, warns = [], []
    if expected["schema_version"] != actual["schema_version"]:
        fails.append("schema_version：預期 %s，實際 %s" % (expected["schema_version"], actual["schema_version"]))
    em, am = expected["modules"], actual["modules"]
    _set_problems("模組 schema 版號新增", set(em["added"].items()), set(am["added"].items()), fails)
    _set_problems("模組 schema 版號變更", {(k, tuple(v)) for k, v in em["changed"].items()},
                  {(k, tuple(v)) for k, v in am["changed"].items()}, fails)
    _set_problems("模組 schema 版號移除", set(em["removed"]), set(am["removed"]), fails)
    for key in ("added", "removed", "changed"):
        _set_problems("資料庫物件" + {"added": "新增", "removed": "移除", "changed": "定義變更"}[key],
                      set(expected["objects"][key]), set(actual["objects"][key]), fails)
    for t in sorted(set(expected["columns"]) | set(actual["columns"])):
        e = expected["columns"].get(t) or {"added": [], "removed": [], "changed": []}
        a = actual["columns"].get(t) or {"added": [], "removed": [], "changed": []}
        for key, lab in (("added", "新增欄位"), ("removed", "移除欄位"), ("changed", "欄位定義變更")):
            _set_problems("資料表 %s %s" % (t, lab), set(e[key]), set(a[key]), fails)
    es, as_ = set(expected["settings"]["added"]), set(actual["settings"]["added"])
    for x in sorted(as_ - es):
        (fails if _MIGRATION_MARK.match(x) else warns).append("設定鍵：實際多出預演沒有預見的鍵 %s" % x)
    for x in sorted(es - as_):
        fails.append("設定鍵：預演預期新增、實際沒有 %s" % x)
    _set_problems("設定鍵移除", set(expected["settings"]["removed"]), set(actual["settings"]["removed"]), fails)
    for k in sorted(set(actual["watch"]) - set(expected["watch"])):
        fails.append("受監看設定 %s 的值被改動（預演沒有預見）" % k)
    return fails, warns


# ══════════════════════════════════════════════════════════════════
# 預檢、預演、同意綁定
# ══════════════════════════════════════════════════════════════════

def python_exe():
    """子行程用的 python：儀表板可能由 pythonw 啟動（沒有主控台，輸出會丟）⇒ 換成同資料夾的 python.exe。"""
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base in ("pythonw.exe", "pythonw"):
        cand = os.path.join(os.path.dirname(exe), "python.exe" if base.endswith(".exe") else "python")
        if os.path.isfile(cand):
            return cand
    return exe


def db_paths(install_root):
    backend = os.path.join(install_root, "backend")
    return os.path.join(backend, "motrix_erp.db"), os.path.join(backend, "license.key")


def precheck(install_root, db_path=None, disk_usage=None):
    """套用前的環境預檢（唯讀）。⇒ 問題清單（空＝通過）。"""
    problems = []
    db = db_path or db_paths(install_root)[0]
    if not os.path.isfile(db):
        return ["找不到正式庫：%s" % db]
    try:
        size = os.path.getsize(db)
        free = (disk_usage or shutil.disk_usage)(os.path.dirname(os.path.abspath(db))).free
        if free < size * MIN_FREE_FACTOR:
            problems.append("磁碟可用空間不足：可用 %d MB，需要至少 %d MB（主庫 %d MB × %d）"
                            % (free // 2**20, size * MIN_FREE_FACTOR // 2**20, size // 2**20, MIN_FREE_FACTOR))
    except OSError as exc:
        problems.append("讀不到磁碟空間：%s" % exc)
    try:
        res = integrity_check(db)
        if res != "ok":
            problems.append("正式庫 integrity_check 不是 ok：%s" % res[:200])
    except Exception as exc:                                        # noqa: BLE001 — 驗不到＝不放行
        problems.append("正式庫 integrity_check 無法執行：%s" % exc)
    return problems


def package_digest(staged):
    """暫存包的簽章內容（package.sha256＋delivery.json，兩者都在簽章範圍內）的 SHA256：同一個包同一個值；任一份被換掉就不同。
    package.sha256 必須存在（讀不到就丟 OSError，呼叫端當成不可用）；delivery.json 沒有就只算前者。"""
    h = hashlib.sha256()
    with open(os.path.join(staged, "package.sha256"), "rb") as f:
        h.update(f.read())
    h.update(b"\0")
    try:
        with open(os.path.join(staged, "delivery.json"), "rb") as f:
            h.update(f.read())
    except OSError:
        pass
    return h.hexdigest()


def consent_digest(pkg_digest, expected_diff):
    """同意綁定值＝包摘要＋預演預期差異。包或預演結果任一改變 ⇒ 值不同 ⇒ 之前的預演不算數。"""
    blob = json.dumps({"pkg": pkg_digest, "diff": expected_diff}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _tree_inventory(root):
    """root 底下每一個檔與資料夾（含 __pycache__、.pyc、任何預演新產生的東西）。"""
    found = set()
    for dp, dns, fns in os.walk(root):
        for d in dns:
            found.add(os.path.join(dp, d))
        for fn in fns:
            found.add(os.path.join(dp, fn))
    return found


def _purge(paths):
    n = 0
    for p in sorted(paths, key=len, reverse=True):
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            n += 1
        except OSError:
            pass
    return n


def _online_backup(src, dst):
    s = _connect_ro(src, timeout=30)
    try:
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()


def rehearse(staged, install_root, work_root, watch_keys=(), run=None, clock=None, verify_fn=None):
    """在正式庫的線上備份副本上，用**新包**的 migrate_like_startup 跑一遍，取預演前後差異＝預期差異。

    ⇒ dict：ok、problems、seconds、db_mb、expected_diff、summary（給人看的行）、pkg_digest、digest（同意綁定值）、
    before_hash（副本預演前的結構雜湊，套用時與正式庫比對）、at（epoch）、
    tool_tail（工具輸出末 400 字；遷移錯誤可能回顯資料 ⇒ 只在失敗時帶，且截斷）。
    副本一律刪除（含 -wal／-shm／modules_disabled.json）；暫存包裡預演新產生的任何檔案或資料夾（.pyc、備援庫、logs…）一律清掉並記在 notes。
    `verify_fn`（選填）＝回傳 `{ok, problems}` 的檢查（儀表板傳 `delivery.verify_staged`）：預演結束後暫存包與簽章清單不符
    （被改過的檔、清單外多出的檔）⇒ 預演不通過，在這一步就失敗，而不是等使用者輸入密碼之後的套用才發現。"""
    clock = clock or time.time
    t0 = clock()
    out = {"ok": False, "problems": [], "notes": [], "seconds": 0.0, "db_mb": None, "expected_diff": None,
           "summary": [], "pkg_digest": None, "digest": None, "before_hash": None, "at": t0, "tool_tail": ""}
    payload = os.path.join(staged, "payload")
    db, lic = db_paths(install_root)
    tool = os.path.join(payload, "backend", "tools", "migrate_like_startup.py")
    if not os.path.isfile(db):
        out["problems"].append("找不到正式庫：%s" % db)
        return out
    if not os.path.isfile(tool):
        out["problems"].append("包裡沒有 backend\\tools\\migrate_like_startup.py：無法預演")
        return out
    try:
        out["pkg_digest"] = package_digest(staged)
    except OSError as exc:
        out["problems"].append("讀不到暫存包的簽章清單：%s" % exc)
        return out
    out["db_mb"] = round(os.path.getsize(db) / 2**20, 1)
    work = os.path.join(work_root, "rehearse_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    copy = os.path.join(work, "motrix_erp.db")
    before_tree = _tree_inventory(payload)
    try:
        os.makedirs(work, exist_ok=True)
        _online_backup(db, copy)
        before = capture_state(copy, watch_keys)
        out["before_hash"] = structure_hash(before)
        cmd = [python_exe(), "-B", tool, "--db", copy]
        if os.path.isfile(lic):
            cmd += ["--license", lic]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        if run is not None:
            rc, text = run(cmd, env)
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=1800, env=env, cwd=work, creationflags=CREATE_NO_WINDOW)
            rc, text = r.returncode, (r.stdout or "") + (r.stderr or "")
        if rc != 0 or "MIGRATE_LIKE_STARTUP_OK" not in text:
            out["problems"].append("預演失敗（migrate_like_startup 結束碼 %s）；正式庫完全沒有被改動" % rc)
            out["tool_tail"] = text[-400:]
            return out
        after = capture_state(copy, watch_keys)
        diff = diff_state(before, after)
        out["expected_diff"] = diff
        out["summary"] = summarize_diff(diff)
        out["digest"] = consent_digest(out["pkg_digest"], diff)
        out["ok"] = True
    except subprocess.TimeoutExpired:
        out["problems"].append("預演逾時（30 分鐘）；正式庫沒有被改動")
    except Exception as exc:                                        # noqa: BLE001 — 預演本身出錯＝不放行
        out["problems"].append("預演程序本身出錯：%s: %s" % (type(exc).__name__, exc))
    finally:
        for suffix in ("", "-wal", "-shm", ".modules_disabled.json"):
            try:
                os.remove(copy + suffix)
            except OSError:
                pass
        shutil.rmtree(work, ignore_errors=True)
        new_entries = _tree_inventory(payload) - before_tree
        if new_entries:
            out["notes"].append("預演在暫存包留下 %d 個新檔或資料夾（例如 .pyc、備援資料庫、logs），已清除（不應發生；請檢查 -B 是否生效）" % len(new_entries))
            _purge(new_entries)
        if verify_fn is not None:
            try:
                v = verify_fn()
            except Exception as exc:                                # noqa: BLE001 — 驗不到暫存包完整 ≠ 通過
                v = {"ok": False, "problems": ["無法檢查暫存包完整性：%s: %s" % (type(exc).__name__, exc)]}
            if not v.get("ok"):
                out["ok"] = False
                out["problems"].append("預演之後暫存包與簽章清單不符，預演不通過：" + "；".join(v.get("problems") or ["（沒有說明）"]))
        out["seconds"] = round(clock() - t0, 1)
    return out


# ══════════════════════════════════════════════════════════════════
# 預期檔、停機估計
# ══════════════════════════════════════════════════════════════════

def load_expectations(payload):
    """包裡選用的 `backend/a1_expectations.json`（簽章清單涵蓋它）。沒有 ⇒ ({}, [注記])；讀不懂 ⇒ ({}, [注記])，
    不當成通過，只是沒有額外檢查項。欄位（全選用）：pages、auth_required（[{method,path}]）、files、log_forbid、watch_settings。"""
    p = os.path.join(payload, EXPECT_REL)
    if not os.path.isfile(p):
        return {}, ["這個包沒有附 a1_expectations.json：只做通用驗證（沒有頁面／未登入／檔案／日誌的專屬檢查項）"]
    try:
        d = json.load(open(p, encoding="utf-8-sig"))
        if not isinstance(d, dict):
            raise ValueError("不是物件")
    except (OSError, ValueError) as exc:
        return {}, ["a1_expectations.json 讀不懂（%s）：已略過" % exc]
    return _sanitize_expectations(d)


_BAD_PATH = re.compile(r"[\s\\@]|://|^//")


def _safe_url_path(p):
    """只准同機的絕對路徑（"/…"）：不准 scheme、"@host"、反斜線、"//host"、空白或控制字元（避免 base_url + 路徑變成打到別的主機）。"""
    return isinstance(p, str) and p.startswith("/") and not _BAD_PATH.search(p) and len(p) <= 300


def _safe_rel_file(p):
    if not isinstance(p, str) or not p or len(p) > 300 or os.path.isabs(p) or re.match(r"^[A-Za-z]:", p) or p.startswith(("/", "\\")):
        return False
    return ".." not in re.split(r"[\\/]+", p)


def _sanitize_expectations(d):
    """預期檔欄位的格式檢查（包有簽章，這是縱深防禦）。不合格的項目丟掉並在注記說明；⇒ (cleaned, notes)。"""
    notes, out = [], {}
    pages = [x for x in (d.get("pages") or []) if _safe_url_path(x)]
    auth = [x for x in (d.get("auth_required") or []) if isinstance(x, dict) and _safe_url_path(x.get("path"))]
    files = [x for x in (d.get("files") or []) if _safe_rel_file(x)]
    for key, kept, raw in (("pages", pages, d.get("pages")), ("auth_required", auth, d.get("auth_required")), ("files", files, d.get("files"))):
        if raw and len(kept) != len(raw):
            notes.append("a1_expectations.json 的 %s 有 %d 項格式不合格，已略過" % (key, len(raw) - len(kept)))
    out["pages"], out["auth_required"], out["files"] = pages, auth, files
    out["log_forbid"] = [x for x in (d.get("log_forbid") or []) if isinstance(x, str)]
    out["watch_settings"] = [x for x in (d.get("watch_settings") or []) if isinstance(x, str)]
    return out, notes


def is_loopback_url(url):
    """事後驗證與健康檢查只准打本機（TLS 驗證是關的，打到別的主機沒有保護）。"""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def _parse_stamp(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except ValueError:
            continue
    return None


def estimate_downtime(install_root, rehearsal_seconds=None):
    """從歷次成功套用的 result.json（started_at／finished_at）估整個套用程序的耗時。⇒ {samples, typical, max}（秒；沒資料 ⇒ None）。
    注意：這是 apply_update.ps1 整段（含套用前的備份與乾跑），不是只有服務停止的時間；實際停機另由 A1 在套用時量。"""
    logs = os.path.join(install_root, "backend", "logs")
    rx = re.compile(r"^apply_update_\d{8}_\d{6}\.result\.json$")
    secs = []
    for n in sorted((n for n in (os.listdir(logs) if os.path.isdir(logs) else []) if rx.match(n)), reverse=True):
        try:
            r = json.load(open(os.path.join(logs, n), encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if r.get("status") != "success":
            continue
        a, b = _parse_stamp(r.get("started_at")), _parse_stamp(r.get("finished_at"))
        if a and b and b >= a:
            secs.append(int((b - a).total_seconds()))
        if len(secs) >= 5:
            break
    if not secs:
        return {"samples": 0, "typical": None, "max": None}
    secs.sort()
    return {"samples": len(secs), "typical": secs[len(secs) // 2], "max": secs[-1]}


# ══════════════════════════════════════════════════════════════════
# 事後驗證
# ══════════════════════════════════════════════════════════════════

def _http_status(url, method="GET", timeout=8):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, method=method, data=(b"{}" if method == "POST" else None),
                                 headers={"Content-Type": "application/json"} if method == "POST" else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def _item(items, id_, ok, title, detail="", severity=None):
    items.append({"id": id_, "ok": bool(ok), "severity": severity or ("ok" if ok else "fail"), "title": title, "detail": detail})


def _check_modules(install_root, apply_started):
    """logs/module_states.json（服務這一次啟動寫的）對照磁碟 backend/modules/*/module.json。⇒ (ok, 詳情, severity)。"""
    backend = os.path.join(install_root, "backend")
    states_path = os.path.join(backend, "logs", "module_states.json")
    try:
        states = json.load(open(states_path, encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return False, "讀不到 logs\\module_states.json：%s" % exc, "fail"
    started = _parse_stamp(states.get("started_at"))
    if apply_started and started and started < apply_started.replace(microsecond=0):     # started_at 只到秒
        return False, "module_states.json 的時間（%s）早於這次套用開始（%s）：不是這次啟動寫的" % (states.get("started_at"), apply_started), "fail"
    disk = {}
    mdir = os.path.join(backend, "modules")
    for name in sorted(os.listdir(mdir) if os.path.isdir(mdir) else []):
        mj = os.path.join(mdir, name, "module.json")
        if os.path.isfile(mj):
            try:
                d = json.load(open(mj, encoding="utf-8-sig"))
                disk[d.get("key") or name] = str(d.get("version") or "")
            except (OSError, ValueError):
                disk[name] = None
    got = {m.get("key"): m for m in states.get("modules") or []}
    bad, soft = [], []
    for key, ver in sorted(disk.items()):
        m = got.get(key)
        if m is None:
            bad.append("%s：磁碟有、載入器沒有看到" % key)
        elif m.get("state") == "loaded":
            if ver is None or str(m.get("version") or "") != ver:
                bad.append("%s：載入版號 %s ≠ 磁碟 %s" % (key, m.get("version"), ver))
        elif m.get("state") == "failed":
            bad.append("%s：載入失敗（%s）" % (key, m.get("reason")))
        else:
            soft.append("%s：%s" % (key, m.get("state")))
    for key in sorted(set(got) - set(disk)):
        if (got[key] or {}).get("state") == "loaded":
            bad.append("%s：載入了，但磁碟沒有 module.json" % key)
    detail = "磁碟 %d 個模組，載入器 %d 個" % (len(disk), len(got))
    if soft:
        detail += "；未載入（停用／未授權，不算失敗）：" + "、".join(soft)
    if bad:
        return False, "；".join(bad) + "。" + detail, "fail"
    return True, detail, "ok"


def _check_logs(install_root, forbid, since_marker="MOTRIX ERP starting"):
    """server.log 最後一次啟動標記之後：不得出現 Traceback 或 forbid 清單的字串。讀不到 ⇒ 警告（驗不到，不假裝通過）。"""
    p = os.path.join(install_root, "backend", "logs", "server.log")
    if not os.path.isfile(p):
        return None, "沒有 logs\\server.log"
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            f.seek(max(0, size - 2 * 1024 * 1024))
            text = f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return None, "讀不到 server.log：%s" % exc
    idx = text.rfind(since_marker)
    seg = text[idx:] if idx >= 0 else text
    hits = []
    if "Traceback (most recent call last)" in seg:
        hits.append("Traceback ×%d" % seg.count("Traceback (most recent call last)"))
    for s in forbid or ():
        if s and s in seg:
            hits.append("「%s」" % s)
    scope = "最後一次啟動之後" if idx >= 0 else "（找不到啟動標記，掃描最後 2 MB）"
    return (not hits), ("%s出現：%s" % (scope, "、".join(hits)) if hits else "%s沒有 Traceback 或禁止字串" % scope)


def verify_after(install_root, base_url, before, expected_diff, expectations, apply_result, db_path=None,
                 http_status=None, apply_started=None, deployed_commit=None):
    """套用後的自動驗證（取代步驟檔「步驟 3」的人工清單）。唯讀。⇒ dict：ok（沒有任何 fail）、items、warnings、actual_diff。

    驗證項：健康（/api/ping）、integrity_check、預期差異 vs 實際差異、模組載入版號＝磁碟、server.log、已部署 commit、
    與包專屬的 pages／auth_required／files／log_forbid／watch_settings（有附 a1_expectations.json 才有）。
    任何 fail ⇒ ok False；**本函式不回滾、不重試、不修**。"""
    http_status = http_status or _http_status
    db = db_path or db_paths(install_root)[0]
    items, warnings = [], []
    ex = expectations or {}
    st = http_status(base_url + "/api/ping")
    _item(items, "ping", st == 200, "健康檢查 /api/ping", "HTTP %s" % st)
    try:
        res = integrity_check(db)
        _item(items, "integrity", res == "ok", "資料庫 integrity_check", res[:200])
    except Exception as exc:                                        # noqa: BLE001
        _item(items, "integrity", False, "資料庫 integrity_check", "無法執行：%s" % exc)
    actual = None
    try:
        after = capture_state(db, ex.get("watch_settings") or ())
        actual = diff_state(before, after)
        if expected_diff is None:                                   # 沒有預演（REQUIRE_REHEARSAL 關閉）：沒有預期可比，明說，不假裝通過
            _item(items, "db_diff", True, "資料庫變更與預演預期相符", "沒有預演結果，未比對", severity="warn")
            warnings.append("沒有預演結果，資料庫變更未與預期比對")
        else:
            fails, warns = compare_diffs(expected_diff, actual)
            _item(items, "db_diff", not fails, "資料庫變更與預演預期相符", "；".join(fails[:8]) if fails else "預演預期的變更全部發生，沒有多出或缺少")
            warnings.extend(warns)
    except Exception as exc:                                        # noqa: BLE001 — 驗不到 ≠ 通過
        _item(items, "db_diff", False, "資料庫變更與預演預期相符", "無法擷取套用後的狀態：%s" % exc)
    ok, detail, sev = _check_modules(install_root, apply_started)
    _item(items, "modules", ok, "模組載入版號與磁碟一致", detail, sev)
    ok, detail = _check_logs(install_root, ex.get("log_forbid"))
    if ok is None:
        _item(items, "logs", True, "server.log 掃描", detail, severity="warn")
        warnings.append("server.log 沒有掃描：" + detail)
    else:
        _item(items, "logs", ok, "server.log 掃描", detail)
    commit = (apply_result or {}).get("commit")
    try:
        dc = json.load(open(os.path.join(install_root, "backend", ".deployed_commit.json"), encoding="utf-8-sig")).get("commit")
    except (OSError, ValueError):
        dc = None
    want = deployed_commit or commit
    _item(items, "deployed_commit", bool(dc) and bool(want) and str(dc) == str(want), "已部署 commit 與包一致",
          "已部署 %s，包 %s" % (str(dc)[:8], str(want)[:8]))
    for pth in ex.get("pages") or []:
        s = http_status(base_url + pth)
        _item(items, "page:" + pth, s == 200, "頁面可開 %s" % pth, "HTTP %s" % s)
    for req in ex.get("auth_required") or []:
        m, pth = (req.get("method") or "GET").upper(), req.get("path") or ""
        s = http_status(base_url + pth, m)
        _item(items, "auth:%s %s" % (m, pth), s == 401, "未登入須回 401：%s %s" % (m, pth), "HTTP %s" % s)
    for rel in ex.get("files") or []:
        okf = os.path.isfile(os.path.join(install_root, rel))
        _item(items, "file:" + rel, okf, "檔案存在 %s" % rel, "" if okf else "不存在")
    return {"ok": all(i["ok"] for i in items), "items": items, "warnings": warnings, "actual_diff": actual}


# ══════════════════════════════════════════════════════════════════
# 稽核（JSONL 雜湊鏈＋ERP audit_log 一列）
# ══════════════════════════════════════════════════════════════════

_audit_lock = threading.Lock()


def audit_event(install_root, event):
    """附加一筆到 backend/logs/a1_audit.jsonl，每筆含前一筆的雜湊（竄改單筆可偵測）。event 不得含密碼／token／設定值。⇒ 雜湊或 None（寫失敗）。"""
    path = os.path.join(install_root, "backend", "logs", "a1_audit.jsonl")
    with _audit_lock:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            prev, torn = "", False
            if os.path.isfile(path):
                raw = open(path, "rb").read()
                torn = bool(raw) and not raw.endswith(b"\n")                    # 上次寫到一半：先補換行，免得新的一筆黏在殘行後面
                for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
                    if not line.strip():
                        continue
                    try:
                        prev = str(json.loads(line).get("hash", ""))
                        break
                    except (ValueError, AttributeError):
                        continue                                                # 殘行／壞行跳過，接在最後一筆讀得懂的後面（鏈驗證會把壞行報出來）
            rec = dict(event, at=datetime.now().isoformat(timespec="seconds"), prev=prev)
            body = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            rec["hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
            with open(path, "a", encoding="utf-8") as f:
                f.write(("\n" if torn else "") + json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
            return rec["hash"]
        except OSError:
            return None


def audit_chain_problems(path, anchors=()):
    """驗證 JSONL 雜湊鏈。⇒ 問題清單（空＝完整）。
    第一行的前筆雜湊必須是空（否則開頭被刪或換過）；`anchors`＝另存在別處的鏈頭雜湊（ERP audit_log 的 detail、交付資料夾的 <包名>.a1.json）：
    每一個都必須出現在鏈裡，否則是尾端被截斷或整條重算過。鏈本身沒有金鑰，防不了有寫入權的人整條重算——靠錨點在別處留底。"""
    problems, prev, seen = [], "", set()
    try:
        lines = [x for x in open(path, encoding="utf-8").read().splitlines() if x.strip()]
    except OSError as exc:
        return ["讀不到 %s：%s" % (path, exc)]
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except ValueError:
            problems.append("第 %d 行讀不懂" % i)
            continue
        h = rec.pop("hash", None)
        body = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        if h != hashlib.sha256(body.encode("utf-8")).hexdigest():
            problems.append("第 %d 行雜湊不符（內容被改動）" % i)
        if rec.get("prev") != prev:
            problems.append("第 %d 行的前筆雜湊對不上（有行被刪、被換，或開頭被截掉）" % i)
        prev = h
        seen.add(h)
    for a in anchors or ():
        if a and a not in seen:
            problems.append("錨點雜湊 %s… 不在鏈裡（尾端被截斷，或整條被重算）" % str(a)[:12])
    return problems


# ══════════════════════════════════════════════════════════════════
# 報告
# ══════════════════════════════════════════════════════════════════

def rollback_hint(install_root, apply_result):
    """回滾指令的文字（**只顯示、本檔永不執行**）。預設只回程式、資料庫保留；`-IncludeDatabase` 需另行確認，這裡不附。"""
    ts = (apply_result or {}).get("timestamp") or "<時間戳>"
    script = os.path.join(install_root, "backend", "tools", "rollback_update.ps1")
    return 'powershell -ExecutionPolicy Bypass -File "%s" -SnapshotTimestamp %s' % (script, ts)


def render_report(rec):
    """⇒ Markdown（正式機回報 摘要.md 的形狀）。rec 來自 apply_with_verification。不含密碼／token／設定值。"""
    r = rec.get("result") or {}
    v = rec.get("verify") or {}
    lines = ["# 套用報告：%s" % rec.get("name"),
             "",
             "- **結果**：%s" % {"succeeded": "成功", "verify_failed": "已套用，但事後驗證有項目未通過或沒有完成", "failed": "失敗", "crashed": "程序中斷"}.get(rec.get("outcome"), rec.get("outcome")),
             "- 套用者：%s" % (rec.get("by") or "（未記錄）"),
             "- commit：%s" % (r.get("commit") or "（無）"),
             "- 腳本結果：status=%s，rolled_back=%s，service=%s，exit=%s" % (r.get("status"), r.get("rolled_back"), r.get("service"), r.get("exit")),
             "- 開始／結束：%s／%s" % (r.get("started_at"), r.get("finished_at")),
             "- 實際停機（/api/ping 不通的區間）：%s" % (("%d 秒" % rec["downtime_seconds"]) if rec.get("downtime_seconds") is not None else "未量到"),
             "- 預演：%s" % (("通過，%s 秒，主庫 %s MB" % (rec["rehearsal"].get("seconds"), rec["rehearsal"].get("db_mb"))) if rec.get("rehearsal") else "（沒有）"),
             ""]
    if rec.get("problems"):
        lines += ["## 問題", ""] + ["- %s" % p for p in rec["problems"]] + [""]
    if v:
        lines += ["## 事後驗證", "", "| 項目 | 結果 | 說明 |", "|---|---|---|"]
        for it in v.get("items", []):
            mark = {"ok": "通過", "warn": "警告", "fail": "未通過"}.get(it.get("severity"), "?")
            lines.append("| %s | %s | %s |" % (it["title"].replace("|", "／"), mark, str(it.get("detail") or "").replace("|", "／").replace("\n", " ")))
        lines.append("")
        if v.get("warnings"):
            lines += ["### 警告（不擋，請人工看一眼）", ""] + ["- %s" % w for w in v["warnings"]] + [""]
    elif rec.get("outcome") != "succeeded":
        lines += ["## 事後驗證", "", "沒有做事後驗證（套用沒有成功，或套用腳本回報的狀態無法確認成功）。", ""]
    if rec.get("outcome") != "succeeded":
        lines += ["## 後續處置（停下，由人決定）", "",
                  "- 系統**不會**自動回滾（套用腳本內建的健康檢查失敗回滾除外，結果見上方 rolled_back）。",
                  "- 需要回滾時由使用者或 PM 明確指示後，人工執行（預設只回程式、資料庫保留）：",
                  "", "    " + rollback_hint(rec.get("install_root") or "", r), ""]
    if rec.get("notes"):
        lines += ["## 注記", ""] + ["- %s" % n for n in rec["notes"]] + [""]
    return "\n".join(lines)


def write_report(install_root, rec, stamp=None):
    """寫 backend/logs/a1_report_<時間戳>.md／.json。⇒ (md路徑, json路徑) 或 (None, None)。報告內容不含秘密。"""
    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join(install_root, "backend", "logs")
    try:
        os.makedirs(d, exist_ok=True)
        md, js = os.path.join(d, "a1_report_%s.md" % stamp), os.path.join(d, "a1_report_%s.json" % stamp)
        with open(md, "w", encoding="utf-8") as f:
            f.write(render_report(rec))
        safe = {k: v for k, v in rec.items() if k not in ("before",)}
        with open(js, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
        return md, js
    except OSError:
        return None, None


def write_summary_next_to(result_json_path, rec):
    """`delivery.write_back` 回傳的 <包名>.result.json 旁邊寫 <包名>.a1.json（包名已由 write_back 驗過）。⇒ 路徑或 None。
    開發機端 `read_results` 只認 `.result.json`，不會被這個旁檔干擾。"""
    suffix = ".result.json"
    if not str(result_json_path).endswith(suffix):
        return None
    final = str(result_json_path)[:-len(suffix)] + ".a1.json"
    try:
        with open(final + ".tmp", "w", encoding="utf-8") as f:
            json.dump(summary_for_write_back(rec), f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(final + ".tmp", final)
        return final
    except OSError:
        return None


def summary_for_write_back(rec):
    """寫回交付資料夾 results\\<包名>.a1.json 的白名單欄位（不含路徑、設定、報告全文）。"""
    v = rec.get("verify") or {}
    return {"name": rec.get("name"), "outcome": rec.get("outcome"), "verify_ok": v.get("ok") if v else None,
            "chain_head": rec.get("chain_head"),
            "failed_items": [i["id"] for i in v.get("items", []) if not i["ok"]] if v else [],
            "warnings": len(v.get("warnings", [])) if v else 0,
            "downtime_seconds": rec.get("downtime_seconds"), "rehearsal_seconds": (rec.get("rehearsal") or {}).get("seconds"),
            "rehearsal_digest": (rec.get("rehearsal") or {}).get("digest")}


# ══════════════════════════════════════════════════════════════════
# 串接：套用前記錄 → 套用 → 事後驗證 → 報告／稽核
# ══════════════════════════════════════════════════════════════════

class _DowntimeMonitor(threading.Thread):
    """套用期間每 PING_POLL_SEC 秒打一次 ping，記第一次不通到之後第一次恢復的區間（量到的是下限＋一個輪詢間隔）。"""

    def __init__(self, ping, clock=time.time, poll=PING_POLL_SEC):
        super().__init__(daemon=True)
        self.ping, self.clock, self.poll = ping, clock, poll
        self.stop_flag = threading.Event()
        self.down_at = None
        self.up_at = None

    def run(self):
        while not self.stop_flag.is_set():
            ok = False
            try:
                ok = bool(self.ping())
            except Exception:                                       # noqa: BLE001
                ok = False
            now = self.clock()
            if not ok and self.down_at is None:
                self.down_at = now
            elif ok and self.down_at is not None and self.up_at is None:
                self.up_at = now
            self.stop_flag.wait(self.poll)

    def seconds(self):
        if self.down_at is None:
            return 0
        return int(round((self.up_at or self.clock()) - self.down_at))


def apply_with_verification(name, staged, install_root, apply_fn, rehearsal, who, base_url,
                            http_status=None, clock=None, poll=PING_POLL_SEC, deployed_commit=None):
    """串起來。apply_fn()＝呼叫端（儀表板）包好的 `delivery.apply_staged(...)`（判定函式留在儀表板，HC1c）。
    apply_fn() ⇒ dict（started／outcome／problems／result／lock）。
    ⇒ rec（dashboard 放進 `_delivery_state["last"]`）：name、outcome（succeeded／verify_failed／failed）、started、
    problems、result、lock、verify、downtime_seconds、rehearsal（精簡）、report、by。

    流程：預檢（失敗⇒不套用）→ 記錄套用前狀態＋稽核「開始」→ 啟停機監測 → apply_fn → 只有「腳本成功（rolled_back=applied）」才做事後驗證。
    事後驗證失敗 ⇒ outcome＝verify_failed，**不回滾**。報告／稽核／ERP audit_log 由呼叫端接著呼叫 `finish(rec, install_root)`。"""
    clock = clock or time.time
    http_status = http_status or _http_status
    db, _lic = db_paths(install_root)
    rec = {"name": name, "outcome": "failed", "started": False, "problems": [], "result": None, "lock": None,
           "verify": None, "downtime_seconds": None, "report": None, "by": who, "install_root": install_root,
           "rehearsal": {k: rehearsal.get(k) for k in ("seconds", "db_mb", "digest", "summary", "at")} if rehearsal else None,
           "notes": list((rehearsal or {}).get("notes") or [])}
    def blocked(problems):
        rec["problems"] = list(problems)
        rec["stopped_at"] = "套用前檢查，沒有開始套用"
        audit_event(install_root, {"event": "apply_blocked", "by": who, "problems": rec["problems"]})
        return rec

    pre = precheck(install_root, db)
    if not is_loopback_url(base_url):
        pre = list(pre) + ["ERP 位址不是本機（%s）：事後驗證只准打本機" % base_url]
    if pre:
        return blocked(["套用前預檢未通過，沒有開始套用："] + pre)
    expectations, exp_notes = load_expectations(os.path.join(staged, "payload"))
    rec["notes"].extend(exp_notes)
    try:
        before = capture_state(db, expectations.get("watch_settings") or ())
    except Exception as exc:                                        # noqa: BLE001
        return blocked(["無法記錄套用前的資料庫狀態，沒有開始套用：%s" % exc])
    # 預演之後正式庫結構若變動過（模組更新、手動改動）：預演的預期差異已不適用，不等套用完才發現
    rh_hash = (rehearsal or {}).get("before_hash")
    if rehearsal is not None and rh_hash and rh_hash != structure_hash(before):
        return blocked(["預演之後正式庫結構已變動，預演結果不再適用，請重新預演"])
    # 稽核寫不進去就不套用：這是一次動正式機的操作，沒有紀錄不准做
    if not audit_event(install_root, {"event": "apply_start", "by": who, "rehearsal_digest": (rehearsal or {}).get("digest")}):
        return blocked(["稽核紀錄（backend\\logs\\a1_audit.jsonl）寫不進去，沒有開始套用：請先排除磁碟或權限問題"])
    mon = _DowntimeMonitor(lambda: http_status(base_url + "/api/ping") == 200, clock=clock, poll=poll)
    mon.start()
    t_start = clock()
    started_dt = datetime.fromtimestamp(t_start)
    try:
        r = apply_fn()
    finally:
        mon.stop_flag.set()
        mon.join(timeout=5)
    rec.update(started=r.get("started", False), problems=list(r.get("problems") or []), result=r.get("result"),
               lock=r.get("lock"), outcome=r.get("outcome") or "failed", downtime_seconds=mon.seconds() if r.get("started") else None)
    res = rec["result"] or {}
    # apply_update.ps1 的 rolled_back（＝$script:ProdState）成功出口只有 "applied"；其他值（restored／applied_no_restore…）
    # 都是失敗路徑。判定為成功（decide_outcome）卻不是 "applied" ⇒ 不猜，不做事後驗證，交給人看。
    script_ok = rec["started"] and rec["outcome"] == "succeeded" and res.get("rolled_back") == SUCCESS_STATE
    if rec["started"] and rec["outcome"] == "succeeded" and not script_ok:
        # 沒做驗證就不准記成功：判定成功卻不是 applied ⇒ 記成「未驗證」（verify_failed），寫回開發機時是 failed，報告列出停下來的後續處置
        rec["outcome"] = "verify_failed"
        rec["problems"].append("套用腳本回報的 rolled_back=%r 不是 %r，沒有做事後驗證：請人工確認現況" % (res.get("rolled_back"), SUCCESS_STATE))
    if script_ok:
        try:
            v = verify_after(install_root, base_url, before, (rehearsal or {}).get("expected_diff"),
                             expectations, res, db, http_status, started_dt, deployed_commit)
        except Exception as exc:                                    # noqa: BLE001 — 驗證程式自己出錯＝不算通過
            v = {"ok": False, "items": [{"id": "verify", "ok": False, "severity": "fail", "title": "事後驗證程序", "detail": "%s: %s" % (type(exc).__name__, exc)}],
                 "warnings": [], "actual_diff": None}
        rec["verify"] = {k: v[k] for k in ("ok", "items", "warnings")}
        if not v["ok"]:
            rec["outcome"] = "verify_failed"
    return rec


def failed_item_ids(rec):
    return [i["id"] for i in (rec.get("verify") or {}).get("items", []) if not i["ok"]]


def stopped_at(rec):
    """「停在哪一步」的一句話（給通知與報告；只放步驟名稱，不放路徑、設定或錯誤全文）。"""
    if rec.get("stopped_at"):
        return rec["stopped_at"]
    out, res = rec.get("outcome"), rec.get("result") or {}
    if out == "succeeded":
        return "全部完成（預檢、套用、事後驗證）"
    if out == "crashed":
        return "套用程序中途出錯" if rec.get("started") else "套用程序在開始前出錯"
    if not rec.get("started"):
        return "套用前檢查，沒有開始套用"
    if out == "verify_failed":
        if rec.get("verify"):
            return "事後驗證（%d 項未通過）" % len(failed_item_ids(rec))
        return "事後驗證（腳本回報的狀態無法確認成功，沒有驗證）"
    return "套用腳本（結果：%s）" % (res.get("rolled_back") or res.get("status") or "未取得")


_OUTCOME_LABEL = {"succeeded": "成功", "verify_failed": "已套用，事後驗證未通過或沒有完成", "failed": "失敗", "crashed": "程序中斷"}


def outcome_label(rec):
    if rec.get("outcome") == "failed" and not rec.get("started"):
        return "被擋下（沒有開始套用）"
    return _OUTCOME_LABEL.get(rec.get("outcome"), str(rec.get("outcome")))


def finish(rec, install_root, db_path=None):
    """報告＋稽核收尾（apply_with_verification 之後呼叫；分開是為了讓儀表板先放 name 再收尾）。⇒ rec（補上 report、chain_head）。
    `chain_head`＝apply_end 那一筆稽核的雜湊：隨後寫進 ERP audit_log 與 <包名>.a1.json（交付資料夾＝另一處留底），用來偵測尾端截斷。
    ERP audit_log／站內通知／Email／LINE 由 `notify_result` 在這之後處理（它們都在新版的後端行程裡做）。"""
    md, js = write_report(install_root, rec)
    rec["report"] = {"md": md, "json": js}
    ev = {"event": "apply_end", "by": rec.get("by"), "name": rec.get("name"), "outcome": rec.get("outcome"),
          "verify_ok": (rec.get("verify") or {}).get("ok"), "downtime_seconds": rec.get("downtime_seconds"),
          "failed_items": failed_item_ids(rec)}
    rec["chain_head"] = audit_event(install_root, ev)
    if rec["chain_head"] is None:
        rec["problems"] = list(rec.get("problems") or []) + ["稽核紀錄寫不進去（apply_end）：請查 backend\\logs\\a1_audit.jsonl"]
    return rec


def finish_crashed(rec, install_root, exc):
    """套用程序本身丟出例外（例如 apply_staged 找不到腳本）：補上 apply_end（outcome=crashed）與一份報告，讓 apply_start 有對應的結尾。"""
    rec["outcome"] = "crashed"
    rec["problems"] = list(rec.get("problems") or []) + ["套用程序本身出錯：%s: %s" % (type(exc).__name__, exc)]
    try:
        return finish(rec, install_root)
    except Exception:                                               # noqa: BLE001 — 連收尾都失敗：至少留一筆稽核
        rec["chain_head"] = audit_event(install_root, {"event": "apply_end", "by": rec.get("by"), "name": rec.get("name"), "outcome": "crashed"})
        return rec


# ══════════════════════════════════════════════════════════════════
# 通知與 ERP 稽核（交給新版後端行程：不把 ERP 的 helpers 載進儀表板）
# ══════════════════════════════════════════════════════════════════

NOTIFY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a1_notify.py")
NOTIFY_TIMEOUT_SEC = 180


def build_notice(rec):
    """通知與 ERP 稽核的內容（純函式）。只放：包名、結果、停在哪一步、未通過項目 id、報告檔名、套用者、鏈頭雜湊。
    **不放**回滾指令、路徑（報告只給檔名）、設定值、密碼、錯誤全文。"""
    md = (rec.get("report") or {}).get("md")
    report_name = os.path.basename(md) if md else ""
    ids = failed_item_ids(rec)
    ok = rec.get("outcome") == "succeeded"
    rows = [("更新包", str(rec.get("name") or "")), ("結果", outcome_label(rec)), ("停在哪一步", stopped_at(rec))]
    if ids:
        rows.append(("未通過項目", "、".join(ids)))
    rows.append(("報告檔", report_name or "（沒有產生）"))
    return {
        "name": str(rec.get("name") or ""), "outcome": rec.get("outcome"), "by": rec.get("by") or "",
        "ok": ok, "title": "系統更新套用%s" % ("完成" if ok else "沒有成功"), "rows": rows,
        "reason": "更新包 %s：%s。" % (rec.get("name"), outcome_label(rec)),
        "badge_text": "更新完成" if ok else "需要處理", "badge_color": "#16A34A" if ok else "#DC2626",
        "failed_items": ids, "report_name": report_name, "chain_head": rec.get("chain_head") or "",
        "downtime_seconds": rec.get("downtime_seconds"), "stopped_at": stopped_at(rec),
        "message": "%s：%s%s；報告 %s" % (rec.get("name"), outcome_label(rec), ("；未通過 " + "、".join(ids)) if ids else "", report_name or "（沒有產生）"),
    }


def notify_result(rec, install_root, run=None):
    """套用結束後（成功、驗證未通過、失敗、被擋、程序中斷都要）：請**安裝目錄裡的後端**寫 ERP 稽核列、對最高管理者發站內通知、Email、LINE
    （`backend/tools/a1_notify.py`，沿用登入失敗告警的 `email_notify.send_registered` 機制；收件人與 LINE 勾選照通知收件人設定）。
    ⇒ dict（各項是否完成）；永不丟例外。失敗只記在 rec["problems"]／稽核，**不影響套用結果**（報告檔與畫面是備援）。
    `run(cmd, env, payload_json) -> (rc, text)`：測試注入點。"""
    notice = build_notice(rec)
    result = {"ok": False, "detail": ""}
    backend = os.path.join(install_root, "backend")
    try:
        cmd = [python_exe(), "-B", NOTIFY_SCRIPT, backend]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        payload = json.dumps(notice, ensure_ascii=False)
        if run is not None:
            rc, text = run(cmd, env, payload)
        else:
            r = subprocess.run(cmd, input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=NOTIFY_TIMEOUT_SEC, env=env, cwd=backend, creationflags=CREATE_NO_WINDOW)
            rc, text = r.returncode, (r.stdout or "") + (r.stderr or "")
        marker = [ln for ln in text.splitlines() if ln.startswith("A1_NOTIFY_RESULT ")]
        got = json.loads(marker[-1][len("A1_NOTIFY_RESULT "):]) if marker else {}
        result = {"ok": rc == 0 and bool(got), "detail": got if got else "後端沒有回報結果（結束碼 %s）" % rc}
    except Exception as exc:                                        # noqa: BLE001
        result = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, exc)}
    rec["notified"] = result
    try:
        d = result["detail"] if isinstance(result["detail"], dict) else {"error": str(result["detail"])[:200]}
        audit_event(install_root, {"event": "apply_notified", "name": rec.get("name"), "ok": result["ok"],
                                   "parts": {k: d.get(k) for k in ("audit_log", "in_app", "mail") if k in d}, "error": d.get("error")})
    except Exception:                                               # noqa: BLE001
        pass
    if not result["ok"]:
        rec["problems"] = list(rec.get("problems") or []) + ["通知／ERP 稽核沒有全部完成（報告檔與本畫面是備援）：%s" % str(result["detail"])[:200]]
    return result
