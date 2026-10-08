# -*- coding: utf-8 -*-
"""第 48 班：勞報單人員 ⇄ 派工連動（設計 docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md）。

① 建立勞報單帶 dispatchIds：同一交易連結多張派發；任一派發的人員名單沒有此人 ⇒ 400 且整張不建 ② 派發頁 byPerson：只列已確認對應、
扣掉手動連結、無金額 ③ payroll migration 5：唯一對應才回填 unconfirmed、同名多位不回填、不建任何連結、冪等 ④ confirm-contractor 權限／狀態
⑤ PUT 不洗掉舊單的推測對應；人工改選視為確認 ⑥ person-dispatches 端點。
"""
import importlib
import itertools
import json

import pytest

from core import source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="派發在外包工班（M04）")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
Q = "MQ-PP48-001"
_N = itertools.count(1)


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _person(name):
    return _x("INSERT INTO contractors (name, id_number, active, created_at, updated_at) VALUES (?,?,1,'2031-01-01','2031-01-01')", (name, "A123456789"))


def _dispatch(client, h, personnel):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (Q, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "", "", "[]"))
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商PP%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": Q, "vendor_id": r.json()["id"], "status": "completed", "personnel_json": personnel,
            "items_json": [{"description": "品項", "qty": 1, "unit": "式", "unitPrice": 500}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _su(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    return _auth(_login(client, u, p))


def _staff(client, make_user, name):
    u, p = make_user(username=name, role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    return _auth(_login(client, u, p))


def _create(client, h, cid, name, dispatch_ids=None, **extra):
    data = {"contractorName": name, "incomeType": "9A", "grossAmount": 35000, "contractorNationality": "本國籍",
            "contractorHasUnionInsurance": False, "slipDate": "2031-06-01"}
    if dispatch_ids is not None:
        data["dispatchIds"] = dispatch_ids
    data.update(extra)
    return client.post("/api/payslips", headers=h, json={"contractor_id": cid, "data": data})


def _old_slip(no, name, cid=None, match=""):
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method,"
       " slip_date, status, tax_rules_version, data_json, created_at, updated_at, contractor_match) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, cid, name, "9A", 100000, 1235, 0, 98765, "匯款", "2031-06-01", "已核准", "2031", json.dumps({"slipNo": no, "contractorName": name}),
        "2031-06-01T00:00:00", "2031-06-01T00:00:00", match))


def test_create_with_dispatch_ids_links_all_in_one_transaction(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    cid = _person("甲乙")
    d1 = _dispatch(client, sa, [{"id": cid, "name": "甲乙", "amount": 1, "note": ""}])
    d2 = _dispatch(client, sa, [{"id": 999, "name": "他人"}, {"id": cid, "name": "甲乙", "amount": 2, "note": ""}])
    r = _create(client, sa, cid, "甲乙", [d1, d2, d1])
    assert r.status_code == 201, r.text
    no = r.json()["slip_no"]
    rows = _q("SELECT dispatch_id FROM payslip_dispatch_links WHERE slip_no=? ORDER BY dispatch_id", (no,))
    assert [x["dispatch_id"] for x in rows] == sorted([d1, d2])
    assert _q("SELECT contractor_id, contractor_match FROM payslips WHERE slip_no=?", (no,)) == [{"contractor_id": cid, "contractor_match": ""}]


def test_dispatch_without_this_person_rejects_and_creates_nothing(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    cid, other = _person("丙"), _person("丁")
    good = _dispatch(client, sa, [{"id": cid, "name": "丙"}])
    bad = _dispatch(client, sa, [{"id": other, "name": "丁"}])
    before = len(_q("SELECT 1 FROM payslips"))
    r = _create(client, sa, cid, "丙", [good, bad])
    assert r.status_code == 400 and "沒有這位受領人" in r.text, r.text
    assert len(_q("SELECT 1 FROM payslips")) == before and _q("SELECT 1 FROM payslip_dispatch_links") == []
    assert _create(client, sa, None, "丙", [good]).status_code == 400            # 沒選名冊人員不能依人連結
    assert _create(client, sa, cid, "丙", [99999]).status_code == 400
    assert _create(client, sa, cid, "丙", "x").status_code == 400
    assert _create(client, sa, cid, "丙", [good]).status_code == 201


def test_dispatch_tab_lists_confirmed_payslips_of_the_same_person_without_money(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    staff = _staff(client, make_user, "pp_staff")
    cid, someone = _person("戊"), _person("他人")
    did = _dispatch(client, sa, [{"id": cid, "name": "戊"}])
    _old_slip("PS-203106-501", "戊", cid, "")              # 已確認、沒手動連結 ⇒ 列出
    _old_slip("PS-203106-502", "戊", cid, "")              # 已確認、已手動連結 ⇒ 不重複列
    _old_slip("PS-203106-503", "戊", cid, "unconfirmed")   # 名稱推測 ⇒ 不列，只算張數
    _old_slip("PS-203106-504", "他人", someone, "")     # 別人
    client.post("/api/payslips/PS-203106-502/dispatch-links", headers=sa, json={"dispatchId": did})
    for h in (sa, staff):
        body = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=h).json()
        assert [x["slipNo"] for x in body["byPerson"]] == ["PS-203106-501"], body
        assert body["unconfirmedCount"] == 1 and [x["slipNo"] for x in body["items"]] == ["PS-203106-502"]
        blob = json.dumps(body, ensure_ascii=False)
        for secret in ("98765", "98,765", "A123456789", "100000", "1235"):
            assert secret not in blob, secret
        assert set(body["byPerson"][0]) <= {"slipNo", "status", "contractorName", "slipDate", "voided"}
    assert client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=staff).json()["canEdit"] is False


def test_migration_backfills_only_unique_name_matches_and_never_links(client, make_user):
    m = importlib.import_module("modules.payroll.migrations.0005_payslip_person_link")
    only, keep = _person("唯一"), _person("保留")
    _person("同名")
    _person("同名")
    _old_slip("PS-203106-601", "唯一")                 # contractor_id NULL、名稱唯一 ⇒ 回填
    _old_slip("PS-203106-602", " 唯一 ")               # 前後空白
    _old_slip("PS-203106-603", "同名")                 # 同名多位 ⇒ 不動
    _old_slip("PS-203106-604", "查無此人")             # 對不到 ⇒ 不動
    _old_slip("PS-203106-605", "唯一", keep, "")  # 已有 contractor_id ⇒ 完全不碰
    import db
    c = db.get_db()
    try:
        assert m.up(c) is None
        first = [dict(r) for r in c.execute("SELECT slip_no, contractor_id, contractor_match FROM payslips WHERE slip_no LIKE 'PS-203106-6%' ORDER BY slip_no")]
        assert m.up(c) is None                         # 冪等
        second = [dict(r) for r in c.execute("SELECT slip_no, contractor_id, contractor_match FROM payslips WHERE slip_no LIKE 'PS-203106-6%' ORDER BY slip_no")]
        c.commit()
    finally:
        c.close()
    assert first == second
    got = {r["slip_no"]: (r["contractor_id"], r["contractor_match"]) for r in first}
    assert got["PS-203106-601"] == (only, "unconfirmed") and got["PS-203106-602"] == (only, "unconfirmed")
    assert got["PS-203106-603"] == (None, "") and got["PS-203106-604"] == (None, "")
    assert got["PS-203106-605"] == (keep, "")
    assert _q("SELECT 1 FROM payslip_dispatch_links") == [], "舊單不可被靜默連到派發"


def test_confirm_contractor_permissions_and_state(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    staff = _staff(client, make_user, "pp_staff")
    cid = _person("己")
    _old_slip("PS-203106-701", "己", cid, "unconfirmed")
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=staff, json={}).status_code == 403
    assert client.post("/api/payslips/PS-NOPE/confirm-contractor", headers=sa, json={}).status_code == 404
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={"contractorId": 987654}).status_code == 404
    r = client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={})
    assert r.status_code == 200 and r.json()["contractorId"] == cid
    assert _q("SELECT contractor_match FROM payslips WHERE slip_no='PS-203106-701'")[0]["contractor_match"] == ""
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={}).status_code == 409


def test_put_keeps_guessed_mapping_and_manual_change_confirms(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    a, b = _person("庚"), _person("辛")
    r = _create(client, sa, a, "庚")
    no = r.json()["slip_no"]
    _x("UPDATE payslips SET contractor_match='unconfirmed' WHERE slip_no=?", (no,))
    body = {"data": {"contractorName": "庚", "incomeType": "9A", "grossAmount": 36000, "contractorNationality": "本國籍",
                     "contractorHasUnionInsurance": False, "slipDate": "2031-06-01"}}
    assert client.put("/api/payslips/" + no, headers=sa, json=body).status_code == 200      # 表單沒帶 id 重存
    assert _q("SELECT contractor_id, contractor_match FROM payslips WHERE slip_no=?", (no,)) == [{"contractor_id": a, "contractor_match": "unconfirmed"}]
    assert client.put("/api/payslips/" + no, headers=sa, json=dict(body, contractor_id=b)).status_code == 200
    assert _q("SELECT contractor_id, contractor_match FROM payslips WHERE slip_no=?", (no,)) == [{"contractor_id": b, "contractor_match": ""}]


def test_person_dispatches_endpoint(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    staff = _staff(client, make_user, "pp_staff")
    cid, other = _person("壬"), _person("癸")
    d1 = _dispatch(client, sa, [{"id": cid, "name": "壬", "amount": 12345}])
    _dispatch(client, sa, [{"id": other, "name": "癸"}])
    r = client.get("/api/payslip-person-dispatches?contractor_id=%d" % cid, headers=sa)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["id"] for i in items] == [d1] and set(items[0]) == {"id", "docCode", "quoteNo", "status", "vendorName", "dispatchDate"}
    assert "12345" not in r.text
    assert client.get("/api/payslip-person-dispatches?contractor_id=%d" % cid, headers=staff).status_code == 403
