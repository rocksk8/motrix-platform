# -*- coding: utf-8 -*-
"""第 32 班套用演練（基線＝prod/a5dea50c＝第 31 班已套用的正式機現況；沿用 drill_train31／30／drill_train_apply 的零件）。

用法：
  python tools/platform/drill_train32.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> \
      [--expect-schema subcontract=4 --expect-schema case=5] [--expect-db-version N] [--runs A,C,E,B] [--keep]

A 套用 → C 資料庫回滾 → E 回滾後重套 → B 只回程式。第 31 班的回歸判準照舊（draft 模組差集、無 traceback、審核端點 401、叫料／匯款表、
設計器預設關…），承攬商 schema 由 `--expect-schema subcontract=4` 判定（第 32 班遷移 0004_dispatch_doc_code_backfill），再加第 32 班的：
  17a 卡住的列（基線用舊程式對舊單「申請完工」⇒ completion_status=待審核、doc_code=''）套用後被補成 DP-YYYYMMDD-NNNN，**只動 doc_code**
      （該列其他欄位逐欄不變；單號日期＝該筆申請完工的日期）
  17b 沒卡住的舊單（原 4 筆）doc_code 仍是空字串、其餘審核欄位不變
  17c 簽核佇列出現「承攬商派發完工」且單號＝補的單號
  17d 套用後對另一筆舊單「申請完工」⇒ 送審當下就補 doc_code，也進佇列
紅線同 TRAIN29-DRILL：不碰正式機／金鑰；全合成資料；埠 6760 只綁 127.0.0.1；跑完清。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402

T = T30.T
BASE32 = "a5dea50c"
STUCK_ID = 5          # 基線用舊程式申請完工 ⇒ 卡住
LATER_ID = 6          # 套用後才申請完工 ⇒ 新程式送審當下補號
DOC_RE = re.compile(r"^DP-(\d{8})-(\d{4})$")


def _row(root, did):
    c = T.ro(root)
    try:
        r = c.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def seed_stuck(root, port):
    """基線（舊程式）：再建兩筆『已驗收』舊單（approval_status=''）；對 STUCK_ID 申請完工 ⇒ 卡住（待審核、doc_code=''）。"""
    now = "2026-09-25T09:00:00"
    c = T.rw(root)
    try:
        vid = c.execute("SELECT MIN(id) FROM vendor_contractors").fetchone()[0]
        for did in (STUCK_ID, LATER_ID):
            c.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, status, created_by,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (did, "%sMQ-001" % T.SEED_TAG, vid, "2026-09-2%d" % did, "DRILL完工待審%d" % did, "[]", 1000 * did, "accepted", "drill", now, now))
        c.commit()
    finally:
        c.close()
    _u, token = T.login(root, port)
    s, d = T.api(port, "/api/contractor-dispatches/%d/completion/request" % STUCK_ID, {}, token, "POST")
    row = _row(root, STUCK_ID)
    review = seed_material_review(root, port, token)
    return {"review_seed": review, "request_status": s, "request_body": str(d)[:200], "row": row,
            "stuck": bool(row and row["completion_status"] in ("待審核", "簽核中") and (row["doc_code"] or "") == "")}


REVIEW_FEE, REVIEW_PAID = 15.0, "2026-10-01"


def seed_material_review(root, port, token):
    """基線：一張已核准的材料申請匯款（核准 1000）＋一筆多付的付款明細（實付 1200、手續費 15、待差額審核）——
    第 32 包要驗出納『差額審核』項目的 fee／paidAt 有值（修正前兩欄被行內註解吞掉）。直接寫表（只用有預設值的欄位）。"""
    now = "2026-10-01T10:00:00"
    c = T.rw(root)
    try:
        sn = json.dumps({"supplierName": "DRILL供應商", "bankCode": "700", "bankName": "中華郵政", "bankAccountNumber": "00012345678901"}, ensure_ascii=False)
        cur = c.execute("INSERT INTO case_material_payments (doc_code, quote_no, item_id, seq, amount_approved, snapshot_json, status, approved_at, created_by, created_at, updated_at)"
                        " VALUES ('DRILL-MP-0001', ?, 'drill-item-1', 1, 1000, ?, '已核准', ?, 'drill', ?, ?)", ("%sMQ-001" % T.SEED_TAG, sn, now, now, now))
        pid = cur.lastrowid
        cur = c.execute("INSERT INTO case_material_payment_lines (payment_id, paid_at, amount, fee, remit_review, paid_by, created_at) VALUES (?,?,?,?, 'pending','drill',?)",
                        (pid, REVIEW_PAID + "T10:00:00", 1200, REVIEW_FEE, now))
        lid = cur.lastrowid
        c.commit()
    finally:
        c.close()
    s, d = T.api(port, "/api/cashier/remit-reviews", token=token)
    items = [i for i in ((d or {}).get("items") or []) if isinstance(i, dict) and str(i.get("key")) == str(lid)] if isinstance(d, dict) else []
    return {"line_id": lid, "baseline_status": s, "baseline_item": {k: items[0].get(k) for k in ("fee", "paidAt", "source", "actual", "payable")} if items else None}


def add32(rec, root):
    c = T.ro(root)
    try:
        rec["dispatch_rows"] = {r["id"]: dict(r) for r in c.execute("SELECT * FROM contractor_dispatches ORDER BY id")}
    finally:
        c.close()
    return rec


def _queue_items(port, token):
    s, d = T.api(port, "/api/approval-queue", token=token)
    # 回傳形狀：{"queue": [{requestedBy, count, items: [...]}], "total": N, ...}（依送審人分組）⇒ 攤平
    items = []
    if isinstance(d, dict):
        for g in d.get("queue") or []:
            items += [i for i in (g.get("items") or []) if isinstance(i, dict)]
    return s, items


def checks32(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    for k in ("16_subcontract_schema_stays_3", "9c_legacy_dispatch_untouched", "16_material_tables_exist_and_empty"):
        res.pop(k, None)                          # 第 32 班：subcontract 3→4；舊單判準改成下面的 17b；材料表改成『筆數＝基線（種子 1 筆申請＋1 筆明細）』
    stuck = getattr(T, "_STUCK", None) or {}
    before = (stuck.get("row") or {})
    after = new_rec.get("dispatch_rows", {}).get(STUCK_ID) or {}
    ok_seed = bool(stuck.get("stuck"))
    code = after.get("doc_code") or ""
    m = DOC_RE.match(code)
    want_day = ((before.get("completion_requested_at") or "")[:10]).replace("-", "")
    changed = sorted(k for k in set(before) | set(after) if k != "doc_code" and before.get(k) != after.get(k))
    res["17a_stuck_row_backfilled_only_doc_code"] = (
        ok_seed and bool(m) and (not want_day or m.group(1) == want_day) and not changed,
        {"seeded_stuck": ok_seed, "request": (stuck.get("request_status"), stuck.get("request_body")), "doc_code": code,
         "want_day": want_day, "other_columns_changed": changed})
    legacy = {i: r for i, r in new_rec.get("dispatch_rows", {}).items() if i <= 4}
    base_legacy = {i: r for i, r in base_rec.get("dispatch_rows", {}).items() if i <= 4}
    res["17b_untouched_legacy_rows_keep_empty_doc_code"] = (
        bool(legacy) and legacy == base_legacy and all((r["doc_code"] or "") == "" and (r["approval_status"] or "") == "" for r in legacy.values()),
        {"rows": len(legacy), "identical_to_baseline": legacy == base_legacy})
    _u, token = T.login(root, port)
    s, items = _queue_items(port, token)
    hit = [i for i in items if isinstance(i, dict) and i.get("typeLabel") == "承攬商派發完工" and i.get("docCode") == code]
    res["17c_queue_shows_completion_with_the_backfilled_code"] = (bool(code) and len(hit) == 1, {"status": s, "items": len(items), "hit": len(hit)})
    # 18：出納差額審核項目的 fee／paidAt（修正：材料申請匯款的兩欄被行內註解吞掉而為空）
    seed = stuck.get("review_seed") or {}
    s3, d3 = T.api(port, "/api/cashier/remit-reviews", token=token)
    its = [i for i in ((d3 or {}).get("items") or []) if isinstance(i, dict) and str(i.get("key")) == str(seed.get("line_id"))] if isinstance(d3, dict) else []
    it = its[0] if its else {}
    res["18_remit_review_item_has_fee_and_paidAt"] = (
        s3 == 200 and len(its) == 1 and it.get("fee") == REVIEW_FEE and it.get("paidAt") == REVIEW_PAID and it.get("source") == "case_material",
        {"status": s3, "item": {k: it.get(k) for k in ("source", "key", "fee", "paidAt", "actual", "payable", "diff")}, "baseline_item": seed.get("baseline_item")})
    c = T.ro(root)
    try:
        tabs = {t: (T.table_exists(c, t), T.count(c, t)) for t in ("case_material_approvals", "case_material_payments", "case_material_payment_lines")}
    finally:
        c.close()
    res["16_material_tables_exist_with_the_seeded_rows_only"] = (tabs == {"case_material_approvals": (True, 0), "case_material_payments": (True, 1), "case_material_payment_lines": (True, 1)}, tabs)
    # 17d：套用後對另一筆舊單申請完工
    sr, dr = T.api(port, "/api/contractor-dispatches/%d/completion/request" % LATER_ID, {}, token, "POST")
    later = _row(root, LATER_ID) or {}
    code2 = later.get("doc_code") or ""
    s2, items2 = _queue_items(port, token)
    hit2 = [i for i in items2 if isinstance(i, dict) and i.get("typeLabel") == "承攬商派發完工" and i.get("docCode") == code2]
    res["17d_new_legacy_completion_request_gets_a_code_and_a_queue_entry"] = (
        sr == 200 and bool(DOC_RE.match(code2)) and len(hit2) == 1,
        {"request": (sr, str(dr)[:160]), "doc_code": code2, "completion_status": later.get("completion_status"), "queue_hits": len(hit2)})
    return res


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    import argparse
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--expect-schema", action="append", default=[])
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version
    for kv in known.expect_schema:
        k, v = kv.split("=")
        T31._EXPECT["schema"][k] = int(v)
    T.deliver = T31.deliver31
    orig_main = T.main

    def main_with_hooks(a):
        T.checks_after_apply = checks32
        prev_rec, prev_mb = T.record, T.make_baseline

        def rec(root):
            return add32(prev_rec(root), root)

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            T._STUCK = seed_stuck(root, port)
            info["stuck_seed"] = {k: v for k, v in T._STUCK.items() if k != "row"}
            return root, info
        T.record, T.make_baseline = rec, mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", BASE32]
    return T30.main(rest)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
