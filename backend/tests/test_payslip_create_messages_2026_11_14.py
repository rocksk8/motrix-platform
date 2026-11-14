# -*- coding: utf-8 -*-
"""T86 U10：勞報單新增／修改填錯值時回白話 400（原本 int()／KeyError 變成 500）；沒有權限的 403 維持原語意。"""
import pytest


def _hdr(client, make_user, name, role="finance", modules=("payslip",)):
    u, p = make_user(username=name, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def _d(**kw):
    d = {"contractorName": "測試承攬人", "incomeType": "50", "grossAmount": 30000, "contractorNationality": "本國籍",
         "contractorHasUnionInsurance": False, "serviceContent": "測試", "slipDate": "2026-10-01"}
    d.update(kw)
    return d


def test_valid_body_still_creates(client, make_user):
    h = _hdr(client, make_user, "ps_msg_ok")
    r = client.post("/api/payslips", headers=h, json={"data": _d()})
    assert r.status_code == 201, r.text
    r2 = client.post("/api/payslips", headers=h, json={"data": _d(grossAmount="30000")})   # 數字字串照舊可用
    assert r2.status_code == 201, r2.text


@pytest.mark.parametrize("gross,expect", [("", "不是數字"), ("30,000", "不是數字"), (None, "不是數字"), ("三萬", "不是數字")])
def test_bad_gross_is_plain_400_not_500(client, make_user, gross, expect):
    h = _hdr(client, make_user, "ps_msg_g%d" % abs(hash(str(gross)) % 997))
    r = client.post("/api/payslips", headers=h, json={"data": _d(grossAmount=gross)})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "給付總額" in detail and expect in detail and "Traceback" not in detail


def test_unknown_income_type_is_plain_400(client, make_user):
    h = _hdr(client, make_user, "ps_msg_inc")
    r = client.post("/api/payslips", headers=h, json={"data": _d(incomeType="ZZ")})
    assert r.status_code == 400, r.text
    assert "所得類別" in r.json()["detail"] and "重新選擇" in r.json()["detail"]


def test_update_path_has_the_same_checks(client, make_user):
    h = _hdr(client, make_user, "ps_msg_upd")
    c = client.post("/api/payslips", headers=h, json={"data": _d()})
    assert c.status_code == 201, c.text
    no = c.json()["slip_no"]
    r = client.put("/api/payslips/%s" % no, headers=h, json={"data": _d(incomeType="ZZ")})
    assert r.status_code == 400, r.text
    assert "所得類別" in r.json()["detail"]
    r = client.put("/api/payslips/%s" % no, headers=h, json={"data": _d(grossAmount="1,000")})
    assert r.status_code == 400 and "給付總額" in r.json()["detail"], r.text


def test_failed_create_does_not_burn_a_slip_number_or_lock(client, make_user):
    h = _hdr(client, make_user, "ps_msg_lock")
    bad = client.post("/api/payslips", headers=h, json={"data": _d(grossAmount="x")})
    assert bad.status_code == 400
    ok = client.post("/api/payslips", headers=h, json={"data": _d()})
    assert ok.status_code == 201, ok.text      # 寫鎖沒留著


def test_user_without_create_capability_still_gets_403_with_the_missing_permission_named(client, make_user):
    h = _hdr(client, make_user, "ps_msg_nocap", modules=())
    r = client.post("/api/payslips", headers=h, json={"data": _d()})
    assert r.status_code == 403
    assert "權限不足" in r.json()["detail"]
