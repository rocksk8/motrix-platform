# -*- coding: utf-8 -*-
"""第 44 班套用演練（基線＝prod/89206122＝第 43 班已上線的正式機現況；新版＝t44-integration 候選包）。
由 drill_train35b 的零件組成（安裝／套用／回滾／A→C→E→B→R 沿用 drill_train_apply），種子與判準換成 44 的。

44 內容（本演練關心的）：core migration 8（`notifications.link`＋兩個索引）、站內通知鈴鐺（所有角色、link、90 天清除）、
職責角色 R1 等價（上線前後每個帳號的生效權限逐人相同）、套用包完整性、模組探針乾淨。其餘分支（多附件、出納附件預覽、獎金信…）
以 `--expect-file`／`--probe-401` 做靜態存在與路由存在題（併入 t44-integration 與否由主持決定）。

判準（44_*；編號對應 docs/platform/plans/T44-REHEARSAL-NOTES.md §4）：
  44_0  包完整性：verify_ok、problems 空、verify_package rc 0、payload 無 __pycache__／pyc、deploy_manifest.verification 有且（scoped 時）base＝基線完整 SHA
  44_1  core migration：module_schema_versions[core]＝--expect-core（預設 8）；基線值記錄（預期 7）
  44_2  notifications.link TEXT NOT NULL DEFAULT ''、索引 idx_notifications_user_created／idx_notifications_created 存在
  44_3  90 天內的通知列：逐列內容同基線、link=''；（超過 90 天的舊列會在啟動時的每日檢查被清掉＝新功能，不算遺失）
  44_4  migrate_like_startup.py ⇒ MIGRATE_LIKE_STARTUP_OK（冪等、模組 migration 完成）
  44_5  R1 等價：套用前快照（基線安裝）、套用後 verify ⇒ 結束碼 0 且輸出含 PASS
  44_6  鈴鐺 API：一般使用者／管理員 GET /api/notifications/mine 200、每筆有 link 鍵；新插入的帶 link 列原樣回傳
  44_7  90 天清除：插一筆 120 天前的列後 purge_old_notifications() 只刪超過 90 天的列（回傳值＝該數），其餘保留
  44_8  探針乾淨：安裝後各模組 provides.probes／pages 全部預期碼（在＝200，缺席＝404）、undeclared_probes 沒有比基線多
  44_9  --probe-401 路由存在（未登入 401）、--expect-file 靜態存在
  C 之後：core 回到基線值、notifications 沒有 link 欄、筆數同基線；B 之後：程式檔逐檔相同（沿用 35a）、舊程式讀得了帶 link 欄的庫（鈴鐺 API 200）
其餘沿用 checks31（無 traceback、單一監聽行程、模組版本差集、模組載入…）；44 之前班次專屬的舊題記錄在 _STALE 並說明理由。
用法（.venv312）：
  python tools/platform/drill_train44.py --delivery-root <演練交付資料夾> --name <包名> --new-commit <SHA> --pubkey-file <演練公鑰.pem> \
         [--drill-root <演練目錄>] [--port 6744] [--runs A,C,E,B] [--expect-db-version 116] [--expect-core 8] \
         [--seed-db <開發庫複本>] [--probe-401 PATH ...] [--expect-file REL ...] [--keep]
紅線同 TRAIN29-DRILL：不碰正式機／正式金鑰／正式資料庫；全合成資料（--seed-db 只匯入 users／notifications 兩張表的列，來源唯讀）；
只綁 127.0.0.1；跑完清（R 之後服務是起著的：清除前一定要先停）。演練交付資料夾由拋棄式金鑰簽發，正式金鑰簽章驗證不在本演練範圍。
"""
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend" / "tools"))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402
import drill_train35a as T35A  # noqa: E402
import product_drill as PD  # noqa: E402

T = T30.T
DM = T.DM
TRAIN = {"number": "44", "base": "89206122", "db_version": 116, "core": 8}
_FAILED = T35A._FAILED
_BASE = T35A._BASE
_PUB = T35A._PUB
_CTX = {"opts": {"probe_401": [], "expect_file": [], "expect_core": TRAIN["core"], "seed_db": None}}

#: 44 之前班次專屬、在這個基線（89206122）上不成立的舊題；理由逐項寫明。第一次實跑若冒出別的舊題：先看失敗證據，確認是舊班次專屬才加進來（不放寬 44 題）
_STALE = {
    "15_designer_default_off": "D12 設計器預設改開（34 班起）",
    "16_subcontract_schema_stays_3": "承攬商 schema 已是 5",
    "16_material_tables_exist_and_empty": "材料申請審核列種子會寫表，表不再是空的",
    "9c_legacy_dispatch_untouched": "第 30 班專屬（舊派發單不動）；基線已含兩段審核",
}
#: 通知舊列：基線 notifications 欄位（沒有 link）
_NOTIF_COLS = ("username", "type", "ref_id", "ref_label", "message", "is_read", "created_at")
#: R1 等價要涵蓋的帳號種類（含舊式 cashier／finance／financial_view 模組勾選、停用、各角色）
_R1_USERS = [
    ("d44_sales_case", "sales", '["case_manage","quotation"]', 1), ("d44_sales_none", "sales", "[]", 1),
    ("d44_eng", "engineer", '["case_manage"]', 1), ("d44_admin", "admin", "[]", 1),
    ("d44_fin_role", "finance", "[]", 1), ("d44_sales_cashier", "sales", '["cashier"]', 1),
    ("d44_sales_finance", "sales", '["finance"]', 1), ("d44_sales_fv", "sales", '["financial_view"]', 1),
    ("d44_eng_payslip", "engineer", '["payslip","cashier"]', 1), ("d44_inactive", "sales", '["case_manage"]', 0),
]
_PW = "Drill-D44-Pass!9"


def _sha(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _notif_rows(root):
    c = T.ro(root)
    try:
        return [dict(r) for r in c.execute("SELECT %s FROM notifications ORDER BY id" % ",".join(("id",) + _NOTIF_COLS)).fetchall()]
    finally:
        c.close()


def seed44(root, port):
    """基線（89206122 程式）上的 44 種子：R1 用的各種帳號＋每人三筆站內通知（舊／中／新，日期相對於現在，供 90 天清除題）。"""
    names = {u: _PW for u, *_ in _R1_USERS}
    hashes = T30._hash_cmds(root, names)
    now = datetime.now()
    stamps = {"old": (now - timedelta(days=120)).isoformat(timespec="seconds"), "mid": (now - timedelta(days=30)).isoformat(timespec="seconds"),
              "new": (now - timedelta(days=1)).isoformat(timespec="seconds")}
    c = T.rw(root)
    try:
        for u, role, mods, active in _R1_USERS:
            c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password)"
                      " VALUES (?,?,?,?,?,?,?,0)", (u, hashes[u], u, role, mods, active, stamps["mid"]))
        targets = [u for u, *_ in _R1_USERS] + [T30.PLAIN[0]]
        n = 0
        for u in targets:
            for tag, read in (("old", 1), ("mid", 0), ("new", 0)):
                c.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES (?,?,?,?,?,?,?)",
                          (u, "drill_%s" % tag, "D44-%s" % tag, "DRILL", "演練通知（%s）" % tag, read, stamps[tag]))
                n += 1
        c.commit()
    finally:
        c.close()
    return {"r1_users": len(_R1_USERS), "notifications": n, "old_rows": len(targets), "stamps": stamps}


def import_seed_db(root, path):
    """--seed-db：只把來源（唯讀）的 users／notifications 列匯進安裝的庫（略過已存在的帳號、不匯入 id）。回匯入筆數。"""
    src = sqlite3.connect("file:%s?mode=ro" % str(path).replace("\\", "/"), uri=True)
    src.row_factory = sqlite3.Row
    dst = T.rw(root)
    got = {"users": 0, "notifications": 0}
    try:
        for tbl in ("users", "notifications"):
            dcols = {r[1] for r in dst.execute("PRAGMA table_info(%s)" % tbl)}
            try:
                rows = src.execute("SELECT * FROM %s" % tbl).fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                d = {k: r[k] for k in r.keys() if k in dcols and k != "id"}
                if tbl == "users" and dst.execute("SELECT 1 FROM users WHERE username=?", (d.get("username"),)).fetchone():
                    continue
                if d:
                    dst.execute("INSERT INTO %s (%s) VALUES (%s)" % (tbl, ",".join(d), ",".join("?" * len(d))), list(d.values()))
                    got[tbl] += 1
        dst.commit()
    finally:
        dst.close()
        src.close()
    return got


def _run_tool(root, script, *args, timeout=300):
    cp = subprocess.run([sys.executable, str(Path(root) / "backend" / "tools" / script), *args], cwd=str(Path(root) / "backend"),
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return cp.returncode, (cp.stdout + cp.stderr)


def equiv_snapshot(root, out):
    return _run_tool(root, "duty_roles_equivalence.py", "snapshot", "--out", str(out), "--db", str(Path(root) / "backend" / "motrix_erp.db"))


def equiv_verify(root, snap):
    return _run_tool(root, "duty_roles_equivalence.py", "verify", "--snapshot", str(snap), "--db", str(Path(root) / "backend" / "motrix_erp.db"))


def db_facts(root):
    c = T.ro(root)
    try:
        sv = {r[0]: r[1] for r in c.execute("SELECT module, version FROM module_schema_versions")} if T.table_exists(c, "module_schema_versions") else {}
        cols = [dict(name=r[1], type=r[2], notnull=r[3], dflt=r[4]) for r in c.execute("PRAGMA table_info(notifications)")]
        idx = {r[1] for r in c.execute("PRAGMA index_list(notifications)")}
        return {"core": sv.get("core"), "cols": cols, "indexes": idx, "count": T.count(c, "notifications")}
    finally:
        c.close()


def deliver44(delivery_root, name, root, base):
    """沿用 35a 的取包／驗章／verify_package，再加：payload 無 pyc、deploy_manifest.verification 檢查（結果存 _CTX 給 44_0）。"""
    payload, rep = T35A.deliver35(delivery_root, name, root, base)
    pycs = [p.relative_to(payload).as_posix() for p in Path(payload).rglob("*") if p.name == "__pycache__" or p.suffix == ".pyc"]
    man = {}
    try:
        man = json.loads((Path(payload) / "deploy_manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    ver = man.get("verification") or {}
    dc = json.loads((Path(root) / "backend" / ".deployed_commit.json").read_text(encoding="utf-8-sig")).get("commit") or ""
    scoped_base = ((ver.get("scoped") or {}).get("base") or "") if ver.get("mode") == "scoped" else None
    rep.update(pycs=pycs[:10], pyc_count=len(pycs), verification_mode=ver.get("mode"), scoped_base=scoped_base, deployed_commit=dc,
               base_ok=(True if scoped_base is None else (bool(scoped_base) and scoped_base.startswith(dc[:8]) and (len(dc) < 40 or scoped_base == dc))))
    _CTX["deliver"] = rep
    return payload, rep


def _bell(port, token):
    s, d = T.api(port, "/api/notifications/mine", token=token)
    items = (d.get("items") if isinstance(d, dict) else d) if s == 200 else None
    return s, items


def probe_clean(root, port, token):
    """安裝後的探針：照安裝的 modules.lock.json／module.json 打 provides.probes（GET）與 pages；在＝200、缺席＝404；undeclared 必須空。"""
    back = Path(root) / "backend"
    lock = json.loads((back / "modules.lock.json").read_text(encoding="utf-8"))
    plan, undeclared = PD.probe_plan(back / "modules", lock)
    bad, n = [], 0
    for mod, present, kind, path in plan:
        n += 1
        if kind == "GET":
            st, _ = T.api(port, path, token=token)
        else:
            st, _ = T.raw_get(port, "/pages/" + path)
        if (st != 200) if present else (st != 404):
            bad.append((mod, kind, path, st, present))
    return {"probes": n, "bad": bad[:20], "bad_count": len(bad), "undeclared": undeclared}


def checks44(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    stale = {k: _STALE[k] for k in _STALE if k in res}
    for k in stale:
        res.pop(k)
    res["44_x_stale_checks_skipped"] = (True, stale)
    o = _CTX["opts"]
    tok = T.login(root, port)[1]
    d = _CTX.get("deliver") or {}
    res["44_0_package_integrity"] = (bool(d.get("verify_ok")) and not d.get("problems") and d.get("verify_package_rc") == 0 and d.get("pyc_count") == 0
                                      and d.get("verification_mode") in ("full", "scoped") and d.get("base_ok"),
                                      {k: d.get(k) for k in ("verify_ok", "problems", "verify_package_rc", "pyc_count", "pycs", "verification_mode", "scoped_base", "deployed_commit", "base_ok", "signature")})
    f = db_facts(root)
    bf = _BASE.get("db") or {}
    res["44_1_core_migration"] = (f["core"] == o["expect_core"] and (bf.get("core") or 0) < o["expect_core"], {"base": bf.get("core"), "now": f["core"], "expected": o["expect_core"]})
    link = next((c for c in f["cols"] if c["name"] == "link"), None)
    want_idx = {"idx_notifications_user_created", "idx_notifications_created"}
    res["44_2_notifications_link_and_indexes"] = (bool(link) and link["type"].upper() == "TEXT" and link["notnull"] == 1 and "''" in str(link["dflt"]) and want_idx <= f["indexes"],
                                                  {"link": link, "indexes": sorted(f["indexes"] & want_idx), "missing": sorted(want_idx - f["indexes"])})
    now_rows = _notif_rows_with_link(root)
    base_rows = _BASE.get("notif_rows") or []
    cutoff0 = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
    # 站內通知 90 天清除在服務啟動時的每日檢查就會跑（daily_checks.run_once 兩種模式都做）⇒ 超過 90 天的舊列在套用後消失是新功能的正常行為；
    # 要保存的是「90 天內」的列：逐列內容與基線相同、link 全為空字串；消失的只能是超過 90 天的列。
    keep_base = [r for r in base_rows if (r["created_at"] or "") >= cutoff0]
    gone = [r for r in base_rows if (r["created_at"] or "") < cutoff0]
    now_plain = [{k: v for k, v in r.items() if k not in ("id", "link")} for r in now_rows]
    base_plain = [{k: v for k, v in r.items()} for r in keep_base]
    only_base = [r for r in base_plain if r not in now_plain]
    res["44_3_recent_notifications_preserved"] = (not only_base and all((r.get("link") or "") == "" for r in now_rows if r["type"].startswith("drill_") and r["type"] != "drill_link"),
                                                  {"base_total": len(base_rows), "base_within_90d": len(keep_base), "base_older_than_90d": len(gone), "now_total": len(now_rows),
                                                   "recent_rows_missing_after_apply": len(only_base), "old_rows_still_present_after_apply": sum(1 for r in gone if r in now_plain)})
    rc, out = _run_tool(root, "migrate_like_startup.py", "--db", str(Path(root) / "backend" / "motrix_erp.db"))
    res["44_4_migrate_like_startup_ok"] = (rc == 0 and "MIGRATE_LIKE_STARTUP_OK" in out, {"rc": rc, "tail": out[-300:]})
    rc, out = equiv_verify(root, _CTX["equiv_snapshot"]) if _CTX.get("equiv_snapshot") else (None, "沒有套用前快照")
    res["44_5_r1_equivalence"] = (rc == 0 and "PASS" in out, {"rc": rc, "tail": out[-400:]})
    # 鈴鐺 API
    ptok = T30._login_as(port, *T30.PLAIN)
    sp, ip = _bell(port, ptok) if ptok else (None, None)
    sa, ia = _bell(port, tok)
    c = T.rw(root)
    try:
        c.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at, link) VALUES (?,?,?,?,?,0,?,?)",
                  (T30.PLAIN[0], "drill_link", "D44-link", "DRILL", "演練帶連結通知", datetime.now().isoformat(timespec="seconds"), "payment-request.html?tab=mine"))
        c.commit()
    finally:
        c.close()
    sp2, ip2 = _bell(port, ptok) if ptok else (None, None)
    got = next((i for i in (ip2 or []) if i.get("type") == "drill_link"), None)
    res["44_6_bell_api_all_roles_with_link"] = (sp == 200 and sa == 200 and isinstance(ip, list) and ip and all("link" in i for i in ip) and bool(got) and got.get("link") == "payment-request.html?tab=mine",
                                                {"plain": sp, "admin": sa, "plain_items": len(ip or []), "all_have_link_key": bool(ip) and all("link" in i for i in ip), "link_roundtrip": (got or {}).get("link")})
    # 90 天清除（函式直接驗）：先插一筆 120 天前的舊列（啟動時的每日檢查已清過種子舊列），呼叫 purge ⇒ 只刪超過 90 天的、其餘保留
    old_ts = (datetime.now() - timedelta(days=120)).isoformat(timespec="seconds")
    c = T.rw(root)
    try:
        c.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at, link) VALUES (?,?,?,?,?,1,?,?)",
                  (T30.PLAIN[0], "drill_purge_old", "D44-old", "DRILL", "演練：120 天前的通知", old_ts, ""))
        c.commit()
    finally:
        c.close()
    before_rows = _notif_rows_with_link(root)
    cutoff = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
    expected_old = sum(1 for r in before_rows if (r["created_at"] or "") < cutoff)
    code = "from helpers.audit import purge_old_notifications as p; print('PURGED', p())"
    cp = subprocess.run([sys.executable, "-c", code], cwd=str(Path(root) / "backend"), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r"PURGED (\d+)", cp.stdout)
    after_rows = _notif_rows_with_link(root)
    res["44_7_purge_90_days"] = (bool(m) and int(m.group(1)) == expected_old and expected_old >= 1 and not any((r["created_at"] or "") < cutoff for r in after_rows)
                                 and len(after_rows) == len(before_rows) - expected_old and not any(r["type"] == "drill_purge_old" for r in after_rows),
                                 {"rc": cp.returncode, "purged": m.group(1) if m else None, "expected_old_rows": expected_old, "before": len(before_rows), "after": len(after_rows), "stderr": cp.stderr[-200:]})
    pc = probe_clean(root, port, tok)
    new_undeclared = sorted(set(pc["undeclared"]) - set(_BASE.get("undeclared") or []))         # 基線就沒宣告 probes 的模組（例如 filehub）不算本班的退步
    pc["undeclared_at_baseline"] = _BASE.get("undeclared")
    pc["new_undeclared"] = new_undeclared
    res["44_8_probes_clean"] = (pc["bad_count"] == 0 and not new_undeclared and pc["probes"] > 0, pc)
    codes = {p: T.api(port, p, None, None, "GET")[0] for p in o["probe_401"]}
    files = {rel: (Path(root) / rel).is_file() for rel in o["expect_file"]}
    res["44_9_extra_routes_and_files"] = (all(v == 401 for v in codes.values()) and all(files.values()), {"routes_unauth": codes, "files": files})
    return res


def _notif_rows_with_link(root):
    c = T.ro(root)
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(notifications)")}
        sel = ",".join(("id",) + _NOTIF_COLS + (("link",) if "link" in cols else ()))
        return [dict(r) for r in c.execute("SELECT %s FROM notifications ORDER BY id" % sel).fetchall()]
    finally:
        c.close()


def _wrap_apply_for_context():
    orig = T.apply_package

    def apply_package(root, port, payload):
        _CTX.update(root=root, port=port, payload=payload)
        return orig(root, port, payload)
    T.apply_package = apply_package


def _wrap_rollback44():
    """C（含資料庫）之後：core 回基線值、notifications 沒有 link 欄、筆數同基線。B（只回程式）之後：舊程式讀得了帶 link 欄的庫（鈴鐺 API 200）。
    程式檔逐檔雜湊沿用 35a 的 _wrap_rollback（B）。"""
    T35A._wrap_rollback()
    orig = T.rollback

    def rollback(root, ts, include_db=False, port=T.PORT):
        rc = orig(root, ts, include_db=include_db, port=port)
        f, bf = db_facts(root), _BASE.get("db") or {}
        if include_db:
            ok = f["core"] == bf.get("core") and not any(c["name"] == "link" for c in f["cols"]) and f["count"] == bf.get("count")
            rc["train44_after_C"] = {"ok": ok, "core": (bf.get("core"), f["core"]), "has_link": any(c["name"] == "link" for c in f["cols"]), "count": (bf.get("count"), f["count"])}
            if not ok:
                _FAILED.append(("C 回滾後資料庫沒有回到基線", rc["train44_after_C"]))
        else:
            ptok = T30._login_as(port, *T30.PLAIN)
            s, items = _bell(port, ptok) if ptok else (None, None)
            ok = s == 200 and any(c["name"] == "link" for c in f["cols"])
            rc["train44_after_B"] = {"ok": ok, "old_code_bell_status": s, "link_column_kept": any(c["name"] == "link" for c in f["cols"])}
            if not ok:
                _FAILED.append(("B 只回程式之後，舊程式讀不了帶 link 欄的庫", rc["train44_after_B"]))
        return rc
    T.rollback = rollback


def _reapply_after_B(_unused=None):
    if not _CTX.get("payload"):
        return
    root, port, payload = _CTX["root"], _CTX["port"], _CTX["payload"]
    try:
        DM.stop(root, port)
    except Exception:                                                  # noqa: BLE001
        pass
    DM.start(root, port)
    rec = T.apply_package(root, port, payload)
    f = db_facts(root)
    rc, out = equiv_verify(root, _CTX["equiv_snapshot"]) if _CTX.get("equiv_snapshot") else (None, "")
    tok = T.login(root, port)[1]
    sp, _items = _bell(port, tok)
    info = {"result": rec.get("result"), "ping": DM.ping(port), "core": f["core"], "r1_rc": rc, "bell": sp,
            "log": T.server_log_tracebacks(root), "listeners": len(T.listening_pids(port))}
    info["ok"] = bool(rec.get("result") and rec["result"].get("status") == "success" and info["ping"] and f["core"] == _CTX["opts"]["expect_core"]
                      and rc == 0 and sp == 200 and info["log"].get("traceback") == 0 and info["listeners"] == 1)
    print("R_REAPPLY::" + json.dumps(info, ensure_ascii=False, default=str))
    if not info["ok"]:
        _FAILED.append(("B 之後重新套用失敗", info))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-core", type=int, default=TRAIN["core"])
    ap.add_argument("--pubkey-file")
    ap.add_argument("--drill-root")
    ap.add_argument("--seed-db")
    ap.add_argument("--probe-401", action="append", default=[])
    ap.add_argument("--expect-file", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version if known.expect_db_version is not None else TRAIN["db_version"]
    _CTX["opts"].update(probe_401=known.probe_401, expect_file=known.expect_file, expect_core=known.expect_core, seed_db=known.seed_db)
    if known.pubkey_file:
        _PUB["pem"] = Path(known.pubkey_file).read_bytes()
    if known.drill_root:
        T.DRILL_ROOT = Path(known.drill_root)
    T.deliver = deliver44
    _wrap_rollback44()
    _wrap_apply_for_context()
    orig_main = T.main
    orig_cleanup = DM.cleanup

    def cleanup(base_real):
        try:
            _reapply_after_B()
        except Exception as e:                                          # noqa: BLE001
            print("R_REAPPLY::ERROR", type(e).__name__, str(e)[:300])
            _FAILED.append(("B 之後重新套用丟例外", str(e)[:200]))
        try:
            if _CTX.get("root"):
                DM.stop(_CTX["root"], _CTX["port"])                     # 重套之後服務是起著的：清除前一定要停
        except Exception as e:                                          # noqa: BLE001
            print("STOP::ERROR", type(e).__name__, str(e)[:200])
        return orig_cleanup(base_real)
    DM.cleanup = cleanup if "--keep" not in rest else orig_cleanup

    def main_with_hooks(a):
        T.checks_after_apply = checks44
        prev_mb = T.make_baseline

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            DM.stop(root, port)                                         # 種子與快照在服務停著時做（避免寫入競爭）
            if _CTX["opts"]["seed_db"]:
                info["seed_db_import"] = import_seed_db(root, _CTX["opts"]["seed_db"])
            info["train44_seed"] = seed44(root, port)
            _BASE["seed"] = info["train44_seed"]
            _BASE["db"] = db_facts(root)
            _BASE["notif_rows"] = [{k: r[k] for k in _NOTIF_COLS} for r in _notif_rows(root)]
            snap = Path(base) / "equiv_before.json"
            rc, out = equiv_snapshot(root, snap)
            info["r1_snapshot"] = {"rc": rc, "tail": out[-200:]}
            if rc != 0:
                _FAILED.append(("R1 套用前快照失敗", info["r1_snapshot"]))
            _CTX["equiv_snapshot"] = snap
            _BASE["tree"] = T35A.tree_digest(root)
            _lk = json.loads((Path(root) / "backend" / "modules.lock.json").read_text(encoding="utf-8"))
            _BASE["undeclared"] = PD.probe_plan(Path(root) / "backend" / "modules", _lk)[1]
            DM.start(root, port)
            info["train44_baseline"] = {"core": _BASE["db"]["core"], "notifications": _BASE["db"]["count"], "tree_files": len(_BASE["tree"])}
            return root, info
        T.make_baseline = mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", TRAIN["base"]]
    if "--port" not in rest:
        rest += ["--port", "6744"]
    rc = T30.main(rest)
    for why, info in _FAILED:
        print("FAIL:", why, json.dumps(info, ensure_ascii=False, default=str))
    return 1 if _FAILED else rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
