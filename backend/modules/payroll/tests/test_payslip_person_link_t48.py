# -*- coding: utf-8 -*-
"""第 48 班：勞報單人員 ⇄ 派工連動（設計 docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md；獨立稽核 #3 修補後）。

① 建立勞報單帶 dispatchIds／單一 dispatchId：同一交易連結；任一派發的人員名單沒有此人 ⇒ 400 且整張不建
② 派發頁 byPerson：只列已確認對應、只限同一案件的派發、扣掉手動連結、無金額；待確認張數只給最高管理者（API 層）
③ payroll migration 5：唯一對應只寫 contractor_guess_id（**不碰金流用的 contractor_id**）、同名多位不回填、已作廢不回填、不建連結、冪等、名冊表不在回 None
④ confirm-contractor：權限、已簽回／已付款／已作廢不給確認、條件式升格 ⑤ PUT：同名重存留推測、改名清推測、人工選名冊＝確認 ⑥ person-dispatches 端點
"""
import importlib
import inspect
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


def _dispatch(client, h, personnel, quote=Q):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (quote, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "", "", "[]"))
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商PP%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": quote, "vendor_id": r.json()["id"], "status": "completed", "personnel_json": personnel,
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


def _old_slip(no, name, cid=None, guess=None, status="已核准"):
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method,"
       " slip_date, status, tax_rules_version, data_json, created_at, updated_at, contractor_guess_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, cid, name, "9A", 100000, 1235, 0, 98765, "匯款", "2031-06-01", status, "2031", json.dumps({"slipNo": no, "contractorName": name}),
        "2031-06-01T00:00:00", "2031-06-01T00:00:00", guess))


def _link(no, did):
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES (?,?,'t','2031-06-01')", (no, did))


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
    assert _q("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no=?", (no,)) == [{"contractor_id": cid, "contractor_guess_id": None}]


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


def test_single_dispatch_id_path_enforces_membership_too(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    cid, other = _person("子"), _person("丑")
    good = _dispatch(client, sa, [{"id": cid, "name": "子"}])
    bad = _dispatch(client, sa, [{"id": other, "name": "丑"}])
    n = len(_q("SELECT 1 FROM payslips"))
    r = _create(client, sa, cid, "子", None, dispatchId=bad)
    assert r.status_code == 400 and "沒有這位受領人" in r.text and len(_q("SELECT 1 FROM payslips")) == n
    assert _create(client, sa, cid, "子", None, dispatchId=good).status_code == 201


def test_dispatch_tab_lists_only_same_case_confirmed_slips_without_money(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    staff = _staff(client, make_user, "pp_staff")
    cid, someone = _person("戊"), _person("他人")
    did = _dispatch(client, sa, [{"id": cid, "name": "戊"}])
    d2 = _dispatch(client, sa, [{"id": cid, "name": "戊"}])                              # 同一案件的另一張派發
    d_other_case = _dispatch(client, sa, [{"id": cid, "name": "戊"}], quote="MQ-PP48-OTHER")
    _old_slip("PS-203106-501", "戊", cid)                 # 已確認、連到同案另一張派發 ⇒ 列出
    _old_slip("PS-203106-502", "戊", cid)                 # 已確認、已手動連結到本派發 ⇒ 不重複列
    _old_slip("PS-203106-503", "戊", None, cid)           # 名稱推測 ⇒ 不列，只算張數（僅最高管理者看得到）
    _old_slip("PS-203106-504", "他人", someone)           # 別人
    _old_slip("PS-203106-505", "戊", cid)                 # 已確認但只連到『別案』的派發 ⇒ 不跨案揭露
    _old_slip("PS-203106-506", "戊", cid)                 # 已確認、沒有任何連結 ⇒ 不列
    _link("PS-203106-501", d2)
    _link("PS-203106-502", did)
    _link("PS-203106-505", d_other_case)
    for h, count in ((sa, 1), (staff, 0)):
        body = client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=h).json()
        assert [x["slipNo"] for x in body["byPerson"]] == ["PS-203106-501"], body
        assert body["unconfirmedCount"] == count, "待確認張數只給最高管理者（API 層）"
        assert [x["slipNo"] for x in body["items"]] == ["PS-203106-502"]
        blob = json.dumps(body, ensure_ascii=False)
        for secret in ("98765", "98,765", "A123456789", "100000", "1235", "PS-203106-505", "PS-203106-506"):
            assert secret not in blob, secret
        assert set(body["byPerson"][0]) <= {"slipNo", "status", "contractorName", "slipDate", "voided"}
    assert client.get("/api/contractor-dispatches/%s/payslip-links" % did, headers=staff).json()["canEdit"] is False


def test_migration_writes_only_the_guess_column_never_contractor_id_and_skips_voided(client, make_user):
    m = importlib.import_module("modules.payroll.migrations.0005_payslip_person_link")
    only, keep = _person("唯一"), _person("保留")
    _person("同名")
    _person("同名")
    _old_slip("PS-203106-601", "唯一", status="已付款")           # 唯一 ⇒ 只寫 guess（金流用的 contractor_id 不動）
    _old_slip("PS-203106-602", " 唯一 ", status="已簽回")         # 前後空白
    _old_slip("PS-203106-603", "同名")                           # 同名多位 ⇒ 不動
    _old_slip("PS-203106-604", "查無此人")                       # 對不到 ⇒ 不動
    _old_slip("PS-203106-605", "唯一", keep)                     # 已有 contractor_id ⇒ 完全不碰
    _old_slip("PS-203106-606", "唯一", status="已作廢")           # 已作廢 ⇒ 不回填
    import db
    c = db.get_db()
    try:
        sql = "SELECT slip_no, contractor_id, contractor_guess_id FROM payslips WHERE slip_no LIKE 'PS-203106-6%' ORDER BY slip_no"
        assert m.up(c) is None
        first = [dict(r) for r in c.execute(sql)]
        assert m.up(c) is None                         # 冪等
        assert first == [dict(r) for r in c.execute(sql)]
        c.commit()
    finally:
        c.close()
    got = {r["slip_no"]: (r["contractor_id"], r["contractor_guess_id"]) for r in first}
    assert got["PS-203106-601"] == (None, only) and got["PS-203106-602"] == (None, only), "contractor_id 必須維持 NULL（金流／總帳只認它）"
    assert got["PS-203106-603"] == (None, None) and got["PS-203106-604"] == (None, None)
    assert got["PS-203106-605"] == (keep, None) and got["PS-203106-606"] == (None, None)
    assert _q("SELECT 1 FROM payslip_dispatch_links") == [], "舊單不可被靜默連到派發"


def test_migration_returns_none_when_contractors_table_is_missing():
    import sqlite3
    m = importlib.import_module("modules.payroll.migrations.0005_payslip_person_link")
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, contractor_id INTEGER, contractor_name TEXT, status TEXT)")
    assert m.up(c) is None, "名冊表不在只是沒東西可回填，不能讓模組下線"
    assert "contractor_guess_id" in {r[1] for r in c.execute("PRAGMA table_info(payslips)")}


def test_confirm_promotes_guess_to_contractor_id_with_permissions_and_status_limits(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    staff = _staff(client, make_user, "pp_staff")
    cid, other = _person("己"), _person("庚庚")
    _old_slip("PS-203106-701", "己", None, cid)
    _old_slip("PS-203106-702", "己", None, cid, status="已簽回")      # 已入帳的不給確認
    _old_slip("PS-203106-703", "己", None, cid, status="已付款")
    _old_slip("PS-203106-704", "己", None, cid, status="已作廢")
    _old_slip("PS-203106-705", "己", None, cid)
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=staff, json={}).status_code == 403
    assert client.post("/api/payslips/PS-NOPE/confirm-contractor", headers=sa, json={}).status_code == 404
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={"contractorId": 987654}).status_code == 404
    for no in ("PS-203106-702", "PS-203106-703", "PS-203106-704"):
        assert client.post("/api/payslips/%s/confirm-contractor" % no, headers=sa, json={}).status_code == 409, no
        assert _q("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no=?", (no,)) == [{"contractor_id": None, "contractor_guess_id": cid}]
    r = client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={})
    assert r.status_code == 200 and r.json()["contractorId"] == cid
    assert _q("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no='PS-203106-701'") == [{"contractor_id": cid, "contractor_guess_id": None}]
    assert client.post("/api/payslips/PS-203106-701/confirm-contractor", headers=sa, json={}).status_code == 409
    r = client.post("/api/payslips/PS-203106-705/confirm-contractor", headers=sa, json={"contractorId": other})     # 人工改指別人
    assert r.status_code == 200 and _q("SELECT contractor_id FROM payslips WHERE slip_no='PS-203106-705'")[0]["contractor_id"] == other


def test_money_paths_never_read_a_guess(client, make_user):
    """推測只存在 contractor_guess_id：確認前 contractor_id 為 NULL（gl_events 對象鍵、匯款候選、受款人檢查都只看它）。"""
    cid = _person("推測者")
    _old_slip("PS-203106-710", "推測者", None, cid, status="已付款")
    row = _q("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no='PS-203106-710'")[0]
    assert row["contractor_id"] is None and row["contractor_guess_id"] == cid
    from modules.payroll import gl_events, remit_link
    for mod in (gl_events, remit_link):
        assert "contractor_guess_id" not in inspect.getsource(mod), "%s 不得讀推測值" % mod.__name__


def test_put_keeps_guess_until_name_change_or_manual_pick(client, make_user):
    sa = _su(client, make_user, "pp_sa")
    a, b = _person("庚"), _person("辛")
    no = _create(client, sa, None, "庚").json()["slip_no"]
    _x("UPDATE payslips SET contractor_guess_id=? WHERE slip_no=?", (a, no))
    body = {"data": {"contractorName": "庚", "incomeType": "9A", "grossAmount": 36000, "contractorNationality": "本國籍",
                     "contractorHasUnionInsurance": False, "slipDate": "2031-06-01"}}

    def cur():
        return _q("SELECT contractor_id, contractor_guess_id FROM payslips WHERE slip_no=?", (no,))[0]
    assert client.put("/api/payslips/" + no, headers=sa, json=body).status_code == 200
    assert cur() == {"contractor_id": None, "contractor_guess_id": a}                           # 同名重存：推測留著，金流欄位仍 NULL
    renamed = {"data": dict(body["data"], contractorName="完全不同的人")}
    assert client.put("/api/payslips/" + no, headers=sa, json=renamed).status_code == 200
    assert cur() == {"contractor_id": None, "contractor_guess_id": None}                       # 改名 ⇒ 推測作廢
    _x("UPDATE payslips SET contractor_guess_id=? WHERE slip_no=?", (a, no))
    assert client.put("/api/payslips/" + no, headers=sa, json=dict(body, contractor_id=b)).status_code == 200
    assert cur() == {"contractor_id": b, "contractor_guess_id": None}                          # 人工選名冊 ⇒ 視為確認


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
