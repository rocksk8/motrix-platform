# -*- coding: utf-8 -*-
"""IP-100 `payables.pending` 的取用端（M05 出納，2026-09-27 使用者裁示請款流程）。

- 請款待付款＝各提供者合併；登錄付款經提供者寫回付款日 ⇒ 從清單消失；finance 只能看、不能登錄；
  來源不存在 404、不是已核准或已登錄過 409、日期格式 400。
- 對方不在（M01 未安裝）：200 available:false＋明說原因，不回空清單裝沒事——
  反向控制用拿掉提供者模擬；真刪 M01 的安裝包裡同一題不需要模擬（提供者本來就不在）。
- 既有 payable-queue（IP-14）與 bonus-queue（IP-8）不受影響。
"""
import json

import pytest

from core import registry
from tests._requires import requires_module

NEEDS_CASE = requires_module("case", "請款的提供者是 M01 案件額外支出")
NO = "MQ-PP-001"


_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _h(client, make_user, name, role, modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _drop_payables(monkeypatch):
    """模擬 M01 不在：拿掉 payables.pending 的所有提供者（legacy 與 ModuleSpec 兩處）。"""
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] != "payables.pending"})
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "payables.pending" else orig(cap))
    assert not registry.providers("payables.pending")


def _seed(status="已核准", paid=""):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "付款客", "付款專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    import db
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
                           " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (NO, "材料", "線材", 1, "", 880, 880, "2031-05-01", json.dumps([{"id": "i1", "kind": "invoice"}]),
                            "pp_eng", "工程師甲", "", "2031-05-01", "2031-05-01", status, paid))
        conn.commit()
        return str(cur.lastrowid)
    finally:
        conn.close()


def _mine(resp, key):
    return [i for i in resp.json()["items"] if i["source"] == "case" and i["key"] == key]


@NEEDS_CASE
def test_lists_approved_unpaid_and_pay_writes_back_then_disappears(client, make_user):
    ok, draft, paid = _seed(), _seed(status="待審核"), _seed(paid="2031-05-09")
    cash = _h(client, make_user, "pp_cash", "sales", ["cashier"])
    r = client.get("/api/cashier/pending-payables", headers=cash)
    assert r.status_code == 200 and r.json()["available"] is True and r.json()["canPay"] is True, r.text
    it = _mine(r, ok)
    assert len(it) == 1 and it[0]["amount"] == 880 and it[0]["invoiceFiles"] == 1 and it[0]["customerName"] == "付款客", it
    assert not _mine(r, draft) and not _mine(r, paid)                                       # 未核准、已付款不列
    r = client.post("/api/cashier/pending-payables/case/%s/pay" % ok, json={"paidDate": "2031-05-20"}, headers=cash)
    assert r.status_code == 200 and r.json()["paidDate"] == "2031-05-20", r.text
    assert _q("SELECT paid_date FROM case_extra_expenses WHERE id=?", (int(ok),))[0]["paid_date"] == "2031-05-20"
    assert not _mine(client.get("/api/cashier/pending-payables", headers=cash), ok)          # 登錄後消失
    D = {"paidDate": "2031-05-21"}           # W1：付款日必填（不帶 ⇒ 400），下面各題要的是別的錯誤
    assert client.post("/api/cashier/pending-payables/case/%s/pay" % ok, json=D, headers=cash).status_code == 409
    assert client.post("/api/cashier/pending-payables/case/%s/pay" % draft, json=D, headers=cash).status_code == 409
    assert client.post("/api/cashier/pending-payables/case/999999/pay", json=D, headers=cash).status_code == 404
    assert client.post("/api/cashier/pending-payables/nope/%s/pay" % draft, json=D, headers=cash).status_code == 404
    assert client.post("/api/cashier/pending-payables/case/%s/pay" % draft, json={"paidDate": "2031/05/20"},
                       headers=cash).status_code == 400
    acts = [r["action"] for r in _q("SELECT action FROM audit_log WHERE action='cashier.payable_paid'")]
    assert acts == ["cashier.payable_paid"]


@NEEDS_CASE
def test_finance_can_view_but_not_pay_and_others_cannot_view(client, make_user):
    key = _seed()
    fin = _h(client, make_user, "pp_fin", "sales", ["finance"])
    r = client.get("/api/cashier/pending-payables", headers=fin)
    assert r.status_code == 200 and r.json()["canPay"] is True and _mine(r, key)          # 第42班：出納與財務合併為財務角色，「出納唯讀／不可核可」的分工不再存在（自核風險已列入 FINANCE-ROLE-GOLIVE 後續）
    nobody = _h(client, make_user, "pp_nobody", "sales", [])
    assert client.get("/api/cashier/pending-payables", headers=nobody).status_code == 403


def test_without_the_case_module_cashier_says_so_and_other_queues_still_work(client, make_user, monkeypatch):
    """M01 不在：請款待付款明說原因；登錄付款 404 說來源不在；應收照常（IP-14／IP-8 不受影響）。
    真刪 M01 的安裝包裡提供者本來就不在（下面的模擬在那裡是 no-op）。"""
    _drop_payables(monkeypatch)
    cash = _h(client, make_user, "pp_cash2", "sales", ["cashier"])
    r = client.get("/api/cashier/pending-payables", headers=cash)
    assert r.status_code == 200 and r.json() == {
        "available": False, "notice": "案件管理模組未安裝：出納頁不顯示請款（案件額外支出）待付款", "items": [], "canPay": False}
    r = client.post("/api/cashier/pending-payables/case/1/pay", json={}, headers=cash)
    assert r.status_code == 404 and "未安裝" in r.json()["detail"]
    assert client.get("/api/cashier/receivable-queue", headers=cash).status_code == 200

