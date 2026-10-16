# -*- coding: utf-8 -*-
"""第 55 班：勞報單「選派發」下拉（提供者 `dispatch.search`＋`GET /api/payslip-dispatch-options`；使用者裁示 1–4）。

① 預設只列受領人在名單內、非草稿非已取消的派發；`include_all` 才列全部（正對照：同一批資料兩種結果不同）
② 搜尋（派發編號／案件單號／廠商名／案件名稱）、`%` 當字面、分頁與 hasMore；看不到的案件不能靠案件名稱搜出來
③ 標籤：已關聯（連到未作廢勞報單）、已連到這張；作廢單的連結不算已關聯
④ 清單不含金額；非最高管理者 403；M04 不在 ⇒ 明說
⑤ 名單外的派發擋下（詳情入口與派發頁入口都擋；沒選名冊人員的勞報單不檢查）；稽核含派發編號與「顯示全部」註記
"""
import itertools
import json

import pytest

from core import registry, source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/subcontract/"), reason="派發在外包工班（M04）")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
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


def _dispatch(client, h, personnel, quote="MQ-DD55-001", vendor=None):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (quote, "已送出", "客戶丙", "專案丁", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "", "", "[]"))
    r = client.post("/api/vendor-contractors", headers=h, json={"name": vendor or "廠商DD%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": quote, "vendor_id": r.json()["id"], "status": "completed", "personnel_json": personnel,
            "items_json": [{"description": "品項", "qty": 1, "unit": "式", "unitPrice": 500}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    _x("UPDATE contractor_dispatches SET doc_code=? WHERE id=?", ("DP-20311231-%04d" % did, did))          # 測試環境建立的派發沒有編號 ⇒ 補上，搜尋才有東西比
    return did


def _su(client, make_user, name="dd_sa"):
    u, p = make_user(username=name, role="superadmin")
    return _auth(_login(client, u, p))


def _staff(client, make_user, name="dd_staff"):
    u, p = make_user(username=name, role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    return _auth(_login(client, u, p))


def _slip(no, cid, status="草稿"):
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method,"
       " slip_date, status, tax_rules_version, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, cid, "某", "9A", 100000, 1235, 0, 98765, "匯款", "2031-06-01", status, "2031", json.dumps({"slipNo": no}), "2031-06-01T00:00:00", "2031-06-01T00:00:00"))


def _opts(client, h, **params):
    qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
    r = client.get("/api/payslip-dispatch-options?" + qs, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(res):
    return [it["id"] for it in res["items"]]


def test_default_is_roster_only_and_excludes_draft_cancelled_show_all_widens(client, make_user):
    sa = _su(client, make_user)
    a, b = _person("甲"), _person("乙")
    d1 = _dispatch(client, sa, [{"id": a, "name": "甲"}])
    d2 = _dispatch(client, sa, [{"id": a, "name": "甲"}])
    d3 = _dispatch(client, sa, [{"id": a, "name": "甲"}])
    d4 = _dispatch(client, sa, [{"id": b, "name": "乙"}])
    _x("UPDATE contractor_dispatches SET status='draft' WHERE id=?", (d2,))
    _x("UPDATE contractor_dispatches SET status='cancelled' WHERE id=?", (d3,))
    assert _ids(_opts(client, sa, contractor_id=a)) == [d1]                                  # 預設：名單內、非草稿非取消
    res = _opts(client, sa, contractor_id=a, include_all="true")
    assert _ids(res) == [d4, d1]                                                              # 正對照：顯示全部多出別人的，草稿／取消仍不列
    assert {it["id"]: it["onRoster"] for it in res["items"]} == {d1: True, d4: False}
    everyone = _ids(_opts(client, sa))
    assert d1 in everyone and d4 in everyone and d2 not in everyone and d3 not in everyone  # 沒給人 ⇒ 全部（非草稿非取消）


def test_roster_match_is_exact_not_substring(client, make_user):
    sa = _su(client, make_user)
    p = _person("丙")
    d = _dispatch(client, sa, [{"id": p * 100 + 11, "name": "撞號"}])                         # id 字串含 p，但不是 p
    assert d not in _ids(_opts(client, sa, contractor_id=p))


def test_search_fields_literal_wildcards_and_paging(client, make_user):
    sa = _su(client, make_user)
    a = _person("丁")
    d1 = _dispatch(client, sa, [{"id": a, "name": "丁"}], quote="MQ-DD55-AAA", vendor="甲級100%工班")
    d2 = _dispatch(client, sa, [{"id": a, "name": "丁"}], quote="MQ-DD55-BBB", vendor="乙級工班")
    code1 = _q("SELECT doc_code FROM contractor_dispatches WHERE id=?", (d1,))[0]["doc_code"]
    assert _ids(_opts(client, sa, q="AAA", include_all="true")) == [d1]                      # 案件單號
    assert code1, "派發編號是空的"
    assert _ids(_opts(client, sa, q=code1, include_all="true")) == [d1], (code1, _q("SELECT id, doc_code FROM contractor_dispatches"))                      # 派發編號
    assert _ids(_opts(client, sa, q="乙級", include_all="true")) == [d2]                     # 廠商名
    assert {d1, d2} <= set(_ids(_opts(client, sa, q="專案丁", include_all="true")))          # 案件名稱（最高管理者看得到案件）
    assert _ids(_opts(client, sa, q="100%25", include_all="true")) == [d1]                   # `%` 是字面，不是萬用字元
    assert _ids(_opts(client, sa, q="%25", include_all="true")) == [d1]                      # 正對照：只有含 % 的廠商名命中，不是全部
    assert _opts(client, sa, q="完全不存在的字串", include_all="true")["items"] == []
    import db
    fn = registry.single_provider("dispatch.search")
    c = db.get_db()
    try:
        p1 = fn(c, q="MQ-DD55", include_all=True, limit=1, offset=0)
        p2 = fn(c, q="MQ-DD55", include_all=True, limit=1, offset=1)
        p3 = fn(c, q="MQ-DD55", include_all=True, limit=1, offset=2)
    finally:
        c.close()
    assert [x["id"] for x in p1["items"]] == [d2] and p1["hasMore"] is True                  # 新到舊
    assert [x["id"] for x in p2["items"]] == [d1] and p2["hasMore"] is False
    assert p3["items"] == [] and p3["hasMore"] is False
    assert client.get("/api/payslip-dispatch-options?offset=-1", headers=sa).status_code == 400


def test_case_name_search_needs_case_visibility_at_provider(client, make_user):
    sa = _su(client, make_user)
    a = _person("戊")
    d = _dispatch(client, sa, [{"id": a, "name": "戊"}], quote="MQ-DD55-VIS")
    fn = registry.single_provider("dispatch.search")
    import db
    c = db.get_db()
    try:
        assert fn(c, q="專案丁", include_all=True, user=None)["items"] == []                   # 沒有呼叫者資訊 ⇒ 案件名稱不能拿來比對
        hit = fn(c, q="MQ-DD55-VIS", include_all=True, user=None)["items"]
        assert [x["id"] for x in hit] == [d] and hit[0]["projectName"] == "" and hit[0]["caseVisible"] is False
    finally:
        c.close()


def test_link_tags_and_no_money_and_permission(client, make_user):
    sa, staff = _su(client, make_user), _staff(client, make_user)
    a = _person("己")
    d1 = _dispatch(client, sa, [{"id": a, "name": "己"}])
    d2 = _dispatch(client, sa, [{"id": a, "name": "己"}])
    _slip("PS-DD55-001", a)
    _slip("PS-DD55-002", a, status="已作廢")
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES ('PS-DD55-001', ?, 't', '2031-06-01')", (d1,))
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, created_by, created_at) VALUES ('PS-DD55-002', ?, 't', '2031-06-01')", (d2,))
    tags = {it["id"]: (it["linked"], it["linkedToThis"]) for it in _opts(client, sa, contractor_id=a, slip_no="PS-DD55-001")["items"]}
    assert tags == {d1: (True, True), d2: (False, False)}                                    # 作廢單的連結不算已關聯
    other = {it["id"]: (it["linked"], it["linkedToThis"]) for it in _opts(client, sa, contractor_id=a, slip_no="PS-DD55-999")["items"]}
    assert other[d1] == (True, False)                                                        # 連到別張 ⇒ 已關聯但仍可選
    txt = json.dumps(_opts(client, sa, contractor_id=a), ensure_ascii=False)
    assert "amount" not in txt.lower() and "unitPrice" not in txt and "500" not in txt        # 不含金額
    assert client.get("/api/payslip-dispatch-options", headers=staff).status_code == 403


def test_provider_missing_says_so(client, make_user, monkeypatch):
    sa = _su(client, make_user)
    real = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda name, *a, **k: None if name == "dispatch.search" else real(name, *a, **k))
    res = _opts(client, sa)
    assert res["items"] == [] and "不能搜尋派發" in res["notice"]


def test_off_roster_pick_is_blocked_on_both_entrances_and_audit_notes(client, make_user):
    sa = _su(client, make_user)
    a, b = _person("庚"), _person("辛")
    mine = _dispatch(client, sa, [{"id": a, "name": "庚"}])
    theirs = _dispatch(client, sa, [{"id": b, "name": "辛"}])
    _slip("PS-DD55-010", a)
    _slip("PS-DD55-011", None)                                                               # 沒選名冊人員 ⇒ 不檢查（同建立勞報單）
    r = client.post("/api/payslips/PS-DD55-010/dispatch-links", headers=sa, json={"dispatchId": theirs})
    assert r.status_code == 400 and "沒有這張勞報單的受領人" in r.text, r.text
    r = client.post("/api/contractor-dispatches/%d/payslip-links" % theirs, headers=sa, json={"slipNo": "PS-DD55-010"})
    assert r.status_code == 400 and "沒有這張勞報單的受領人" in r.text, r.text                 # 派發頁入口一樣擋
    assert _q("SELECT 1 FROM payslip_dispatch_links") == []
    assert client.post("/api/payslips/PS-DD55-010/dispatch-links", headers=sa, json={"dispatchId": mine, "viaShowAll": True}).status_code == 201   # 正對照
    assert client.post("/api/payslips/PS-DD55-011/dispatch-links", headers=sa, json={"dispatchId": theirs}).status_code == 201
    assert client.post("/api/payslips/PS-DD55-010/dispatch-links", headers=sa, json={"dispatchId": mine}).status_code == 409                       # 重複
    rows = _q("SELECT target_label FROM audit_log WHERE action='payslip.dispatch_link' ORDER BY id")
    code = _q("SELECT doc_code FROM contractor_dispatches WHERE id=?", (mine,))[0]["doc_code"]
    assert code and code in rows[0]["target_label"] and "顯示全部" in rows[0]["target_label"] and "顯示全部" not in rows[1]["target_label"]


def test_page_size_comes_from_the_setting_and_falls_back_when_unreadable(client, make_user, monkeypatch):
    """下拉一次載入幾筆來自設定 payslip_dispatch_picker.page_size（預設 30）；設定層出問題時退回後備值，不讓下拉壞掉。"""
    from helpers import settings_registry as SR
    from modules.subcontract.api import dispatch_payslip_links as DL
    assert SR.get("payslip_dispatch_picker", "page_size") == 30 == DL.SEARCH_PAGE            # 預設＝上線前常數
    sa = _su(client, make_user, "dd_sa_ps")
    a = _person("戊")
    d1 = _dispatch(client, sa, [{"id": a, "name": "戊"}], quote="MQ-DD55-PS1")
    d2 = _dispatch(client, sa, [{"id": a, "name": "戊"}], quote="MQ-DD55-PS2")
    real = SR.get
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 1 if (g, f) == ("payslip_dispatch_picker", "page_size") else real(g, f, **kw))
    r = _opts(client, sa, q="MQ-DD55-PS", include_all="true")
    assert _ids(r) == [d2] and r["hasMore"] is True                                          # 設定 1 筆 ⇒ 一頁一筆
    def _boom(g, f, **kw):
        raise RuntimeError("設定層壞了")
    monkeypatch.setattr(SR, "get", _boom)
    assert set(_ids(_opts(client, sa, q="MQ-DD55-PS", include_all="true"))) == {d1, d2}      # 後備 30 筆
