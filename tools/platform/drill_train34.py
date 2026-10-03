# -*- coding: utf-8 -*-
"""第 34 班套用演練（骨架；基線＝prod/8ae8b8cc＝第 33 班A 已套用的正式機現況）。由 drill_train33 複製：通用零件（交付／套用／回滾／A→C→E→B）沿用 drill_train_apply／30／31，
本班判準寫在 `CHECKS`（34a–34e 已實作；`_todo()` 樁保留給之後新增的題，會讓演練明確失敗、不誤報綠）。

用法（同 drill_train33）：
  python tools/platform/drill_train34.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA>       [--base-commit 8ae8b8cc] [--expect-schema k=N ...] [--expect-db-version N] [--runs A,C,E,B] [--keep]

本班已實作（種子＝基線材料申請三筆＋已驗收派發；判準在 `checks34`）。本班要涵蓋（主持 2026-10-03 指派；細節待整合分支）：
  34a M2 變更申請 migration 0006 對**正式機資料形狀**的升級（種子＝正式機現況：材料申請筆數／狀態分布，合成資料；升級後逐欄不變、新表／新欄預設、回滾回舊形狀）
  34b 出貨單連動（出貨單 ↔ 材料申請／採購單連結：舊出貨單不連結仍可用；有已到料且有剩餘量卻沒連 ⇒ 送審前警示）
  34c D7 鎖定（全額付款的舊材料申請不能改金額、新額不低於已付）
  34d D12 設計器預設開的切換（預設開、?designer=0／localStorage 可切回；舊的「預設關」判準 15_designer_default_off 要換成「預設開」）
  34e 沿用 33 班判準：19a–19h 在 33A 已上線，34 班只需確認 voucher 表與分期流程不退化（用 19d 的精簡版）
紅線同 TRAIN29-DRILL：不碰正式機／金鑰；全合成資料；埠 6760 只綁 127.0.0.1（由 da 獨占）；跑完清。
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402

T = T30.T

#: 班別參數：schema 期望＝case 5→6（M2a 的 0006 覆核表）；db_version 不變（None＝同基線）
TRAIN = {"number": 34, "base": "8ae8b8cc", "schema": {"case": 6}, "db_version": None}
_FAILED = []
_LEGACY_CALLS = [0]

SEED_QUOTE = "%sMQ-001" % T.SEED_TAG
#: 種子（基線＝第 33 班A 程式）：材料申請三筆（全額已付舊單、部分已付已核准、未付已核准）＋四張已驗收派發（B 階段與 A 階段的舊流程用）
MATERIALS = [
    {"itemId": "dp1", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1, "paidStatus": "paid", "paidAmount": 2000, "paidDate": "2026-08-01", "notes": "", "quoteItemId": ""},
    {"itemId": "dp2", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1, "paidStatus": "partial", "paidAmount": 800, "paidDate": "2026-08-01", "notes": "", "quoteItemId": ""},
    {"itemId": "du1", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1, "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "quoteItemId": ""},
]
APPROVED_ITEMS = ("dp2", "du1")
KIND_DID = 31                      # 分期不退化（34e）用的已驗收派發
LEGACY_DIDS = (32, 33, 34, 35)     # 舊流程（整筆匯款申請）用：A、B 階段各取下一張


def seed34(root, port):
    """基線種子：材料申請（含已付形狀）＋已驗收派發。直接寫表（只用有預設值的欄位）。"""
    now = "2026-09-28T09:00:00"
    c = T.rw(root)
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (SEED_QUOTE,)).fetchone()
        d = json.loads(row["data_json"] or "{}") if row else {}
        cr = d.get("caseRecord") or {}
        cr["materialOrders"] = MATERIALS
        d["caseRecord"] = cr
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), SEED_QUOTE))
        for iid in APPROVED_ITEMS:
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (SEED_QUOTE, iid, "已核准"))
        vid = c.execute("SELECT MIN(id) FROM vendor_contractors").fetchone()[0]
        for did in (KIND_DID,) + LEGACY_DIDS:
            c.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, status, created_by,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (did, SEED_QUOTE, vid, "2026-09-28", "DRILL34-%d" % did, "[]", 1000, 0.05, "accepted", "drill", now, now))
        c.commit()
    finally:
        c.close()
    return {"materials": len(MATERIALS), "approved": list(APPROVED_ITEMS), "kind_dispatch": KIND_DID, "legacy_dispatches": list(LEGACY_DIDS)}


def record34(rec, root):
    c = T.ro(root)
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (SEED_QUOTE,)).fetchone()
        rec["mat_orders"] = ((json.loads(row["data_json"] or "{}").get("caseRecord") or {}).get("materialOrders")) if row else None
        rec["mat_approvals"] = [dict(r) for r in c.execute("SELECT * FROM case_material_approvals ORDER BY quote_no, item_id")] if T.table_exists(c, "case_material_approvals") else []
        rec["mat_changes_table"] = T.table_exists(c, "case_material_changes")
        rec["mat_changes_indexes"] = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='case_material_changes'")) if rec["mat_changes_table"] else []
        rec["mat_changes_rows"] = T.count(c, "case_material_changes")
    finally:
        c.close()
    return rec


def _wrap_legacy_flow():
    """B 階段補驗（da 建議）：舊程式對已遷移的庫跑舊流程——在原本的費用單舊流程之外，再建一張整筆匯款申請（舊 API、不帶款別）。
    A、B 各取下一張種子派發（C 回滾後庫還原、同一張可再用，但簡單起見用遞增）。"""
    orig = T.legacy_flow

    def legacy_flow(port, token):
        ok, detail = orig(port, token)
        n = _LEGACY_CALLS[0]
        _LEGACY_CALLS[0] += 1
        did = LEGACY_DIDS[n % len(LEGACY_DIDS)]
        s, d = T.api(port, "/api/contractor-vouchers", {"dispatch_id": did}, token, "POST")
        detail = dict(detail, whole_voucher=(s, (d or {}).get("voucher_no") if isinstance(d, dict) else str(d)[:120]), dispatch=did)
        return bool(ok and s == 201), detail
    T.legacy_flow = legacy_flow


def _wrap_rollback():
    """C（資料庫回滾）之後：case_material_changes 表必須消失、case schema 回基線（由主流程判）；結果寫進 rc["train34_after_C"]，失敗讓結束碼非 0。"""
    orig = T.rollback

    def rollback(root, ts, include_db=False, port=T.PORT):
        rc = orig(root, ts, include_db=include_db, port=port)
        if include_db:
            c = T.ro(root)
            try:
                info = {"changes_table_exists": T.table_exists(c, "case_material_changes"), "material_approvals": T.count(c, "case_material_approvals")}
            finally:
                c.close()
            info["ok"] = not info["changes_table_exists"]
            rc["train34_after_C"] = info
            if not info["ok"]:
                _FAILED.append(("C 回滾後 case_material_changes 還在", info))
        return rc
    T.rollback = rollback


def _todo(what):
    return (False, {"status": "未實作的紅燈樁", "todo": what})


def checks34(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    for k in ("15_designer_default_off", "16_subcontract_schema_stays_3", "9c_legacy_dispatch_untouched", "16_material_tables_exist_and_empty"):
        res.pop(k, None)                          # 15：D12 預設改開（見 34d）；其餘是舊班的專屬題
    _u, token = T.login(root, port)
    # 34a M2a 覆核表（case 0006）：表與索引在、空；既有材料申請資料與審核列逐欄不變；基線沒有這張表（正對照）
    want_idx = {"idx_cmc_doc_code", "idx_cmc_one_live", "idx_cmc_item", "idx_cmc_status"}
    res["34a_material_changes_table_and_existing_material_data_untouched"] = (
        (not base_rec.get("mat_changes_table")) and bool(new_rec.get("mat_changes_table")) and new_rec.get("mat_changes_rows") == 0
        and want_idx <= set(new_rec.get("mat_changes_indexes") or [])
        and new_rec.get("mat_orders") == base_rec.get("mat_orders") and new_rec.get("mat_approvals") == base_rec.get("mat_approvals") and bool(base_rec.get("mat_orders")),
        {"baseline_has_table": base_rec.get("mat_changes_table"), "new_has_table": new_rec.get("mat_changes_table"), "rows": new_rec.get("mat_changes_rows"),
         "indexes": new_rec.get("mat_changes_indexes"), "orders_same": new_rec.get("mat_orders") == base_rec.get("mat_orders"),
         "approvals_same": new_rec.get("mat_approvals") == base_rec.get("mat_approvals")})
    # 34b 出貨單連動：可出貨材料提供者（case 側）已掛上——靜態：安裝版 case 的 module.json／檔案
    cj = Path(root) / "backend" / "modules" / "case"
    mj = (cj / "module.json").read_text(encoding="utf-8", errors="replace") if (cj / "module.json").is_file() else ""
    res["34b_shippable_material_provider_present"] = ((cj / "material_shippable.py").is_file() and "material.shippable" in mj,
                                                     {"file": (cj / "material_shippable.py").is_file(), "declared_in_module_json": "material.shippable" in mj})
    # 34c D7：全額已付的舊單不能改金額（paid_in_full）、其他欄位可存；部分已付新小計低於已付 ⇒ 400；未付的可改
    def orders(extra_by_item):
        out = []
        for m in MATERIALS:
            o = dict(m)
            o.update(extra_by_item.get(m["itemId"], {}))
            out.append(o)
        return out

    def patch(lst):
        return T.api(port, "/api/quotations/%s/material-orders" % SEED_QUOTE, {"materialOrders": lst}, token, "PATCH")
    s1, r1 = patch(orders({"dp1": {"unitPrice": 1200, "totalPrice": 2400}}))
    rej1 = [x.get("code") for x in ((r1 or {}).get("rejected") or [])] if isinstance(r1, dict) else None
    c = T.ro(root)
    try:
        row = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (SEED_QUOTE,)).fetchone()
        cur = {m["itemId"]: m for m in ((json.loads(row["data_json"]).get("caseRecord") or {}).get("materialOrders") or [])}
    finally:
        c.close()
    s2, r2 = patch(orders({"dp1": {"notes": "DRILL備註"}}))
    s3, _r3 = patch(orders({"dp2": {"unitPrice": 300, "totalPrice": 600}}))
    s4, r4 = patch(orders({"du1": {"unitPrice": 500, "totalPrice": 1000}}))
    res["34c_d7_paid_in_full_amount_lock"] = (
        s1 == 200 and rej1 == ["paid_in_full"] and (cur.get("dp1") or {}).get("totalPrice") == 2000
        and s2 == 200 and not ((r2 or {}).get("rejected") if isinstance(r2, dict) else True) and s3 == 400 and s4 == 200 and not ((r4 or {}).get("rejected") if isinstance(r4, dict) else True),
        {"change_amount_on_paid": (s1, rej1), "paid_total_after": (cur.get("dp1") or {}).get("totalPrice"), "notes_on_paid": s2, "below_paid": s3, "unpaid_change": s4})
    # 34d D12 設計器預設開：程式預設開（useFD:true 或預設開的判斷）、仍帶舊畫面標記（可切回）
    js = Path(root) / "frontend" / "js" / "expense-types-designer.js"
    html = Path(root) / "frontend" / "pages" / "expense-types.html"
    jt = js.read_text(encoding="utf-8", errors="replace") if js.is_file() else ""
    ht = html.read_text(encoding="utf-8", errors="replace") if html.is_file() else ""
    default_on = bool(re.search(r"useFD:\s*true", jt)) or "'et_designer') !== '0'" in jt
    can_switch_back = ("et-fields" in ht and "et-add-reserved" in ht) and ("et_designer" in jt or "designer=0" in jt)
    st, _b = T.raw_get(port, "/pages/expense-types.html")
    res["34d_designer_default_on_and_switch_back"] = (default_on and can_switch_back and st in (200, 401, 403, 302),
                                                     {"js_present": js.is_file(), "default_on": default_on, "old_markup_and_switch": can_switch_back, "page_status": st})
    # 34e 分期不退化：試算不寫入 → 訂金 300 → 進度款 700（最後一期）→ 再開被拒 → 作廢只能最新一期 → 重開序號 2
    sp, _dp = T.api(port, "/api/contractor-vouchers/preview", {"dispatch_id": KIND_DID, "kind": "deposit", "amount": 300}, token, "POST")
    s1c, d1 = T.api(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "deposit", "amount": 300}, token, "POST")
    s2c, d2 = T.api(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 700}, token, "POST")
    s3c, _d3 = T.api(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 1}, token, "POST")
    n1, n2 = (d1 or {}).get("voucher_no"), (d2 or {}).get("voucher_no")
    v1, _x = T.api(port, "/api/contractor-vouchers/%s/void" % n1, {"reason": "演練"}, token, "POST")
    v2, _x = T.api(port, "/api/contractor-vouchers/%s/void" % n2, {"reason": "演練"}, token, "POST")
    s4c, d4 = T.api(port, "/api/contractor-vouchers", {"dispatch_id": KIND_DID, "kind": "progress", "amount": 700}, token, "POST")
    res["34e_installment_flow_not_regressed"] = (
        sp == 200 and s1c == 201 and s2c == 201 and ((d2 or {}).get("plan") or {}).get("is_last") is True and s3c == 400 and v1 == 409 and v2 == 200 and s4c == 201 and (d4 or {}).get("seq") == 2,
        {"preview": sp, "create": (s1c, s2c, s3c), "void_first": v1, "void_latest": v2, "reopen": (s4c, (d4 or {}).get("seq"))})
    return res


CHECKS = checks34


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version if known.expect_db_version is not None else TRAIN.get("db_version")
    schema = dict(TRAIN["schema"])
    for kv in known.expect_schema:
        k, v = kv.split("=")
        schema[k] = int(v)
    T31._EXPECT["schema"].update(schema)
    T.deliver = T31.deliver31
    _wrap_legacy_flow()
    _wrap_rollback()
    orig_main = T.main

    def main_with_hooks(a):
        T.checks_after_apply = CHECKS
        prev_rec, prev_mb = T.record, T.make_baseline

        def rec(root):
            return record34(prev_rec(root), root)

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            info["train34_seed"] = seed34(root, port)
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
