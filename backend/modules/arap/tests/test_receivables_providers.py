"""IP-98 `receivables.income_items`／IP-99 `receivables.tax_invoices` 提供方這一側（隨 M05 搬走）。

① 登記：兩個 capability 各有 M05 的一個提供者
② 正對照：一張已成案、已收款並填了發票號碼的報價 ⇒ 兩個 provider 都列出它；M08 現金口徑收入與稅務匯出照常；T100 預覽不帶收款缺口
"""
import json

from core import registry
import pytest


def _sa(client, make_user):
    u, p = make_user("rcv_prov_sa", "Conn-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed(no="MQ-202609-RCV1"):
    import db
    conn = db.get_db()
    try:
        data = {"caseRecord": {"payment": {"items": [
            {"type": "訂金款", "pct": 100, "amount": 10500, "received": True, "receivedAt": "2026-09-10",
             "invoiceNo": "AB12345678", "invoiceDate": "2026-09-10"}]}}}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "探針客戶", "探針專案", 10500, 10000, json.dumps(data, ensure_ascii=False),
                      "2026-09-01T00:00:00", "2026-09-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()
    return no


def test_providers_are_registered(client):
    from modules.arap import receivables
    assert registry.single_provider("receivables.income_items") is receivables.collect_income_items
    assert registry.single_provider("receivables.tax_invoices") is receivables.collect_tax_invoices


def test_positive_control_both_providers_list_the_paid_invoiced_item(client, make_user):
    no = _seed()
    inc = registry.single_provider("receivables.income_items")("2026-09-01", "2026-09-30")
    assert [i["quoteNo"] for i in inc] == [no], inc
    tax = registry.single_provider("receivables.tax_invoices")(2026, 9)
    assert [(t["quoteNo"], t["invoiceNo"]) for t in tax] == [(no, "AB12345678")], tax
    h = _sa(client, make_user)
    from core import source_tree
    if source_tree.module_installed("modules/analytics/"):
        r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash", headers=h).json()
        assert r["incomeNotice"] == "" and [i["quoteNo"] for i in r["monthIncomeItems"]] == [no]
        assert client.get("/api/reports/tax-export?year=2026&month=9", headers=h).status_code == 200
    if source_tree.module_installed("modules/accounting/"):                  # T100 那一段要 M06（2026-09-26 搬遷）
        prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h).json()
        from modules.accounting.api import accounting_export as ae
        assert ae.T100_RECEIVABLES_MISSING not in prev["notice"]
        assert any(e["sourceType"] == "quotation_payment" for e in prev["events"]), prev["events"]
