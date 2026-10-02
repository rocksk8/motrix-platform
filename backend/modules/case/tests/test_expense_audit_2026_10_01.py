# -*- coding: utf-8 -*-
"""A2 S2：費用單據的稽核 detail 帶「發生了什麼」的摘要（類型／單號／金額／明細列數／部門／收款人類型），
**永遠不含**收款人姓名、銀行、帳號、其餘明細列內容、data（標題沿用單據說明＝第一列摘要，既有作法）；舊版列（kind=''）只帶金額（行為不變）。"""
import json
from datetime import date

import pytest

SENT = "/api/quotations/-/extra-expenses"
ACCOUNT, BANK, PAYEE, SUMMARY, LINE2 = "9876543210123", "玉山銀行", "機密收款人", "第一列品項", "第二列機密明細"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def H(client, make_user):
    out = {}
    for u, role, mods in (("au_form", "sales", ["expense_forms"]), ("au_sa", "superadmin", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        out[u] = _login(client, name, pw)
    return out


def _audit(action):
    return [dict(r, detail=json.loads(r["detail"] or "{}")) for r in _q("SELECT action, target_type, target_id, detail FROM audit_log WHERE action=? ORDER BY id", (action,))]


def _create(client, h):
    r = client.post(SENT, headers=h, json={"kind": "travel", "lines": [{"category": "交通費", "summary": SUMMARY, "amount": 1200}, {"category": "住宿費", "summary": LINE2, "amount": 800}],
                                           "data": {"applicant": "au_form", "dept": 7}, "payeeType": "employee", "payeeName": PAYEE, "payeeBank": BANK, "payeeAccount": ACCOUNT})
    assert r.status_code == 201, r.text
    return r.json()


def test_every_lifecycle_audit_row_has_the_summary_and_no_personal_data(client, H):
    c = _create(client, H["au_form"])
    eid = c["id"]
    up = client.patch("%s/%d" % (SENT, eid), headers=H["au_form"], json={"kind": "travel", "lines": [{"category": "交通費", "summary": SUMMARY, "amount": 1500}],
                                                                         "payeeType": "employee", "payeeName": PAYEE, "payeeBank": BANK, "payeeAccount": ACCOUNT})
    assert up.status_code == 200, up.text
    _no_tiers()
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["au_form"]).status_code == 200
    assert client.post("%s/%d/void" % (SENT, eid), headers=H["au_sa"], json={"reason": "重複"}).status_code == 200
    for action in ("extra_expense.create", "extra_expense.update", "extra_expense.auto_approve", "extra_expense.void"):
        (row,) = _audit(action)
        d = row["detail"]
        assert d["kind"] == "travel" and d["docCode"] == c["docCode"] and d["departmentId"] == 7 and d["payeeType"] == "employee" and d["currency"] == "TWD", (action, d)
        assert d["lineCount"] == (2 if action == "extra_expense.create" else 1) and d["totalCost"] == (2000 if action == "extra_expense.create" else 1500), (action, d)
    assert _audit("extra_expense.update")[0]["detail"]["before"]["totalCost"] == 2000                                  # 前值
    assert _audit("extra_expense.void")[0]["detail"]["reason"] == "重複"
    blob = json.dumps([r for r in _q("SELECT action, target_label, detail FROM audit_log WHERE action LIKE 'extra_expense.%'")], ensure_ascii=False)
    for secret in (ACCOUNT, BANK, PAYEE, LINE2):
        assert secret not in blob, secret                                                                                 # 稽核不含收款人姓名／銀行／帳號／其餘明細列內容（第一列＝單據說明，標題沿用既有作法）


def test_approve_reject_and_delete_carry_the_summary(client, H):
    a = _create(client, H["au_form"])["id"]
    assert client.delete("%s/%d" % (SENT, a), headers=H["au_form"]).status_code == 200
    (row,) = _audit("extra_expense.delete")
    assert row["detail"]["kind"] == "travel" and row["detail"]["totalCost"] == 2000 and row["detail"]["lineCount"] == 2
    b = _create(client, H["au_form"])["id"]
    appr = {"requestedBy": "au_form", "requestedByDisplay": "x", "requestedAt": "2026-10-01T10:00:00",
            "tiers": [{"order": 0, "approvers": [{"username": "au_sa", "display_name": "sa"}, ]}, {"order": 1, "approvers": [{"username": "au_sa", "display_name": "sa"}]}], "currentTier": 0}
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?", (json.dumps(appr), b))
        c.commit()
    finally:
        c.close()
    r = client.post("%s/%d/approve" % (SENT, b), headers=H["au_sa"], json={})
    assert r.status_code == 200, r.text
    (ap,) = _audit("extra_expense.approve")
    assert ap["detail"]["tier"] == 1 and ap["detail"]["kind"] == "travel" and ap["detail"]["totalCost"] == 2000
    rj = client.post("%s/%d/reject" % (SENT, b), headers=H["au_sa"], json={"reason": "金額不對"})
    assert rj.status_code == 200, rj.text
    (rr,) = _audit("extra_expense.reject")
    assert rr["detail"]["reason"] == "金額不對" and rr["detail"]["docCode"].startswith("TE-")


def test_legacy_rows_audit_only_carries_the_amount(client, H, seed_extra_expense):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  ("MQ-AUD-1", "已送出", "客", "案", 0, 0, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()
    r = client.post("/api/quotations/MQ-AUD-1/extra-expenses", headers=H["au_sa"], json={"description": "舊版運費", "qty": 2, "unitCost": 500})
    assert r.status_code == 201, r.text
    (row,) = _audit("extra_expense.create")
    assert row["detail"] == {"totalCost": 1000.0}                                                                         # 舊版列：行為不變，只多金額
