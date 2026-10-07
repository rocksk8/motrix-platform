# -*- coding: utf-8 -*-
"""第 46 班 P3：勞報單 ⇄ 承攬派發雙向連結（payroll migration 4 的 `payslip_dispatch_links`；提供者 `payslip.dispatch_links`／`dispatch.brief`）。
🔴 派發頁只看到單號、狀態、受領人姓名、開單日期（無金額、無身分資料）；建立／解除＝最高管理者＋勞報單模組。"""
import json

import pytest

from core import source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login, _payload

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="派發在外包工班（M04）")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
Q = "MQ-PL46-001"
_N = __import__("itertools").count(1)


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _slip(no, status="草稿", net=98765, data=None):
    d = {"slipNo": no, "contractorName": "受領甲", "idNumber": "A123456789", "bankAccountNumber": "28881234567890"}
    d.update(data or {})
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method,"
       " slip_date, status, tax_rules_version, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, None, "受領甲", "9A", 100000, 1235, 0, net, "匯款", "2031-06-01", status, "2031", json.dumps(d, ensure_ascii=False), "2031-06-01T00:00:00", "2031-06-01T00:00:00"))


def _dispatch(client, h):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (Q, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商PL%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": Q, "vendor_id": r.json()["id"], "status": "completed", "items_json": [{"description": "品項", "qty": 1, "unit": "式", "unitPrice": 5000, "amount": 5000}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _su(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    return _auth(_login(client, u, p))


def _staff(client, make_user, name):
    u, p = make_user(username=name, role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    return _auth(_login(client, u, p))


def test_link_from_payslip_side_lists_dispatch_brief_and_blocks_duplicates(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    _slip("PS-203107-001")
    r = client.post("/api/payslips/PS-203107-001/dispatch-links", headers=sa, json={"dispatchId": did, "note": "5 月工"})
    assert r.status_code == 201, r.text
    assert client.post("/api/payslips/PS-203107-001/dispatch-links", headers=sa, json={"dispatchId": did}).status_code == 409
    got = client.get("/api/payslips/PS-203107-001/dispatch-links", headers=sa).json()
    assert len(got["items"]) == 1 and got["items"][0]["dispatch"]["quoteNo"] == Q and got["items"][0]["dispatch"]["id"] == did and got["notice"] == ""
    assert client.post("/api/payslips/PS-203107-001/dispatch-links", headers=sa, json={"dispatchId": 99999}).status_code == 404
    assert client.post("/api/payslips/PS-203107-001/dispatch-links", headers=sa, json={"dispatchId": "x"}).status_code == 400
    assert client.post("/api/payslips/PS-NOPE/dispatch-links", headers=sa, json={"dispatchId": did}).status_code == 404


def test_one_dispatch_many_payslips_and_one_payslip_many_dispatches(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    d1, d2 = _dispatch(client, sa), _dispatch(client, sa)
    for no in ("PS-203107-011", "PS-203107-012"):
        _slip(no)
    for no, did in (("PS-203107-011", d1), ("PS-203107-012", d1), ("PS-203107-011", d2)):
        assert client.post("/api/payslips/%s/dispatch-links" % no, headers=sa, json={"dispatchId": did}).status_code == 201
    on_d1 = client.get("/api/contractor-dispatches/%s/payslip-links" % d1, headers=sa).json()["items"]
    assert sorted(i["slipNo"] for i in on_d1) == ["PS-203107-011", "PS-203107-012"]
    assert len(client.get("/api/payslips/PS-203107-011/dispatch-links", headers=sa).json()["items"]) == 2


def test_dispatch_side_shows_no_money_or_identity_and_staff_cannot_edit(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    staff = _staff(client, make_user, "pl46_staff")
    did = _dispatch(client, sa)
    _slip("PS-203107-021", status="已核准")
    client.post("/api/payslips/PS-203107-021/dispatch-links", headers=sa, json={"dispatchId": did})
    r = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=staff)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["canOpen"] is False and body["canEdit"] is False
    blob = json.dumps(body, ensure_ascii=False)
    for secret in ("98765", "98,765", "A123456789", "28881234567890", "100000"):
        assert secret not in blob, secret
    it = body["items"][0]
    assert it["slipNo"] == "PS-203107-021" and it["status"] == "已核准" and it["contractorName"] == "受領甲" and it["slipDate"] == "2031-06-01"
    assert set(it) <= {"slipNo", "dispatchId", "status", "contractorName", "slipDate", "voided", "note", "linkedBy", "linkedAt"}
    assert client.post("/api/contractor-dispatches/%s/payslip-links" % did, headers=staff, json={"slipNo": "PS-203107-021"}).status_code == 403
    assert client.delete("/api/contractor-dispatches/%s/payslip-links/PS-203107-021" % did, headers=staff).status_code == 403
    assert len(_q("SELECT * FROM payslip_dispatch_links")) == 1


def test_dispatch_side_link_and_unlink_by_superadmin(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    _slip("PS-203107-031")
    r = client.post("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa, json={"slipNo": "PS-203107-031"})
    assert r.status_code == 201, r.text
    body = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa).json()
    assert body["canOpen"] is True and body["canEdit"] is True and len(body["items"]) == 1
    assert client.delete("/api/contractor-dispatches/%s/payslip-links/PS-203107-031" % did, headers=sa).status_code == 200
    assert client.delete("/api/contractor-dispatches/%s/payslip-links/PS-203107-031" % did, headers=sa).status_code == 404
    assert client.get("/api/contractor-dispatches/99999/payslip-links", headers=sa).status_code == 404


def test_unlink_rules_paid_voided_and_cannot_link_a_voided_slip(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    _slip("PS-203107-041", status="已付款")
    _slip("PS-203107-042", status="已核准")
    _slip("PS-203107-043", status="已作廢")
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES ('PS-203107-041', ?, 't', '2031-06-01')", (did,))
    assert client.delete("/api/payslips/PS-203107-041/dispatch-links/%s" % did, headers=sa).status_code == 409, "已付款不可解除"
    _slip("PS-203107-044", status="已付款", data={"paid_via_remit": "PV-1"})
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES ('PS-203107-044', ?, 't', '2031-06-01')", (did,))
    assert client.delete("/api/payslips/PS-203107-044/dispatch-links/%s" % did, headers=sa).status_code == 409, "經匯款單付款也不可解除"
    assert client.post("/api/payslips/PS-203107-043/dispatch-links", headers=sa, json={"dispatchId": did}).status_code == 409, "作廢單不能新關聯"
    assert client.post("/api/payslips/PS-203107-042/dispatch-links", headers=sa, json={"dispatchId": did}).status_code == 201
    _x("UPDATE payslips SET status='已作廢' WHERE slip_no='PS-203107-042'")
    items = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa).json()["items"]
    assert {i["slipNo"]: i["voided"] for i in items}["PS-203107-042"] is True, "作廢 ⇒ 連結保留並標已作廢"
    assert client.delete("/api/payslips/PS-203107-042/dispatch-links/%s" % did, headers=sa).status_code == 200


def test_non_superadmin_cannot_use_payslip_side_endpoints(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    staff = _staff(client, make_user, "pl46_staff")
    did = _dispatch(client, sa)
    _slip("PS-203107-051")
    assert client.get("/api/payslips/PS-203107-051/dispatch-links", headers=staff).status_code in (401, 403)
    assert client.post("/api/payslips/PS-203107-051/dispatch-links", headers=staff, json={"dispatchId": did}).status_code in (401, 403)
    assert not _q("SELECT * FROM payslip_dispatch_links")


def test_create_payslip_with_source_dispatch_links_in_one_transaction(client, make_user):
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    body = _payload()
    body["data"]["dispatchId"] = did
    r = client.post("/api/payslips", json=body, headers=sa)
    assert r.status_code == 201, r.text
    no = r.json()["slip_no"]
    assert [l["slip_no"] for l in _q("SELECT slip_no FROM payslip_dispatch_links WHERE dispatch_id=?", (did,))] == [no]
    assert "dispatchId" not in json.loads(_q("SELECT data_json FROM payslips WHERE slip_no=?", (no,))[0]["data_json"]), "不存進單據 data"
    before = len(_q("SELECT * FROM payslips"))
    bad = _payload()
    bad["data"]["dispatchId"] = 99999
    assert client.post("/api/payslips", json=bad, headers=sa).status_code == 400
    assert len(_q("SELECT * FROM payslips")) == before, "查無派發 ⇒ 不建勞報單"


def test_payroll_absent_is_said_not_silently_empty(client, make_user, monkeypatch):
    from core import registry
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda name: None if name == "payslip.dispatch_links" else real(name))
    body = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa).json()
    assert body["available"] is False and "薪資獎金模組未安裝" in body["notice"] and body["items"] == []
    assert client.post("/api/contractor-dispatches/%s/payslip-links" % did, headers=sa, json={"slipNo": "PS-X"}).status_code == 409


def test_dispatch_links_get_applies_the_per_case_guard(client, make_user):
    """複核 L1：派發頁勞報單區塊與其他每案端點同一道案件層守門——看不到該案的人 ⇒ 擋下（不洩漏連結）。"""
    sa = _su(client, make_user, "pl46_sa")
    did = _dispatch(client, sa)
    _slip("PS-203107-061")
    client.post("/api/payslips/PS-203107-061/dispatch-links", headers=sa, json={"dispatchId": did})
    u, p = make_user(username="pl46_outsider", role="user", modules=["contractor_list"], legacy_finance_flag=False)
    out = _auth(_login(client, u, p))
    r = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=out)
    assert r.status_code in (403, 404), r.text
    assert "PS-203107-061" not in r.text
