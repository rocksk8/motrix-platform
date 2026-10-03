# -*- coding: utf-8 -*-
"""第 35a 班套用演練（d5；基線＝prod/6927e222＝第 34 班已上線的正式機現況；新版＝35a 候選包）。由 drill_train34 的零件組成：
安裝／套用／回滾／A→C→E→B 沿用 drill_train_apply，種子與判準換成 35a 的。

35a 內容（精算頁）：新增欄位（additive）— settlement-actuals 的未對應材料列帶 quantity／unit、額外支出列帶 description；
案件頁新增精算入口 `cm-tab-settlement`（連到 settlement.html，權限 canSeeFinancial）；settlement.html 列名稱顯示品名／數量／單位／說明；
S1 修正：髒數量（'²'、None、空字串、'nan'、'abc'、'1e999'）不再讓端點 500；db_version 116 不變、case schema 維持 6。

判準（host 2026-10-03 指派）：
  35a_1  財務使用者 GET settlement-actuals ⇒ 200、帶 quantity／unit／description；與套用前相比「只多了這三種鍵、其餘每個值逐位相同」（含 totals）
  35a_2  非財務使用者（看得到案件、沒有財務檢視）⇒ 403，回應不含任何新欄位
  35a_3  案件頁含 cm-tab-settlement（檔案＋伺服器實際送出）；settlement.html 200 且含 matLabel／extLabel
  35a_4  髒數量不 500（S1）
  35a_5  B（只回程式）之後：commit＝基線、程式檔雜湊與基線逐檔相同（不含 logs／資料庫／上傳／暫存）
其餘沿用 checks31（模組載入、無 traceback、單一監聽行程…）；35a 之前班次專屬的舊題在 _STALE 說明理由後略過。

用法（.venv312）：
  python tools/platform/drill_train35a.py --delivery-root <演練交付資料夾> --name <包名> --new-commit <SHA> --pubkey-file <演練公鑰.pem> \
         [--runs A,B] [--keep] [--drill-root <演練目錄>] [--port 6765]
⚠ 演練交付資料夾由演練金鑰簽發（拋棄式；私鑰不離開演練暫存）⇒ 驗章用 --pubkey-file 的演練公鑰；**正式金鑰簽章的驗證不在這次演練範圍**
（正式機上由 delivery.py verify 用已安裝版本內建公鑰驗）。紅線同 TRAIN29-DRILL：不碰正式機／正式金鑰；全合成資料；只綁 127.0.0.1；跑完清。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402

T = T30.T
TRAIN = {"number": "35a", "base": "6927e222", "schema": {"case": 6, "subcontract": 5}, "db_version": 116}
SEED_QUOTE = "%sMQ-001" % T.SEED_TAG
ENG = ("drill_eng", "Drill-Eng-Pass!9")
_FAILED = []
_BASE = {}          # 基線（舊程式）取得的東西：settlement 回應、程式檔雜湊
_PUB = {"pem": None}

#: 35a 之前班次專屬、在這個基線（已含 M2／出貨連動／設計器預設開）上不成立的舊題；略過理由逐項寫明
_STALE = {
    "15_designer_default_off": "D12 設計器預設改開（34 班起），舊判準是「預設關」",
    "16_subcontract_schema_stays_3": "承攬商 schema 已是 5（本班判準改成 case=6／subcontract=5）",
    "16_material_tables_exist_and_empty": "35a 的種子會寫 case_material_approvals（材料申請審核列），表不再是空的",
    "9c_legacy_dispatch_untouched": "第 30 班專屬（舊派發單不動）；基線已含兩段審核，種子派發的欄位預設不同",
}

#: 精算端點 35a 新增的鍵（additive）：除此之外的差異都算問題
NEW_KEYS = {"quantity", "unit", "description"}
#: 程式檔雜湊要排除的執行期東西
_SKIP_DIRS = {"logs", "uploads", "db_backups", "__pycache__", ".pytest_cache", "backups", "staging", "rollback_snapshots"}   # rollback_snapshots＝apply 產生的備份（執行期產物，不是程式檔）
_SKIP_SUFFIX = (".pyc", ".db", ".db-wal", ".db-shm", ".log", ".sqlite")
_SKIP_NAMES = {".deployed_commit.json", ".install_identity", "company_confirmation.sig", "module_states.json"}


def tree_digest(root):
    """安裝目錄的「程式檔」雜湊 {相對路徑: sha256}（backend／frontend／tools／product＋根目錄檔；排除執行期檔）。"""
    root = Path(root)
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if f.endswith(_SKIP_SUFFIX) or f in _SKIP_NAMES or "credentials" in f.lower() or f.startswith("apply_update_") or f.startswith("rollback_update_"):
                continue
            p = Path(base) / f
            rel = p.relative_to(root).as_posix()
            if rel.startswith("backend/tools/") and rel.endswith((".ps1", ".bat")):
                continue                      # 演練會改寫 $ProdRoot／$Port 兩行（見 drill_train_apply.rewrite_tools）⇒ 腳本檔另比
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def seed35(root, port):
    """基線（6927e222 程式）上的精算種子：兩個報價品項、材料申請（未對應、數量 2 台）＋非財務使用者（看得到案件）。"""
    c = T.rw(root)
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (SEED_QUOTE,)).fetchone()
        d = json.loads(row["data_json"] or "{}")
        d["items"] = [{"id": "a", "description": "品項A", "qty": 10, "cost": 1000}, {"id": "b", "description": "品項B", "qty": 100, "cost": 5}]
        cr = d.get("caseRecord") or {}
        cr["materialOrders"] = [{"itemId": "X", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 125, "totalPrice": 250}]
        d["caseRecord"] = cr
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), SEED_QUOTE))
        c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (SEED_QUOTE, "X", "已核准"))
        hashes = T30._hash_cmds(root, {ENG[0]: ENG[1]})
        now = "2026-10-03T09:00:00"
        c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password)"
                  " VALUES (?,?,?,?,?,1,?,0)", (ENG[0], hashes[ENG[0]], ENG[0], "engineer", '["case_manage"]', now))
        uid = c.execute("SELECT id FROM users WHERE username=?", (ENG[0],)).fetchone()["id"]
        c.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([uid]), SEED_QUOTE))
        c.commit()
    finally:
        c.close()
    return {"quote": SEED_QUOTE, "items": 2, "material_X": {"quantity": 2, "unit": "台", "total": 250}, "engineer_user": ENG[0]}


def _settle(port, token, quote=SEED_QUOTE):
    return T.api(port, "/api/quotations/%s/settlement-actuals" % quote, token=token)


def diff_shapes(base, new, path=""):
    """⇒ (新增鍵路徑集合, 值不同的路徑清單, 消失的鍵路徑清單)。dict 逐鍵、list 逐位比（長度不同也算值不同）。"""
    added, changed, removed = set(), [], []
    if isinstance(base, dict) and isinstance(new, dict):
        for k in new:
            if k not in base:
                added.add(path + "/" + k)
        for k in base:
            if k not in new:
                removed.append(path + "/" + k)
            else:
                a, ch, rm = diff_shapes(base[k], new[k], path + "/" + k)
                added |= a
                changed += ch
                removed += rm
    elif isinstance(base, list) and isinstance(new, list):
        if len(base) != len(new):
            changed.append((path, "len %d→%d" % (len(base), len(new))))
        for i, (x, y) in enumerate(zip(base, new)):
            a, ch, rm = diff_shapes(x, y, "%s[%d]" % (path, i))
            added |= a
            changed += ch
            removed += rm
    elif base != new:
        changed.append((path, "%r→%r" % (base, new)))
    return added, changed, removed


def record35(rec, root):
    rec["tree"] = None                     # 雜湊另在需要時算（避免每次 record 都掃整個安裝）
    return rec


def _wrap_rollback():
    """B（只回程式）之後：程式檔雜湊與基線逐檔相同；結果寫進 rc["train35a_tree_after_B"]，失敗讓結束碼非 0。C（含資料庫）不比。"""
    orig = T.rollback

    def rollback(root, ts, include_db=False, port=T.PORT):
        rc = orig(root, ts, include_db=include_db, port=port)
        if not include_db and _BASE.get("tree"):
            now = tree_digest(root)
            base = _BASE["tree"]
            diff = sorted(k for k in set(base) | set(now) if base.get(k) != now.get(k))
            info = {"files_base": len(base), "files_now": len(now), "diff_count": len(diff), "diff_sample": diff[:40],
                    "only_in_now": sorted(set(now) - set(base))[:20], "only_in_base": sorted(set(base) - set(now))[:20]}
            info["ok"] = not diff
            rc["train35a_tree_after_B"] = info
            if not info["ok"]:
                _FAILED.append(("B 回滾後程式檔與基線不逐檔相同", info))
        return rc
    T.rollback = rollback


def checks35(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    stale = {k: _STALE[k] for k in _STALE if k in res}
    for k in stale:
        res.pop(k)
    res["35a_0_stale_checks_skipped"] = (True, stale)
    _u, tok = T.login(root, port)
    # 35a_1 財務使用者：200、帶新欄位、與套用前比只多了新鍵（含 totals 逐位相同）
    s, d = _settle(port, tok)
    base = _BASE.get("settle")
    added, changed, removed = diff_shapes(base, d) if (base and isinstance(d, dict)) else (set(), [("no-base", None)], [])
    added_names = {a.rsplit("/", 1)[-1] for a in added}
    mats = ((d.get("unassigned") or {}).get("materials") or []) if isinstance(d, dict) else []
    extras = ((d.get("unassigned") or {}).get("extras") or []) if isinstance(d, dict) else []
    m_ok = any(m.get("itemId") == "X" and m.get("quantity") == 2 and m.get("unit") == "台" and m.get("name") for m in mats)
    e_ok = bool(extras) and all("description" in e for e in extras) and any((e.get("description") or "").startswith("DRILL舊式支出") for e in extras)
    res["35a_1_financial_new_fields_and_totals_identical"] = (
        s == 200 and m_ok and e_ok and added_names <= NEW_KEYS and added_names == NEW_KEYS and not changed and not removed
        and d.get("totals") == (base or {}).get("totals"),
        {"status": s, "added_keys": sorted(added_names), "changed": changed[:6], "removed": removed[:6], "totals": (d or {}).get("totals") if isinstance(d, dict) else None,
         "totals_identical": isinstance(d, dict) and d.get("totals") == (base or {}).get("totals"), "material_X_ok": m_ok, "extras_with_description": len(extras)})
    # 35a_2 非財務使用者：403、沒有任何新欄位
    etok = T30._login_as(port, *ENG)
    s2, d2 = _settle(port, etok) if etok else (None, None)
    txt = json.dumps(d2, ensure_ascii=False) if d2 is not None else ""
    res["35a_2_non_financial_403_and_no_new_fields"] = (
        s2 == 403 and not any(('"%s"' % k) in txt for k in NEW_KEYS) and "totals" not in txt,
        {"status": s2, "body": txt[:160], "login_ok": bool(etok)})
    # 35a_3 案件頁精算入口、精算頁
    cm_file = (Path(root) / "frontend" / "pages" / "case-management.html").read_text(encoding="utf-8", errors="replace")
    st_file = (Path(root) / "frontend" / "pages" / "settlement.html").read_text(encoding="utf-8", errors="replace")
    sc, cb = T.raw_get(port, "/pages/case-management.html")
    ss, sb = T.raw_get(port, "/pages/settlement.html")
    cbt = cb.decode("utf-8", "replace") if isinstance(cb, (bytes, bytearray)) else str(cb)
    sbt = sb.decode("utf-8", "replace") if isinstance(sb, (bytes, bytearray)) else str(sb)
    res["35a_3_case_tab_link_and_settlement_page"] = (
        'data-testid="cm-tab-settlement"' in cm_file and "matLabel" in st_file and "extLabel" in st_file
        and sc == 200 and 'data-testid="cm-tab-settlement"' in cbt and ss == 200 and "matLabel" in sbt and "extLabel" in sbt,
        {"case_file_has_link": 'data-testid="cm-tab-settlement"' in cm_file, "settlement_file_has_labels": "matLabel" in st_file,
         "served": {"case-management.html": (sc, 'data-testid="cm-tab-settlement"' in cbt), "settlement.html": (ss, "matLabel" in sbt)}})
    # 35a_4 S1：髒數量不 500（直接改庫再打端點；結束後還原）
    c = T.rw(root)
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (SEED_QUOTE,)).fetchone()
        orig = row["data_json"]
        dj = json.loads(orig)
        mo = dj["caseRecord"]["materialOrders"]
        bad = ["²", None, "", "nan", "abc", "1e999"]
        dj["caseRecord"]["materialOrders"] = mo + [{"itemId": "Q%d" % i, "itemName": "髒%d" % i, "quantity": q, "unit": "", "unitPrice": 1, "totalPrice": 100} for i, q in enumerate(bad)]
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(dj, ensure_ascii=False), SEED_QUOTE))
        for i in range(len(bad)):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (SEED_QUOTE, "Q%d" % i, "已核准"))
        c.commit()
    finally:
        c.close()
    s4, d4 = _settle(port, tok)
    qs = {m["itemId"]: m.get("quantity") for m in (((d4 or {}).get("unassigned") or {}).get("materials") or [])} if isinstance(d4, dict) else {}
    c = T.rw(root)
    try:
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (orig, SEED_QUOTE))
        c.execute("DELETE FROM case_material_approvals WHERE quote_no=? AND item_id LIKE 'Q%'", (SEED_QUOTE,))
        c.commit()
    finally:
        c.close()
    res["35a_4_dirty_quantity_does_not_500"] = (
        s4 == 200 and all(qs.get("Q%d" % i, "missing") is None for i in range(len(bad))),
        {"status": s4, "dirty_quantities": {k: v for k, v in qs.items() if k.startswith("Q")}})
    return res


def deliver35(delivery_root, name, root, base):
    """同 drill_train31.deliver31，但驗章用演練公鑰（演練交付資料夾由拋棄式金鑰簽發）。⇒ (payload, 報告)。"""
    import delivery as D
    staging = Path(base) / "staging"
    staging.mkdir(exist_ok=True)
    staged = D.stage(str(delivery_root), name, str(staging))
    verify = D.verify_staged(staged, str(root), pubkey_pem=_PUB["pem"], run_verify_package=False)
    payload = Path(staged) / D.PAYLOAD
    ver = str(T31._EXPECT["db_version"] or T31._base_db_version(root))
    vp = subprocess.run([sys.executable, str(payload / "backend" / "tools" / "verify_package.py"), str(payload), "--expect-db-version", ver],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return payload, {"verify_ok": verify.get("ok"), "problems": verify.get("problems"), "notes": verify.get("notes"),
                     "verify_package_rc": vp.returncode, "verify_package_tail": (vp.stdout + vp.stderr)[-600:], "expect_db_version": ver,
                     "signature": "演練金鑰（拋棄式）；正式金鑰簽章驗證不在本演練範圍"}


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    ap.add_argument("--pubkey-file")
    ap.add_argument("--drill-root")
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version if known.expect_db_version is not None else TRAIN["db_version"]
    schema = dict(TRAIN["schema"])
    for kv in known.expect_schema:
        k, v = kv.split("=")
        schema[k] = int(v)
    T31._EXPECT["schema"].update(schema)
    if known.pubkey_file:
        _PUB["pem"] = Path(known.pubkey_file).read_bytes()      # bytes（delivery.verify_signature 要 bytes）
    if known.drill_root:
        T.DRILL_ROOT = Path(known.drill_root)
    T.deliver = deliver35
    _wrap_rollback()
    orig_main = T.main

    def main_with_hooks(a):
        T.checks_after_apply = checks35
        prev_rec, prev_mb = T.record, T.make_baseline

        def rec(root):
            return record35(prev_rec(root), root)

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            info["train35a_seed"] = seed35(root, port)
            _u, tok = T.login(root, port)
            s, d = _settle(port, tok)
            _BASE["settle"] = d if s == 200 else None
            _BASE["tree"] = tree_digest(root)
            info["train35a_baseline"] = {"settlement_status": s, "tree_files": len(_BASE["tree"]),
                                         "totals": (d or {}).get("totals") if isinstance(d, dict) else None}
            return root, info
        T.record, T.make_baseline = rec, mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", TRAIN["base"]]
    rc = T30.main(rest)
    for why, info in _FAILED:
        print("FAIL:", why, json.dumps(info, ensure_ascii=False))
    return 1 if _FAILED else rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
