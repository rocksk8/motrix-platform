# -*- coding: utf-8 -*-
"""`GET /api/definitions/{kind}/{key}/diff?a=default` 的 `default` ＝**程式出貨的預設（v0）**，不是「目前生效的版本」。

路由 docstring 寫「`default`＝程式預設」，但實作呼叫 `D.resolve`（套用順序 role ＞ company 最新發布 ＞ 程式預設）：公司已發布過 ⇒ 回的是公司最新版，
於是 `a=default&b=latest` 永遠是同一份、差異恆為空——無法比較「公司版 vs 出貨預設」（第 33 班已發布請購單類型範本的前置）。
其他呼叫端（編輯頁「與已發布版的差異」＝`a=latest&b=draft`）不受影響：下面也釘住。"""
import json

import pytest

from helpers import expense_types as ET


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    sa, sp = make_user(username="dd_sa", role="superadmin")
    adm, ap = make_user(username="dd_adm", role="admin")
    return client, _login(client, sa, sp), _login(client, adm, ap)


def _shipped(code="travel"):
    return json.loads(json.dumps(ET._default_for(code)))                       # 程式出貨的預設（深拷貝）


def _publish(client, h, code, body):
    r = client.put("/api/definitions/expense_type/%s/draft" % code, json={"body": body}, headers=h)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    p = client.post("/api/definitions/expense_type/%s/publish" % code, json={}, headers=h)
    assert p.status_code == 200, p.text
    return p.json()["version"]


def _diff(client, h, code, a, b, kind="expense_type"):
    r = client.get("/api/definitions/%s/%s/diff" % (kind, code), params={"a": a, "b": b}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["changes"]


def _paths(changes):
    return sorted(c["path"] for c in changes)


def test_default_vs_latest_shows_how_the_company_version_differs_from_the_shipped_default(world):
    client, h, _ = world
    body = _shipped()
    body["name"] = "公司自己改的名稱"
    _publish(client, h, "travel", body)
    ch = _diff(client, h, "travel", "default", "latest")
    print("default→latest:", ch)
    assert any(c["path"].endswith("name") for c in ch), "公司版與出貨預設只差名稱 ⇒ 差異要看得到（原本 default 解析成公司版，差異恆為空）"
    assert len(ch) == 1, ch


def test_default_is_the_shipped_default_even_after_several_company_versions(world):
    client, h, _ = world
    b1 = _shipped(); b1["name"] = "第一版"
    b2 = _shipped(); b2["name"] = "第二版"
    _publish(client, h, "travel", b1)
    _publish(client, h, "travel", b2)
    assert _paths(_diff(client, h, "travel", "default", "default")) == []                      # 自己對自己
    ch = _diff(client, h, "travel", "default", "latest")
    assert len(ch) == 1 and ch[0]["path"].endswith("name")
    ch1 = _diff(client, h, "travel", "default", "1")
    assert len(ch1) == 1 and ch1[0]["path"].endswith("name")
    assert _paths(_diff(client, h, "travel", "1", "latest")) != [], "第一版與最新版不同（版本對版本照常）"


def test_default_with_no_company_version_is_still_the_shipped_default(world):
    client, h, _ = world
    draft = _shipped(); draft["name"] = "只有草稿"
    assert client.put("/api/definitions/expense_type/petty_cash/draft", json={"body": dict(_shipped("petty_cash"), name="只有草稿")}, headers=h).status_code == 200
    ch = _diff(client, h, "petty_cash", "default", "draft")
    assert len(ch) == 1 and ch[0]["path"].endswith("name"), ch
    assert _diff(client, h, "petty_cash", "default", "default") == []


def test_other_callers_are_unchanged_latest_vs_draft_and_numeric_versions(world):
    """編輯頁「與已發布版的差異」＝latest vs draft；版本號對版本號；沒有的版本照舊 400/空。"""
    client, h, _ = world
    b1 = _shipped(); b1["name"] = "已發布"
    _publish(client, h, "travel", b1)
    draft = dict(b1, name="草稿又改了")
    assert client.put("/api/definitions/expense_type/travel/draft", json={"body": draft}, headers=h).status_code == 200
    ch = _diff(client, h, "travel", "latest", "draft")
    assert len(ch) == 1 and ch[0]["path"].endswith("name"), ch
    assert _diff(client, h, "travel", "latest", "1") == []
    r = client.get("/api/definitions/expense_type/travel/diff", params={"a": "zzz", "b": "latest"}, headers=h)
    assert r.status_code == 400


def test_diff_stays_superadmin_only(world):
    client, h, hadm = world
    assert client.get("/api/definitions/expense_type/travel/diff", params={"a": "default", "b": "latest"}, headers=hadm).status_code in (401, 403)


def test_a_kind_without_a_shipped_default_gives_an_empty_default(world):
    """沒有程式預設的種類（例：custom_module）：`default` ＝空內容，不是公司版（差異＝整份新增，而不是恆為空）。"""
    client, h, _ = world
    body = {"name": "x", "icon": "", "permission": "custom.dd_cm", "fields": [], "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []}, "ui": {"form": {"groups": []}, "list": {"columns": []}}}
    assert client.put("/api/definitions/custom_module/dd_cm/draft", json={"body": body}, headers=h).status_code == 200
    ch = _diff(client, h, "dd_cm", "default", "draft", kind="custom_module")
    print("custom_module default→draft:", ch[:3], len(ch))
    assert ch, "沒有出貨預設 ⇒ default 是空內容，與草稿比應有差異（原本若已發布過公司版會解析成公司版）"
