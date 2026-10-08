# -*- coding: utf-8 -*-
"""users.html 編輯視窗：職責角色（有權限清單）的 chip 不得丟 JS 例外（第 48 班整合退化釘住）。

退化：`:title="(r.permissions||[]).map(dutyKeyLabel)"` 把方法未綁定傳入 ⇒ `this.duty` undefined ⇒
`Cannot read properties of undefined (reading 'keys')`——只在『職責角色有權限』時才發生，p8 e2e 隱含撞到。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


@pytest.mark.e2e
def test_users_edit_modal_renders_duty_role_chips_with_permissions(live_server, make_user, new_context, client):
    admin = make_user(username="dchip_admin", role="superadmin")
    make_user(username="dchip_staff", role="viewer", modules=[])
    tok = client.post("/api/auth/login", json={"username": admin[0], "password": admin[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    r = client.post("/api/duty-roles", json={"key": "dchip_role", "name": "晶片測試角色", "permissions": ["reports"]}, headers=h)
    assert r.status_code == 201, r.text
    errors = []
    pg = new_context(viewport={"width": 1366, "height": 900}).new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, admin[0], admin[1])
    pg.goto(live_server + "/pages/users.html")
    row = pg.locator("div", has=pg.get_by_text("dchip_staff", exact=True)).filter(has=pg.get_by_role("button", name="編輯")).last
    row.get_by_role("button", name="編輯").click()
    pg.wait_for_selector('[data-testid="duty-role-dchip_role"]')
    title = pg.locator('[data-testid="duty-role-dchip_role"]').first.get_attribute("title")
    assert title and title.strip(), "chip 的 title 要列出權限標籤"
    assert not errors, errors
