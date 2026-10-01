# -*- coding: utf-8 -*-
"""32-Q6（使用者裁示 2026-10-02）：案件額外支出清單的合計與營運報表同一條規則——只計待審核／簽核中／已核准、且類型要進金流；
請購單、草稿、已駁回不計（`uncountedAmount` 另給）；作廢與被遮蔽的列照舊不計。"""
import json

import pytest

import db
from modules.case import recognition as R

SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def H(client, make_user):
    u, pw = make_user(username="q6_sa", role="superadmin")
    return _login(client, u, pw)


def _mk(client, H, kind, amount, status=None):
    r = client.post(SENT, headers=H, json={"kind": kind, "lines": [{"category": "雜項", "summary": kind, "amount": amount}],
                                           "payeeName": "某人", "payeeType": "employee", "data": {"applicant": "q6_sa"}})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    if status:
        c = db.get_db()
        c.execute("UPDATE case_extra_expenses SET status=? WHERE id=?", (status, eid))
        c.commit()
        c.close()
    return eid


def _list(client, H):
    r = client.get(SENT, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_only_counted_statuses_and_payable_kinds_are_totalled(client, H):
    _mk(client, H, "purchase_order", 1000, "已核准")
    _mk(client, H, "travel", 200, "待審核")
    _mk(client, H, "petty_cash", 30, "簽核中")
    _mk(client, H, "purchase_req", 5000, "已核准")          # 請購單：已核准也不計
    _mk(client, H, "travel", 400)                           # 草稿
    _mk(client, H, "travel", 7000, "已駁回")
    d = _list(client, H)
    assert d["totalAmount"] == 1230 and d["totalPending"] == 230
    assert d["uncountedAmount"] == 5000 + 400 + 7000
    assert len(d["items"]) == 6                              # 清單仍列出全部（只是合計不同）


def test_voided_rows_still_excluded_and_empty_case_is_zero(client, H):
    assert _list(client, H)["totalAmount"] == 0 and _list(client, H)["uncountedAmount"] == 0
    _mk(client, H, "travel", 999, "已作廢")
    d = _list(client, H)
    assert d["totalAmount"] == 0 and d["uncountedAmount"] == 0


def test_list_total_equals_the_operating_report_source(client, H):
    """與營運報表同一條規則：清單合計＝extra_entries 的權責口徑合計（同一組單據）。"""
    _mk(client, H, "purchase_order", 1000, "已核准")
    _mk(client, H, "travel", 200, "待審核")
    _mk(client, H, "purchase_req", 5000, "已核准")
    _mk(client, H, "travel", 7000, "已駁回")
    c = db.get_db()
    try:
        rep = sum(e["amount"] for e in R.extra_entries(c, "accrual") if e["quoteNo"] == "")
    finally:
        c.close()
    assert _list(client, H)["totalAmount"] == rep == 1200
