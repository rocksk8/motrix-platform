"""參數化報表範本（T79 候選）：參數驗證、篩選、與營運報表對帳、權限、Excel。

核心守則：範本**不重算金額**——沒有任何條件時，案件清單／業務員績效必須與 `/api/reports/financial` 的
casesAll／salesPerf 逐列相同（同一份算法）；有條件時是它的子集。
"""
import io
import json

import openpyxl
import pytest

NOW = "2026-01-01T00:00:00"


def _hdr(client, make_user, name, role="finance", modules=None):
    u, p = make_user(name, "Conn-Pass-123", role=role, modules=modules, legacy_finance_flag=False)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _pay(received, rcv_at="", expected="", pct=100):
    it = {"id": 1, "type": "尾款", "pct": pct, "received": received}
    if rcv_at:
        it["receivedAt"] = rcv_at
    if expected:
        it["expectedReceiptDate"] = expected
    return it


def _seed():
    """兩個部門、兩位業務、四張案件。回傳 (deptA, deptB)。

    MQ-T1  A部 甲業務  2026-03-10 已成案 100000 全收(03-20)        未精算  客戶「大海科技」
    MQ-T2  A部 甲業務  2026-05-10 已結案 200000 全收(05-30)        已精算  客戶「小山工程」
    MQ-T3  B部 乙業務  2026-05-12 已成案 300000 未收、預計 06-15     未精算  客戶「大海科技」
    MQ-T4  B部 乙業務  2026-08-01 已成案  50000 未收、沒填預計日     未精算  客戶「=1+1」
    """
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES ('事業處', 0, ?)", (NOW,))
        div = conn.execute("SELECT id FROM divisions WHERE name='事業處'").fetchone()["id"]
        ids = []
        for nm in ("工程部", "業務部"):
            conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,0,?)", (div, nm, NOW))
            ids.append(conn.execute("SELECT id FROM departments WHERE name=?", (nm,)).fetchone()["id"])
        uids = {}
        for uname, dept in (("甲業務", ids[0]), ("乙業務", ids[1])):
            conn.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at,"
                         " must_change_password, department_id) VALUES (?,?,?,?,?,1,?,0,?)",
                         ("rt_" + ("a" if uname == "甲業務" else "b"), "x", uname, "viewer", "[]", NOW, dept))
            uids[uname] = conn.execute("SELECT id FROM users WHERE display_name=?", (uname,)).fetchone()["id"]
        cases = [
            ("MQ-T1", "甲業務", "已成案", "2026-03-10", 100000, "大海科技", [_pay(True, "2026-03-20")], None),
            ("MQ-T2", "甲業務", "已結案", "2026-05-10", 200000, "小山工程", [_pay(True, "2026-05-30")], "finalized"),
            ("MQ-T3", "乙業務", "已成案", "2026-05-12", 300000, "大海科技", [_pay(False, expected="2026-06-15")], None),
            ("MQ-T4", "乙業務", "已成案", "2026-08-01", 50000, "=1+1", [_pay(False)], None),
        ]
        for qn, sp, tag, qd, total, cust, pay, settle in cases:
            dj = {"dealTag": tag, "caseRecord": {"roles": {"sales": sp}, "payment": {"items": pay}}}
            if settle:
                dj["settlement"] = {"status": settle, "summary": {"netProfit": 40000, "grossProfit": 50000}}
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                "created_at, updated_at, deal_tag, quote_date, sales_person, sales_person_id, settle_status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (qn, "已送出", cust, "專案" + qn[-1], total, total, json.dumps(dj), NOW, NOW, tag, qd, sp,
                 uids[sp], settle or ""))
        conn.commit()
        return ids[0], ids[1]
    finally:
        conn.close()


def _run(client, h, tid, qs=""):
    return client.get(f"/api/report-templates/{tid}/run" + ("?" + qs if qs else ""), headers=h)


def _nos(r):
    assert r.status_code == 200, r.text[:300]
    return {row["quoteNo"] for row in r.json()["rows"]}


# ── 權限 ────────────────────────────────────────────────────────────────────

URLS = ["/api/report-templates", "/api/report-templates/case-list/run", "/api/report-templates/payments/run",
        "/api/report-templates/sales-perf/run", "/api/report-templates/case-list/excel"]
PDF_URL = "/api/report-templates/case-list/pdf"      # xlsx 的 PDF 姊妹（平台規則）：需要 Edge 才出得了檔 ⇒ 只驗閘門


@pytest.mark.parametrize("url", URLS)
def test_gate_same_as_reports(client, make_user, url):
    assert client.get(url).status_code == 401
    for role in ("viewer", "engineer", "sales", "admin"):
        h = _hdr(client, make_user, "rtg_%s_%d" % (role, URLS.index(url)), role, modules=["reports"])
        r = client.get(url, headers=h)
        assert r.status_code == 403, (url, role, r.status_code)
        assert "財務" in r.json()["detail"]
    h = _hdr(client, make_user, "rtg_fin_%d" % URLS.index(url), "finance")
    assert client.get(url, headers=h).status_code == 200, url


def test_pdf_sibling_has_the_same_gate(client, make_user):
    assert client.get(PDF_URL).status_code == 401
    for role in ("viewer", "engineer", "sales", "admin"):
        h = _hdr(client, make_user, "rtg_pdf_" + role, role, modules=["reports"])
        r = client.get(PDF_URL, headers=h)
        assert r.status_code == 403 and "財務" in r.json()["detail"], (role, r.status_code)
    h = _hdr(client, make_user, "rtg_pdf_fin", "finance")
    assert client.get(PDF_URL + "?bogus=1", headers=h).status_code == 400, "PDF 與 Excel 走同一套參數驗證"
    assert client.get("/api/report-templates/nope/pdf", headers=h).status_code == 404


# ── 參數驗證 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("qs", [
    "bogus=1",                                  # 未知參數
    "date_from=2026-13-01",                     # 不存在的日期
    "date_from=2026/03/01",                     # 格式
    "date_from=2026-06-01&date_to=2026-05-01",  # 起>迄
    "department_id=abc", "department_id=99999",
    "deal_tag=報價中",                          # v1 母體只有成案／結案
    "settle_status=whatever",
    "customer=" + "字" * 41,
    "paid=received",                            # case-list 沒有 paid 參數
])
def test_bad_params_are_400(client, make_user, qs):
    _seed()
    h = _hdr(client, make_user, "rtv_" + str(abs(hash(qs)) % 10 ** 6))
    r = _run(client, h, "case-list", qs)
    assert r.status_code == 400, (qs, r.status_code, r.text[:200])


def test_unknown_template_404_and_empty_values_ignored(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtv_404")
    assert _run(client, h, "nope").status_code == 404
    assert _nos(_run(client, h, "case-list", "date_from=&department_id=&deal_tag=&customer=")) == {"MQ-T1", "MQ-T2", "MQ-T3", "MQ-T4"}


# ── 案件清單 ─────────────────────────────────────────────────────────────────

def test_case_list_filters(client, make_user):
    a, b = _seed()
    h = _hdr(client, make_user, "rtc1")
    assert _nos(_run(client, h, "case-list")) == {"MQ-T1", "MQ-T2", "MQ-T3", "MQ-T4"}
    assert _nos(_run(client, h, "case-list", "date_from=2026-05-01&date_to=2026-05-31")) == {"MQ-T2", "MQ-T3"}
    assert _nos(_run(client, h, "case-list", "date_from=2026-05-10&date_to=2026-05-10")) == {"MQ-T2"}, "起迄皆含"
    assert _nos(_run(client, h, "case-list", "date_from=2026-06-01")) == {"MQ-T4"}
    assert _nos(_run(client, h, "case-list", f"department_id={a}")) == {"MQ-T1", "MQ-T2"}
    assert _nos(_run(client, h, "case-list", f"department_id={b}")) == {"MQ-T3", "MQ-T4"}
    assert _nos(_run(client, h, "case-list", "deal_tag=已結案")) == {"MQ-T2"}
    assert _nos(_run(client, h, "case-list", "settle_status=finalized")) == {"MQ-T2"}
    assert _nos(_run(client, h, "case-list", "settle_status=pending")) == {"MQ-T1", "MQ-T3", "MQ-T4"}
    assert _nos(_run(client, h, "case-list", "sales_person=乙")) == {"MQ-T3", "MQ-T4"}
    assert _nos(_run(client, h, "case-list", "customer=大海")) == {"MQ-T1", "MQ-T3"}
    # 條件疊加是 AND
    assert _nos(_run(client, h, "case-list", f"customer=大海&department_id={b}&date_from=2026-05-01")) == {"MQ-T3"}
    assert _nos(_run(client, h, "case-list", "customer=不存在")) == set()


def test_case_list_summary_and_rows_are_consistent(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtc2")
    d = _run(client, h, "case-list", "date_from=2026-05-01&date_to=2026-05-31").json()
    s = {x["label"]: x["value"] for x in d["summary"]}
    assert s["案件數"] == 2 == len(d["rows"])
    assert s["合約總額"] == sum(r["total"] for r in d["rows"]) == 500000
    assert s["已收款"] == sum(r["received"] for r in d["rows"]) == 200000
    assert s["收款率"] == 40.0
    assert d["params"] == {"date_from": "2026-05-01", "date_to": "2026-05-31"}
    assert all(c["key"] in d["rows"][0] for c in d["columns"])


def test_no_conditions_equals_operating_report(client, make_user):
    """不重算：無條件時與 /api/reports/financial 的 casesAll 同案同金額；業務員績效與其 salesPerf 逐列相同。"""
    _seed()
    h = _hdr(client, make_user, "rtc3")
    fin = client.get("/api/reports/financial?period=2026", headers=h).json()
    by = {c["quoteNo"]: c for c in fin["casesAll"]}
    rows = _run(client, h, "case-list").json()["rows"]
    assert {r["quoteNo"] for r in rows} == set(by)
    for r in rows:
        c = by[r["quoteNo"]]
        assert (r["total"], r["received"], r["collectionRate"], r["estMargin"], r["actualMargin"], r["owner"], r["dept"]) == \
            (c["total"], c["receivedAmount"], c["collectionRate"], c["netMarginPct"], c["actualMarginPct"], c["ownerName"], c["deptName"])
    sp = _run(client, h, "sales-perf").json()["rows"]
    want = [(x["salesPerson"], x["caseCount"], x["totalAmount"], x["receivedAmount"], x["collectionRate"],
             x["avgMarginPct"], x["avgActualMarginPct"], x["settledCount"]) for x in fin["salesPerf"]]
    got = [(x["owner"], x["caseCount"], x["total"], x["received"], x["collectionRate"], x["estMargin"], x["actualMargin"], x["settled"])
           for x in sp]
    assert got == want and len(got) == 2


def test_department_filter_matches_operating_report(client, make_user):
    a, _ = _seed()
    h = _hdr(client, make_user, "rtc4")
    fin = client.get(f"/api/reports/financial?period=2026&department_id={a}", headers=h).json()
    assert _nos(_run(client, h, "case-list", f"department_id={a}")) == {c["quoteNo"] for c in fin["casesAll"]}


# ── 業務員績效 ───────────────────────────────────────────────────────────────

def test_sales_perf_respects_conditions(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rts1")
    d = _run(client, h, "sales-perf", "date_from=2026-05-01&date_to=2026-05-31").json()
    got = {r["owner"]: (r["caseCount"], r["total"], r["received"]) for r in d["rows"]}
    assert got == {"甲業務": (1, 200000, 200000), "乙業務": (1, 300000, 0)}
    d = _run(client, h, "sales-perf", "settle_status=finalized").json()
    assert [(r["owner"], r["settled"]) for r in d["rows"]] == [("甲業務", 1)]
    assert _run(client, h, "sales-perf", "customer=x").status_code == 400, "sales-perf 沒有 customer 參數"


# ── 收款明細 ─────────────────────────────────────────────────────────────────

def test_payments_filters_and_date_basis(client, make_user):
    a, b = _seed()
    h = _hdr(client, make_user, "rtp1")
    assert _nos(_run(client, h, "payments")) == {"MQ-T1", "MQ-T2", "MQ-T3", "MQ-T4"}
    assert _nos(_run(client, h, "payments", "paid=received")) == {"MQ-T1", "MQ-T2"}
    assert _nos(_run(client, h, "payments", "paid=unreceived")) == {"MQ-T3", "MQ-T4"}
    # 已收依實收日、未收依預計收款日
    assert _nos(_run(client, h, "payments", "date_from=2026-05-01&date_to=2026-06-30")) == {"MQ-T2", "MQ-T3"}
    assert _nos(_run(client, h, "payments", f"department_id={a}")) == {"MQ-T1", "MQ-T2"}
    assert _nos(_run(client, h, "payments", "customer=大海&paid=unreceived")) == {"MQ-T3"}


def test_payments_undated_rows_are_reported_not_silently_dropped(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtp2")
    d = _run(client, h, "payments", "date_from=2026-01-01&date_to=2026-12-31").json()
    assert "MQ-T4" not in {r["quoteNo"] for r in d["rows"]}
    assert any("1 筆" in n and "沒填" in n for n in d["notes"]), d["notes"]
    d = _run(client, h, "payments").json()
    assert "MQ-T4" in {r["quoteNo"] for r in d["rows"]}
    assert not any("沒填" in n for n in d["notes"])


def test_payments_amounts_match_operating_report(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtp3")
    fin = client.get("/api/reports/financial?period=2026", headers=h).json()
    want = {(i["quoteNo"], i["idx"]): (i["amount"], i["received"]) for i in fin["allItems"]}
    got = {(r["quoteNo"], 0): (r["amount"], r["state"] == "已收") for r in _run(client, h, "payments").json()["rows"]}
    assert got == want


# ── 目錄／截斷／Excel ─────────────────────────────────────────────────────────

def test_catalog_lists_templates_with_dept_options(client, make_user):
    a, b = _seed()
    h = _hdr(client, make_user, "rtl1")
    d = client.get("/api/report-templates", headers=h).json()
    assert [t["id"] for t in d["templates"]] == ["case-list", "payments", "sales-perf"]
    dept = next(p for p in d["templates"][0]["params"] if p["type"] == "department")
    assert sorted(o[0] for o in dept["options"]) == sorted([a, b])
    assert "事業處 / 工程部" in [o[1] for o in dept["options"]]


def test_every_template_row_has_all_catalog_columns(client, make_user):
    """欄位目錄與實際列要同步：目錄裡的 key 每一列都要有（否則畫面空白欄、Excel 空欄）。"""
    _seed()
    h = _hdr(client, make_user, "rtl2")
    import modules.analytics.api.report_templates as rt
    for tid, t in rt.TEMPLATES.items():
        rows = _run(client, h, tid).json()["rows"]
        assert rows, tid
        for r in rows:
            assert {c["key"] for c in t["columns"]} <= set(r), (tid, set(c["key"] for c in t["columns"]) - set(r))


def test_truncation_is_declared(client, make_user, monkeypatch):
    _seed()
    import modules.analytics.api.report_templates as rt
    monkeypatch.setattr(rt, "MAX_ROWS", 2)
    h = _hdr(client, make_user, "rtl3")
    d = _run(client, h, "case-list").json()
    assert d["truncated"] is True and len(d["rows"]) == 2
    assert any("只列出前 2 列" in n for n in d["notes"])
    assert {x["label"]: x["value"] for x in d["summary"]}["案件數"] == 4, "彙總算全部，不是被截斷的那幾列"


def test_excel_download(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtx1")
    r = client.get("/api/report-templates/case-list/excel?date_from=2026-05-01&date_to=2026-05-31", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["報表"]
    assert [c.value for c in ws[1]][:3] == ["案件號", "客戶", "專案名稱"]
    assert {ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)} == {"MQ-T2", "MQ-T3"}
    cond = {row[0].value: row[1].value for row in wb["條件"].iter_rows(min_row=1) if row[0].value}
    assert cond["報價日 起"] == "2026-05-01" and cond["報價日 迄"] == "2026-05-31" and cond["部門"] == "（全部）"
    assert cond["案件數"] == 2


def test_excel_neutralises_formula_text(client, make_user):
    """客戶名稱「=1+1」寫進 Excel 不得成為公式（沿用 helpers.xlsx_out 的中和）。"""
    _seed()
    h = _hdr(client, make_user, "rtx2")
    r = client.get("/api/report-templates/case-list/excel?customer=1%2B1", headers=h)
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["報表"]
    vals = [ws.cell(row=2, column=2).value]
    assert vals[0] != "=1+1" and not str(ws.cell(row=2, column=2).value).startswith("="), vals
    assert ws.cell(row=2, column=2).data_type != "f"


def test_excel_is_audited_with_its_conditions_and_rate_limited(client, make_user):
    _seed()
    import db
    h = _hdr(client, make_user, "rtx3")
    assert client.get("/api/report-templates/payments/excel?date_from=2026-01-01&paid=received", headers=h).status_code == 200
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT detail FROM audit_log WHERE action='export.xlsx' AND target_id='report-template'").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    d = json.loads(rows[0]["detail"])
    assert d["module"] == "analytics" and d["rows"] and d["rows"] >= 2
    assert d["filters"]["tid"] == "payments" and d["filters"]["date_from"] == "2026-01-01" and d["filters"]["paid"] == "received"
    assert client.get("/api/report-templates/payments/excel", headers=h).status_code == 429


def test_bad_params_on_excel_are_400_not_a_file(client, make_user):
    _seed()
    h = _hdr(client, make_user, "rtx4")
    assert client.get("/api/report-templates/case-list/excel?date_from=bad", headers=h).status_code == 400
