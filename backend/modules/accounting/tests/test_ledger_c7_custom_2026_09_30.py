# -*- coding: utf-8 -*-
"""總帳 C7 · 自訂模組單據入帳（事件來源 custom_modules）：入帳中的單據 ⇒ E20（權責）／E20b（收付款）事件；離開入帳狀態 ⇒ 事件消失 ⇒ 引擎反向；
收入關聯到內建案件不重複；欄位對應科目（gl_custom_field_map）可覆寫；缺日期明說、不靜默少列。全程走真實的建構器（定義發布→單據→狀態轉換）。"""
import json

import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import custom_events as CE
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES

KEY = "c7gl"
_N = [0]


def _body():
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)      # noqa: E731
    return {"name": "總帳串接測試", "permission": "custom." + KEY, "numbering": {"prefix": "GC", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True),
                       f("amt", "收入", "number", finance={"kind": "income", "dateField": "d", "cashDateField": "cd", "caseField": "case", "cashAmountField": "cash"}),
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
    u, p = make_user("c7boss%d" % id(client), "Custom-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body()}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield client, h, c
    c.close()


def _mk(client, h, **vals):
    base = {"title": "T"}
    base.update(vals)
    r = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": base})
    assert r.status_code == 200, r.text
    return r.json()["record_no"]


def _do(client, h, no, t):
    r = client.post("/api/custom/%s/records/%s/transitions/%s" % (KEY, no, t), headers=h, json={})
    assert r.status_code == 200, r.text


def _ev(no, code=None):
    res = CE.gl_events("2031-05-01", "2031-05-31")
    return [e for e in res["events"] if e["doc_no"] == no and (code is None or e["event_code"] == code)], res["notice"]


def _pairs(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_income_and_expense_events_accrual_and_cash(world):
    client, h, _ = world
    no = _mk(client, h, amt=10000, cash=10500, cost=4000, d="2031-05-10", cd="2031-05-20")
    _do(client, h, no, "submit")
    evs, notice = _ev(no)
    by = {(e["event_code"], e["meta"]["kind"]): e for e in evs}
    assert _pairs(by[("E20", "income")]) == [("AR", "D", 10000), ("REV_OTHER", "C", 10000)]
    assert _pairs(by[("E20", "expense")]) == [("EXP_OTHER", "D", 4000), ("AP", "C", 4000)]
    assert _pairs(by[("E20b", "income")]) == [("BANK", "D", 10500), ("AR", "C", 10500)]              # 現金金額用 cashAmountField
    assert _pairs(by[("E20b", "expense")]) == [("AP", "D", 4000), ("BANK", "C", 4000)]               # 沒設現金金額 ⇒ 同權責金額
    assert all(C.validate_event(e) == [] and e["source_type"].startswith("custom_record") for e in evs)
    assert "含稅總額" in notice and "其餘含稅全額入帳" in notice                    # G3：措辭改為含稅總額；沒有稅額欄位時行為不變
    assert not [e for e in CE.gl_events("2031-06-01", "2031-06-30")["events"] if e["doc_no"] == no]      # 日期窗


def test_drafts_are_not_posted_and_leaving_the_state_reverses_through_the_engine(world):
    client, h, conn = world
    no = _mk(client, h, amt=5000, d="2031-05-11")
    assert _ev(no)[0] == []                                                # 草稿：不入帳
    _do(client, h, no, "submit")
    E.run(conn, "2031-05-01", "2031-05-31", "acc")
    conn.commit()
    row = conn.execute("SELECT status, voucher_id FROM gl_source_events WHERE source_key LIKE ? AND event_code='E20'", ("%::" + no + "::amt",)).fetchone()
    assert row["status"] == "drafted" and row["voucher_id"]
    _do(client, h, no, "withdraw")                                          # 撤回 ⇒ 事件消失
    r = E.run(conn, "2031-05-01", "2031-05-31", "acc")
    conn.commit()
    assert r["stats"]["orphans"] >= 1
    assert conn.execute("SELECT status FROM gl_source_events WHERE source_key LIKE ? AND event_code='E20'", ("%::" + no + "::amt",)).fetchone()[0] == "orphan"


def test_income_linked_to_a_builtin_case_is_not_booked_twice(world):
    client, h, conn = world
    conn.execute("INSERT OR IGNORE INTO quotations(quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name) VALUES ('MQ-C7-1','已成案',1,1,'{}','n','n','甲')")
    conn.commit()
    no = _mk(client, h, amt=8000, cost=3000, d="2031-05-12", case="MQ-C7-1")
    _do(client, h, no, "submit")
    evs, notice = _ev(no)
    kinds = {(e["event_code"], e["meta"]["kind"]) for e in evs}
    assert ("E20", "income") not in kinds and ("E20", "expense") in kinds                        # 收入由內建報價單認列；支出照記
    exp = [e for e in evs if e["meta"]["kind"] == "expense" and e["event_code"] == "E20"][0]
    assert _pairs(exp)[0][0] == "COST_PROJECT" and exp["case_no"] == "MQ-C7-1"                  # 有案件 ⇒ 專案成本
    assert "內建報價單" in notice


def test_field_map_overrides_accounts_and_tax_code(world):
    client, h, conn = world
    conn.execute("INSERT OR REPLACE INTO gl_custom_field_map(module_key, field_key, debit_account, credit_account, tax_code, kind, is_active) VALUES (?,?,?,?,?,?,1)",
                 (KEY, "amt", "1191", "4111", "OUT-5", "income"))
    conn.commit()
    try:
        no = _mk(client, h, amt=3000, d="2031-05-13")
        _do(client, h, no, "submit")
        (e,) = _ev(no, "E20")[0]
        assert [l.get("account_code") for l in e["lines"]] == ["1191", "4111"] and e["tax_code"] == "OUT-5"
    finally:
        conn.execute("DELETE FROM gl_custom_field_map WHERE module_key=?", (KEY,))
        conn.commit()


def test_undated_and_zero_lines_are_reported_not_silently_dropped(world):
    client, h, _ = world
    no = _mk(client, h, amt=1000)                                            # 沒有權責日
    zero = _mk(client, h, amt=0, d="2031-05-14")
    _do(client, h, no, "submit")
    _do(client, h, zero, "submit")
    evs, notice = _ev(no)
    assert evs == [] and "沒有權責日期" in notice
    assert _ev(zero)[0] == []                                                # 金額 0 不產生


def test_provider_is_registered_under_custom_modules_and_source_is_listed(client):
    import importlib
    spec = importlib.import_module("modules.accounting").MODULE
    assert ("gl.events", "custom_modules") in spec.providers and "custom_modules" in C.SOURCES
    assert ROLES.DEFAULT_ROLES["REV_OTHER"] == "4141"
