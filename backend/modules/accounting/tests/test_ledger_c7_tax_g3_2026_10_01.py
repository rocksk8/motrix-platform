# -*- coding: utf-8 -*-
"""總帳 G3 · 自訂模組金額欄位的稅額規則（`finance.taxField`／`finance.docTypeField`；規則待使用者確認，見 custom_events 模組說明）。
全程走真實建構器：定義發布 → 單據 → 入帳 → `custom_events.gl_events`。金額欄位＝含稅總額；
有稅額欄位＋統一發票 ⇒ 拆進項（支出）／銷項（收入）稅額；收據等非統一發票、稅額不合理、沒有稅額欄位 ⇒ 含稅全額入帳（與 G3 之前相同）。
另驗 L1 helper 的擴充：`gl_lines` 原樣帶出 `finance` 屬性字典與單據 `data`（唯讀副本）。"""
import pytest

import db
from helpers import custom_finance as CF
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import custom_events as CE
from modules.accounting.ledger import roles as ROLES

KEY = "c7tax"


def _body(doc_type_field=True):
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)      # noqa: E731
    fin_exp = {"kind": "expense", "dateField": "d", "caseField": "case", "taxField": "tax"}
    fin_inc = {"kind": "income", "dateField": "d", "caseField": "case", "taxField": "tax"}
    if doc_type_field:
        fin_exp["docTypeField"] = "dtype"
        fin_inc["docTypeField"] = "dtype"
    return {"name": "稅額測試", "permission": "custom." + KEY, "numbering": {"prefix": "GT", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True),
                       f("cost", "費用（含稅）", "number", finance=fin_exp),
                       f("rev", "收入（含稅）", "number", finance=fin_inc),
                       f("tax", "稅額", "number"), f("dtype", "憑證種類", "text"),
                       f("d", "權責日", "date"), f("case", "關聯案件", "text")],
            "finance": {"postStates": ["done"]},
            "workflow": {"initial": "draft",
                         "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "入帳"}, {"key": "closed", "label": "結案", "final": True}],
                         "transitions": [{"key": "submit", "label": "入帳", "from": "draft", "to": "done"},
                                         {"key": "close", "label": "結案", "from": "done", "to": "closed"}]}}


@pytest.fixture()
def world(client, make_user):
    u, p = make_user("c7tax%d" % id(client), "Custom-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body()}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield client, h, c
    c.close()


def _post(client, h, **vals):
    base = {"title": "T", "d": "2031-06-10"}
    base.update(vals)
    r = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": base})
    assert r.status_code == 200, r.text
    no = r.json()["record_no"]
    t = client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, no), headers=h, json={})
    assert t.status_code == 200, t.text
    return no


def _e20(no):
    res = CE.gl_events("2031-06-01", "2031-06-30")
    return [e for e in res["events"] if e["doc_no"] == no and e["event_code"] == "E20"], res["notice"]


def _pairs(ev):
    return [(l["role"], l["side"], l["amount"]) for l in ev["lines"]]


def test_invoice_expense_splits_input_tax(world):
    client, h, _ = world
    no = _post(client, h, cost=10500, tax=500, dtype="統一發票")
    (ev,), notice = _e20(no)
    assert _pairs(ev) == [("EXP_OTHER", "D", 10000), ("INPUT_TAX", "D", 500), ("AP", "C", 10500)]
    assert ev["tax_code"] == "IN-5" and C.validate_event(ev) == []
    assert "1 筆已拆" in notice


def test_invoice_income_splits_output_tax(world):
    client, h, _ = world
    no = _post(client, h, rev=21000, tax=1000, dtype="invoice")
    (ev,), _n = _e20(no)
    assert _pairs(ev) == [("AR", "D", 21000), ("REV_OTHER", "C", 20000), ("OUTPUT_TAX", "C", 1000)]
    assert ev["tax_code"] == "OUT-5" and C.validate_event(ev) == []


def test_case_link_keeps_project_cost_and_splits_tax(world):
    client, h, _ = world
    no = _post(client, h, cost=1050, tax=50, dtype="統一發票", case="MQ-NOPE-1")
    (ev,), _n = _e20(no)
    assert _pairs(ev) == [("COST_PROJECT", "D", 1000), ("INPUT_TAX", "D", 50), ("AP", "C", 1050)]


@pytest.mark.parametrize("dtype", ["收據", "國外憑證", ""])
def test_non_invoice_folds_tax_into_cost(world, dtype):
    client, h, _ = world
    no = _post(client, h, cost=10500, tax=500, dtype=dtype)
    (ev,), notice = _e20(no)
    assert _pairs(ev) == [("EXP_OTHER", "D", 10500), ("AP", "C", 10500)] and ev["tax_code"] == ""
    assert "非統一發票" in notice                                     # 說明原因，不靜默


@pytest.mark.parametrize("tax", [0, None, 10500, 99999])
def test_no_or_unreasonable_tax_keeps_full_amount(world, tax):
    client, h, _ = world
    vals = {"cost": 10500, "dtype": "統一發票"}
    if tax is not None:
        vals["tax"] = tax
    no = _post(client, h, **vals)
    (ev,), _n = _e20(no)
    assert _pairs(ev) == [("EXP_OTHER", "D", 10500), ("AP", "C", 10500)] and ev["tax_code"] == ""


def test_tax_field_without_doc_type_field_is_treated_as_invoice(client, make_user):
    u, p = make_user("c7tax2%d" % id(client), "Custom-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body(doc_type_field=False)}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    c.close()
    no = _post(client, h, cost=10500, tax=500)
    (ev,), _n = _e20(no)
    assert _pairs(ev) == [("EXP_OTHER", "D", 10000), ("INPUT_TAX", "D", 500), ("AP", "C", 10500)]


def test_field_map_account_applies_to_the_cost_line_only(world):
    client, h, c = world
    c.execute("INSERT OR REPLACE INTO gl_custom_field_map(module_key, field_key, debit_account, credit_account, tax_code, kind, is_active) VALUES (?,?,?,?,?,?,1)",
              (KEY, "cost", "6112", "", "", ""))
    c.commit()
    no = _post(client, h, cost=10500, tax=500, dtype="統一發票")
    (ev,), _n = _e20(no)
    assert [(l.get("account_code", ""), l["role"], l["amount"]) for l in ev["lines"]] == [("6112", "EXP_OTHER", 10000), ("", "INPUT_TAX", 500), ("", "AP", 10500)]


def test_gl_lines_passes_the_whole_finance_dict_and_data(world):
    client, h, c = world
    no = _post(client, h, cost=10500, tax=500, dtype="統一發票")
    rec = [r for r in CF.gl_lines(c) if r["recordNo"] == no][0]
    assert rec["data"]["tax"] == 500 and rec["data"]["dtype"] == "統一發票"
    ln = [x for x in rec["lines"] if x["field"] == "cost"][0]
    assert ln["finance"] == {"kind": "expense", "dateField": "d", "caseField": "case", "taxField": "tax", "docTypeField": "dtype"}
    ln["finance"]["taxField"] = "hacked"                              # 唯讀副本：改它不影響下一次
    again = [r for r in CF.gl_lines(c) if r["recordNo"] == no][0]
    assert [x for x in again["lines"] if x["field"] == "cost"][0]["finance"]["taxField"] == "tax"
