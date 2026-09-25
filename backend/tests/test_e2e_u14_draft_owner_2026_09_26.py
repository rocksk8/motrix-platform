# -*- coding: utf-8 -*-
"""U14（使用者 2026-09-26 裁示）前端：自訂模組草稿只有建立者與超級管理員可以修改、送出。

後端（C，c-audit-d）已擋 403 並在 GET 單據回 `canEdit`；本檔驗頁面照它顯示：
同權限的其他人看不到「編輯」與「送出」，並看到說明；建立者、超級管理員看得到而且送得出去（正對照，斷言打 DB）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

KEY = "u14_draft"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _module():
    return {
        "name": "U14 草稿測試", "permission": "custom.%s" % KEY, "numbering": {"prefix": "UD", "date": "", "digits": 3},
        "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
        "workflow": {"initial": "draft", "states": [
            {"key": "draft", "label": "草稿"},
            {"key": "sent", "label": "已送出", "final": True}],
            "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "sent"}]}}


def _setup(client, make_user):
    admin = make_user(username="u14_admin", role="superadmin")
    owner = make_user(username="u14_owner", role="viewer", modules=["custom.%s" % KEY])
    peer = make_user(username="u14_peer", role="viewer", modules=["custom.%s" % KEY])
    ah = _h(client, admin)
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _module()}, headers=ah).status_code == 200
    r = client.post("/api/definitions/custom_module/%s/publish" % KEY, json={}, headers=ah)
    assert r.status_code == 200, r.text
    r = client.post("/api/custom/%s/records" % KEY, json={"values": {"a": "x"}}, headers=_h(client, owner))
    assert r.status_code == 200, r.text
    return admin, owner, peer, r.json()["record_no"]


def _status(no):
    return _q("SELECT status FROM custom_records WHERE module_key=? AND record_no=?", (KEY, no))[0]["status"]


def _open(new_context, base, user, no, errors):
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append("%s: %s" % (user[0], e)))
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/custom-records.html?key=%s&no=%s" % (KEY, no))
    page.wait_for_selector('#cr-record[data-record-no="%s"][data-busy="0"]' % no)
    return page


@pytest.mark.e2e
def test_peer_with_same_permission_sees_no_edit_or_submit(live_server, make_user, new_context, client):
    _, _, peer, no = _setup(client, make_user)
    got = client.get("/api/custom/%s/records/%s" % (KEY, no), headers=_h(client, peer)).json()
    assert got["canEdit"] is False, "前提：伺服器說這個人不能改"
    errors = []
    page = _open(new_context, live_server, peer, no, errors)
    page.wait_for_selector("#cr-draft-locked", state="visible")       # 正面訊號先出現，才檢查按鈕不在
    assert page.locator("#cr-edit").count() == 0
    assert page.locator('[data-transition="submit"]').count() == 0
    assert page.locator("#cr-out-html").is_visible()                   # 仍可檢視與輸出
    assert _status(no) == "draft"
    assert not errors, errors


@pytest.mark.e2e
@pytest.mark.parametrize("who", ["owner", "superadmin"])
def test_owner_and_superadmin_can_edit_and_submit(live_server, make_user, new_context, client, who):
    """正對照：建立者、超級管理員看得到編輯與送出，按下去 DB 真的變成已送出。"""
    admin, owner, _, no = _setup(client, make_user)
    user = owner if who == "owner" else admin
    errors = []
    page = _open(new_context, live_server, user, no, errors)
    page.wait_for_selector("#cr-edit", state="visible")
    assert not page.locator("#cr-draft-locked").is_visible()
    page.click('[data-transition="submit"]')
    page.wait_for_selector('#cr-record[data-status="sent"][data-busy="0"]')
    assert _status(no) == "sent"
    assert not errors, errors
