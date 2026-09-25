"""參照欄選項（`GET /api/custom/{key}/ref-options/{field}`）：被參照的那一方也要有讀取權限（主持 2026-09-26，P8 前端代理回報）。

原本只檢查「目前這個自訂模組」的權限 ⇒ 有 A 模組權限的人，可以經 A 的參照欄讀到 B 模組的單號清單、或客戶清單。
① 參照 `custom:<B>`：有 A 沒有 B ⇒ 403；兩個都有 ⇒ 200 且列出 B 的單據（正對照）
② 參照 `customers`：沒有客戶相關權限 ⇒ 403；有 ⇒ 200
③ 參照 `users`：登入即可（簽核人、借用人等欄位本來就要挑人）
"""
import copy

import pytest

from tests.test_custom_modules_engine_2026_09_25 import loan_definition

A, B = "ref_parent", "ref_child"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Refopt-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _publish(client, h, key, body):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200


@pytest.fixture()
def two_modules(client, make_user):
    sa = _login(client, make_user, "ro_super", role="superadmin")
    child = copy.deepcopy(loan_definition())
    child.update(name="被參照模組", permission="custom." + B)
    _publish(client, sa, B, child)
    parent = copy.deepcopy(loan_definition())
    parent.update(name="參照方模組", permission="custom." + A)
    parent["fields"] += [{"key": "child_no", "label": "關聯單", "type": "ref", "target": "custom:" + B},
                         {"key": "customer", "label": "客戶", "type": "ref", "target": "customers"}]
    _publish(client, sa, A, parent)
    r = client.post("/api/custom/%s/records" % B, headers=sa, json={"values": {"item": "子單", "qty": 1}})
    assert r.status_code == 200, r.text
    return sa, r.json()["record_no"]


def test_ref_to_another_custom_module_needs_that_modules_permission(client, make_user, two_modules):
    _sa, child_no = two_modules
    only_a = _login(client, make_user, "ro_only_a", modules=["custom." + A])
    both = _login(client, make_user, "ro_both", modules=["custom." + A, "custom." + B])
    url = "/api/custom/%s/ref-options/child_no" % A
    r = client.get(url, headers=only_a)
    assert r.status_code == 403, r.text
    r = client.get(url, headers=both)
    assert r.status_code == 200 and child_no in [o["value"] for o in r.json()], r.text


def test_ref_to_customers_needs_a_customer_permission(client, make_user, two_modules):
    no_cust = _login(client, make_user, "ro_no_cust", modules=["custom." + A])
    with_cust = _login(client, make_user, "ro_with_cust", modules=["custom." + A, "customer"])
    url = "/api/custom/%s/ref-options/customer" % A
    assert client.get(url, headers=no_cust).status_code == 403
    assert client.get(url, headers=with_cust).status_code == 200


def test_ref_to_users_only_needs_login(client, make_user, two_modules):
    only_a = _login(client, make_user, "ro_users_only_a", modules=["custom." + A])
    r = client.get("/api/custom/%s/ref-options/borrower" % A, headers=only_a)
    assert r.status_code == 200 and isinstance(r.json(), list)
