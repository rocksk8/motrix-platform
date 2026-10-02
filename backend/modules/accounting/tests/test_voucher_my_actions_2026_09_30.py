# -*- coding: utf-8 -*-
"""W1 R3：GET /api/vouchers/{id} 帶 `my_actions`——這個人現在可以按哪些鍵、不能按的原因（判準與動作端點同一套，前端不再自己判）。"""
import pytest

import db

_N = [0]


def _login(client, make_user, name, role="staff"):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = ["cashier", "finance"]
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _draft(client, h):
    r = client.post("/api/vouchers", headers=h, json={"voucher_date": "2190-05-10", "summary": "MA", "lines": [
        {"account_code": "1113", "summary": "x", "debit": 10, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 10}]})
    return r.json()["id"]


def _acts(client, h, vid):
    return client.get("/api/vouchers/%d" % vid, headers=h).json()["my_actions"]


def test_final_slot_is_blocked_for_finance_with_the_sentence_and_open_for_superadmin(client, make_user):
    _, fin = _login(client, make_user, "ma_fin")
    _, sup = _login(client, make_user, "ma_sup", role="superadmin")
    vid = _draft(client, fin)
    assert _acts(client, fin, vid) == {"void": {"allowed": True, "reason": ""}}                    # 草稿：只有作廢（狀態不對的鍵不列）
    client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
    a = _acts(client, fin, vid)
    assert a["approve"]["allowed"] is True and a["send_back"]["allowed"] is True                    # 第一層：財務可簽
    client.post("/api/vouchers/%d/approve" % vid, headers=fin, json={})
    a = _acts(client, fin, vid)
    assert a["approve"]["allowed"] is False and "最高管理者" in a["approve"]["reason"]              # 最終層：財務不可簽，原因是一句人話
    assert _acts(client, sup, vid)["approve"] == {"allowed": True, "reason": ""}


def test_void_rules_are_reported_before_the_click(client, make_user):
    _, fin = _login(client, make_user, "ma_fin2")
    _, sup = _login(client, make_user, "ma_sup2", role="superadmin")
    vid = _draft(client, fin)
    for who, act in ((fin, "submit"), (fin, "approve"), (sup, "approve"), (fin, "post")):
        assert client.post("/api/vouchers/%d/%s" % (vid, act), headers=who, json={}).status_code == 200
    assert _acts(client, fin, vid)["void"]["allowed"] is False and "最高管理者" in _acts(client, fin, vid)["void"]["reason"]
    assert _acts(client, sup, vid)["void"]["allowed"] is True
    c = db.get_db()
    try:
        c.execute("UPDATE vouchers_all SET kind='auto' WHERE id=?", (vid,))
        c.commit()
    finally:
        c.close()
    assert _acts(client, sup, vid)["void"]["allowed"] is False and "來源單據" in _acts(client, sup, vid)["void"]["reason"]      # 系統產生的：連最高管理者也不行


def test_configured_flow_non_approver_is_told_who_the_approver_is(client, make_user):
    from helpers import _set_setting
    fu, fin = _login(client, make_user, "ma_fin3")
    mu, mgr = _login(client, make_user, "ma_mgr")
    _set_setting("voucher_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"username": mu, "displayName": "王經理"}]}]})
    try:
        vid = _draft(client, fin)
        client.post("/api/vouchers/%d/submit" % vid, headers=fin, json={})
        a = _acts(client, fin, vid)
        assert a["approve"]["allowed"] is False and "王經理" in a["approve"]["reason"]
        assert _acts(client, mgr, vid)["approve"]["allowed"] is True
    finally:
        c = db.get_db()
        c.execute("DELETE FROM system_settings WHERE key='voucher_approval_flow'")
        c.commit()
        c.close()
