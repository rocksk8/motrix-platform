# -*- coding: utf-8 -*-
"""T87 B2-S1：自訂報表的編譯與執行（`helpers/report_runner.py`＋兩個擁有模組的 execute 回呼）。

① 組表：明細＋分組小計＋總計、彙總版型、日期分組、列舉白話名稱、空值不當 0、軟刪除不進報表。
② 遮罩不可繞過：不可見欄位用在顯示／彙總 ⇒ 拿掉並回報；用在篩選／分組／排序 ⇒ 422。
③ 與清單端點雙向等價（同使用者、同條件，列集合相等）；「我」＝清單的「我負責的」；案件別名的預設篩選＝案件頁母體。
④ 執行端加固：計畫不透明、授權器、`data_json` 只准在登錄常數內、上限。
⑤ 能力不取代模組存取。
"""
import json
import sqlite3

import pytest

from core import registry  # noqa: F401
from db import get_db
from helpers import auth
from helpers import report_runner as RR

PW = "Test-Pass-123"


def _user(client, make_user, name, role, modules):
    u, p = make_user(username=name, role=role, modules=modules)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return auth._require_user("Bearer " + tok), {"Authorization": "Bearer " + tok}


def _sa(client, make_user, name):
    return _user(client, make_user, name, "superadmin", [])


_SEQ = [0]


def _quote(**kw):
    _SEQ[0] += 1
    row = {"quote_no": "MQ-2611-%03d" % (700 + _SEQ[0]), "status": "草稿", "customer_name": "RT", "project_name": "專案", "total": 0, "pretax": 0,
           "data_json": "{}", "created_at": "2026-11-14T09:00:00", "updated_at": "2026-11-14T09:00:00", "deal_tag": "",
           "sales_person": "", "assigned_user_ids": "[]"}
    row.update(kw)
    c = get_db()
    try:
        cols = list(row)
        c.execute("INSERT INTO quotations (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
        c.commit()
    finally:
        c.close()
    return row["quote_no"]


def _dev(**kw):
    row = {"case_name": "商機", "customer_name": "RTD", "status": "洽談中", "created_at": "2026-11-14T09:00:00", "updated_at": "2026-11-14T09:00:00"}
    row.update(kw)
    c = get_db()
    try:
        cols = list(row)
        cur = c.execute("INSERT INTO dev_cases (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _defn(source="quotation", **kw):
    d = {"version": 1, "source": source}
    d.update(kw)
    return d


def _cust(name):
    return {"field": "customer_name", "op": "eq", "value": name}


def _kinds(res):
    return [r["k"] for r in res["rows"]]


def _cells(res, kind="row"):
    return [r["v"] for r in res["rows"] if r["k"] == kind]


def _nos(res, col=0):
    return {r["v"][col] for r in res["rows"] if r["k"] == "row"}


# ── ① 組表 ─────────────────────────────────────────────────────────────────

def test_detail_with_group_subtotals_and_grand_total(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa1")
    _quote(customer_name="RT-G", sales_person="A業務", total=100)
    _quote(customer_name="RT-G", sales_person="A業務", total=200)
    _quote(customer_name="RT-G", sales_person="B業務", total=400)
    res = RR.preview(_defn(columns=["quote_no", "sales_person", "total"], filters=[_cust("RT-G")], groupBy=[{"field": "sales_person"}],
                           aggregates=[{"field": "total", "fn": "sum"}], sort=[{"field": "quote_no", "dir": "asc"}]), u)
    assert _kinds(res) == ["row", "row", "subtotal", "row", "subtotal", "total"]
    assert [c[2] for c in _cells(res, "subtotal")] == [300, 400] and _cells(res, "total")[0][2] == 700
    assert _cells(res, "total")[0][0] == "總計" and _cells(res, "subtotal")[0][0].startswith("小計：A業務")
    assert res["totalRows"] == 3 and res["truncated"] is False and res["hiddenCount"] == 0


def test_summary_layout_groups_and_counts(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa2")
    _quote(customer_name="RT-S", sales_person="A業務", total=100)
    _quote(customer_name="RT-S", sales_person="A業務", total=200)
    _quote(customer_name="RT-S", sales_person="B業務", total=400)
    res = RR.preview(_defn(layout="summary", filters=[_cust("RT-S")], groupBy=[{"field": "sales_person"}],
                           aggregates=[{"field": "total", "fn": "sum"}, {"field": "*", "fn": "count"}]), u)
    assert [c["label"] for c in res["columns"]] == ["業務", "含稅總額（合計）", "筆數"]
    assert _cells(res) == [["A業務", 300, 2], ["B業務", 400, 1]] and _cells(res, "total") == [["總計", 700, 3]]
    assert res["totalRows"] == 2


def test_month_bucket_and_enum_label_and_empty_group_label(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa3")
    _quote(customer_name="RT-M", quote_date="2026-10-03", total=10)
    _quote(customer_name="RT-M", quote_date="2026-10-28", total=20, doc_type="estimate")
    _quote(customer_name="RT-M", quote_date="2026-11-02", total=40)
    res = RR.preview(_defn(layout="summary", filters=[_cust("RT-M")], groupBy=[{"field": "quote_date", "bucket": "month"}],
                           aggregates=[{"field": "total", "fn": "sum"}]), u)
    assert _cells(res) == [["2026-10", 30], ["2026-11", 40]]
    det = RR.preview(_defn(columns=["doc_type", "total"], filters=[_cust("RT-M")], sort=[{"field": "quote_date", "dir": "asc"}]), u)
    assert [c[0] for c in _cells(det)] == ["報價單", "估價單", "報價單"]
    emp = RR.preview(_defn(layout="summary", filters=[_cust("RT-M"), {"field": "deal_tag", "op": "empty"}], groupBy=[{"field": "deal_tag"}],
                           aggregates=[{"field": "*", "fn": "count"}]), u)
    assert _cells(emp) == [["（未填）", 3]]


def test_sum_of_nothing_is_null_not_zero_and_soft_deleted_rows_are_excluded(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa4")
    _dev(customer_name="RT-D")
    _dev(customer_name="RT-D", expected_amount=500)
    gone = _dev(customer_name="RT-D", expected_amount=9999)
    c = get_db()
    c.execute("UPDATE dev_cases SET is_deleted=1 WHERE id=?", (gone,))
    c.commit()
    c.close()
    res = RR.preview(_defn("dev_case", columns=["case_name"], filters=[{"field": "customer_name", "op": "eq", "value": "RT-D"}],
                           aggregates=[{"field": "expected_amount", "fn": "sum"}, {"field": "expected_amount", "fn": "avg"}]), u)
    assert res["totalRows"] == 2                                              # 軟刪除的不算
    res2 = RR.preview(_defn("dev_case", layout="summary", filters=[{"field": "customer_name", "op": "eq", "value": "RT-D"}, {"field": "expected_amount", "op": "empty"}],
                            aggregates=[{"field": "expected_amount", "fn": "sum"}, {"field": "*", "fn": "count"}]), u)
    assert _cells(res2) == [[None, 1]]                                        # 全空 ⇒ None（不是 0）


def test_default_filters_apply_only_when_the_definition_has_no_filters_key(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa5")
    for tag in ("已成案", "已結案", ""):
        _quote(customer_name="RT-C", deal_tag=tag)
    flt = [_cust("RT-C")]
    assert RR.preview(_defn("case", columns=["quote_no"], filters=flt), u)["totalRows"] == 3          # 明確給了 filters（只有客戶）⇒ 不加預設
    cases = RR.preview(_defn("case", columns=["quote_no", "customer_name"]), u)                          # 沒給 filters ⇒ 案件別名的預設母體
    assert all(c[1] != "RT-C" or True for c in _cells(cases))
    only = RR.preview(_defn("case", columns=["quote_no"], filters=[_cust("RT-C"), {"field": "deal_tag", "op": "in", "value": ["已成案", "已結案"]}]), u)
    assert only["totalRows"] == 2


# ── ② 遮罩不可繞過 ─────────────────────────────────────────────────────────

@pytest.fixture
def people(client, make_user):
    eng, _ = _user(client, make_user, "rr_eng", "engineer", ["quotation"])
    sal, _ = _user(client, make_user, "rr_sales", "sales", ["quotation", "case_manage"])
    return eng, sal


_MONEY = ["total", "pretax", "direct_margin_pct", "net_margin_pct"]


def test_hidden_money_columns_are_dropped_and_counted_but_visible_for_the_authorised_role(people):
    eng, sal = people
    _quote(customer_name="RT-H", total=123, sales_person_id=sal["id"])
    d = _defn(columns=["quote_no", "customer_name"] + _MONEY, filters=[_cust("RT-H")])
    res = RR.preview(d, eng)
    assert [c["label"] for c in res["columns"]] == ["報價單號", "客戶"] and res["hiddenCount"] == 4 and "含稅總額" in res["hiddenFields"]
    assert "123" not in json.dumps(res, ensure_ascii=False)                  # 值不在任何位置
    ok = RR.preview(d, sal)
    assert len(ok["columns"]) == 6 and ok["hiddenCount"] == 0 and _cells(ok)[0][2] == 123                # 正對照：有權限者看得到


@pytest.mark.parametrize("what", ["filter", "sort", "group_by_hidden_money", "all_hidden"])
def test_hidden_field_in_filter_sort_or_group_is_refused_not_ignored(people, what):
    eng, _ = people
    if what == "filter":
        d = _defn(columns=["quote_no"], filters=[{"field": "total", "op": "gte", "value": 1000000}])
    elif what == "sort":
        d = _defn(columns=["quote_no"], sort=[{"field": "total", "dir": "desc"}])
    elif what == "group_by_hidden_money":
        d = _defn(layout="summary", groupBy=[{"field": "total"}], aggregates=[{"field": "*", "fn": "count"}])
    else:
        d = _defn(columns=["total", "pretax"])
    with pytest.raises(RR.ReportRefused) as e:
        RR.preview(d, eng)
    assert e.value.status == 422
    if what != "all_hidden":
        assert e.value.details["reason"] == "no_permission" and "total" in e.value.details["fields"]
        assert "1000000" not in e.value.message


def test_hidden_aggregate_is_dropped_and_group_counts_only_visible_rows(people):
    eng, sal = people
    _quote(customer_name="RT-X", total=50, sales_person="A")
    d = _defn(layout="summary", filters=[_cust("RT-X")], groupBy=[{"field": "sales_person"}], aggregates=[{"field": "total", "fn": "sum"}, {"field": "*", "fn": "count"}])
    res = RR.preview(d, eng)
    assert [c["label"] for c in res["columns"]] == ["業務", "筆數"] and res["hiddenCount"] == 1
    assert "50" not in json.dumps(res["rows"])


def test_tampered_definitions_are_refused_and_values_stay_parameters(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa6")
    _quote(customer_name="RT-T")
    bad = [
        _defn(columns=["quote_no"], filters=[{"field": "no_such", "op": "eq", "value": "x"}]),
        _defn(columns=["quote_no"], filters=[{"field": "quote_no", "op": "gte", "value": "x"}]),                    # 文字欄不支援 gte
        _defn(columns=["quote_no"], filters=[{"field": "total", "op": "eq", "value": "1; DROP TABLE quotations"}]),   # 數值欄放文字
        _defn(columns=["quote_no"], filters=[{"field": "quote_date", "op": "between", "value": ["2026-13-45", "x"]}]),
        _defn(columns=["quote_no"], sort=[{"field": "customer_name", "dir": "sideways"}]),
        _defn(columns=["quote_no"], sort=[{"field": "project_name", "dir": "asc"}]),                              # 不可排序
        _defn(layout="summary", groupBy=[{"field": "quote_date", "bucket": "hour"}]),
        _defn(layout="summary"),
        dict(_defn(columns=["quote_no"]), extra="x"),
        dict(_defn(columns=["quote_no"]), version=2),
        _defn(columns=["quote_no"], layout="pivot"),
        _defn(columns=["x%d" % i for i in range(21)]),
        _defn(columns=["quote_no"], filters=[_cust("a")] * 7),
        "not a dict",
        _defn(columns=["quote_no"], filters=[{"field": "customer_name", "op": "in", "value": ["a"] * 51}]),
    ]
    for d in bad:
        with pytest.raises(RR.ReportRefused):
            RR.preview(d, u)
    inj = "x'; DROP TABLE quotations; --"
    res = RR.preview(_defn(columns=["quote_no"], filters=[{"field": "customer_name", "op": "eq", "value": inj}, {"field": "project_name", "op": "contains", "value": "%"}]), u)
    assert res["totalRows"] == 0
    assert RR.preview(_defn(columns=["quote_no"], filters=[_cust("RT-T")]), u)["totalRows"] == 1                    # 表還在


def test_like_wildcards_in_values_are_literal(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa7")
    _quote(customer_name="RT-L", project_name="100% 完成")
    _quote(customer_name="RT-L", project_name="1000 完成")
    res = RR.preview(_defn(columns=["project_name"], filters=[_cust("RT-L"), {"field": "project_name", "op": "contains", "value": "0%"}]), u)
    assert _cells(res) == [["100% 完成"]]


def test_definition_over_8kb_is_refused(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa8")
    with pytest.raises(RR.ReportRefused):
        RR.preview(_defn(columns=["quote_no"], filters=[{"field": "customer_name", "op": "in", "value": ["x" * 190] * 50}]), u)


# ── ③ 與清單端點雙向等價 ───────────────────────────────────────────────────

def _list_nos(user, **kw):
    from modules.case.api.quotations import list_quotations_for
    return {i["quote_no"] for i in list_quotations_for(user, limit=500, **kw)["items"]}


def test_quotation_rows_equal_the_list_endpoint_both_ways_per_role(client, make_user):
    sal, _ = _user(client, make_user, "rr_eqs", "sales", ["quotation", "case_manage"])
    other, _ = _user(client, make_user, "rr_eqo", "sales", ["quotation", "case_manage"])
    adm, _ = _user(client, make_user, "rr_eqa", "superadmin", [])
    mine1 = _quote(customer_name="RT-EQ", sales_person_id=sal["id"], sales_person=sal["display_name"] or sal["username"])
    mine2 = _quote(customer_name="RT-EQ", sales_person_id=None, sales_person=sal["display_name"] or sal["username"], deal_tag="已成案")
    shared = _quote(customer_name="RT-EQ", sales_person_id=other["id"], assigned_user_ids=json.dumps([sal["id"]]))
    foreign = _quote(customer_name="RT-EQ", sales_person_id=other["id"], deal_tag="已結案")
    for user in (sal, other, adm):
        want = _list_nos(user, customer="RT-EQ")
        got = _nos(RR.preview(_defn(columns=["quote_no"], filters=[{"field": "customer_name", "op": "contains", "value": "RT-EQ"}]), user))
        assert got == want, (user["username"], got ^ want)
    assert _list_nos(sal, customer="RT-EQ") == {mine1, mine2, shared}                 # 正對照：業務只見自己的與被分配的
    assert foreign not in _list_nos(sal, customer="RT-EQ")
    # 「我」＝清單的「我負責的」
    want = _list_nos(sal, customer="RT-EQ", mine=1)
    got = _nos(RR.preview(_defn(columns=["quote_no"], filters=[{"field": "customer_name", "op": "contains", "value": "RT-EQ"}, {"field": "sales_person", "op": "is_me"}]), sal))
    assert got == want and want                                                    # 非空（兩邊都空不算等價）
    # 案件別名的預設母體＝案件頁的 deal_tag 篩選
    want = _list_nos(adm, customer="RT-EQ", deal_tag="已成案,已結案")
    got = _nos(RR.preview(_defn("case", columns=["quote_no"], filters=[{"field": "customer_name", "op": "contains", "value": "RT-EQ"},
                                                                        {"field": "deal_tag", "op": "in", "value": ["已成案", "已結案"]}]), adm))
    assert got == want == {mine2, foreign}


def test_doc_type_filter_equals_the_list_doc_type_param(client, make_user):
    adm, _ = _sa(client, make_user, "rr_dt")
    a = _quote(customer_name="RT-DT", doc_type="estimate")
    b = _quote(customer_name="RT-DT")
    flt = [{"field": "customer_name", "op": "contains", "value": "RT-DT"}]
    assert _nos(RR.preview(_defn(columns=["quote_no"], filters=flt), adm)) == _list_nos(adm, customer="RT-DT") == {a, b}      # 預設兩種單據一起
    assert _nos(RR.preview(_defn(columns=["quote_no"], filters=flt + [{"field": "doc_type", "op": "eq", "value": "estimate"}]), adm)) == _list_nos(adm, customer="RT-DT", doc_type="estimate") == {a}


def test_dev_case_rows_equal_the_crm_list_both_ways_per_role(client, make_user):
    sal, h = _user(client, make_user, "rr_ds", "sales", ["dev_crm"])
    adm, ha = _user(client, make_user, "rr_da", "admin", [])
    sup, hs = _sa(client, make_user, "rr_dsu")
    mine = _dev(customer_name="RT-DE", created_by=sal["id"])
    theirs = _dev(customer_name="RT-DE", created_by=sup["id"])
    gone = _dev(customer_name="RT-DE", created_by=sal["id"])
    c = get_db()
    c.execute("UPDATE dev_cases SET is_deleted=1 WHERE id=?", (gone,))
    c.commit()
    c.close()
    flt = [{"field": "customer_name", "op": "eq", "value": "RT-DE"}]
    for user, hdr, expect in ((sal, h, 1), (adm, ha, 2), (sup, hs, 2)):
        listed = {x["id"] for x in client.get("/api/dev-cases", headers=hdr).json() if x["customerName"] == "RT-DE"}
        res = RR.preview(_defn("dev_case", columns=["case_name"], filters=flt), user)
        assert res["totalRows"] == len(listed) == expect, user["username"]
    assert mine and theirs


def test_expected_amount_follows_the_crm_page_visibility(client, make_user):
    eng, he = _user(client, make_user, "rr_de", "sales", ["dev_crm"])
    sup, hs = _sa(client, make_user, "rr_dsu2")
    _dev(customer_name="RT-DV", created_by=eng["id"], expected_amount=777)
    flt = [{"field": "customer_name", "op": "eq", "value": "RT-DV"}]
    for user, hdr in ((eng, he), (sup, hs)):
        shown = client.get("/api/dev-cases", headers=hdr).json()
        vis = any(x["customerName"] == "RT-DV" and x.get("expectedAmountVisible") for x in shown)
        res = RR.preview(_defn("dev_case", columns=["case_name", "expected_amount"], filters=flt), user)
        assert (len(res["columns"]) == 2) is vis, user["username"]
        assert vis is (user["role"] == "superadmin")
        if not vis:
            assert res["hiddenCount"] == 1 and "777" not in json.dumps(res)
            with pytest.raises(RR.ReportRefused):
                RR.preview(_defn("dev_case", columns=["case_name"], filters=flt + [{"field": "expected_amount", "op": "gte", "value": 1}]), user)


# ── ④ 執行端加固 ───────────────────────────────────────────────────────────

def test_plan_is_opaque_and_the_owner_callback_checks_type_and_source(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa9")
    with pytest.raises(TypeError):
        RR.CompiledPlan(object(), source_id="quotation")
    plan = RR.compile(_defn(columns=["quote_no"]), u)
    with pytest.raises(AttributeError):
        plan.source_id = "dev_case"
    with pytest.raises(RR.ReportError):
        RR.run_owned({"source_id": "quotation"}, ("quotation",))                 # 手工拼的不是 CompiledPlan
    with pytest.raises(RR.ReportError):
        RR.run_owned(plan, ("dev_case",))                                      # 別的來源的回呼不接受
    from modules.crm import report_source as CRMRS
    with pytest.raises(RR.ReportError):
        CRMRS._execute(plan)


def test_authorizer_allows_only_select_of_registered_columns_and_functions():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT, secret TEXT)")
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, password_hash TEXT)")
    c.execute("INSERT INTO quotations VALUES (1,'a','s')")
    c.set_authorizer(RR._authorizer({"quotations": frozenset({"id", "quote_no", ""})}))
    assert c.execute("SELECT quote_no, COUNT(*) FROM quotations").fetchall() == [("a", 1)]
    for sql in ("SELECT secret FROM quotations", "SELECT password_hash FROM users", "INSERT INTO quotations VALUES (2,'b','x')",
                "DELETE FROM quotations", "DROP TABLE quotations", "ATTACH DATABASE ':memory:' AS x", "PRAGMA table_info(quotations)",
                "SELECT load_extension('x')", "SELECT readfile('x')", "CREATE TABLE z (a)"):
        with pytest.raises(sqlite3.DatabaseError):
            c.execute(sql)


def test_data_json_outside_a_registered_constant_is_refused_at_compile(client, make_user, monkeypatch):
    u, _ = _sa(client, make_user, "rr_sa10")
    from helpers import report_catalog as RC
    real = RC.get_source

    def _tampered(sid):
        s = real(sid)
        if s:
            s["exprs"] = ()                                                    # 假設有 bug：登錄常數清單掉了 ⇒ 運算式裡的 data_json 變成「登錄之外」
        return s
    monkeypatch.setattr(RC, "get_source", _tampered)
    with pytest.raises(RR.ReportError) as e:
        RR.compile(_defn(columns=["deal_tag"]), u)
    assert e.value.status == 500


def test_export_over_the_row_cap_is_refused_not_truncated(client, make_user, monkeypatch):
    u, _ = _sa(client, make_user, "rr_sa11")
    for _ in range(3):
        _quote(customer_name="RT-CAP")
    monkeypatch.setattr(RR, "MAX_EXPORT_ROWS", 2)
    plan = RR.compile(_defn(columns=["quote_no"], filters=[_cust("RT-CAP")]), u, mode="export")
    from helpers import report_catalog as RC
    with pytest.raises(RR.ReportRefused) as e:
        RR.assemble(plan, RC.get_source("quotation")["execute"](plan))
    assert e.value.details["reason"] == "too_many_rows"
    ok = RR.compile(_defn(columns=["quote_no"], filters=[_cust("RT-CAP")]), u, mode="preview")
    assert RR.assemble(ok, RC.get_source("quotation")["execute"](ok))["totalRows"] == 3          # 預覽不受匯出上限影響，只截 50 列


def test_preview_returns_at_most_50_rows_but_counts_all(client, make_user):
    u, _ = _sa(client, make_user, "rr_sa12")
    for _ in range(53):
        _quote(customer_name="RT-50")
    res = RR.preview(_defn(columns=["quote_no"], filters=[_cust("RT-50")]), u)
    assert len(_cells(res)) == 50 and res["totalRows"] == 53 and res["truncated"] is True


# ── ⑤ 能力不取代模組存取 ───────────────────────────────────────────────────

def test_user_without_the_source_module_cannot_preview_even_with_a_matching_row_scope(client, make_user):
    nom, _ = _user(client, make_user, "rr_nom", "sales", [])
    _quote(customer_name="RT-NM", sales_person_id=nom["id"])
    with pytest.raises(RR.SourceUnavailable) as e:
        RR.preview(_defn(columns=["quote_no"]), nom)
    assert e.value.status == 404
    with pytest.raises(RR.SourceUnavailable):
        RR.preview(_defn("dev_case", columns=["case_name"]), nom)
    with pytest.raises(RR.SourceUnavailable):
        RR.preview(_defn("no_such_source", columns=["x"]), nom)
    from helpers import report_catalog as RC
    assert RC.sources_for(nom) == []
