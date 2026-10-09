# -*- coding: utf-8 -*-
"""第 49 班補丁（W1c-P2b）：八個 approver 端點的 `cascade` 與匯款 `hasFee` 的嚴格旗標。

`cascade` 字串 "false"／"0"／"" 以前是 truthy ⇒ 『替簽核人自動簽完剩下的連續層』被誤觸發。現在先驗旗標（在碰資料庫、簽核鏈之前）：非布林 ⇒ 422，什麼都不寫；
真布林（含 false）⇒ 照舊往下走（這裡用不存在的單據，所以是 404，證明旗標沒有擋掉正常請求）。
"""
import pytest

import db

BAD = ["false", "0", ""]

CASCADE_URLS = [
    "/api/invoice-vouchers/NOPE/approve",
    "/api/payment-requests/NOPE/approve",
    "/api/quotations/NOPE/extra-expenses/1/approve",
    "/api/quotations/NOPE/extra-expenses/1/change-request/approve",
    "/api/completion-notes/NOPE/approve",
    "/api/contractor-vouchers/NOPE/approve",
    "/api/contractor-dispatches/1/approve",
    "/api/contractor-dispatches/1/completion/approve",
    "/api/shipping-notes/NOPE/approve",
]


@pytest.fixture()
def su(client, make_user):
    u, p = make_user(username="sb2_su", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _writes():
    c = db.get_db()
    try:
        return (c.execute("SELECT COUNT(*) FROM audit_log WHERE COALESCE(result, 'ok') = 'ok'").fetchone()[0], c.execute("SELECT COUNT(*) FROM notifications").fetchone()[0])
    finally:
        c.close()


@pytest.mark.parametrize("url", CASCADE_URLS)
def test_string_cascade_is_422_before_anything_is_touched(client, su, url):
    before = _writes()
    for bad in BAD:
        r = client.post(url, json={"cascade": bad}, headers=su)
        assert r.status_code == 422, (url, bad, r.status_code, r.text[:160])
    assert _writes() == before, "422 不可留下任何稽核／通知"


@pytest.mark.parametrize("url", CASCADE_URLS)
def test_real_booleans_and_missing_flag_still_reach_the_handler(client, su, url):
    for body in ({"cascade": False}, {"cascade": True}, {}, {"cascade": None}):
        r = client.post(url, json=body, headers=su)
        assert r.status_code != 422, (url, body, r.status_code, r.text[:160])      # 不存在的單據 ⇒ 404／400 等，但不是旗標錯誤


def test_remit_has_fee_flag():
    from fastapi import HTTPException
    from modules.subcontract import remit
    for bad in BAD:
        with pytest.raises(HTTPException) as e:
            remit.parse_remit({"actualAmount": 100, "hasFee": bad, "fee": 5}, 100)
        assert e.value.status_code == 422
        with pytest.raises(HTTPException):
            remit.parse_remit({"actualAmount": 100, "has_fee": bad, "fee": 5}, 100)
    assert remit.parse_remit({"actualAmount": 100, "hasFee": True, "fee": 5}, 100)["fee"] == 5
    assert remit.parse_remit({"actualAmount": 100, "hasFee": False, "fee": 5}, 100)["fee"] == 0
    assert remit.parse_remit({"actualAmount": 100, "has_fee": True, "fee": 7}, 100)["fee"] == 7
    assert remit.parse_remit({"actualAmount": 100, "fee": 5}, 100)["fee"] == 0, "沒帶旗標 ⇒ 沒有手續費"
