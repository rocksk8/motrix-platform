# -*- coding: utf-8 -*-
"""第 49 班（使用者裁示）：網路架構規劃書讀取端點加上和「依案件查詢」同一道逐案權限。

綁定案件的規劃書：看不到該案的人（不是該案業務／協作者、不是 admin 以上、沒有 case_manage）在清單看不到、單筆／匯出（Excel、PDF）／拓樸預覽／個資告知查詢都是 404
（看不到＝不存在）；沒綁案件的獨立規劃書不受影響；admin／最高管理者照舊。另補洞：匯出與拓樸預覽原本只要登入，現在也要規劃書讀取模組。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "逐案權限要 M01 的 case.access 提供者")

CASE = "MQ-NP49-001"


def _h(client, make_user, name, role, mods):
    u, p = make_user(username=name, role=role, modules=mods)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}, u


@pytest.fixture()
def world(client, make_user):
    sa, _ = _h(client, make_user, "np49_sa", "superadmin", None)
    admin, _ = _h(client, make_user, "np49_admin", "admin", ["netplan"])
    owner, owner_name = _h(client, make_user, "np49_owner", "sales", ["netplan", "quotation"])
    other, _ = _h(client, make_user, "np49_other", "sales", ["netplan", "quotation"])
    cm, _ = _h(client, make_user, "np49_cm", "engineer", ["netplan", "case_manage"])
    nomod, _ = _h(client, make_user, "np49_nomod", "sales", ["dashboard"])
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person) VALUES (?,?,?,?,?,?,?,?)",
                  (CASE, "已送出", "客", "案", json.dumps({}), "t", "t", owner_name))
        c.commit()
    finally:
        c.close()
    bound = client.post("/api/network-plans", headers=sa, json={"quoteNo": CASE, "siteName": "綁案件"})
    alone = client.post("/api/network-plans", headers=sa, json={"siteName": "獨立評估"})
    assert bound.status_code == 201 and alone.status_code == 201, (bound.text, alone.text)
    return {"sa": sa, "admin": admin, "owner": owner, "other": other, "cm": cm, "nomod": nomod, "bound": bound.json()["id"], "alone": alone.json()["id"]}


def _names(client, h):
    r = client.get("/api/network-plans", headers=h)
    assert r.status_code == 200, r.text
    return sorted(p["siteName"] for p in r.json())


def test_list_hides_case_bound_plans_from_people_without_case_access(client, world):
    assert _names(client, world["other"]) == ["獨立評估"]
    for who in ("sa", "admin", "owner", "cm"):
        assert _names(client, world[who]) == ["獨立評估", "綁案件"], who
    assert client.get("/api/network-plans?quote_no=" + CASE, headers=world["other"]).json() == []


def test_single_plan_is_404_for_people_without_case_access(client, world):
    b, a = world["bound"], world["alone"]
    assert client.get("/api/network-plans/%d" % b, headers=world["other"]).status_code == 404
    assert client.get("/api/network-plans/%d" % a, headers=world["other"]).status_code == 200
    for who in ("sa", "admin", "owner", "cm"):
        assert client.get("/api/network-plans/%d" % b, headers=world[who]).status_code == 200, who
    assert client.get("/api/network-plans/99999", headers=world["other"]).status_code == 404            # 不存在與看不到同一個 404


def test_exports_topology_preview_and_privacy_lookup_follow_the_same_rule(client, world):
    b = world["bound"]
    for path, method in (("/export/excel", "get"), ("/export/pdf", "get"), ("/privacy-notice", "get"), ("/topology-preview", "post")):
        kw = {"json": {"data": {}}} if method == "post" else {}
        r = getattr(client, method)("/api/network-plans/%d%s" % (b, path), headers=world["other"], **kw)
        assert r.status_code == 404, (path, r.status_code)
    assert client.get("/api/network-plans/%d/export/excel" % b, headers=world["owner"]).status_code == 200
    assert client.get("/api/network-plans/%d/export/excel" % b, headers=world["admin"]).status_code == 200
    assert client.get("/api/network-plans/%d/export/excel" % world["alone"], headers=world["other"]).status_code == 200


def test_exports_and_preview_now_need_a_netplan_read_module(client, world):
    """補洞：原本匯出／拓樸預覽只驗登入，沒有任何規劃書模組的帳號也能匯出任一份。"""
    for path, method in (("/export/excel", "get"), ("/export/pdf", "get"), ("/topology-preview", "post")):
        kw = {"json": {"data": {}}} if method == "post" else {}
        r = getattr(client, method)("/api/network-plans/%d%s" % (world["alone"], path), headers=world["nomod"], **kw)
        assert r.status_code == 403, (path, r.status_code)


def test_without_the_case_module_bound_plans_are_admin_only(client, world, monkeypatch):
    from tests.platform.test_case_stage_connectors import _without
    _without(monkeypatch, "case.access", "case")
    assert _names(client, world["other"]) == ["獨立評估"]
    assert _names(client, world["owner"]) == ["獨立評估"]
    assert _names(client, world["admin"]) == ["獨立評估", "綁案件"]
    assert client.get("/api/network-plans/%d" % world["bound"], headers=world["owner"]).status_code == 404
    assert client.get("/api/network-plans/%d" % world["bound"], headers=world["sa"]).status_code == 200
