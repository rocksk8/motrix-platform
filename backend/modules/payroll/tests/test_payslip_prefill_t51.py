# -*- coding: utf-8 -*-
"""第 51 班：勞報單表單『預設選取已派工、一鍵帶入』的後端部分（IP-115 加法）。

- `GET /api/payslip-person-dispatches?contractor_id=`：多回 scope／itemsSummary／projectName／customerName／caseVisible／linkedForThisPerson；
  不含草稿與已取消；案件名稱只給通過案件讀取守門的人；仍不含金額。
- `GET /api/payslip-person-dispatches/by-dispatch?dispatch_id=`：派發名單裡的外包名冊人員（id、姓名），供 ?dispatchId= 預選受領人。
"""
import itertools

import pytest

from core import source_tree
from modules.payroll.tests.test_payslip_person_link_t48 import _archive_tmp, _auth, _create, _dispatch, _login, _person, _q, _su, _x   # noqa: F401

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="派發在外包工班（M04）")

_N = itertools.count(1)


def _staff_payslip_only(client, make_user, name):
    u, p = make_user(username=name, role="user", modules=["payslip"], legacy_finance_flag=False)
    return _auth(_login(client, u, p))


def _list(client, h, pid):
    r = client.get("/api/payslip-person-dispatches?contractor_id=%d" % pid, headers=h)
    assert r.status_code == 200, r.text
    return {i["id"]: i for i in r.json()["items"]}


def test_items_carry_case_name_scope_and_item_summary_and_still_no_money(client, make_user):
    h = _su(client, make_user, "pf51_su")
    pid = _person("王小明")
    q = "MQ-PF51-%d" % next(_N)
    did = _dispatch(client, h, [{"id": pid, "name": "王小明", "amount": 7777, "note": "秘"}], quote=q)
    _x("UPDATE contractor_dispatches SET scope=?, items_json=?, dispatch_date=? WHERE id=?",
       ("管線施工", '[{"description":"拉線"},{"description":"打洞"},{"description":""},{"description":"收尾"},{"description":"第四個"}]', "2031-03-08", did))
    it = _list(client, h, pid)[did]
    assert (it["projectName"], it["customerName"], it["caseVisible"]) == ("案", "客", True)
    assert it["scope"] == "管線施工" and it["itemsSummary"] == "拉線、打洞、收尾" and it["dispatchDate"] == "2031-03-08"
    assert it["linkedForThisPerson"] is False
    assert "7777" not in str(it) and "秘" not in str(it), "不含金額／備註"


def test_case_names_only_for_users_who_pass_the_case_guard(client, make_user):
    h = _su(client, make_user, "pf51_su2")
    pid = _person("李四")
    did = _dispatch(client, h, [{"id": pid, "name": "李四", "amount": 1, "note": ""}], quote="MQ-PF51-%d" % next(_N))
    hs = _staff_payslip_only(client, make_user, "pf51_staff")          # 有勞報單模組，但不是案件成員、沒有 case_manage
    it = _list(client, hs, pid)[did]
    assert it["caseVisible"] is False and it["projectName"] == "" and it["customerName"] == "", it
    assert it["docCode"] == "" or isinstance(it["docCode"], str)       # 單號照給（畫面只顯示單號）


def test_draft_and_cancelled_dispatches_are_not_listed(client, make_user):
    h = _su(client, make_user, "pf51_su3")
    pid = _person("陳五")
    ids = {st: _dispatch(client, h, [{"id": pid, "name": "陳五", "amount": 1, "note": ""}], quote="MQ-PF51-%d" % next(_N)) for st in ("draft", "cancelled", "completed", "sent")}
    for st, did in ids.items():
        _x("UPDATE contractor_dispatches SET status=? WHERE id=?", (st, did))
    listed = _list(client, h, pid)
    assert set(listed) == {ids["completed"], ids["sent"]}, listed


def test_linked_for_this_person_ignores_void_payslips_and_other_people(client, make_user):
    h = _su(client, make_user, "pf51_su4")
    a, b = _person("甲甲"), _person("乙乙")
    q = "MQ-PF51-%d" % next(_N)
    did = _dispatch(client, h, [{"id": a, "name": "甲甲", "amount": 1, "note": ""}, {"id": b, "name": "乙乙", "amount": 1, "note": ""}], quote=q)
    r = _create(client, h, a, "甲甲", dispatch_ids=[did])
    assert r.status_code in (200, 201), r.text
    slip = r.json()["slip_no"]
    assert _list(client, h, a)[did]["linkedForThisPerson"] is True
    assert _list(client, h, b)[did]["linkedForThisPerson"] is False, "乙乙沒有連過"
    _x("UPDATE payslips SET status='已作廢' WHERE slip_no=?", (slip,))
    assert _list(client, h, a)[did]["linkedForThisPerson"] is False, "作廢的勞報單不算已連結"


def test_by_dispatch_returns_the_roster_persons_of_that_dispatch(client, make_user):
    h = _su(client, make_user, "pf51_su5")
    a, b = _person("單人"), _person("雙人")
    d1 = _dispatch(client, h, [{"id": a, "name": "單人", "amount": 9, "note": ""}], quote="MQ-PF51-%d" % next(_N))
    d2 = _dispatch(client, h, [{"id": a, "name": "單人", "amount": 9, "note": ""}, {"id": b, "name": "雙人", "amount": 9, "note": ""}], quote="MQ-PF51-%d" % next(_N))
    d0 = _dispatch(client, h, [], quote="MQ-PF51-%d" % next(_N))
    get = lambda did: client.get("/api/payslip-person-dispatches/by-dispatch?dispatch_id=%d" % did, headers=h)
    assert get(d1).json()["persons"] == [{"id": a, "name": "單人"}] and "9" not in str(get(d1).json()["persons"])
    assert [p["id"] for p in get(d2).json()["persons"]] == [a, b]
    assert get(d0).json()["persons"] == [] and get(999999).json()["persons"] == []
    assert client.get("/api/payslip-person-dispatches/by-dispatch?dispatch_id=%d" % d1).status_code in (401, 403)
