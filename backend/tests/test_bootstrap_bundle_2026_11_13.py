# -*- coding: utf-8 -*-
"""GET /api/bootstrap 與 GET /api/dashboard/bundle（2026-11-13，外網載入效能第二階段）。

鐵則（PM）：bootstrap／bundle **不可以回傳比各自原本端點更多的資料**。本檔逐區段、逐欄、逐角色比對：
  - 區段內容 == 單打原端點的回應（同一個使用者、同一個瞬間）；
  - 不該給這個角色的區段（onlineUsers 只給最高管理者；totp／moduleCounts 只給最高管理者與管理員）不在回應裡；
  - 本公司資料未設定（428 閘門）時只放白名單內的區段，其餘 errors 記 428、不給資料（見 test_bootstrap_setup_gate）；
  - 任何一段壞了（403／出錯）⇒ 該段缺／null、不整包失敗。
"""
import json

import pytest

from routers import bootstrap as B

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    """每個角色一個帳號＋一點資料（報價單、通知），讓各區段不是空殼比對。"""
    import db
    hdr = {}
    for role in ROLES:
        u, pw = make_user(username="bb_" + role, role=role)
        hdr[role] = _login(client, u, pw)
    conn = db.get_db()
    try:
        appr = {"requestedBy": "bb_sales", "requestedByDisplay": "業務", "requestedAt": "2026-11-12T01:00:00", "currentTier": 0,
                "tiers": [{"approvers": [{"username": "bb_admin", "displayName": "管理員", "status": "pending"}]}]}
        for i, (st, tag) in enumerate((("待審核", ""), ("已送出", ""), ("已核准", "已成案"), ("已核准", "已結案"))):
            conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at, deal_tag)"
                         " VALUES (?,?,?,?,?,?,?,?,?)",
                         ("BB-%03d" % i, st, "客戶%d" % i, "專案%d" % i, 1000 * (i + 1),
                          json.dumps({"approval": appr} if st == "待審核" else {}, ensure_ascii=False),
                          "2026-11-0%d" % (i + 1), "2026-11-0%d" % (i + 1), tag))
        for role in ROLES:
            conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at, link) "
                         "VALUES (?,?,?,?,?,?,?,?)", ("bb_" + role, "info", "x", "BB", "測試通知", 0, "2026-11-12T02:00:00", ""))
        conn.commit()
    finally:
        conn.close()
    return hdr


def _get_json(client, path, h):
    r = client.get(path, headers=h)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)


def _strip_volatile(name, body):
    """比對時唯一放寬的欄位：在線人數的『幾秒前』會隨兩次請求之間的時間差跳動。"""
    if name == "onlineUsers" and isinstance(body, dict):
        body = json.loads(json.dumps(body))
        for u in body.get("users", []):
            u.pop("secondsAgo", None)
    return body


# ── bootstrap：逐區段、逐角色 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ROLES)
def test_bootstrap_sections_equal_the_original_endpoints(client, world, role):
    h = world[role]
    r = client.get("/api/bootstrap", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["v"] == 1 and d["errors"] == {}, d["errors"]
    want = B.sections_for(role, False)
    assert [k for k in d if k not in ("v", "errors")] == want
    for name in want:
        code, orig = _get_json(client, B.ORIGINAL_PATH[name], h)
        assert code == 200, (role, name, code)
        assert _strip_volatile(name, d[name]) == _strip_volatile(name, orig), (role, name)


@pytest.mark.parametrize("role", ROLES)
def test_bootstrap_never_gives_a_section_the_original_would_refuse(client, world, role):
    """不多給：bootstrap 裡每個區段，原端點對同一個人都回 200；沒放進來的區段，不是原端點也拒絕就是前端本來就不對這個角色發。"""
    h = world[role]
    d = client.get("/api/bootstrap", headers=h).json()
    for name, path in B.ORIGINAL_PATH.items():
        code, _ = _get_json(client, path, h)
        if name in d:
            assert code == 200, (role, name)
        elif name == "onlineUsers":
            assert code == (200 if role == "superadmin" else 403), (role, name, code)


def test_role_limited_sections_are_absent_for_other_roles(client, world):
    assert "onlineUsers" in client.get("/api/bootstrap", headers=world["superadmin"]).json()
    for role in ("admin", "sales", "engineer", "viewer", "finance"):
        d = client.get("/api/bootstrap", headers=world[role]).json()
        assert "onlineUsers" not in d, role
    for role in ("sales", "engineer", "viewer", "finance"):
        d = client.get("/api/bootstrap", headers=world[role]).json()
        assert "totp" not in d and "moduleCounts" not in d, role
    d = client.get("/api/bootstrap", headers=world["admin"]).json()
    assert "totp" in d and "moduleCounts" in d and "onlineUsers" not in d


def test_bootstrap_requires_login(client):
    assert client.get("/api/bootstrap").status_code == 401
    assert client.get("/api/bootstrap", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_must_change_password_user_is_blocked_like_other_api(client, make_user):
    """必須先改密碼的帳號：bootstrap 不在白名單 ⇒ 403（前端退回各自打原端點，原端點同樣只放白名單）。"""
    import db
    u, pw = make_user(username="bb_mcp", role="admin")
    h = _login(client, u, pw)
    conn = db.get_db()
    conn.execute("UPDATE users SET must_change_password=1 WHERE username=?", (u,))
    conn.commit()
    conn.close()
    r = client.get("/api/bootstrap", headers=h)
    assert r.status_code == 403 and r.json().get("code") == "must_change_password"


def test_one_failing_section_does_not_sink_the_others(client, world, monkeypatch):
    from fastapi import HTTPException
    from routers import system

    def _forbid(authorization=None):
        raise HTTPException(403, "no")

    def _boom(authorization=None):
        raise RuntimeError("x")
    monkeypatch.setattr(system, "get_bonus_module_status", _forbid)
    monkeypatch.setattr(system, "module_availability", _boom)
    d = client.get("/api/bootstrap", headers=world["admin"]).json()
    assert d["errors"] == {"bonusModuleStatus": 403, "moduleAvailability": 500}
    assert "bonusModuleStatus" not in d and "moduleAvailability" not in d
    assert d["me"]["username"] == "bb_admin" and "menu" in d and "approvalCount" in d


def test_sections_for_is_pure_and_ordered():
    assert B.sections_for("superadmin", False) == list(B.ORIGINAL_PATH)
    assert B.sections_for("viewer", True) == ["me", "menu", "branding"]
    assert B.sections_for("admin", True) == ["me", "menu", "branding", "totp"]


def test_setup_gate_allowed_sections_match_main():
    """SETUP_GATE_OK 必須剛好等於「原端點在 main 的白名單或公開清單內」的區段（否則 bootstrap 會成為繞過閘門的後門，或白白少給）。"""
    import main
    from helpers import company_setup as cs
    allowed = cs.compile_allowed(main._COMPANY_SETUP_ALLOWED)
    ok = set()
    for name, path in B.ORIGINAL_PATH.items():
        if path in main._PUBLIC_API_PATHS or cs.is_allowed(allowed, "GET", path):
            ok.add(name)
    assert ok == set(B.SETUP_GATE_OK), (ok, B.SETUP_GATE_OK)
    assert cs.is_allowed(allowed, "GET", "/api/bootstrap")


def test_bootstrap_is_not_recorded_in_the_trail():
    import trail
    assert trail.should_skip("/api/bootstrap")


# ── dashboard bundle ───────────────────────────────────────────────────────────

ORIG = {"stats": "/api/dashboard/stats", "monthly": "/api/dashboard/monthly", "expenses": "/api/dashboard/expenses-monthly",
        "funnel": "/api/dashboard/funnel", "opsAlerts": "/api/dashboard/ops-alerts", "activityFeed": "/api/dashboard/activity-feed?limit=8"}


@pytest.mark.parametrize("role", ROLES)
def test_bundle_sections_equal_the_original_endpoints(client, world, role):
    h = world[role]
    r = client.get("/api/dashboard/bundle", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["errors"] == {}
    assert [k for k in d if k != "errors"] == list(ORIG)
    for name, path in ORIG.items():
        code, orig = _get_json(client, path, h)
        assert code == 200, (role, name, code)
        assert d[name] == orig, (role, name)


def test_bundle_shows_real_data_not_just_empty_shells(client, world):
    d = client.get("/api/dashboard/bundle", headers=world["superadmin"]).json()
    assert d["stats"].get("totalCount", d["stats"].get("total_count", 0)) or json.dumps(d["stats"]) != "{}"
    assert any(v for v in d["stats"].values()), "正對照：stats 不是空的"


@pytest.mark.parametrize("role", ("superadmin", "sales", "viewer"))
def test_bundle_department_filter_and_activity_limit_match_the_originals(client, world, role):
    h = world[role]
    d = client.get("/api/dashboard/bundle?department_id=1&activity_limit=3", headers=h).json()
    for name, path in (("stats", "/api/dashboard/stats?department_id=1"), ("monthly", "/api/dashboard/monthly?department_id=1"),
                       ("expenses", "/api/dashboard/expenses-monthly?department_id=1"),
                       ("activityFeed", "/api/dashboard/activity-feed?limit=3&department_id=1"),
                       ("funnel", "/api/dashboard/funnel"), ("opsAlerts", "/api/dashboard/ops-alerts")):
        code, orig = _get_json(client, path, h)
        assert code == 200 and d[name] == orig, (role, name)


def test_bundle_without_finance_gets_the_same_empty_finance_sections_as_the_originals(client, world):
    """沒有財務權限的人：monthly／expenses 與原端點一樣是空殼（不是 null、更不是多給資料）。"""
    d = client.get("/api/dashboard/bundle", headers=world["sales"]).json()
    assert d["monthly"] == {"items": []}
    assert d["expenses"] == {"items": [], "otherBreakdown": {}}


def test_bundle_limits_are_validated_like_the_original(client, world):
    h = world["admin"]
    assert client.get("/api/dashboard/bundle?activity_limit=0", headers=h).status_code == 422
    assert client.get("/api/dashboard/bundle?activity_limit=101", headers=h).status_code == 422
    assert client.get("/api/dashboard/bundle").status_code == 401


def test_bundle_failing_section_is_null_and_others_survive(client, world, monkeypatch):
    from fastapi import HTTPException
    from modules.analytics.api import dashboard as D

    def _forbid(*a, **k):
        raise HTTPException(403, "no")

    def _boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(D, "dashboard_funnel", _forbid)
    monkeypatch.setattr(D, "dashboard_ops_alerts", _boom)
    d = client.get("/api/dashboard/bundle", headers=world["admin"]).json()
    assert d["funnel"] is None and d["opsAlerts"] is None
    assert d["errors"] == {"funnel": 403, "opsAlerts": 500}
    assert d["stats"] and d["activityFeed"] is not None


def test_bundle_is_grouped_with_the_dashboard_in_the_trail():
    import trail
    assert "/api/dashboard/bundle" in dict((g[0], g[2]) for g in trail._FANOUT_GROUPS)["/api/dashboard"]
