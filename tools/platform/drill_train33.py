# -*- coding: utf-8 -*-
"""第 33 班套用演練（參數化版；基線預設＝prod/52033606＝第 32 班已套用的正式機現況）。由 drill_train32 改寫：
第 32 班專屬的判準（17a–d 卡住的列、18 出納差額審核）已在基線生效，不再沿用；通用零件（交付／套用／回滾／A→C→E→B）仍走 drill_train_apply／30／31。

用法：
  python tools/platform/drill_train33.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> \
      [--base-commit 52033606] [--expect-schema subcontract=5] [--expect-db-version N] [--runs A,C,E,B] [--keep]

參數化：`TRAIN`（班別、預設基線、預設 schema 期望）與 `CHECKS`（本班判準函式清單）是唯一要改的兩處；下一班複製本檔改這兩處即可。
  --base-commit       基線 commit（預設 TRAIN["base"]）
  --expect-schema k=N 套用後 module_schema_versions[k]==N（可重複；沒給就用 TRAIN["schema"]）；C 回滾後須回到基線值
  --expect-db-version 套用後 schema_version.version（沒給＝不變）

A 套用 → C 資料庫回滾 → E 回滾後重套 → B 只回程式。第 31 班的通用回歸判準（draft 模組差集、無 traceback、審核端點 401、掛載點、設計器預設關、
叫料／匯款表…）照舊（drill_train31.checks31），再加第 33 班（31-B 匯款款別／分期匯款申請）：
  19a 基線 4 筆舊式匯款申請（已核准×4、已付×2〔實付 NULL＝舊資料〕、零稅率×1、含個人點工×1）套用後：舊欄位逐欄不變，新欄預設（kind=''、seq=0、voided_at=''）
  19b `dispatch_id` 單欄 UNIQUE 拿掉（同派發可有多張）、分期的部分唯一索引存在
  19c `GET /api/remit-kinds`：未登入 401、管理員 200 且含四個預設款別
  19d 分期流程：試算不寫入 → 訂金 300 → 進度款 700（最後一期）→ 再開被拒（額度用完）→ 作廢只能從最新一期（第 1 期 409、第 2 期 200）→ 重開可行（序號 2）
  19e 舊式整筆申請：在另一張派發建立仍可行（kind=''）；同派發再開分期 409（互斥）
  19f 發票：分期申請可登錄發票（PATCH …/invoice）；舊式整筆申請 409（發票在派發上）
  19g 舊申請列表形狀不變（kind=''、發票欄位空）；`PRAGMA integrity_check`＝ok、`foreign_key_check` 無違規
紅線同 TRAIN29-DRILL：不碰正式機／金鑰；全合成資料；埠 6760 只綁 127.0.0.1；跑完清。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402

T = T30.T

#: 班別參數：下一班只改這裡與 CHECKS
TRAIN = {"number": 33, "base": "52033606", "schema": {"subcontract": 5}}

SEED_QUOTE = "%sMQ-001" % T.SEED_TAG
LEGACY_VOUCHER_DISPATCHES = (1, 2, 3, 4)        # seed30 建的四筆派發：各配一張舊式匯款申請
KIND_DID, WHOLE_DID = 21, 22                    # 套用後做分期／整筆流程用的兩張已驗收派發（基線種入，approval_status 預設空＝舊單）


def seed33(root, port):
    """基線（第 32 班程式、subcontract schema 4）：4 筆舊式匯款申請＋兩張待用的已驗收派發。直接寫表（只用有預設值的欄位）。"""
    now = "2026-09-25T09:00:00"
    c = T.rw(root)
    try:
        vid = c.execute("SELECT MIN(id) FROM vendor_contractors").fetchone()[0]
        for did in (KIND_DID, WHOLE_DID):
            c.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, status, created_by,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (did, SEED_QUOTE, vid, "2026-09-28", "DRILL分期%d" % did, "[]", 1000, 0.05, "accepted", "drill", now, now))
        shapes = [  # (派發, 稅率, 個人點工, 已付, 實付)
            (1, 0.05, 0, 1, None), (2, 0.0, 0, 1, None), (3, 0.05, 500, 0, None), (4, 0.05, 0, 0, None)]
        for i, (did, rate, personnel, paid, actual) in enumerate(shapes, 1):
            total = 1000 * did
            tax = int(round(total * rate))
            snap = {"vendorName": "DRILL承攬商", "totalAmount": total, "taxRate": rate, "taxAmount": tax, "personnelTotal": personnel,
                    "grandTotal": total + tax + personnel, "personnel": [{"name": "甲", "amount": personnel}] if personnel else []}
            c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, is_paid, paid_at, remit_actual,"
                      " remit_fee, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      ("DRILL-PV-%04d" % i, did, SEED_QUOTE, vid, "已核准" if i != 4 else "草稿", json.dumps(snap, ensure_ascii=False), paid,
                       "2026-09-2%d" % i if paid else "", actual, 0, "drill", now, now))
        c.commit()
        rows = [dict(r) for r in c.execute("SELECT * FROM contractor_payment_vouchers ORDER BY id")]
    finally:
        c.close()
    return {"vouchers": len(rows), "kind_dispatch": KIND_DID, "whole_dispatch": WHOLE_DID}


def record33(rec, root):
    c = T.ro(root)
    try:
        rec["voucher_rows"] = {r["id"]: dict(r) for r in c.execute("SELECT * FROM contractor_payment_vouchers ORDER BY id")}
        rec["voucher_table_sql"] = (c.execute("SELECT sql FROM sqlite_master WHERE name='contractor_payment_vouchers'").fetchone() or [""])[0] or ""
        rec["voucher_index_sql"] = [r[0] or "" for r in c.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='contractor_payment_vouchers'")]
    finally:
        c.close()
    return rec


def _post(port, path, body, token, method="POST"):
    return T.api(port, path, body, token, method)


def checks33(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    for k in ("16_subcontract_schema_stays_3", "9c_legacy_dispatch_untouched", "16_material_tables_exist_and_empty"):
        res.pop(k, None)                          # 基線已是 subcontract 4／材料表已有第 32 班的種子 ⇒ 由 --expect-schema 與下面的判準取代
    _u, token = T.login(root, port)
    base_rows, new_rows = base_rec.get("voucher_rows") or {}, new_rec.get("voucher_rows") or {}
    # 19a 舊列逐欄不變、新欄預設
    old_cols = set(next(iter(base_rows.values()), {}).keys()) if base_rows else set()
    diff = {i: sorted(k for k in old_cols if new_rows.get(i, {}).get(k) != r.get(k)) for i, r in base_rows.items() if i in new_rows}
    diff = {i: v for i, v in diff.items() if v}
    seeded_new = [r for i, r in new_rows.items() if i in base_rows]
    defaults_ok = all((r.get("kind") or "") == "" and (r.get("seq") or 0) == 0 and (r.get("voided_at") or "") == "" for r in seeded_new)
    res["19a_old_vouchers_unchanged_new_columns_default"] = (bool(base_rows) and set(base_rows) <= set(new_rows) and not diff and defaults_ok,
                                                           {"rows": len(base_rows), "changed_columns": diff, "defaults_ok": defaults_ok})
    # 19b 單欄 UNIQUE 拿掉、分期的部分唯一索引在
    tsql = (new_rec.get("voucher_table_sql") or "").replace("\n", " ")
    idx = " ".join(new_rec.get("voucher_index_sql") or [])
    inline_unique = "dispatch_id" in tsql.split("UNIQUE")[1][:40] if "UNIQUE" in tsql else False
    res["19b_dispatch_unique_gone_partial_indexes_present"] = (not inline_unique and "kind" in idx and "WHERE" in idx.upper(),
                                                               {"inline_unique_on_dispatch": inline_unique, "indexes": new_rec.get("voucher_index_sql")})
    # 19c 款別下拉
    s401, _b = T.api(port, "/api/remit-kinds", None, None, "GET")
    s200, body = T.api(port, "/api/remit-kinds", None, token, "GET")
    codes = {k.get("code") for k in (body or {}).get("kinds", []) if isinstance(k, dict)} if isinstance(body, dict) else set()
    res["19c_remit_kinds_api"] = (s401 == 401 and s200 == 200 and {"deposit", "progress", "completion", "acceptance"} <= codes, {"unauth": s401, "admin": s200, "codes": sorted(codes)})
    # 19d 分期流程
    n_before = len([1 for _ in new_rows])
    sp, dp = _post(port, "/api/contractor-vouchers/preview", {"dispatch_id": KIND_DID, "kind": "deposit", "amount": 300}, token)
    c = T.ro(root)
    try:
        wrote = c.execute("SELECT COUNT(*) FROM contractor_payment_vouchers WHERE dispatch_id=?", (KIND_DID,)).fetchone()[0]
    finally:
        c.close()
    s1, d1 = _post(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "deposit", "amount": 300}, token)
    s2, d2 = _post(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 700}, token)
    s3, d3 = _post(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 1}, token)
    no1, no2 = (d1 or {}).get("voucher_no"), (d2 or {}).get("voucher_no")
    v1, _x = _post(port, "/api/contractor-vouchers/%s/void" % no1, {"reason": "演練"}, token)
    v2, _x = _post(port, "/api/contractor-vouchers/%s/void" % no2, {"reason": "演練"}, token)
    s4, d4 = _post(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 700}, token)
    last2 = ((d2 or {}).get("plan") or {}).get("is_last")
    res["19d_installment_flow_preview_create_cap_void_lifo_reopen"] = (
        sp == 200 and wrote == 0 and s1 == 201 and s2 == 201 and last2 is True and s3 == 400 and v1 == 409 and v2 == 200 and s4 == 201 and (d4 or {}).get("seq") == 2,
        {"preview": sp, "preview_wrote": wrote, "create": (s1, s2, s3), "last_is_last": last2, "void_first": v1, "void_latest": v2, "reopen": (s4, (d4 or {}).get("seq"))})
    # 19e 舊式整筆與分期互斥
    sw, dw = _post(port, "/api/contractor-vouchers", {"dispatch_id": WHOLE_DID}, token)
    sk, _b = _post(port, "/api/contractor-vouchers", {"dispatch_id": WHOLE_DID, "kind": "deposit", "amount": 100}, token)
    c = T.ro(root)
    try:
        wk = c.execute("SELECT kind FROM contractor_payment_vouchers WHERE voucher_no=?", ((dw or {}).get("voucher_no"),)).fetchone()
    finally:
        c.close()
    res["19e_whole_voucher_still_works_and_excludes_installments"] = (sw == 201 and wk is not None and (wk[0] or "") == "" and sk == 409, {"whole": sw, "kind_after_whole": sk})
    # 19f 發票
    si, di = T.api(port, "/api/contractor-vouchers/%s/invoice" % (d4 or {}).get("voucher_no"), {"invNo": "DR-001", "invDate": "2026-10-05"}, token, "PATCH")
    sl, _b = T.api(port, "/api/contractor-vouchers/%s/invoice" % (dw or {}).get("voucher_no"), {"invNo": "DR-002", "invDate": "2026-10-05"}, token, "PATCH")
    res["19f_installment_invoice_ok_whole_voucher_409"] = (si == 200 and (di or {}).get("invDate") == "2026-10-05" and sl == 409, {"installment": si, "whole": sl})
    # 19g 舊申請列表形狀、庫完整性
    sg, lst = T.api(port, "/api/contractor-vouchers?quote_no=%s" % SEED_QUOTE, None, token, "GET")
    legacy = [v for v in (lst if isinstance(lst, list) else []) if v.get("voucherNo", "").startswith("DRILL-PV-")]
    c = T.ro(root)
    try:
        integ = c.execute("PRAGMA integrity_check").fetchone()[0]
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        c.close()
    res["19g_legacy_listing_shape_and_db_integrity"] = (sg == 200 and len(legacy) == len(base_rows) and all(v.get("kind") == "" and v.get("invDate") == "" for v in legacy)
                                                       and integ == "ok" and not fk, {"status": sg, "legacy": len(legacy), "integrity": integ, "fk_violations": len(fk), "rows_before": n_before})
    return res


#: 本班判準（下一班：新增／替換函式）
CHECKS = checks33


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version
    schema = dict(TRAIN["schema"])
    for kv in known.expect_schema:
        k, v = kv.split("=")
        schema[k] = int(v)
    T31._EXPECT["schema"].update(schema)
    T.deliver = T31.deliver31
    orig_main = T.main

    def main_with_hooks(a):
        T.checks_after_apply = CHECKS
        prev_rec, prev_mb = T.record, T.make_baseline

        def rec(root):
            return record33(prev_rec(root), root)

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            info["train33_seed"] = seed33(root, port)
            return root, info
        T.record, T.make_baseline = rec, mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", TRAIN["base"]]
    return T30.main(rest)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
