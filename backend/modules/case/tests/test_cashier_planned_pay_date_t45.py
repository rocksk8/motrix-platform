# -*- coding: utf-8 -*-
"""第 45 班 S1：出納端點 PATCH /api/cashier/pending-payables/{source}/{key}/planned-pay-date（來源無關、經 IP-100 提供者，不經案件守門）。
含 Q4：行事曆「付款待辦」事件文字不放受款人、付款條件、金額。Google 用假行事曆；不連外。"""
import pytest

from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = [requires_module("case", "預定付款日提供者在 M01"), requires_module("arap", "出納端點在 M05")]

NO = "MQ-T45PAY-001"


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur
    finally:
        conn.close()


def _row(exp_id):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
    finally:
        conn.close()


def _seed(planned="", status="已核准", paid="", kind="", pay_terms=""):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "預付客", "預付專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    return _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
              " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date, kind, planned_pay_date, pay_terms)"
              " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (NO, "材料", "線材", 1, "", 1200, 1200, "2031-05-01", "[]", "t45_eng", "工程師甲", "材料行甲", "2031-05-01",
               "2031-05-01", status, paid, kind, planned, pay_terms)).lastrowid


def _hdr(client, make_user, name, role="superadmin", modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _url(eid, source="case"):
    return "/api/cashier/pending-payables/%s/%s/planned-pay-date" % (source, eid)


def _gcal(monkeypatch):
    from modules.case import payable_calendar
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, payable_calendar)
    _fake_gcal.set_events(events={"payable_due": True})
    return cal


def test_finance_sets_changes_and_clears(client, make_user):
    eid = _seed()
    h = _hdr(client, make_user, "t45_fin", role="finance")
    r = client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-10"})
    assert r.status_code == 200 and r.json()["plannedPayDate"] == "2031-06-10", r.text
    assert _row(eid)["planned_pay_date"] == "2031-06-10"
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-20"}).status_code == 200
    assert _row(eid)["planned_pay_date"] == "2031-06-20"
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": ""}).status_code == 200
    assert _row(eid)["planned_pay_date"] == ""


def test_finance_not_case_member_can_set_cm14b_positive_control(client, make_user):
    """財務不是該案成員、案件頁對他唯讀——出納端點仍能改（不經案件守門，不需要放寬 CM14b）。"""
    eid = _seed()
    h = _hdr(client, make_user, "t45_fin2", role="finance")
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-07-01"}).status_code == 200


def test_non_finance_roles_forbidden(client, make_user):
    eid = _seed(planned="2031-06-01")
    for name, role in (("t45_admin", "admin"), ("t45_user", "user")):
        h = _hdr(client, make_user, name, role=role)
        assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-07-01"}).status_code == 403
    assert client.patch(_url(eid), json={"plannedPayDate": "2031-07-01"}).status_code in (401, 403)
    assert _row(eid)["planned_pay_date"] == "2031-06-01", "被擋的請求不可改到資料"


def test_validation_and_unknown_targets(client, make_user):
    eid = _seed()
    h = _hdr(client, make_user, "t45_sa")
    for bad in ("2031/06/10", "2031-02-30", "下週"):
        assert client.patch(_url(eid), headers=h, json={"plannedPayDate": bad}).status_code == 400
    assert client.patch(_url(eid), headers=h, json={}).status_code == 400                    # 沒帶鍵 ≠ 清除
    assert client.patch(_url(eid, "nope"), headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 404
    assert client.patch(_url(999999), headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 404
    assert client.patch(_url("abc"), headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 404
    assert _row(eid)["planned_pay_date"] == ""


def test_paid_unapproved_and_non_payable_kinds_rejected(client, make_user):
    h = _hdr(client, make_user, "t45_sa")
    paid = _seed(planned="2031-06-01", paid="2031-06-02")
    r = client.patch(_url(paid), headers=h, json={"plannedPayDate": "2031-07-01"})
    assert r.status_code == 409 and "歷史" in r.json()["detail"]
    assert _row(paid)["planned_pay_date"] == "2031-06-01"
    draft = _seed(status="草稿")
    assert client.patch(_url(draft), headers=h, json={"plannedPayDate": "2031-07-01"}).status_code == 404
    pr = _seed(kind="purchase_request")                                                       # 請購單不進出納
    assert client.patch(_url(pr), headers=h, json={"plannedPayDate": "2031-07-01"}).status_code == 404


def test_audit_written_without_amount(client, make_user):
    import db
    eid = _seed(planned="2031-06-01")
    h = _hdr(client, make_user, "t45_sa")
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-09"}).status_code == 200
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT * FROM audit_log WHERE action=?", ("cashier.planned_pay_date",)).fetchall()
    finally:
        conn.close()
    assert rows, "要留稽核"
    text = " ".join(str(v) for v in dict(rows[-1]).values())
    assert "2031-06-01" in text and "2031-06-09" in text and "1200" not in text and "1,200" not in text


def test_calendar_event_follows_and_has_no_money_payee_or_terms(client, make_user, monkeypatch):
    cal = _gcal(monkeypatch)
    eid = _seed(pay_terms="月結30天")
    h = _hdr(client, make_user, "t45_sa")
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    ev = [e for e in cal.events.values()]
    assert len(ev) == 1
    blob = " ".join(str(v) for v in ev[0].values())
    assert "2031-06-10" in blob and "線材" in blob
    for leak in ("材料行甲", "月結30天", "受款人", "付款條件", "1200", "1,200"):
        assert leak not in blob, leak
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-15"}).status_code == 200
    assert len(cal.events) == 1 and "2031-06-15" in " ".join(str(v) for v in list(cal.events.values())[0].values())
    assert client.patch(_url(eid), headers=h, json={"plannedPayDate": ""}).status_code == 200
    assert cal.events == {}, "清除預定日 ⇒ 事件收掉"


def test_provider_without_method_is_409(client, make_user, monkeypatch):
    from core import registry
    h = _hdr(client, make_user, "t45_sa")
    real = registry.providers

    class _Bare:
        @staticmethod
        def pending(conn):
            return []

    monkeypatch.setattr(registry, "providers", lambda name: dict(real(name), bare=_Bare) if name == "payables.pending" else real(name))
    r = client.patch(_url("1", "bare"), headers=h, json={"plannedPayDate": "2031-06-10"})
    assert r.status_code == 409 and "不支援" in r.json()["detail"]
