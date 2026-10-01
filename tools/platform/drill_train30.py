# -*- coding: utf-8 -*-
"""第 30 班套用演練（沿用 drill_train_apply 的零件；基線＝47db5613＝第 29 班正式機現況）。

用法：
  python tools/platform/drill_train30.py --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> [--runs A,C,E,B] [--keep]

判準（host 2026-10-02 指派）：A→C→E→B；承攬商 schema 3；舊派發單不動（approval_status=''）；新審核端點未登入 401；
builder-B 的 daily_tasks 掛載點在；一般使用者的待簽紅點資料來源可用；檔案中心開檔；勞報單帳號遮蔽；無 traceback。
紅線同 TRAIN29-DRILL：不碰正式機／正式機金鑰；全合成資料；埠 6760 只綁 127.0.0.1；跑完清（服務、安裝、暫存）。
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train_apply as T  # noqa: E402

DM = T.DM
BASE30 = "47db5613"
PLAIN = ("drill_plain", "Drill-Plain-Pass!9")
STAFF = ("drill_staff", "Drill-Staff-Pass!9")
FULL = "00012345678901"
MASKED = "****8901"
_orig_seed = T.seed
_orig_record = T.record


def _hash_cmds(root, names):
    """用安裝版自己的 helpers.auth 產生密碼雜湊（子行程，cwd＝安裝的 backend）。"""
    code = ("import sys,json\nfrom helpers.auth import _hash_pw\n"
            "print(json.dumps({u:_hash_pw(p) for u,p in json.loads(sys.argv[1]).items()}))")
    r = subprocess.run([sys.executable, "-c", code, json.dumps(names)], cwd=str(Path(root) / "backend"),
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise T.DrillError("產生密碼雜湊失敗：" + r.stderr[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def seed30(root, port):
    out = _orig_seed(root, port)
    now = "2026-09-25T09:00:00"
    c = T.rw(root)
    try:
        # 承攬商派發單 4 筆（舊版，沒有審核欄位）
        c.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES ('DRILL承攬商', ?, ?)", (now, now))
        vid = c.execute("SELECT MAX(id) FROM vendor_contractors").fetchone()[0]
        ids = []
        for i, st in enumerate(["draft", "sent", "confirmed", "completed"], 1):
            cur = c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, status, created_by,"
                            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            ("%sMQ-001" % T.SEED_TAG, vid, "2026-09-2%d" % i, "DRILL派發%d" % i, "[]", 1000 * i, st, "drill", now, now))
            ids.append(cur.lastrowid)
        out["dispatch_ids"] = ids
        # 外包人（含收款帳號）＋一般使用者／勞報單權限使用者
        c.execute("INSERT INTO contractors (name, bank_code, bank_name, bank_account_name, bank_account_number, created_at, updated_at)"
                  " VALUES ('DRILL甲承攬人','700','中華郵政','DRILL甲承攬人',?,?,?)", (FULL, now, now))
        out["contractor_id"] = c.execute("SELECT MAX(id) FROM contractors").fetchone()[0]
        hashes = _hash_cmds(root, {PLAIN[0]: PLAIN[1], STAFF[0]: STAFF[1]})
        for (u, _p), mods in ((PLAIN, "[]"), (STAFF, '["payslip"]')):
            c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password)"
                      " VALUES (?,?,?,?,?,1,?,0)", (u, hashes[u], u, "sales", mods, now))
        c.commit()
    finally:
        c.close()
    return out


def seed_payslip(root, port):
    """基線（舊程式）下建一張勞報單（帳號全碼；舊程式沒有遮蔽）⇒ slip_no。"""
    _u, token = T.login(root, port)
    cid = T.ro(root).execute("SELECT id FROM contractors WHERE name='DRILL甲承攬人'").fetchone()[0]
    s, d = T.api(port, "/api/payslips", {"contractor_id": cid, "data": {
        "contractorName": "DRILL甲承攬人", "incomeType": "9A", "grossAmount": 30000, "contractorNationality": "本國籍",
        "contractorHasUnionInsurance": False, "slipDate": "2026-09-25", "bankName": "中華郵政", "bankAccountNumber": FULL}}, token)
    return d.get("slip_no") if s == 201 else None


def record30(root):
    rec = _orig_record(root)
    c = T.ro(root)
    try:
        cols = T.columns(c, "contractor_dispatches")
        rec["dispatch_cols"] = cols
        rec["dispatch_digest"] = [dict(r) for r in c.execute(
            "SELECT id, quote_no, vendor_id, scope, items_json, total_amount, status FROM contractor_dispatches ORDER BY id")]
        if "approval_status" in cols:
            rec["dispatch_approval"] = [dict(r) for r in c.execute(
                "SELECT id, approval_status, completion_status, doc_code, approval_json FROM contractor_dispatches ORDER BY id")]
        else:
            rec["dispatch_approval"] = None
        rec["payslip_bank"] = [r[0] for r in c.execute("SELECT data_json FROM payslips")] and \
            [json.loads(r[0]).get("bankAccountNumber") for r in c.execute("SELECT data_json FROM payslips")]
    finally:
        c.close()
    return rec


def _login_as(port, user, pw):
    s, b = T.api(port, "/api/auth/login", {"username": user, "password": pw})
    return b["token"] if s == 200 else None


def checks30(root, port, base_rec, new_rec, t0, package_modules):
    res = {}
    res["1_version"] = (bool(new_rec["commit"]), new_rec["commit"])
    res["2_ping"] = (DM.ping(port), "")
    s1, _ = T.raw_get(port, "/openapi.json")
    s2, _ = T.raw_get(port, "/docs")
    res["5_api_docs_off"] = (s1 == 404 and s2 == 404, (s1, s2))
    bm, nm = base_rec["module_states"], new_rec["module_states"]
    changed = {k: (bm.get(k, {}).get("version"), v["version"]) for k, v in nm.items() if bm.get(k, {}).get("version") != v["version"]}
    res["6_modules"] = (all(v["state"] == "loaded" for v in nm.values()) and set(changed) == set(package_modules),
                        {"changed": changed, "unexpected": sorted(set(changed) ^ set(package_modules)), "count": len(nm)})
    tb = T.server_log_tracebacks(root)
    res["7_log_no_traceback"] = (tb.get("traceback") == 0, tb)
    pids = T.listening_pids(port)
    res["8_one_listener"] = (len(pids) == 1, pids)
    sv = new_rec["schema_versions"]
    bsv = base_rec["schema_versions"]
    res["9a_subcontract_schema_3"] = (sv.get("subcontract") == 3, {"base": bsv.get("subcontract"), "new": sv.get("subcontract")})
    res["9a_other_schemas_unchanged"] = ({k: v for k, v in sv.items() if k != "subcontract"} == {k: v for k, v in bsv.items() if k != "subcontract"},
                                         {"base": bsv, "new": sv})
    res["9a_db_version"] = (new_rec["db_version"] == base_rec["db_version"], (base_rec["db_version"], new_rec["db_version"]))
    cols = new_rec["dispatch_cols"]
    need = ["approval_status", "approval_json", "doc_code", "completion_status", "cancel_reason", "cancelled_at"]
    res["9b_dispatch_cols"] = (all(x in cols for x in need), [x for x in need if x not in cols])
    legacy = new_rec["dispatch_approval"] or []
    res["9c_legacy_dispatch_untouched"] = (
        new_rec["dispatch_digest"] == base_rec["dispatch_digest"] and len(legacy) == len(base_rec["dispatch_digest"]) > 0
        and all(r["approval_status"] == "" and r["completion_status"] == "" and r["doc_code"] == "" and r["approval_json"] == "{}" for r in legacy),
        {"rows": len(legacy), "digest_same": new_rec["dispatch_digest"] == base_rec["dispatch_digest"]})
    same = all(new_rec["counts"][t] == base_rec["counts"][t] for t in ("custom_records", "dev_cases", "quotations", "case_extra_expenses"))
    res["9c_counts"] = (same, {t: (base_rec["counts"][t], new_rec["counts"][t]) for t in T.COUNT_TABLES})
    # 新審核端點：未登入 401
    eps = ["/api/contractor-dispatches/1/submit", "/api/contractor-dispatches/1/approve", "/api/contractor-dispatches/1/reject",
           "/api/contractor-dispatches/1/withdraw", "/api/contractor-dispatches/1/completion/request",
           "/api/contractor-dispatches/1/completion/approve", "/api/contractor-dispatches/1/completion/reject",
           "/api/contractor-dispatches/1/completion/withdraw"]
    codes = {e: T.api(port, e, {}, None, "POST")[0] for e in eps}
    res["10_approval_endpoints_401"] = (all(v == 401 for v in codes.values()), codes)
    # builder-B：daily_tasks 掛載點（宣告）＋公開端點
    _u, token = T.login(root, port)
    s, d = T.api(port, "/api/platform/mount-points", token=token)
    pts = [p.get("id") for p in (d.get("points") if isinstance(d, dict) else [])]
    s2m, d2 = T.api(port, "/api/platform/mounts?point=daily_tasks.daily-tasks", token=token)
    res["11_builder_b_mount"] = (s == 200 and any("daily" in (p or "") for p in pts) and s2m == 200, {"points": pts[:12], "mounts": (s2m, str(d2)[:120])})
    # 一般使用者：待簽紅點資料來源（/api/approval-queue/count）可用；sidebar 帶紅點邏輯在
    ptok = _login_as(port, *PLAIN)
    sc, dc = T.api(port, "/api/approval-queue/count", token=ptok)
    sb = (Path(root) / "frontend" / "static" / "sidebar.js").read_text(encoding="utf-8", errors="replace")
    res["12_approval_dot_plain_user"] = (ptok is not None and sc == 200 and isinstance(dc, dict) and "count" in dc and "approval-queue/count" in sb, {"count_status": sc, "body": dc})
    # 檔案中心開檔：頁面含開檔按鈕；superadmin 搜尋有回、開檔位元組與種子相同；一般使用者看不到別人的檔
    fc = (Path(root) / "frontend" / "pages" / "file-center.html").read_text(encoding="utf-8", errors="replace")
    ss, sd = T.api(port, "/api/filehub/search?q=signed&date_from=", token=token)
    items = (sd.get("items") if isinstance(sd, dict) else None) or []
    opened = None
    if items:
        it = items[0]
        st, body = T.raw_get(port, "/api/attachments/open?type=%s&doc=%s&file=%s" % (it["sourceType"], it["docNo"], it["fileId"]), token)
        opened = (st, len(body), body[:4])
    ps, pd = T.api(port, "/api/filehub/search?q=signed&date_from=", token=ptok)
    res["13_file_center_open"] = ("data-fc-open" in fc and ss == 200 and bool(items) and opened and opened[0] == 200 and opened[1] > 0,
                                  {"items": len(items), "opened": opened, "plain_search": ps, "plain_items": len((pd.get("items") if isinstance(pd, dict) else None) or [])})
    # 勞報單帳號遮蔽
    slip = (new_rec.get("slip_no"))
    stok = _login_as(port, *STAFF)
    sa = ss2 = None
    if slip:
        ss2, sd2 = T.api(port, "/api/payslips/%s" % slip, token=stok)
        sa = ((sd2.get("data") or {}).get("bankAccountNumber") if isinstance(sd2, dict) else None)
        sup, sud = T.api(port, "/api/payslips/%s" % slip, token=token)
        su = ((sud.get("data") or {}).get("bankAccountNumber") if isinstance(sud, dict) else None)
        raw = T.api(port, "/api/payslips/%s" % slip, token=stok)
        leak = FULL in json.dumps(raw[1], ensure_ascii=False)
        res["14_payslip_mask"] = (ss2 == 200 and sa == MASKED and su == FULL and not leak, {"staff": sa, "superadmin": su, "leak": leak})
    else:
        res["14_payslip_mask"] = (False, "基線沒建出勞報單")
    return res


def main(argv=None):
    # 換掉第 29 班版的種子／記錄／檢查，其餘流程（A→C→E→B、回滾、清理）沿用
    T.SPECIFIC = ()                                  # 第 30 班的鍵名（9a_／9b_／10_…）全部都要算數，不套第 29 班的略過清單
    T.seed = seed30
    T.record = record30
    T.checks_after_apply = checks30
    orig_legacy = T.check_legacy_usable
    T.check_legacy_usable = lambda root, port, base_rec: (True, {"skipped": "第 30 班不比附件（第 29 班判準）"}, T.login(root, port)[1])
    T.legacy_flow = lambda port, token: (True, {"skipped": True})
    # 基線建好後補建勞報單（舊程式下）：包一層 make_baseline
    orig_mb = T.make_baseline

    def mb(base, port, commit):
        root, info = orig_mb(base, port, commit)
        info["slip_no"] = seed_payslip(root, port)
        T._SLIP = info["slip_no"]
        return root, info
    T.make_baseline = mb
    orig_rec = record30

    def rec_with_slip(root):
        r = orig_rec(root)
        r["slip_no"] = getattr(T, "_SLIP", None)
        return r
    T.record = rec_with_slip
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--base-commit" not in argv:
        argv += ["--base-commit", BASE30]
    if "--rehearsal" not in argv:
        argv.append("--rehearsal")                 # 第 29 班專屬判準（SPECIFIC 前綴）不套；第 30 班判準已併入 checks30（鍵名 9a_/9b_/9c_ 前綴會被略過！）
    return T.main(argv)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
