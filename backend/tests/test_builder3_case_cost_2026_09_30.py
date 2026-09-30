# -*- coding: utf-8 -*-
"""建構器第三輪 S2.5 收尾（2026-09-30，主持裁示：收入／支出都要接到案件成本）：
自訂模組關聯到內建案件的入帳金流 ⇒ 案件財務總覽 `customFinance`、成本精算頁「額外支出」含自訂模組支出；
收入因內建報價單已認列而略過（標 skipped、不進 total）；沒有查看財務金額權限 ⇒ 403。"""
import json

import pytest

from tests._requires import requires_module
from tests._e2e_login import inject_login

pytestmark = requires_module("case", "本檔的題打 M01（案件）的財務總覽與成本精算頁")

KEY = "b3cc"
CASE = "MQ-B3CC-001"


def _login(client, make_user, name, role="superadmin", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}, u, p


def _seed_case():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (CASE, "已送出", "成本測客", "測專", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _module(client, h):
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)
    body = {"name": "案件金流", "permission": "custom." + KEY, "numbering": {"prefix": "CC", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True),
                       f("inc", "收入", "number", finance={"kind": "income", "dateField": "d", "caseField": "case"}),
                       f("cost", "成本", "number", finance={"kind": "expense", "dateField": "d", "caseField": "case"}),
                       f("d", "日期", "date"), f("case", "關聯案件", "text")],
            "finance": {"postStates": ["done"]},
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "入帳", "final": True}],
                         "transitions": [{"key": "submit", "label": "入帳", "from": "draft", "to": "done"}]}}
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200


def _record(client, h, **vals):
    no = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": dict({"title": "T", "d": "2031-02-03"}, **vals)}).json()["record_no"]
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (KEY, no), headers=h, json={}).status_code == 200
    return no


@pytest.fixture()
def world(client, make_user):
    h, u, p = _login(client, make_user, "b3cc_boss")
    _module(client, h)
    _seed_case()
    return client, h, u, p


def test_finance_summary_and_case_endpoint_carry_custom_expense_and_skipped_income(world):
    client, h, _u, _p = world
    exp = _record(client, h, cost=1200, case=CASE)
    inc = _record(client, h, inc=5000, case=CASE)                                   # 內建案件已認列收入 ⇒ 略過
    other = _record(client, h, cost=999, case="OTHER-CASE")
    fs = client.get("/api/quotations/%s/finance-summary" % CASE, headers=h)
    assert fs.status_code == 200, fs.text
    cf = fs.json()["customFinance"]
    assert cf["expense"]["total"] == 1200 and [i["recordNo"] for i in cf["expense"]["items"]] == [exp]
    assert cf["income"]["total"] == 0 and cf["income"]["skippedTotal"] == 5000
    assert [(i["recordNo"], i.get("skipped")) for i in cf["income"]["items"]] == [(inc, True)]
    assert other not in json.dumps(cf)
    ep = client.get("/api/custom-modules/finance/case/%s" % CASE, headers=h).json()
    assert ep == cf                                                                  # 兩條路同一份


def test_case_endpoint_needs_financial_view_and_case_access(client, make_user):
    h, _u, _p = _login(client, make_user, "b3cc_boss")
    _module(client, h)
    _seed_case()
    _record(client, h, cost=10, case=CASE)
    hv, _u2, _p2 = _login(client, make_user, "b3cc_viewer", role="viewer", modules=[])
    assert client.get("/api/custom-modules/finance/case/%s" % CASE, headers=hv).status_code == 403


@pytest.mark.e2e
def test_settlement_page_adds_custom_expense_to_extra_cost_and_shows_the_skipped_income(live_server, world, new_context):
    client, h, u, p = world
    _record(client, h, cost=1200, case=CASE)
    _record(client, h, inc=5000, case=CASE)
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u, p)
    page.goto(live_server + "/pages/settlement.html?no=" + CASE)
    page.wait_for_selector('[data-testid="settle-custom-expense"]', timeout=20000)
    assert "1,200" in page.locator('[data-testid="settle-custom-expense"]').inner_text()
    hint = page.locator('[data-testid="settle-custom-income-skipped"]').inner_text()
    assert "1 筆收入" in hint and "未重複計入" in hint
    assert not errors, errors


def test_case_endpoint_unknown_or_invisible_case_is_404_not_403(world):
    client, h, _u, _p = world
    r = client.get("/api/custom-modules/finance/case/NO-SUCH-CASE", headers=h)
    assert r.status_code == 404 and "不存在" in r.text                           # 查無／看不到＝同一個 404（M01-O1），不洩漏案件是否存在
