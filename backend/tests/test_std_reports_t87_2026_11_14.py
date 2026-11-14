# -*- coding: utf-8 -*-
"""T87 B1 標準報表（/api/std-reports）：權限矩陣、金額遮蔽、條件驗證、與既有報表的數字一致、匯出稽核。

釘住的規則（PM 裁示）：
- 營收／毛利／應收帳齡 ⇒ 沿用營運報表的閘門（財務／超管，或 reports 模組＋金額可視）；
- 案件進度 ⇒ 不含任何金額，範圍與案件清單一致（row_access）；
- 業務漏斗 ⇒ 件數照給，金額與「未填件數」依 can_see_financial；沒有業務開發權限 ⇒ 商機部分為空（不是 0）；
- 新端點不另寫第二套金額定義：應收帳齡合計＝/api/reports/ar-aging，營收逐筆＝收入明細提供者。
"""
import io
import json

import openpyxl
import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題讀寫案件（報價單／階段）資料並打標準報表端點")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
BASE = "/api/std-reports"
IDS = ("revenue", "gross-margin", "ar-aging", "case-progress", "sales-funnel")
MONEY_IDS = ("revenue", "gross-margin", "ar-aging")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _db():
    import db
    return db.get_db()


def _uid(username):
    conn = _db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _case(no, owner_id, owner_name, pretax=100000, total=105000, quote_date="2026-10-05", pay=None, extra=None):
    data = {"dealTag": "已成案"}
    cr = {"payment": {"items": pay or []}}
    data["caseRecord"] = cr
    data.update(extra or {})
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
            " updated_at, deal_tag, quote_date, sales_person_id, sales_person, net_margin_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "客戶" + no, "專案" + no, total, pretax, json.dumps(data, ensure_ascii=False),
             "2026-10-01T00:00:00", "2026-10-01T00:00:00", "已成案", quote_date, owner_id, owner_name, 20.0))
        conn.commit()
    finally:
        conn.close()


def _stage(no, label, order, done=False, due=""):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, start_date, due_date, assigned_to,"
            " depends_on, created_at, updated_at) VALUES (?,?,?,?,?,'',?,'[]','[]','t','t')",
            (no, label, order, 1 if done else 0, "2026-10-10" if done else "", due))
        conn.commit()
    finally:
        conn.close()


def _dev(name, status, owner_id, amount=None, created="2026-10-02T00:00:00"):
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO dev_cases (case_name, customer_name, status, sales_persons, planners, created_by, created_at,"
            " updated_at, assigned_to, expected_amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, "商機客戶" + name, status, json.dumps([owner_id]), "[]", owner_id, created, created, owner_id, amount))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    sa = make_user("sr_sa", role="superadmin")
    s1 = make_user("sr_sales1", role="sales", modules=None)
    s2 = make_user("sr_sales2", role="sales", modules=None)
    nomod = make_user("sr_nomod", role="viewer", modules=[])
    qdev = make_user("sr_qdev", role="viewer", modules=["dashboard", "quotation", "dev_crm"])
    devonly = make_user("sr_devonly", role="viewer", modules=["dashboard", "dev_crm"])
    i1, i2 = _uid("sr_sales1"), _uid("sr_sales2")
    # Q1：業務 1；收款一筆已收（10 月）、一筆未收；兩個階段（一完成、一已逾預定日）
    _case("SR-Q1", i1, "sr_sales1", pay=[
        {"type": "訂金", "amount": 52500, "received": True, "receivedAt": "2026-10-20"},
        {"type": "尾款", "amount": 52500, "received": False}])
    _stage("SR-Q1", "設計", 1, done=True)
    _stage("SR-Q1", "施工", 2, done=False, due="2026-01-05")
    # Q2：業務 2；沒有任何階段
    _case("SR-Q2", i2, "sr_sales2", pretax=200000, total=210000, quote_date="2026-10-08", pay=[
        {"type": "全額", "amount": 210000, "received": False}])
    _dev("機會A", "洽談中", i1, amount=500000)
    _dev("機會B", "洽談中", i1, amount=None)
    _dev("機會C", "成案", i1, amount=300000)
    _dev("機會D", "未成案", i2, amount=100000)
    iq = _uid("sr_qdev")                               # 無金額權限的使用者自己的商機（逐案可見才看得到）
    _dev("機會E", "洽談中", iq, amount=777000)
    _dev("機會F", "洽談中", iq, amount=None)
    _dev("機會G", "成案", iq, amount=333000)
    names = {"sa": sa, "s1": s1, "s2": s2, "nomod": nomod, "qdev": qdev, "devonly": devonly}
    h = {n: _login(client, *c) for n, c in names.items()}
    import helpers.xlsx_out as X
    X._export_times.clear()
    return h


def _get(client, h, rid, qs=""):
    return client.get(BASE + "/" + rid + (("?" + qs) if qs else ""), headers=h)


def _walk(o):
    """所有鍵與葉值（掃遮蔽用）。"""
    if isinstance(o, dict):
        for k, v in o.items():
            yield ("k", k)
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)
    else:
        yield ("v", o)


# ── 權限矩陣 ─────────────────────────────────────────────────────────────────

def test_catalog_lists_five_reports_with_availability(client, world):
    j = client.get(BASE, headers=world["sa"]).json()
    assert [r["id"] for r in j["reports"]] == list(IDS)
    assert all(r["available"] and r["reason"] == "" for r in j["reports"])
    assert j["maxRows"] == 20000 and isinstance(j["salesOptions"], list) and isinstance(j["departmentOptions"], list)
    rev = next(r for r in j["reports"] if r["id"] == "revenue")
    assert "basis" in rev["params"] and rev["needsMoney"] is True
    ar = next(r for r in j["reports"] if r["id"] == "ar-aging")
    assert "date_from" not in ar["params"] and "date_to" not in ar["params"]


def test_catalog_for_user_with_no_module_is_empty_but_ok(client, world):
    r = client.get(BASE, headers=world["nomod"])
    assert r.status_code == 200 and r.json()["reports"] == [] and r.json()["salesOptions"] == []


def test_catalog_requires_login(client, world):
    assert client.get(BASE).status_code in (401, 403)


@pytest.mark.parametrize("rid", IDS)
def test_superadmin_opens_every_report(client, world, rid):
    r = _get(client, world["sa"], rid)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["id"] == rid and isinstance(j["kpis"], list) and isinstance(j["notes"], list)
    assert j["truncated"] is False and j["generatedAt"]


@pytest.mark.parametrize("rid", IDS)
def test_no_module_user_is_refused_everywhere(client, world, rid):
    assert _get(client, world["nomod"], rid).status_code == 403


@pytest.mark.parametrize("rid", MONEY_IDS)
def test_quotation_dev_user_without_money_view_cannot_open_money_reports(client, world, rid):
    assert _get(client, world["qdev"], rid).status_code == 403


def test_dev_only_user_sees_funnel_but_not_case_progress(client, world):
    assert _get(client, world["devonly"], "sales-funnel").status_code == 200
    assert _get(client, world["devonly"], "case-progress").status_code == 403


def test_unknown_report_is_404(client, world):
    assert _get(client, world["sa"], "no-such").status_code == 404


# ── 案件進度 ─────────────────────────────────────────────────────────────────

def test_case_progress_semantics_and_no_money(client, world):
    j = _get(client, world["sa"], "case-progress").json()
    rows = {r["quoteNo"]: r for r in j["tables"][0]["rows"]}
    q1, q2 = rows["SR-Q1"], rows["SR-Q2"]
    assert (q1["stagesDone"], q1["stagesTotal"], q1["progressPct"]) == (1, 2, 50)
    assert q1["status"] == {"v": "已逾預定日", "tone": "warn"} and q1["nextStage"] == "施工" and q1["overdueDays"] > 0
    assert q2["stagesTotal"] == 0 and q2["progressPct"] is None and q2["status"]["v"] == "未排定"
    assert all(c["type"] != "money" for c in j["tables"][0]["columns"])
    assert all(k["type"] != "money" for k in j["kpis"])
    assert j["moneyMasked"] is False
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["unscheduled"] >= 1 and kp["overdueStages"] >= 1


def test_case_progress_scopes_to_visible_cases(client, world):
    mine = {r["quoteNo"] for r in _get(client, world["s1"], "case-progress").json()["tables"][0]["rows"]}
    assert "SR-Q1" in mine and "SR-Q2" not in mine


def test_case_progress_filters(client, world):
    sid = _uid("sr_sales2")
    rows = _get(client, world["sa"], "case-progress", "sales_id=%d" % sid).json()["tables"][0]["rows"]
    assert {r["quoteNo"] for r in rows} == {"SR-Q2"}
    rows = _get(client, world["sa"], "case-progress", "customer=SR-Q1").json()["tables"][0]["rows"]
    assert {r["quoteNo"] for r in rows} == {"SR-Q1"}
    rows = _get(client, world["sa"], "case-progress", "date_from=2026-10-07").json()["tables"][0]["rows"]
    assert {r["quoteNo"] for r in rows} == {"SR-Q2"}


# ── 業務漏斗與遮蔽 ───────────────────────────────────────────────────────────

def test_funnel_with_money_view(client, world):
    j = _get(client, world["sa"], "sales-funnel").json()
    dev = {d["status"]: d for d in j["funnel"]["dev"]}
    assert [d["status"] for d in j["funnel"]["dev"]] == ["洽談中", "成案", "未成案", "暫擱置"]
    assert dev["洽談中"]["count"] == 4 and dev["洽談中"]["amount"] == 500000 + 777000 and dev["洽談中"]["missing"] == 2
    assert dev["成案"]["count"] == 2 and dev["成案"]["amount"] == 300000 + 333000
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["pipelineAmount"] == 500000 + 777000
    assert kp["devWinRate"] == 66.7                       # 成案 2 / (成案 2＋未成案 1)
    assert j["moneyMasked"] is False
    open_rows = {r["caseName"]: r for r in j["tables"][0]["rows"]}
    assert open_rows["機會A"]["amount"] == 500000 and open_rows["機會B"]["amount"] == {"state": "unfilled"}


def test_funnel_without_money_view_leaks_neither_amounts_nor_missing_counts(client, world):
    r = _get(client, world["qdev"], "sales-funnel")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["moneyMasked"] is True
    for d in j["funnel"]["dev"]:
        assert d["amount"] is None and d["missing"] is None
    kp = {k["key"]: k for k in j["kpis"]}
    assert kp["pipelineAmount"]["value"] is None and kp["pipelineAmount"]["note"] == ""
    for row in j["tables"][0]["rows"]:
        assert row["amount"] is None
    flat = json.dumps(j, ensure_ascii=False)
    assert "沒有金額檢視權限" not in flat                  # 遮蔽說明由前端依 moneyMasked 統一顯示
    assert "未填" not in flat and "777000" not in flat and "333000" not in flat
    # 件數照給
    dev = {d["status"]: d["count"] for d in j["funnel"]["dev"]}
    assert dev["洽談中"] == 2 and dev["成案"] == 1


def test_funnel_xlsx_without_money_view_has_no_amount_or_missing_column(client, world):
    r = client.get(BASE + "/sales-funnel/excel", headers=world["qdev"])
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    cells = [str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None]
    blob = "\n".join(cells)
    assert "未填" not in blob and "777000" not in blob and "333000" not in blob
    heads = [str(c.value) for row in wb["商機漏斗"].iter_rows(min_row=1, max_row=1) for c in row]
    assert "預估金額" not in heads and "未填件數" not in heads


def test_funnel_without_dev_permission_has_empty_dev_part_not_zeros(client, world, make_user):
    h = _login(client, *make_user("sr_qonly", role="viewer", modules=["dashboard", "quotation"]))
    j = _get(client, h, "sales-funnel").json()
    assert j["funnel"]["dev"] == [] and j["tables"] == []
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["pipelineAmount"] is None and kp["devWinRate"] is None
    assert j["funnel"]["quote"] is not None and any("業務開發模組" in n for n in j["notes"])


def test_funnel_quote_part_counts(client, world):
    j = _get(client, world["sa"], "sales-funnel").json()
    q = j["funnel"]["quote"]
    assert q["submitted"] >= 2 and q["won"] + q["lost"] + q["pending"] <= q["submitted"]


# ── 與既有報表的數字一致 ─────────────────────────────────────────────────────

def test_ar_aging_total_matches_operating_report(client, world):
    std = _get(client, world["sa"], "ar-aging").json()
    old = client.get("/api/reports/ar-aging", headers=world["sa"]).json()
    kp = {k["key"]: k for k in std["kpis"]}
    assert kp["total"]["value"] == old["total"]["amount"]
    assert kp["total"]["note"] == "%d 筆" % old["total"]["count"]
    assert [k["key"] for k in std["kpis"][1:]] == [b["key"] for b in old["bands"]]
    assert [k["value"] for k in std["kpis"][1:]] == [b["amount"] for b in old["bands"]]
    assert "帳齡依報價日計算" in std["notes"][0]
    assert len(std["tables"][0]["rows"]) == old["total"]["count"]
    assert all("owner" not in i for b in old["bands"] for i in b["items"])        # 營運報表原輸出不多出欄位


def test_ar_aging_filters_narrow_the_same_definition(client, world):
    sid = _uid("sr_sales2")
    std = _get(client, world["sa"], "ar-aging", "sales_id=%d" % sid).json()
    assert {r["quoteNo"] for r in std["tables"][0]["rows"]} == {"SR-Q2"}
    assert std["kpis"][0]["value"] == 210000


def test_ar_aging_rejects_period_conditions(client, world):
    assert _get(client, world["sa"], "ar-aging", "date_from=2026-01-01").status_code == 400


def test_revenue_cash_series_matches_income_items_provider(client, world):
    j = _get(client, world["sa"], "revenue", "date_from=2026-10-01&date_to=2026-10-31").json()
    from modules.analytics.api import reports as rp
    items = rp._collect_income_items("2026-10-01", "2026-10-31", None)
    assert sum(i["amount"] for i in items) == 52500
    assert j["series"] == [{"key": "2026-10", "label": j["series"][0]["label"], "cash": 52500, "accrual": j["series"][0]["accrual"]}]
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["revenue"] == 52500 and kp["contract"] == 105000 + 210000 and kp["caseCount"] == 2
    assert j["params"]["basis"] == "cash"
    from helpers.recognition_basis import BASIS_NOTES
    assert j["notes"][0] == BASIS_NOTES["cash"]
    by = {r["owner"]: r for r in j["tables"][0]["rows"]}
    assert sum(r["revenue"] for r in by.values()) == 52500


def test_revenue_sales_filter_and_basis(client, world):
    sid = _uid("sr_sales2")
    j = _get(client, world["sa"], "revenue", "date_from=2026-10-01&date_to=2026-10-31&sales_id=%d" % sid).json()
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["revenue"] == 0 and kp["caseCount"] == 1 and kp["contract"] == 210000   # 業務 2 的案件這個月沒有收款（真的 0）
    acc = _get(client, world["sa"], "revenue", "basis=accrual").json()
    assert acc["params"]["basis"] == "accrual"
    assert _get(client, world["sa"], "revenue", "basis=bogus").status_code == 400


def test_revenue_default_range_is_last_twelve_months(client, world):
    j = _get(client, world["sa"], "revenue").json()
    assert len(j["series"]) == 12


def test_revenue_rejects_ranges_over_sixty_months(client, world):
    assert _get(client, world["sa"], "revenue", "date_from=2015-01-01&date_to=2026-10-31").status_code == 400


def test_gross_margin_weighted_and_unsettled_is_not_zero(client, world):
    j = _get(client, world["sa"], "gross-margin").json()
    kp = {k["key"]: k["value"] for k in j["kpis"]}
    assert kp["estMargin"] == 20.0
    assert kp["actMargin"] == {"state": "unsettled"} and kp["gap"] == {"state": "unsettled"} and kp["settledCount"] == 0
    row = next(r for r in j["tables"][0]["rows"] if r["quoteNo"] == "SR-Q1")
    assert row["actMargin"] == {"state": "unsettled"} and row["settle"]["v"] == "未精算"
    assert row["total"] == 105000 and row["estMargin"] == 20.0


# ── 條件驗證 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("qs", [
    "bogus=1", "date_from=2026-13-40", "date_from=abc", "date_from=2026-10-31&date_to=2026-10-01",
    "sales_id=abc", "sales_id=99999999", "department_id=99999999", "customer=" + "字" * 41,
    "date_from=2026-10-01&date_from=2026-10-02",
])
def test_bad_conditions_are_400(client, world, qs):
    assert _get(client, world["sa"], "gross-margin", qs).status_code == 400


def test_basis_only_applies_to_revenue(client, world):
    assert _get(client, world["sa"], "gross-margin", "basis=cash").status_code == 400


def test_empty_values_are_treated_as_unset(client, world):
    r = _get(client, world["sa"], "case-progress", "date_from=&sales_id=&customer=")
    assert r.status_code == 200 and r.json()["params"] == {}


# ── 匯出：Excel／PDF 姊妹／稽核 ─────────────────────────────────────────────

def test_excel_filename_audit_and_cooldown(client, world):
    import helpers.xlsx_out as X
    X._export_times.clear()
    r = client.get(BASE + "/revenue/excel?date_from=2026-10-01&date_to=2026-10-31", headers=world["sa"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    from urllib.parse import unquote
    assert "MOTRIX_標準報表_營收_" in unquote(r.headers["content-disposition"])
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames[0] == "逐月走勢" and "條件" in wb.sheetnames
    conn = _db()
    try:
        row = conn.execute("SELECT detail, target_id FROM audit_log WHERE action='export.xlsx' AND target_id='std-report' "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None
    d = json.loads(row["detail"])
    assert d["module"] == "analytics" and d["filters"]["rid"] == "revenue" and d["filters"]["date_from"] == "2026-10-01"
    assert d["rows"] and d["rows"] > 0
    r2 = client.get(BASE + "/revenue/excel", headers=world["sa"])
    assert r2.status_code == 429


def test_invalid_condition_does_not_consume_export_cooldown(client, world):
    import helpers.xlsx_out as X
    X._export_times.clear()
    assert client.get(BASE + "/gross-margin/excel?bogus=1", headers=world["sa"]).status_code == 400
    assert client.get(BASE + "/gross-margin/excel", headers=world["sa"]).status_code == 200


def test_excel_is_gated_like_the_data_endpoint(client, world):
    import helpers.xlsx_out as X
    X._export_times.clear()
    assert client.get(BASE + "/revenue/excel", headers=world["nomod"]).status_code == 403
    assert client.get(BASE + "/revenue/excel", headers=world["qdev"]).status_code == 403


def test_pdf_sibling_is_registered_with_same_gate(client, world):
    import main
    paths = {getattr(r, "path", "") for r in main.app.routes}
    assert "/api/std-reports/{rid}/pdf" in paths
    assert client.get(BASE + "/revenue/pdf", headers=world["nomod"]).status_code == 403


def test_excel_for_case_progress_has_no_money_headers(client, world):
    import helpers.xlsx_out as X
    X._export_times.clear()
    r = client.get(BASE + "/case-progress/excel", headers=world["sa"])
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    heads = [str(c.value) for row in wb["案件進度明細"].iter_rows(min_row=1, max_row=1) for c in row]
    assert "完成度" in heads and not any("金額" in h for h in heads)
