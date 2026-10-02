# -*- coding: utf-8 -*-
"""第 31 班套用演練（基線＝prod/6b5d2865＝第 30 班已套用的正式機現況；沿用 drill_train_apply／drill_train30 的零件）。

用法：
  python tools/platform/drill_train31.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> \
      [--expect-db-version N] [--expect-schema key=N ...] [--runs A,C,E,B] [--keep]

A 套用 → C 資料庫回滾 → E 回滾後重套 → B 只回程式。判準 = 第 30 班的回歸（承攬商派發單舊列不動、審核端點 401、掛載點、紅點、
檔案中心開檔、勞報單帳號遮蔽、無 traceback、模組版本差集＝包內差集）＋第 31 班：
  - 31-C 遷移：每個 `--expect-schema key=N` 套用後 module_schema_versions[key]==N，C 回滾後回到基線值；沒給＝只記錄不判定，並要求「沒有任何 schema 版本變小」
  - 資料庫版本：`--expect-db-version`（預設＝基線的版本，不變）
  - 新表單設計器預設關閉：請款類型頁的程式 `useFD: false`、頁面仍帶舊表格畫面（et-fields／et-add-reserved）、?designer=1 才開
紅線同 TRAIN29-DRILL：不碰正式機／金鑰；全合成資料；埠 6760 只綁 127.0.0.1；跑完清。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402

T = T30.T
BASE31 = "6b5d2865"
_EXPECT = {"db_version": None, "schema": {}}


def deliver31(delivery_root, name, root, base):
    import delivery as D
    staging = Path(base) / "staging"
    staging.mkdir(exist_ok=True)
    staged = D.stage(str(delivery_root), name, str(staging))
    verify = D.verify_staged(staged, str(root), run_verify_package=False)
    payload = Path(staged) / D.PAYLOAD
    ver = str(_EXPECT["db_version"] or _base_db_version(root))
    vp = subprocess.run([sys.executable, str(payload / "backend" / "tools" / "verify_package.py"), str(payload), "--expect-db-version", ver],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return payload, {"verify_ok": verify.get("ok"), "problems": verify.get("problems"), "notes": verify.get("notes"),
                     "verify_package_rc": vp.returncode, "verify_package_tail": (vp.stdout + vp.stderr)[-600:], "expect_db_version": ver}


def _base_db_version(root):
    c = T.ro(root)
    try:
        return (c.execute("SELECT version FROM schema_version WHERE id=1").fetchone() or [116])[0]
    finally:
        c.close()


def checks31(root, port, base_rec, new_rec, t0, package_modules):
    res = T30.checks30(root, port, base_rec, new_rec, t0, package_modules)
    # 第 30 班的 schema 判準（承攬商 2→3、db_version 不變）在基線已是 3 ⇒ 改成第 31 班的規則
    sv, bsv = new_rec["schema_versions"], base_rec["schema_versions"]
    res.pop("9a_subcontract_schema_3", None)
    res.pop("9a_other_schemas_unchanged", None)
    res.pop("9a_db_version", None)
    shrunk = {k: (bsv[k], sv.get(k)) for k in bsv if (sv.get(k) or 0) < (bsv[k] or 0)}
    res["9a_no_schema_version_shrinks"] = (not shrunk, {"shrunk": shrunk, "changed": {k: (bsv.get(k), v) for k, v in sv.items() if bsv.get(k) != v}})
    for k, n in _EXPECT["schema"].items():
        res["9a_schema_%s_is_%d" % (k, n)] = (sv.get(k) == n, {"base": bsv.get(k), "new": sv.get(k)})
    want_db = _EXPECT["db_version"]
    res["9a_db_version"] = ((new_rec["db_version"] == want_db) if want_db else (new_rec["db_version"] == base_rec["db_version"]),
                            {"base": base_rec["db_version"], "new": new_rec["db_version"], "expected": want_db})
    # 新表單設計器預設關閉
    js = (Path(root) / "frontend" / "js" / "expense-types-designer.js")
    html = (Path(root) / "frontend" / "pages" / "expense-types.html")
    jt = js.read_text(encoding="utf-8", errors="replace") if js.is_file() else ""
    ht = html.read_text(encoding="utf-8", errors="replace") if html.is_file() else ""
    off = bool(re.search(r"useFD:\s*false", jt)) and "localStorage.getItem('et_designer') === '1'" in jt
    st, body = T.raw_get(port, "/pages/expense-types.html")
    page_ok = st in (200, 401, 403, 302) and "et-fields" in ht and "et-add-reserved" in ht and "et-fd-host" in ht
    res["15_designer_default_off"] = (off and page_ok, {"js_present": js.is_file(), "default_off": off, "old_ui_markup_present": "et-fields" in ht, "designer_host_present": "et-fd-host" in ht, "page_status": st})
    # 31-C：叫料核准／材料款匯款——未登記 401、三張新表存在且空、承攬商 schema 維持 3
    mats = ["/api/quotations/DRILL-NONE/material-order-approvals", "/api/quotations/DRILL-NONE/material-payments", "/api/material-suppliers"]
    posts = ["/api/material-payments/1/submit", "/api/material-payments/1/approve", "/api/material-payments/1/reject",
             "/api/material-payments/1/withdraw", "/api/material-payments/1/void", "/api/material-payments/1/privacy-notice/ack",
             "/api/quotations/DRILL-NONE/material-orders/1/payments",
             "/api/quotations/DRILL-NONE/material-orders/1/submit", "/api/quotations/DRILL-NONE/material-orders/1/approve",
             "/api/quotations/DRILL-NONE/material-orders/1/reject", "/api/quotations/DRILL-NONE/material-orders/1/withdraw",
             "/api/quotations/DRILL-NONE/material-orders/1/cancel", "/api/quotations/DRILL-NONE/material-orders/1/receive"]
    codes = {u: T.api(port, u, None, None, "GET")[0] for u in mats}
    codes.update({u: T.api(port, u, {}, None, "POST")[0] for u in posts})
    res["16_material_endpoints_unauth_401"] = (all(v == 401 for v in codes.values()), {k: v for k, v in codes.items() if v != 401} or "all 401")
    c = T.ro(root)
    try:
        tabs = {t: (T.table_exists(c, t), T.count(c, t)) for t in ("case_material_approvals", "case_material_payments", "case_material_payment_lines")}
    finally:
        c.close()
    res["16_material_tables_exist_and_empty"] = (all(e and n == 0 for e, n in tabs.values()), tabs)
    res["16_subcontract_schema_stays_3"] = (sv.get("subcontract") == 3, sv.get("subcontract"))
    return res


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    _EXPECT["db_version"] = known.expect_db_version
    for kv in known.expect_schema:
        k, v = kv.split("=")
        _EXPECT["schema"][k] = int(v)
    T30.T.deliver = deliver31
    # drill_train30.main 會把 checks_after_apply 設成 checks30 ⇒ 先讓它設，再在 T 上換成 checks31
    orig_main = T.main

    def main_with_checks(a):
        T.checks_after_apply = checks31
        return orig_main(a)
    T.main = main_with_checks
    if "--base-commit" not in rest:
        rest += ["--base-commit", BASE31]
    return T30.main(rest)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
