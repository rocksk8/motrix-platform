# -*- coding: utf-8 -*-
"""h3 複測最後兩項（2026-11-14）：
(a) 使用狀況頁「目前在線」／成員表的角色走 MotrixRole：finance 顯示「財務」，不是原始代碼。
(b) 權限設定頁對非最高管理者＝與其他僅限最高管理者頁同一張拒絕畫面（「這一頁僅限最高管理者使用」），
    沒有頁面外框、沒有「僅最高管理者可執行此操作」錯誤、也不打 /api/permmatrix。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")


def _json(route, body):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


@pytest.mark.e2e
def test_online_stats_shows_finance_as_caiwu_not_raw_code(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_osrole_super", role="superadmin")
    page = new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    people = [
        {"userId": 91, "displayName": "財務小何", "role": "finance"},
        {"userId": 92, "displayName": "一般小王", "role": "user"},
        {"userId": 93, "displayName": "工程小吳", "role": "engineer"},
    ]
    page.route("**/api/online-users**", lambda r: _json(r, {"count": 3, "users": people}))
    page.route("**/api/user-activity?**", lambda r: _json(r, {
        "items": [{"userId": p["userId"], "displayName": p["displayName"], "role": p["role"], "totalSeconds": 3600, "days": {"2026-11-01": 3600}} for p in people],
        "members": [{"userId": p["userId"], "displayName": p["displayName"], "role": p["role"], "active": True} for p in people]}))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/online-stats.html")
    body = page.locator('[data-testid="os-body"]')
    body.wait_for(state="visible", timeout=20000)
    page.get_by_text("財務小何").first.wait_for(state="visible", timeout=20000)
    text = body.inner_text()
    assert "財務" in text and "一般使用者" in text and "工程師" in text, text
    for raw in ("finance", "engineer"):
        assert raw not in text, "畫面不可出現原始角色代碼 %s：%s" % (raw, text)
    assert not errs, errs


@pytest.mark.e2e
@pytest.mark.parametrize("role", ["admin", "user"])
def test_permission_matrix_non_super_gets_the_shared_denial_screen(live_server, make_user, new_page, login_as, role):
    user = make_user(username="e2e_pmdeny_" + role, role=role)
    page = new_page()
    errs, api = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("request", lambda rq: api.append(rq.url) if "/api/permmatrix" in rq.url else None)
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/permission-matrix.html")
    notice = page.locator("#no-module-notice")
    notice.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(1200)
    text = notice.inner_text()
    assert "您沒有這個頁面的權限" in text and "這一頁僅限最高管理者使用" in text, text
    assert page.locator('[data-testid="pm-error"]').count() == 0 or not page.locator('[data-testid="pm-error"]').is_visible()
    assert page.get_by_text("僅最高管理者可執行此操作").count() == 0
    assert page.locator('[data-testid="pm-tab-matrix"]').count() == 0, "不該有頁面外框（分頁）"
    assert not api, "非最高管理者不該打 /api/permmatrix：%s" % api
    assert not errs, errs


@pytest.mark.e2e
def test_permission_matrix_superadmin_page_intact(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_pmsuper", role="superadmin")
    page = new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/permission-matrix.html")
    page.locator('[data-testid="pm-tab-matrix"]').wait_for(state="visible", timeout=20000)
    assert page.locator("#no-module-notice").count() == 0
    page.wait_for_timeout(1000)
    assert not errs, errs
