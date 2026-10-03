# -*- coding: utf-8 -*-
"""第 35b 班套用演練（d5；基線＝prod/326e6676＝第 35a 班已上線的正式機現況；新版＝35b 候選包 345a34cd）。由 drill_train35a 的零件組成
（安裝／套用／回滾／A→C→E→B 沿用 drill_train_apply），種子與判準換成 35b 的。

35b 內容：
  案件／精算：精算稅基 B（承攬商成本＝未稅＋外包人員；稅額是進項稅額不計成本）、完結時後端全欄位重算（F1）、已完結再存要理由（理由僅財務檢視可見）、
              完結 409 訊息中性、結案報表 PDF 新完結案多一行承攬商稅額說明、精算頁已對應清單
  標案雷達：空結果頁不是解析失敗、不寄信日（週六日／國定假日）、假日表、狀態列各種狀態、驗證碼頁停止抓取詳細頁、每列「前往來源網站明細」連結＋未取得說明
判準（主持 2026-10-04 指派）：
  35b_1  財務使用者 GET settlement-actuals：dispatchTotal＝未稅＋外包人員（種子 10000＋2000＝12000、稅 500、含稅 12500、dispatchBasis pretax）；與套用前相比只有 dispatchTotal／totalActualCost 變
  35b_2  非財務使用者 ⇒ 403、無任何新欄位
  35b_3  舊的已凍結案（沒有口徑標記）讀取不變
  35b_4  真實瀏覽器在精算頁按完結 ⇒ 存下 12000／pretax／與草稿同總成本
  35b_5  偽造的完結 ⇒ 409（dispatchTotal 0＋pretax 標記；含稅 12500 蓋 pretax 標記）且不存檔；誠實 payload 正對照 200
  35b_6  重新開啟沒有理由 ⇒ 422；有理由 ⇒ 200；理由對非財務帳號在 GET /api/quotations/{no}、/case-bundle、/versions 都看不到、財務帳號看得到
  35b_7  新完結案的結案報表 PDF 有「承攬商：未稅／稅額」行；舊案 PDF 與套用前文字相同
  35b_8  案件頁含 cm-tab-settlement；settlement.html 含重新開啟理由對話框
  35b_t* 標案雷達（演練用程式層替身，不連網、不寄信，見 drill_35b_tender_harness.py）＋頁面狀態列＋列連結（真瀏覽器）
  35b_c  13 個模組載入、版本 case 1.0.129／tender_radar 1.5.6／analytics 1.0.29、無 traceback、單一監聽行程（沿用 checks31）
  B      只回程式 ⇒ 程式檔逐檔與基線相同；之後再套用一次（R）
用法（.venv312）：
  python tools/platform/drill_train35b.py --delivery-root <演練交付資料夾> --name <包名> --new-commit <SHA> --pubkey-file <演練公鑰.pem> \
         [--runs A,B] [--keep] [--drill-root <演練目錄>] [--port 6766]
紅線：不碰正式機／正式金鑰／正式資料庫／G: 雲端檔；不連真實標案網站；只綁 127.0.0.1；全合成資料；跑完清。
"""
import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drill_train30 as T30  # noqa: E402
import drill_train31 as T31  # noqa: E402
import drill_train35a as T35A  # noqa: E402

T = T30.T
DM = T30.DM if hasattr(T30, "DM") else T.DM
TRAIN = {"number": "35b", "base": "326e6676", "schema": {"case": 6, "subcontract": 5}, "db_version": 116}
ENG = ("drill_eng", "Drill-Eng-Pass!9")
Q_NEW1, Q_NEW2, Q_OLD = "DRILL-35B-N1", "DRILL-35B-N2", "DRILL-35B-OLD"
SECRET = "機密理由XYZ金額99999"
_FAILED = T35A._FAILED
_BASE = T35A._BASE
_PUB = T35A._PUB
_CTX = {}
EXPECT_VERSIONS = {"case": "1.0.129", "tender_radar": "1.5.6", "analytics": "1.0.29"}

#: 35b 之前班次專屬、在這個基線（已含 35a）上不成立的舊題；理由逐項寫明
_STALE = dict(T35A._STALE)
_STALE.update({
    "9c_legacy_dispatch_untouched": "第 30 班專屬（舊派發單不動）；基線已含兩段審核，種子派發的欄位預設不同",
})
#: 標案 fixtures（安裝包不含 tests/）：取自標案分支工作樹（與 int2 的同檔雜湊相同，演練前已逐檔比對）
FIXTURES = Path("D:/開發測試檔/t35b-tender/backend/modules/tender_radar/tests/fixtures")
T35A._SKIP_DIRS.add("backup_alerts")        # 執行期產生的備份告警檔（演練庫沒有備份目標），不是程式檔
_SESSION_KEYS = ("token", "userId", "username", "displayName", "role", "modules", "loginAt")
_PREVISITED = ("motrix_totp_reminder_shown", "motrix_approval_banner_shown")
_STAMP = re.compile(r"\d{4}[-/]\d\d[-/]\d\d[ T]\d\d:\d\d(:\d\d)?")


def _install_py():
    return sys.executable


def seed35b(root, port):
    """基線（326e6676 程式）上的 35b 種子：兩個新案（各一張已驗收派發：未稅 10000、稅率 5%、外包人員 2000；報價稅前 100000）、
    一個舊的已凍結完結案（summary 沒有 dispatchBasis）、非財務使用者（被指派這三案）。"""
    c = T.rw(root)
    try:
        vid = c.execute("SELECT MIN(id) FROM vendor_contractors").fetchone()[0]
        if vid is None:
            c.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES ('DRILL承攬商35b','2026-10-04','2026-10-04')")
            vid = c.execute("SELECT MAX(id) FROM vendor_contractors").fetchone()[0]
        hashes = T30._hash_cmds(root, {ENG[0]: ENG[1]})
        now = "2026-10-04T09:00:00"
        c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password)"
                  " VALUES (?,?,?,?,?,1,?,0)", (ENG[0], hashes[ENG[0]], ENG[0], "engineer", '["case_manage"]', now))
        uid = c.execute("SELECT id FROM users WHERE username=?", (ENG[0],)).fetchone()["id"]
        old_summary = {"quotedPretax": 100000, "itemActualTotal": 10000, "itemPoUnadopted": 0, "extraTotal": 0, "dispatchTotal": 12500, "totalActualCost": 22500,
                       "remitFeeTotal": 0, "customExpenseTotal": 0, "grossProfit": 77500, "grossMarginPct": 77.5, "adminCost": 10000, "charityDonation": 775,
                       "netProfit": 66725, "netMarginPct": 66.7}
        for q in (Q_NEW1, Q_NEW2, Q_OLD):
            d = {"dealTag": "已成案", "items": [{"id": "a", "description": "品項A", "qty": 1, "cost": 10000, "unitPrice": 10000, "amount": 10000}],
                 "tot": {"pretax": 100000, "total": 105000}, "customerName": "演練客戶"}
            settle_status = ""
            deal_tag = "已成案"
            if q == Q_OLD:
                d["settlement"] = {"status": "finalized", "items": [{"id": "a", "adoptSystem": False, "actualTotalCost": 10000}], "offsets": [],
                                   "summary": old_summary, "finalizedAt": "2026-09-30T10:00:00", "finalizedBy": "drill"}
                d["editHistory"] = [{"rev": 1, "at": "2026-09-30T10:00:00", "by": "drill", "byDisplay": "drill", "type": "settlement_finalized"}]
                settle_status = "finalized"
                deal_tag = "已結案"
            c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, settle_status, assigned_user_ids)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (q, "已送出", "演練客戶", "35b 演練案 " + q, 105000, 100000, json.dumps(d, ensure_ascii=False), "2026-09-01T00:00:00", now, deal_tag, settle_status, json.dumps([uid])))
            c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, tax_rate, status, created_by,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (q, vid, "2026-09-20", "DRILL35B派發", "[]", json.dumps([{"name": "DRILL點工", "amount": 2000}], ensure_ascii=False), 10000, 0.05, "accepted", "drill", now, now))
        c.commit()
    finally:
        c.close()
    return {"quotes": [Q_NEW1, Q_NEW2, Q_OLD], "dispatch": {"untaxed": 10000, "rate": 0.05, "personnel": 2000}, "engineer_user": ENG[0]}


def _actuals(port, token, quote):
    return T.api(port, "/api/quotations/%s/settlement-actuals" % quote, token=token)


def _json_text(x):
    return json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x


def page_payload(d, quoted_pretax=100000):
    """逐字照精算頁 calcSummary 的算法，用後端單一來源（settlement-actuals）的數字組出完結 payload。"""
    t = d["totals"]
    items = [{"id": i["itemId"], "adoptSystem": True, "actualTotalCost": i["actual"]["amount"]} for i in d["items"]]
    extra_total = t["extraTotal"] + t["materialUnassignedTotal"] + t["remitFeeTotal"] + t["customExpenseTotal"]
    total = t["itemActualTotal"] + 0 + extra_total + t["dispatchTotal"]
    gross = quoted_pretax - total
    admin = int(round(quoted_pretax * 0.10))
    charity = int(round(gross * 0.01 + 1e-9))
    net = gross - admin - charity
    summ = {"quotedPretax": quoted_pretax, "quotedTotal": 105000, "itemActualTotal": t["itemActualTotal"], "itemPoUnadopted": 0, "extraTotal": extra_total,
            "dispatchTotal": t["dispatchTotal"], "totalActualCost": total, "remitFeeTotal": t["remitFeeTotal"], "customExpenseTotal": t["customExpenseTotal"],
            "purchasedTotal": t["purchasedTotal"], "materialUnassignedTotal": t["materialUnassignedTotal"], "dispatchTax": t.get("dispatchTax"),
            "dispatchGrandTotal": t.get("dispatchGrandTotal"), "dispatchBasis": "pretax", "grossProfit": gross,
            "grossMarginPct": round(gross / quoted_pretax * 100, 1), "adminCost": admin, "charityDonation": charity, "netProfit": net,
            "netMarginPct": round(net / quoted_pretax * 100, 1)}
    return {"status": "finalized", "items": items, "summary": summ, "offsets": []}


def pdf_text(raw):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(raw))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def _norm_pdf(txt):
    return _STAMP.sub("<時間>", re.sub(r"\s+", " ", txt))


def browser_session_init(port, user, pw):
    s, d = T.api(port, "/api/auth/login", {"username": user, "password": pw})
    if s != 200 or not isinstance(d, dict):
        raise RuntimeError("登入失敗 %s" % _json_text(d)[:120])
    sess = {k: d.get(k) for k in _SESSION_KEYS}
    flags = "".join("sessionStorage.setItem(%s, '1');" % json.dumps(k) for k in _PREVISITED)
    return "try { localStorage.setItem('motrix_session', %s); %s } catch (e) {}" % (json.dumps(json.dumps(sess)), flags)


def browser_finalize(port, user, pw, quote):
    """真實瀏覽器：開精算頁 ⇒ 按「完結精算」⇒「確認完結」；回 (PUT 狀態, 回應文字)。"""
    from playwright.sync_api import sync_playwright
    S = "Alpine.$data(document.body)"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(viewport={"width": 1400, "height": 1100})
            ctx.add_init_script(browser_session_init(port, user, pw))
            page = ctx.new_page()
            page.goto("http://127.0.0.1:%d/pages/settlement.html?no=%s" % (port, quote))
            page.locator('[data-testid="stl-finalize"]').wait_for(state="visible", timeout=30000)
            page.wait_for_function("() => %s.summary && %s._actualsOk && !%s.loading" % (S, S, S), timeout=30000)
            page.locator('[data-testid="stl-finalize"]').click()
            with page.expect_response(lambda r: r.request.method == "PUT" and "/settlement" in r.url, timeout=30000) as resp:
                page.get_by_role("button", name="確認完結").click()
            st, txt = resp.value.status, resp.value.text()[:200]
            page.wait_for_function("() => %s.settlement.status === 'finalized' && !%s.saving" % (S, S), timeout=30000)
            return st, txt
        finally:
            b.close()


def browser_tender_rows(port, user, pw):
    """真實瀏覽器：標案雷達頁——每列的來源網站連結與「未取得」說明。"""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script(browser_session_init(port, user, pw))
            page = ctx.new_page()
            page.route("**/*tile*", lambda r: r.abort())
            page.goto("http://127.0.0.1:%d/pages/tender-radar.html" % port)
            page.wait_for_selector('tr[data-case-no="D35B-1"]', timeout=30000)
            for no in ("D35B-1", "D35B-2", "D35B-3"):
                row = page.locator('tr[data-case-no="%s"]' % no)
                a = row.locator("a[data-source-link]")
                out[no] = {"link_count": a.count(), "link_text": a.first.inner_text().strip() if a.count() else None,
                           "target": a.first.get_attribute("target") if a.count() else None, "rel": a.first.get_attribute("rel") if a.count() else None,
                           "href": a.first.get_attribute("href") if a.count() else None,
                           "helper_count": row.locator("[data-captcha-help]").count(),
                           "helper_text": [h.inner_text().strip() for h in row.locator("[data-captcha-help]").all()],
                           "location_missing": row.locator("[data-location-missing]").count(), "method_missing": row.locator("[data-method-missing]").count()}
            out["notices"] = [n.inner_text().strip()[:60] for n in page.locator("[data-source-notice]").all()]
        finally:
            b.close()
    return out


def run_harness(root, mode, *args):
    import os as _os
    env = dict(_os.environ, DRILL_FIXTURES=str(FIXTURES))
    cp = subprocess.run([sys.executable, str(HERE / "drill_35b_tender_harness.py"), mode, *args], cwd=str(Path(root) / "backend"), env=env,
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    line = next((ln for ln in cp.stdout.splitlines() if ln.startswith("::JSON::")), None)
    if cp.returncode != 0 or line is None:
        return None, {"rc": cp.returncode, "stdout_tail": cp.stdout[-800:], "stderr_tail": cp.stderr[-1200:]}
    return json.loads(line[len("::JSON::"):]), {"rc": cp.returncode}


def checks35b(root, port, base_rec, new_rec, t0, package_modules):
    res = T31.checks31(root, port, base_rec, new_rec, t0, package_modules)
    stale = {k: _STALE[k] for k in _STALE if k in res}
    for k in stale:
        res.pop(k)
    res["35b_0_stale_checks_skipped"] = (True, stale)
    admin_user, tok = T.login(root, port)
    admin_pw = "Drill-%d-Pass!9" % port
    _CTX["admin"] = (admin_user, admin_pw)

    # 35b_1 財務使用者：新口徑；與套用前比只有 dispatchTotal／totalActualCost 變、其餘值相同
    s, d = _actuals(port, tok, Q_NEW1)
    base = _BASE.get("new1")
    added, changed, removed = T35A.diff_shapes(base, d) if (base and isinstance(d, dict)) else (set(), [("no-base", None)], [])
    t = (d or {}).get("totals", {}) if isinstance(d, dict) else {}
    changed_paths = sorted(p for p, _ in changed)
    res["35b_1_financial_pretax_basis"] = (
        s == 200 and t.get("dispatchTotal") == 12000 and t.get("dispatchTax") == 500 and t.get("dispatchGrandTotal") == 12500 and t.get("dispatchBasis") == "pretax"
        and set(changed_paths) <= {"/totals/dispatchTotal", "/totals/totalActualCost"} and not removed,
        {"status": s, "dispatchTotal": t.get("dispatchTotal"), "dispatchTax": t.get("dispatchTax"), "dispatchGrandTotal": t.get("dispatchGrandTotal"),
         "dispatchBasis": t.get("dispatchBasis"), "baseline_dispatchTotal": ((base or {}).get("totals") or {}).get("dispatchTotal"),
         "changed_vs_baseline": [list(x) for x in changed], "added_keys": sorted(a.rsplit("/", 1)[-1] for a in added), "removed": removed[:5],
         "draft_totalActualCost": t.get("totalActualCost")})
    _CTX["draft_total_cost"] = t.get("totalActualCost")

    # 35b_2 非財務使用者：403、沒有新欄位
    etok = T30._login_as(port, *ENG)
    s2, d2 = _actuals(port, etok, Q_NEW1) if etok else (None, None)
    txt = _json_text(d2) if d2 is not None else ""
    res["35b_2_non_financial_403_no_new_fields"] = (
        s2 == 403 and not any(k in txt for k in ("dispatchTax", "dispatchBasis", "dispatchGrandTotal", "totals")), {"status": s2, "body": txt[:140], "login_ok": bool(etok)})

    # 35b_3 舊的已凍結案：讀取不變（沒有值改變、沒有鍵消失；dispatchTotal 仍是存檔當時的含稅 12500）
    so, do = _actuals(port, tok, Q_OLD)
    bo = _BASE.get("old")
    a3, c3, r3 = T35A.diff_shapes(bo, do) if (bo and isinstance(do, dict)) else (set(), [("no-base", None)], [])
    res["35b_3_old_frozen_case_unchanged"] = (
        so == 200 and isinstance(do, dict) and do.get("frozen") is True and do["totals"]["dispatchTotal"] == 12500 and not c3 and not r3,
        {"status": so, "frozen": (do or {}).get("frozen") if isinstance(do, dict) else None,
         "dispatchTotal": ((do or {}).get("totals") or {}).get("dispatchTotal") if isinstance(do, dict) else None,
         "changed": [list(x) for x in c3[:6]], "removed": r3[:6], "added_keys": sorted(a.rsplit("/", 1)[-1] for a in a3)})

    # 35b_4 真實瀏覽器完結 N1
    try:
        pst, ptxt = browser_finalize(port, admin_user, admin_pw, Q_NEW1)
    except Exception as e:                                              # noqa: BLE001
        pst, ptxt = None, "%s: %s" % (type(e).__name__, str(e)[:200])
    ss, sd = T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, token=tok)
    summ = ((sd or {}).get("settlement") or {}).get("summary") or {} if isinstance(sd, dict) else {}
    res["35b_4_browser_finalize_stores_pretax"] = (
        pst == 200 and isinstance(sd, dict) and sd["settlement"].get("status") == "finalized" and summ.get("dispatchTotal") == 12000
        and summ.get("dispatchBasis") == "pretax" and summ.get("totalActualCost") == _CTX.get("draft_total_cost"),
        {"put_status": pst, "put_text": ptxt, "stored": {k: summ.get(k) for k in ("dispatchTotal", "dispatchTax", "dispatchGrandTotal", "dispatchBasis", "totalActualCost", "netProfit")},
         "draft_totalActualCost": _CTX.get("draft_total_cost")})

    # 35b_5 偽造的完結 ⇒ 409 不存檔；誠實 payload（正對照）⇒ 200
    sN, dN = _actuals(port, tok, Q_NEW2)
    honest = page_payload(dN)
    forged1 = json.loads(json.dumps(honest))
    forged1["summary"].update(dispatchTotal=0, totalActualCost=honest["summary"]["totalActualCost"] - 12000, netProfit=888888)
    forged2 = json.loads(json.dumps(honest))
    forged2["summary"].update(dispatchTotal=12500, totalActualCost=honest["summary"]["totalActualCost"] + 500)           # 含稅額蓋 pretax 標記
    r1 = T.api(port, "/api/quotations/%s/settlement" % Q_NEW2, {"settlement": forged1}, tok, "PUT")
    r2 = T.api(port, "/api/quotations/%s/settlement" % Q_NEW2, {"settlement": forged2}, tok, "PUT")
    st_after = (T.api(port, "/api/quotations/%s/settlement" % Q_NEW2, token=tok)[1] or {}).get("settlement") or {}
    res["35b_5_tampered_finalize_409_and_not_saved"] = (
        r1[0] == 409 and r2[0] == 409 and (st_after.get("status") or "") != "finalized",
        {"dispatchTotal_0_with_pretax_marker": [r1[0], _json_text(r1[1])[:150]], "gross_12500_under_pretax": [r2[0], _json_text(r2[1])[:150]], "status_after": st_after.get("status")})
    r3_ = T.api(port, "/api/quotations/%s/settlement" % Q_NEW2, {"settlement": honest}, tok, "PUT")
    res["35b_5b_honest_payload_positive_control_200"] = (r3_[0] == 200, {"status": r3_[0], "body": _json_text(r3_[1])[:120]})

    # 35b_6 重新開啟理由：沒有理由 422；有理由 200；對非財務帳號不可見、財務帳號可見
    cur = (T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, token=tok)[1] or {}).get("settlement") or {}
    draft = dict(cur, status="draft")
    n0 = T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, {"settlement": draft}, tok, "PUT")
    n1 = T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, {"settlement": draft, "reason": "   "}, tok, "PUT")
    still = ((T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, token=tok)[1] or {}).get("settlement") or {}).get("status")
    ok1 = T.api(port, "/api/quotations/%s/settlement" % Q_NEW1, {"settlement": draft, "reason": SECRET}, tok, "PUT")
    paths = ["/api/quotations/%s" % Q_NEW1, "/api/quotations/%s/case-bundle" % Q_NEW1, "/api/quotations/%s/versions" % Q_NEW1]
    eng = {p: T.api(port, p, token=etok) for p in paths} if etok else {}
    fin = {p: T.api(port, p, token=tok) for p in paths}
    eng_leak = [p for p, (st_, b_) in eng.items() if SECRET in _json_text(b_)]
    fin_see = [p for p, (st_, b_) in fin.items() if SECRET in _json_text(b_)]
    res["35b_6_reopen_needs_reason"] = (n0[0] == 422 and n1[0] == 422 and still == "finalized" and ok1[0] == 200,
                                         {"no_reason": [n0[0], _json_text(n0[1])[:90]], "blank_reason": n1[0], "status_after_refusals": still, "with_reason": ok1[0]})
    res["35b_6b_reason_hidden_from_non_financial"] = (
        bool(eng) and eng.get(paths[0], (None,))[0] == 200 and not eng_leak and paths[0] in fin_see and paths[2] in fin_see,
        {"engineer_statuses": {p: v[0] for p, v in eng.items()}, "engineer_leaks": eng_leak, "financial_sees_reason_in": fin_see})

    # 35b_7 結案報表 PDF（僅限已結案案件：N2 完結後把案件標成已結案；舊案種子已是已結案）
    c = T.rw(root)
    try:
        c.execute("UPDATE quotations SET deal_tag='已結案' WHERE quote_no=?", (Q_NEW2,))
        c.commit()
    finally:
        c.close()
    pn = T.raw_get(port, "/api/quotations/%s/closing-report-pdf" % Q_NEW2, tok, timeout=120)
    po = T.raw_get(port, "/api/quotations/%s/closing-report-pdf" % Q_OLD, tok, timeout=120)
    try:
        tn = pdf_text(pn[1]) if pn[0] == 200 else ""
        to = pdf_text(po[1]) if po[0] == 200 else ""
    except Exception as e:                                              # noqa: BLE001
        tn, to = "", "PDF 文字抽取失敗：%s" % e
    bt = _BASE.get("old_pdf_text")
    new_has_line = "承攬商" in tn and "進項稅額" in tn and "未稅" in tn
    res["35b_7_closing_pdf_new_case_has_tax_line"] = (pn[0] == 200 and new_has_line, {"status": pn[0], "bytes": len(pn[1]) if pn[0] == 200 else None,
                                                     "has_line": new_has_line, "excerpt": (tn[tn.find("承攬商"): tn.find("承攬商") + 80] if "承攬商" in tn else tn[:80])})
    old_same = bt is not None and po[0] == 200 and _norm_pdf(to) == _norm_pdf(bt)
    res["35b_7b_closing_pdf_old_case_unchanged"] = (po[0] == 200 and "進項稅額" not in to and old_same,
                                                    {"status": po[0], "baseline_pdf_available": bt is not None, "text_equal_to_baseline": old_same,
                                                     "len_now": len(to), "len_base": len(bt or "")})

    # 35b_8 頁面
    cm_file = (Path(root) / "frontend" / "pages" / "case-management.html").read_text(encoding="utf-8", errors="replace")
    st_file = (Path(root) / "frontend" / "pages" / "settlement.html").read_text(encoding="utf-8", errors="replace")
    sc, cb = T.raw_get(port, "/pages/case-management.html")
    ss2, sb = T.raw_get(port, "/pages/settlement.html")
    cbt = cb.decode("utf-8", "replace") if isinstance(cb, (bytes, bytearray)) else str(cb)
    sbt = sb.decode("utf-8", "replace") if isinstance(sb, (bytes, bytearray)) else str(sb)
    res["35b_8_pages_served"] = ('data-testid="cm-tab-settlement"' in cm_file and 'data-testid="cm-tab-settlement"' in cbt and sc == 200
                                 and ss2 == 200 and 'data-testid="stl-reopen-modal"' in sbt and "原因僅財務人員可見" in sbt and "_finalizing" in sbt,
                                 {"case-management": [sc, 'data-testid="cm-tab-settlement"' in cbt], "settlement": [ss2, 'data-testid="stl-reopen-modal"' in sbt, "原因僅財務人員可見" in sbt]})

    # 35b_t 標案雷達：程式層（替身）
    unit, info = run_harness(root, "unit")
    if unit is None:
        res["35b_t_harness"] = (False, info)
    else:
        for k, v in sorted(unit.items()):
            res["35b_%s" % k] = (bool(v[0]), v[1])
    # 頁面狀態列（寫進安裝的資料庫、讀 API 的 notices；結束還原）
    notices = {}
    for label, args in (("empty_day", ("empty_day", "-")), ("format_changed_and_captcha", ("format_changed", "captcha"))):
        _o, inf = run_harness(root, "state", *args)
        s_, b_ = T.api(port, "/api/tender-radar/status", token=tok)
        notices[label] = {"http": s_, "kinds": [n.get("kind") for n in (b_.get("notices") or [])] if isinstance(b_, dict) else _json_text(b_)[:100],
                          "listState": b_.get("listState") if isinstance(b_, dict) else None, "detailState": b_.get("detailState") if isinstance(b_, dict) else None}
    run_harness(root, "state", "ok", "ok")
    res["35b_t6_page_status_notices"] = (
        notices["empty_day"]["http"] == 200 and "empty_day" in notices["empty_day"]["kinds"]
        and "format_changed" in notices["format_changed_and_captcha"]["kinds"] and "detail_captcha" in notices["format_changed_and_captcha"]["kinds"], notices)
    # 列連結與未取得說明（真瀏覽器；標案列直接寫進安裝的資料庫，測完刪）
    c = T.rw(root)
    try:
        for no, loc, meth in (("D35B-1", "台中市", "公開招標"), ("D35B-2", None, None), ("D35B-3", "高雄市", None)):
            c.execute("INSERT INTO tenders (case_no, name, org, location, tender_method, url, fetched_at) VALUES (?,?,?,?,?,?,?)",
                      (no, "演練標案" + no, "演練機關", loc, meth, "https://web.pcc.gov.tw/prkms/urlSelector/common/tpam?pk=" + no, "2026-10-04"))
        c.commit()
    finally:
        c.close()
    try:
        rows = browser_tender_rows(port, admin_user, admin_pw)
    except Exception as e:                                              # noqa: BLE001
        rows = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
    c = T.rw(root)
    try:
        c.execute("DELETE FROM tenders WHERE case_no LIKE 'D35B-%'")
        c.commit()
    finally:
        c.close()
    HELP = "地點與招標方式需在來源網站通過驗證碼後查看"
    ok_rows = isinstance(rows, dict) and "error" not in rows and all(
        rows[n]["link_count"] == 1 and rows[n]["link_text"] == "前往來源網站明細" and rows[n]["target"] == "_blank" and "noopener" in (rows[n]["rel"] or "")
        for n in ("D35B-1", "D35B-2", "D35B-3")) and rows["D35B-1"]["helper_count"] == 0 and rows["D35B-2"]["helper_text"] == [HELP, HELP] and rows["D35B-3"]["helper_text"] == [HELP]
    res["35b_t7_row_link_and_missing_helper_rendered"] = (ok_rows, rows)

    # 35b_c 模組版本
    vers = {}
    for m, want in EXPECT_VERSIONS.items():
        mj = Path(root) / "backend" / "modules" / m / "module.json"
        vers[m] = json.loads(mj.read_text(encoding="utf-8-sig")).get("version") if mj.is_file() else None
    res["35b_c_module_versions"] = (vers == EXPECT_VERSIONS, {"installed": vers, "expected": EXPECT_VERSIONS})
    return res


def _wrap_apply_for_context():
    orig = T.apply_package

    def apply_package(root, port, payload):
        _CTX.update(root=root, port=port, payload=payload)
        return orig(root, port, payload)
    T.apply_package = apply_package


def _reapply_after_B(root_unused=None):
    """B（只回程式）之後再套用一次（主持：回滾後重套）；結果寫到 stdout 與暫存 JSON；失敗讓結束碼非 0。"""
    if not _CTX.get("payload"):
        return
    root, port, payload = _CTX["root"], _CTX["port"], _CTX["payload"]
    DM = T.DM
    try:
        DM.stop(root, port)
    except Exception:                                                  # noqa: BLE001
        pass
    DM.start(root, port)
    rec = T.apply_package(root, port, payload)
    new = T.record(root)
    adm = _CTX.get("admin")
    tok = T.login(root, port)[1]
    so, do = _actuals(port, tok, Q_OLD)
    s1, d1 = _actuals(port, tok, Q_NEW2)
    info = {"result": rec.get("result"), "commit": new.get("commit"), "ping": DM.ping(port),
            "old_case_frozen_dispatchTotal": ((do or {}).get("totals") or {}).get("dispatchTotal") if isinstance(do, dict) else None,
            "new2_frozen": (d1 or {}).get("frozen") if isinstance(d1, dict) else None,
            "log": T.server_log_tracebacks(root), "listeners": len(T.listening_pids(port))}
    info["ok"] = bool(rec.get("result") and rec["result"].get("status") == "success" and DM.ping(port) and info["old_case_frozen_dispatchTotal"] == 12500
                      and info["log"].get("traceback") == 0 and info["listeners"] == 1)
    print("R_REAPPLY::" + json.dumps(info, ensure_ascii=False, default=str))
    if not info["ok"]:
        _FAILED.append(("B 之後重新套用失敗", info))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--expect-db-version", type=int)
    ap.add_argument("--pubkey-file")
    ap.add_argument("--drill-root")
    known, rest = ap.parse_known_args(argv)
    T31._EXPECT["db_version"] = known.expect_db_version if known.expect_db_version is not None else TRAIN["db_version"]
    T31._EXPECT["schema"].update(TRAIN["schema"])
    if known.pubkey_file:
        _PUB["pem"] = Path(known.pubkey_file).read_bytes()
    if known.drill_root:
        T.DRILL_ROOT = Path(known.drill_root)
    T.deliver = T35A.deliver35
    T35A._wrap_rollback()
    _wrap_apply_for_context()
    orig_main = T.main
    orig_cleanup = T.DM.cleanup

    def cleanup(base_real):
        try:
            _reapply_after_B()
        except Exception as e:                                          # noqa: BLE001
            print("R_REAPPLY::ERROR", type(e).__name__, str(e)[:300])
            _FAILED.append(("B 之後重新套用丟例外", str(e)[:200]))
        try:
            if _CTX.get("root"):
                T.DM.stop(_CTX["root"], _CTX["port"])          # 重套之後服務是起著的：清除前一定要停（否則刪不掉目錄、埠也被佔著）
        except Exception as e:                                  # noqa: BLE001
            print("STOP::ERROR", type(e).__name__, str(e)[:200])
        return orig_cleanup(base_real)
    T.DM.cleanup = cleanup if "--keep" not in rest else orig_cleanup

    def main_with_hooks(a):
        T.checks_after_apply = checks35b
        prev_mb = T.make_baseline

        def mb(base, port, commit):
            root, info = prev_mb(base, port, commit)
            info["train35b_seed"] = seed35b(root, port)
            _u, tok = T.login(root, port)
            s1, d1 = _actuals(port, tok, Q_NEW1)
            s2, d2 = _actuals(port, tok, Q_OLD)
            _BASE["new1"] = d1 if s1 == 200 else None
            _BASE["old"] = d2 if s2 == 200 else None
            pr = T.raw_get(port, "/api/quotations/%s/closing-report-pdf" % Q_OLD, tok, timeout=120)
            try:
                _BASE["old_pdf_text"] = pdf_text(pr[1]) if pr[0] == 200 else None
            except Exception:                                           # noqa: BLE001
                _BASE["old_pdf_text"] = None
            _BASE["tree"] = T35A.tree_digest(root)
            info["train35b_baseline"] = {"new1_dispatchTotal": ((d1 or {}).get("totals") or {}).get("dispatchTotal") if isinstance(d1, dict) else None,
                                         "old_dispatchTotal": ((d2 or {}).get("totals") or {}).get("dispatchTotal") if isinstance(d2, dict) else None,
                                         "old_pdf_status": pr[0], "old_pdf_text_len": len(_BASE["old_pdf_text"] or ""), "tree_files": len(_BASE["tree"])}
            return root, info
        T.make_baseline = mb
        return orig_main(a)
    T.main = main_with_hooks
    if "--base-commit" not in rest:
        rest += ["--base-commit", TRAIN["base"]]
    if "--port" not in rest:
        rest += ["--port", "6766"]
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
