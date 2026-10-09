# -*- coding: utf-8 -*-
"""第 49 班 W1-c-P2：每個請求旗標的接收點——字串 "false"／"0"／"" ⇒ 422 且什麼都沒寫；真布林照舊。
（守門 tests/platform/test_no_truthy_request_flags.py 保證不會再出現 bool(body.get(...))。）"""
import json

import pytest

import db

BAD = ["false", "0", ""]


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def su(client, make_user):
    u, p = make_user(username="sb_su", role="superadmin")
    return _login(client, u, p)


def _setting(key):
    c = db.get_db()
    try:
        r = c.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else None
    finally:
        c.close()


# ── 最高優先：個人外包匯款『強制關聯勞報單』的緊急開關 ─────────────────────────────────
def test_remit_require_payslip_switch_only_takes_real_booleans(client, su):
    url = "/api/contractor-vouchers/settings/remit-require-payslip"
    for bad in BAD:
        assert client.put(url, json={"enabled": bad}, headers=su).status_code == 422, bad
    assert _setting("remit_require_payslip") is None, "422 不可寫入設定"
    assert client.put(url, json={"enabled": False, "reason": "緊急"}, headers=su).json() == {"enabled": False}
    assert _setting("remit_require_payslip") in ("0", 0)
    assert client.put(url, json={"enabled": True}, headers=su).json() == {"enabled": True}


def test_ledger_feature_switch(client, su):
    for bad in BAD:
        assert client.put("/api/ledger/features/engine_drafts", json={"enabled": bad}, headers=su).status_code == 422, bad
    assert client.put("/api/ledger/features/engine_drafts", json={"enabled": False}, headers=su).status_code == 200


@pytest.mark.parametrize("method,url,key", [
    ("post", "/api/ledger/years/2026/closing/generate", "regenerate"),
    ("post", "/api/ledger/years/2026/close", "accept_warnings"),
    ("post", "/api/ledger/periods/999999/close", "accept_warnings"),
    ("post", "/api/vouchers/999999/void", "reopen"),
    ("patch", "/api/bonus/groups/999999/active", "is_active"),
])
def test_flag_sites_reject_string_flags_before_touching_anything(client, su, method, url, key):
    for bad in BAD:
        body = {key: bad}
        if key == "reopen":
            body["reason"] = "測試作廢"
        r = getattr(client, method)(url, json=body, headers=su)
        assert r.status_code == 422, (url, bad, r.status_code, r.text[:160])


def test_category_map_nondeductible_flag(client, su):
    for bad in BAD:
        r = client.put("/api/ledger/category-map", json={"category": "x", "account_code": "5101", "nondeductible": bad}, headers=su)
        assert r.status_code == 422, (bad, r.status_code, r.text[:160])


def test_cascade_flag_on_the_three_approvers(client, su):
    for url in ("/api/quotations/NOPE/material-orders/it1/approve", "/api/quotations/NOPE/material-changes/1/approve", "/api/material-payments/1/approve"):
        for bad in BAD:
            assert client.post(url, json={"cascade": bad}, headers=su).status_code == 422, (url, bad)


def test_preview_html_internal_flag(client, su):
    for bad in BAD:
        assert client.post("/api/quotations/preview-html", json={"data": {}, "internal": bad}, headers=su).status_code == 422, bad


def test_payslip_union_insurance_flag_changes_withholding_so_it_must_be_strict(client, su):
    body = {"data": {"contractorName": "測試承攬人", "incomeType": "9A", "grossAmount": 35000, "contractorNationality": "本國籍",
                     "contractorHasUnionInsurance": "false", "slipDate": "2026-12-20"}}
    r = client.post("/api/payslips", json=body, headers=su)
    assert r.status_code == 422, r.text[:200]
    body["data"]["contractorHasUnionInsurance"] = False
    assert client.post("/api/payslips", json=body, headers=su).status_code in (200, 201)


def test_payment_received_flag_and_cashier_fee_flag_units():
    from fastapi import HTTPException
    from modules.case.api import quotations as Q
    from modules.case import payables as PB
    from modules.case import material_payment as MP
    for bad in BAD:
        with pytest.raises(HTTPException) as e:
            Q._validate_receipt_body({"received": bad})
        assert e.value.status_code == 422
        with pytest.raises(HTTPException) as e2:
            PB.parse_remit({"actualAmount": 100, "hasFee": bad, "fee": 5}, 100)
        assert e2.value.status_code == 422
        with pytest.raises(HTTPException) as e3:
            MP.parse_line({"actualAmount": 100, "hasFee": bad, "fee": 5}, 100)
        assert e3.value.status_code == 422
    assert PB.parse_remit({"actualAmount": 100, "hasFee": True, "fee": 5}, 100)["fee"] == 5
    assert MP.parse_line({"actualAmount": 100, "hasFee": False, "fee": 5}, 100)["fee"] == 0


def test_ledger_request_normalize_rejects_string_accept_warnings():
    """非最高管理者送出的結帳申請：旗標被存成申請參數、最高管理者核准時照用——字串不可在這裡被轉成 true。"""
    from modules.accounting.ledger import requests as R
    with pytest.raises(R.RequestError):
        R._flag({"accept_warnings": "false"}, "accept_warnings")
    assert R._flag({"accept_warnings": True}, "accept_warnings") is True and R._flag({}, "accept_warnings") is False
