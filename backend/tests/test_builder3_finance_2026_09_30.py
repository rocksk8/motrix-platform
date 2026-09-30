# -*- coding: utf-8 -*-
"""建構器第三輪 S2.5（2026-09-30）：自訂模組的收入／支出串接營運報表與案件成本。
- 即時算：單據在入帳狀態才計入、離開就不計（不建分錄表）；權責用權責日、現金用現金日與現金金額
- outbox：進入入帳狀態寫 POSTED、離開寫 REVERSED（同交易；反覆進出各一筆）
- 收入關聯到內建案件 ⇒ 略過（dupSkipped）；缺該口徑日期 ⇒ 待補登計數；修訂版入帳後舊版不再計入
- 營運報表（IP-9 expense.entries）現金口徑用現金日；權責用權責日"""
import json

import pytest

from helpers import custom_finance as FIN

KEY = "b3fin"


def _login(client, make_user, name="b3fin_boss"):
    u, p = make_user(name, "Custom-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _body():
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)
    return {"name": "金流測試", "permission": "custom." + KEY, "numbering": {"prefix": "FN", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True),
                       f("amt", "收入", "number", finance={"kind": "income", "dateField": "d", "cashDateField": "cd",
                                                          "caseField": "case", "cashAmountField": "cash"}),
                       f("cash", "實收", "number"),
                       f("cost", "成本", "number", finance={"kind": "expense", "dateField": "d", "cashDateField": "cd", "caseField": "case"}),
                       f("d", "權責日", "date"), f("cd", "現金日", "date"), f("case", "關聯案件", "text")],
            "finance": {"postStates": ["done"]},
            "workflow": {"initial": "draft",
                         "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "入帳"}, {"key": "closed", "label": "結案", "final": True}],
                         "transitions": [{"key": "submit", "label": "入帳", "from": "draft", "to": "done"},
                                         {"key": "withdraw", "label": "撤回", "from": "done", "to": "draft"},
                                         {"key": "close", "label": "結案", "from": "done", "to": "closed"}]}}


@pytest.fixture()
def world(client, make_user):
    h = _login(client, make_user)
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body()}).json()
    assert r["problems"] == [], r["problems"]
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    return client, h


def _mk(client, h, **vals):
    base = {"title": "T"}
    base.update(vals)
    r = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": base})
    assert r.status_code == 200, r.text
    return r.json()["record_no"]


def _do(client, h, no, t):
    r = client.post("/api/custom/%s/records/%s/transitions/%s" % (KEY, no, t), headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def _conn():
    import db
    return db.get_db()


def _events():
    c = _conn()
    try:
        return [(r["event"], r["record_no"]) for r in c.execute("SELECT event, record_no FROM custom_record_finance_outbox ORDER BY id")]
    finally:
        c.close()


def _income(basis, a="2031-01-01", b="2031-12-31", dept=None):
    c = _conn()
    try:
        return FIN.income_items(c, a, b, basis, dept)
    finally:
        c.close()


def _expense(a="2031-01-01", b="2031-12-31"):
    c = _conn()
    try:
        return FIN.expense_entries(c, a, b)
    finally:
        c.close()


def test_only_posted_records_count_and_leaving_the_state_withdraws_them_live(world):
    client, h = world
    no = _mk(client, h, amt=1000, cash=1050, cost=300, d="2031-03-05", cd="2031-04-10")
    assert _income("accrual") == [] and _expense() == []                          # 草稿不計
    _do(client, h, no, "submit")
    acc, cash = _income("accrual"), _income("cash")
    assert [(i["receivedAt"], i["amount"], i["taxNote"]) for i in acc] == [("2031-03-05", 1000.0, "未稅")]
    assert [(i["receivedAt"], i["amount"], i["taxNote"]) for i in cash] == [("2031-04-10", 1050.0, "含稅")]   # 現金＝現金日＋實收
    ex = _expense()
    assert len(ex) == 1 and ex[0]["amount"] == 300 and ex[0]["date"] == "2031-03-05" and ex[0]["cashDate"] == "2031-04-10" and ex[0]["cashAmount"] == 300
    _do(client, h, no, "withdraw")                                                # 離開入帳狀態 ⇒ 即時撤回
    assert _income("accrual") == [] and _income("cash") == [] and _expense() == []
    _do(client, h, no, "submit")                                                  # 再入帳 ⇒ 又計入
    assert len(_income("cash")) == 1
    _do(client, h, no, "close")                                                   # 結案（不在入帳狀態）⇒ 不計
    assert _income("cash") == [] and _expense() == []


def test_outbox_events_follow_entering_and_leaving_with_unique_keys_each_time(world):
    client, h = world
    no = _mk(client, h, amt=100, cost=10, d="2031-01-02")
    assert _events() == []
    _do(client, h, no, "submit")
    _do(client, h, no, "withdraw")
    _do(client, h, no, "submit")
    ev = _events()
    assert [e for e, _n in ev] == [FIN.EVENT_POSTED, FIN.EVENT_REVERSED, FIN.EVENT_POSTED] and {n for _e, n in ev} == {no}
    c = _conn()
    try:
        row = c.execute("SELECT payload_json, kind FROM custom_record_finance_outbox ORDER BY id LIMIT 1").fetchone()
    finally:
        c.close()
    p = json.loads(row["payload_json"])
    assert row["kind"] == "expense+income" and {ln["kind"] for ln in p["lines"]} == {"income", "expense"}
    _do(client, h, no, "close")                                                   # 入帳 → 結案：離開 ⇒ REVERSED
    assert _events()[-1][0] == FIN.EVENT_REVERSED


def test_no_events_for_modules_without_finance_fields(client, make_user):
    h = _login(client, make_user, "b3fin_plain")
    body = _body()
    for f in body["fields"]:
        f.pop("finance", None)
    body.pop("finance")
    body["workflow"]["states"][1]["approval"] = None
    body["workflow"]["states"][1].pop("approval")
    key = "b3plain"
    body["permission"] = "custom." + key
    assert client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200
    no = client.post("/api/custom/%s/records" % key, headers=h, json={"values": {"title": "x", "amt": 5}}).json()["record_no"]
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), headers=h, json={}).status_code == 200
    assert _events() == []                                                         # 反向控制


def test_undated_lines_are_counted_not_silently_dropped(world):
    client, h = world
    a = _mk(client, h, amt=100, cost=50, d="2031-05-01")                          # 有權責日、沒有現金日
    _do(client, h, a, "submit")
    c = _conn()
    try:
        assert FIN.undated_counts(c, "accrual") == {"income": 0, "expense": 0}
        assert FIN.undated_counts(c, "cash") == {"income": 1, "expense": 1}
    finally:
        c.close()
    assert _income("cash") == [] and len(_income("accrual")) == 1


def test_income_linked_to_a_builtin_case_is_skipped_but_reported(world):
    client, h = world
    c = _conn()
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(quotations)")]
        need = {r[1]: r[4] for r in c.execute("PRAGMA table_info(quotations)") if r[3] and r[4] is None and not r[5]}
        vals = {k: ("x" if k not in ("id",) else None) for k in need}
        vals["quote_no"] = "Q-B3FIN-1"
        c.execute("INSERT INTO quotations (%s) VALUES (%s)" % (",".join(vals), ",".join("?" * len(vals))), list(vals.values()))
        c.commit()
        assert "quote_no" in cols
    finally:
        c.close()
    dup = _mk(client, h, amt=500, d="2031-06-01", cd="2031-06-02", cash=500, case="Q-B3FIN-1")
    free = _mk(client, h, amt=700, d="2031-06-03", cd="2031-06-04", cash=700, case="NOT-A-CASE")
    _do(client, h, dup, "submit")
    _do(client, h, free, "submit")
    assert [i["recordNo"] for i in _income("accrual")] == [free]                    # 內建案件的收入不重複計
    c = _conn()
    try:
        assert [d["recordNo"] for d in FIN.dup_skipped(c)] == [dup]
    finally:
        c.close()


def test_department_filter_needs_a_case_attribution(world):
    client, h = world
    no = _mk(client, h, amt=100, d="2031-07-01", cd="2031-07-01")
    _do(client, h, no, "submit")
    assert len(_income("accrual", dept=None)) == 1
    assert _income("accrual", dept=999) == []                                       # 沒有關聯案件無法歸屬 ⇒ 篩部門時排除


def test_revision_supersedes_the_old_record_only_after_the_new_one_posts(world):
    client, h = world
    no = _mk(client, h, amt=100, d="2031-08-01", cd="2031-08-01")
    _do(client, h, no, "submit")
    c = _conn()
    try:
        from helpers import custom_builder_support as S
        user = dict(c.execute("SELECT * FROM users WHERE username='b3fin_boss'").fetchone())
        rev = S.create_revision(c, KEY, no, "金額更正", user)
    finally:
        c.close()
    assert rev["record_no"] == no + "-R1"
    assert [i["recordNo"] for i in _income("accrual")] == [no]                       # 新版還是草稿：舊版照計
    client.put("/api/custom/%s/records/%s" % (KEY, rev["record_no"]), headers=h, json={"values": {"title": "T", "amt": 120, "d": "2031-08-01", "cd": "2031-08-01"}})
    _do(client, h, rev["record_no"], "submit")
    got = _income("accrual")
    assert [(i["recordNo"], i["amount"]) for i in got] == [(no + "-R1", 120.0)]      # 新版入帳 ⇒ 舊版不再計入，同一筆不算兩次


def test_case_finance_lists_posted_lines_of_a_case(world):
    client, h = world
    no = _mk(client, h, amt=100, cost=40, d="2031-09-01", case="CASE-X")
    _do(client, h, no, "submit")
    c = _conn()
    try:
        cf = FIN.case_finance(c, "CASE-X")
        assert cf["expense"]["total"] == 40 and cf["expense"]["items"][0]["recordNo"] == no
        assert cf["income"]["total"] == 100
        assert FIN.case_finance(c, "OTHER") == {"expense": {"total": 0, "items": []}, "income": {"total": 0, "items": []}}
    finally:
        c.close()


def test_report_expenses_use_cash_date_and_amount_on_cash_basis_and_accrual_date_otherwise(world):
    client, h = world
    no = _mk(client, h, cost=300, d="2031-03-05", cd="2031-04-10")
    _do(client, h, no, "submit")
    from modules.analytics.api import reports
    cash = reports._collect_expenses(2031, None, "cash")
    acc = reports._collect_expenses(2031, None, "accrual")
    m = lambda x: {r["month"]: r["other"] for r in x["monthly"]}
    assert m(cash)["2031-04"] == 300 and m(cash)["2031-03"] == 0
    assert m(acc)["2031-03"] == 300 and m(acc)["2031-04"] == 0
    assert any(d["category"] == "金流測試" for d in cash["details"]["other"])
    # 缺現金日 ⇒ 現金口徑不計，並在 unavailable 明說
    n2 = _mk(client, h, cost=50, d="2031-05-01")
    _do(client, h, n2, "submit")
    cash2 = reports._collect_expenses(2031, None, "cash")
    assert m(cash2)["2031-05"] == 0
    assert any(u.get("category") == "custom" and "待補登" in u["reason"] for u in cash2["unavailable"])
    assert not any(u.get("category") == "custom" for u in reports._collect_expenses(2031, None, "accrual")["unavailable"])
