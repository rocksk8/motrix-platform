# -*- coding: utf-8 -*-
"""會計規定（2026-09-30，B 類）：這幾個動作只有最高管理者（會計主管）能直接做，一般財務人員一律 403 並說明：
已過帳傳票的作廢、期初批次撤銷、角色→科目對應、科目報表列／屬性、報表列設定、取消扣繳繳庫登記。
最高管理者不是被擋（可能因為資料不存在而 404／400／409，但不是 403）。"""
import pytest

import db
from modules.accounting.ledger import features as F


def _login(client, make_user, name, role="staff"):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = ["cashier", "finance"]
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def both(client, make_user):
    c = db.get_db()
    F.set_flag(c, "withholding", True)
    c.commit()
    c.close()
    return _login(client, make_user, "bo_fin"), _login(client, make_user, "bo_sup", role="superadmin")


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/ledger/opening/999999/undo", {}),
    ("PUT", "/api/ledger/roles", {"role": "CASH", "account_code": "1113"}),
    ("PATCH", "/api/ledger/accounts/1113", {"note": "x"}),
    ("PATCH", "/api/ledger/fs-lines/BS_CASH", {"note": "x"}),
    ("POST", "/api/ledger/withholding/unremit", {"ids": [1], "reason": "測試原因"}),
])
def test_finance_is_refused_and_superadmin_is_not(client, both, method, path, body):
    fin, sup = both
    r = client.request(method, path, headers=fin, json=body)
    assert r.status_code == 403 and "最高管理者" in r.json()["detail"], (path, r.status_code, r.text[:120])
    assert client.request(method, path, headers=sup, json=body).status_code != 403, path


def test_void_of_a_posted_voucher_is_superadmin_only_while_unposted_stays_open(client, both):
    fin, sup = both
    def mk():
        r = client.post("/api/vouchers", headers=fin, json={"voucher_date": "2187-05-10", "summary": "B", "lines": [
            {"account_code": "1113", "summary": "x", "debit": 10, "credit": 0}, {"account_code": "4111", "summary": "x", "debit": 0, "credit": 10}]})
        return r.json()["id"]
    draft = mk()
    assert client.post("/api/vouchers/%d/void" % draft, headers=fin, json={"reason": "草稿作廢"}).status_code == 200      # 未過帳：照舊
    posted = mk()
    for who, act in ((fin, "submit"), (fin, "approve"), (sup, "approve"), (fin, "post")):
        assert client.post("/api/vouchers/%d/%s" % (posted, act), headers=who, json={}).status_code == 200
    r = client.post("/api/vouchers/%d/void" % posted, headers=fin, json={"reason": "財務想作廢"})
    assert r.status_code == 403 and "已過帳" in r.json()["detail"]
    assert client.post("/api/vouchers/%d/void" % posted, headers=sup, json={"reason": "會計主管作廢"}).status_code == 200
