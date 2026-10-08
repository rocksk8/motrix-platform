# -*- coding: utf-8 -*-
"""採購單廠商收款帳戶不外洩（第 47 班，獨立審查 ab）：清單／我的申請／變更申請提議裡的 payeeAccount 只給末四碼，只有財務角色與最高管理者（has_finance_access）
拿得到完整值（完整帳號仍以出納端點為主、每次留稽核）；省略收款人欄位的草稿重存／變更申請不會洗掉已存的收款資料；銀行＋分行的長度上限放寬到前端的 101 字。"""
import json

import pytest

from modules.case.tests.test_queue_detail_real_forms_2026_10_07 import (  # noqa: F401  (world 是 fixture)
    DOCS, LINES, SENT, _approve_row, _db, world)
from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
FULL = "123456789012"


def _hdr(client, creds):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": creds[0], "password": creds[1]}).json()["token"]}


def _body(w, **extra):
    data = dict(DOCS["purchase_order"]["data"], applicant=w["user"], dept=w["dept"], req_date="2031-06-01")
    return {"kind": "purchase_order", "data": data, "lines": LINES, "departmentId": w["dept"], "expenseDate": "2031-06-01", **extra}


def _row(eid):
    c = _db()
    try:
        return dict(c.execute("SELECT * FROM case_extra_expenses WHERE id=?", (eid,)).fetchone())
    finally:
        c.close()


@pytest.fixture
def req(client, world, make_user):
    """非財務的申請人（admin，無出納權限）建立的採購單，帶完整帳號。"""
    creds = make_user(username="pam_req", role="admin", legacy_finance_flag=False)
    h = _hdr(client, creds)
    r = client.post(SENT, headers=h, json=_body(world, payeeType="vendor", payeeName="甲廠商", payeeBank="玉山銀行 台中分行", payeeAccount=FULL))
    assert r.status_code == 201, r.text
    return {"h": h, "id": r.json()["id"], "creds": creds}


def _list_row(client, h, eid):
    r = client.get(SENT, headers=h)
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["items"] if x["id"] == eid), r.text


def test_requester_non_finance_gets_last4_in_list_and_mine(client, world, req):
    row, text = _list_row(client, req["h"], req["id"])
    assert row["payeeAccount"] == "****9012" and FULL not in text
    mine = client.get("/api/extra-expenses/mine", headers=req["h"])
    assert mine.status_code == 200 and FULL not in mine.text
    assert next(x for x in mine.json() if x["id"] == req["id"])["payeeAccount"] == "****9012"
    assert row["payeeBank"] == "玉山銀行 台中分行", "銀行名稱不是機敏，照給"


def test_approver_in_the_chain_gets_last4(client, world, req, make_user):
    apr = make_user(username="pam_apr", role="admin", legacy_finance_flag=False)
    appr = {"requestedBy": "pam_req", "currentTier": 0, "tiers": [{"approvers": [{"username": "pam_apr", "displayName": "簽核人", "status": "pending"}]}]}
    c = _db()
    try:
        c.execute("UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?", (json.dumps(appr, ensure_ascii=False), req["id"]))
        c.commit()
    finally:
        c.close()
    row, text = _list_row(client, _hdr(client, apr), req["id"])
    assert FULL not in text and row.get("payeeAccount", "****9012") in ("****9012", "")


def test_finance_and_superadmin_get_the_full_value_in_the_list(client, world, req, make_user):
    fin = _hdr(client, make_user(username="pam_fin", role="finance"))
    for h in (fin, world["h"]):
        row, _ = _list_row(client, h, req["id"])
        assert row["payeeAccount"] == FULL


def test_change_request_proposal_is_masked_for_non_finance_and_whole_for_finance(client, world, req):
    _approve_row(req["id"])
    body = _body(world, payeeType="vendor", payeeName="甲廠商", payeeBank="玉山銀行 台中分行", payeeAccount="999988887777")
    assert client.put("%s/%d/change-request" % (SENT, req["id"]), headers=req["h"], json=body).status_code == 200
    row, text = _list_row(client, req["h"], req["id"])
    assert "999988887777" not in text and row["change"]["payeeAccount"] == "****7777"
    frow, _ = _list_row(client, world["h"], req["id"])
    assert frow["change"]["payeeAccount"] == "999988887777"


def test_change_request_that_omits_payee_fields_keeps_the_stored_payee(client, world, req):
    _approve_row(req["id"])
    body = _body(world)                                          # 完全沒帶 payee* 欄位
    assert "payeeAccount" not in body
    r = client.put("%s/%d/change-request" % (SENT, req["id"]), headers=req["h"], json=body)
    assert r.status_code == 200, r.text
    appr = {"requestedBy": "pam_req", "currentTier": 0, "tiers": [{"approvers": [{"username": world["user"], "displayName": "超管", "status": "pending"}]}]}
    c = _db()
    try:                                                         # 申請人沒有部門 ⇒ 送審會被擋；直接把變更申請放到『待審核』，再由超管核准
        c.execute("UPDATE case_extra_expenses SET change_status='待審核', change_approval_json=? WHERE id=?", (json.dumps(appr, ensure_ascii=False), req["id"]))
        c.commit()
    finally:
        c.close()
    a = client.post("%s/%d/change-request/approve" % (SENT, req["id"]), headers=world["h"])
    assert a.status_code == 200, a.text
    row = _row(req["id"])
    assert (row["payee_name"], row["payee_bank"], row["payee_account"], row["payee_type"]) == ("甲廠商", "玉山銀行 台中分行", FULL, "vendor")


def test_draft_patch_keeps_when_omitted_and_clears_when_sent_empty(client, world, req):
    base = _body(world)
    assert client.patch(SENT + "/%d" % req["id"], headers=req["h"], json=base).status_code == 200
    assert _row(req["id"])["payee_account"] == FULL, "沒帶＝保留"
    r = client.patch(SENT + "/%d" % req["id"], headers=req["h"], json={**base, "payeeType": "vendor", "payeeName": "", "payeeBank": "", "payeeAccount": ""})
    assert r.status_code == 200, r.text
    row = _row(req["id"])
    assert (row["payee_name"], row["payee_bank"], row["payee_account"]) == ("", "", ""), "明確送空值＝清除"


def test_bank_plus_branch_up_to_101_chars_is_accepted_and_a_masked_value_is_not_a_valid_account(client, world, req):
    ok = client.post(SENT, headers=req["h"], json=_body(world, payeeType="vendor", payeeName="甲", payeeBank=("銀" * 60) + " " + ("分" * 40), payeeAccount="123456"))
    assert ok.status_code == 201, ok.text
    bad = client.patch(SENT + "/%d" % req["id"], headers=req["h"], json=_body(world, payeeType="vendor", payeeName="甲", payeeBank="玉山銀行", payeeAccount="****9012"))
    assert bad.status_code == 400, "把清單的遮罩值原樣送回來不會悄悄覆蓋真帳號"
