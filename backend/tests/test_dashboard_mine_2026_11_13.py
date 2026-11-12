# -*- coding: utf-8 -*-
"""首頁「我的工作」`GET /api/dashboard/mine`：待簽核同源、權限分組、提供者壞掉只少一組、快取。"""
import pytest

from routers import dashboard_mine as DM


def test_age_and_tone():
    from datetime import datetime
    now = datetime(2026, 11, 13, 12, 0, 0)
    assert DM.age_days("2026-11-13 08:00:00", now) == 0
    assert DM.age_days("2026-11-10 08:00:00", now) == 3
    assert DM.age_days("", now) == 0 and DM.age_days("壞字串", now) == 0
    assert [DM.age_tone(d) for d in (0, 1, 2, 3, 4, 9)] == ["ok", "ok", "warn", "warn", "crit", "crit"]


def test_blocker_display():
    it = {"tiers": [{"approvers": [{"username": "a", "status": "approved"}, {"username": "b", "displayName": "小B", "status": "pending"}]}], "currentTier": 0}
    assert DM.blocker_display(it) == "小B"
    assert DM.blocker_display({"type": "case_change", **it}) == "最高管理者"
    assert DM.blocker_display({}) == "最高管理者"


def test_clean_group_drops_malformed():
    assert DM._clean_group({"title": "沒 key"}) is None
    assert DM._clean_group("x") is None
    g = DM._clean_group({"key": "k", "title": "T", "kind": "亂寫", "items": [{"title": "a", "tone": "紅"}, {"nope": 1}], "count": "abc"})
    assert g["kind"] == "work" and g["count"] == 1 and g["items"][0]["tone"] == "ok" and len(g["items"]) == 1


def test_provider_failure_only_drops_that_group(monkeypatch):
    from core import registry
    def boom(u): raise RuntimeError("x")
    def ok(u): return [{"key": "zz", "title": "好的", "count": 2, "order": 99}]
    monkeypatch.setattr(registry, "providers", lambda cap: {"a": boom, "b": ok} if cap == "dashboard.mine_groups" else {})
    monkeypatch.setattr(DM, "_approval_groups", lambda u, now: [DM._group("approvals", "待我簽核", [], order=10)])
    r = DM.build_mine({"username": "u", "role": "sales"})
    assert r["errors"] == ["a"]
    assert [g["key"] for g in r["groups"]] == ["approvals", "zz"]
    assert r["empty"] is False


def test_empty_when_all_zero(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    monkeypatch.setattr(DM, "_approval_groups", lambda u, now: [DM._group("approvals", "待我簽核", [], order=10)])
    assert DM.build_mine({"username": "u", "role": "sales"})["empty"] is True


def _h(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed(quote_no, approvers, requested_by="applicant", at="2026-11-10T09:00:00"):
    import json
    import db
    data = {"quoteNo": quote_no, "approval": {"requestedBy": requested_by, "requestedAt": at, "currentTier": 0,
                                             "tiers": [{"approvers": [{"username": u, "displayName": u, "status": "pending"} for u in approvers]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "待審核", "客戶" + quote_no, "專案", 1000, 952, json.dumps(data, ensure_ascii=False), at, at, "", requested_by, "[]"))
        conn.commit()
    finally:
        conn.close()


def test_api_requires_login(client):
    assert client.get("/api/dashboard/mine").status_code == 401


def test_api_shape_cache_and_permission_groups(client, make_user):
    u = make_user("dm_sales", role="sales", modules=["quotation", "case_manage"])
    DM.reset_cache()
    r = client.get("/api/dashboard/mine", headers=_h(client, *u))
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) >= {"groups", "empty", "errors", "generatedAt"} and d["errors"] == []
    keys = [g["key"] for g in d["groups"]]
    assert keys[0] == "approvals" and "my_cases" in keys
    assert "receivable_overdue" not in keys          # 業務沒有財務權限 ⇒ 沒有「錢」那一組
    h = _h(client, *u)
    assert client.get("/api/dashboard/mine", headers=h).json()["generatedAt"] == d["generatedAt"]   # 快取
    assert client.get("/api/dashboard/mine?fresh=1", headers=h).status_code == 200


def test_boss_gets_money_group_and_stuck(client, make_user):
    sa = make_user("dm_sa", role="superadmin")
    _seed("MQ-DM-001", ["dm_other"])                 # 卡在別人身上、2 天以上 ⇒ 老闆的「卡住的單」
    DM.reset_cache()
    d = client.get("/api/dashboard/mine", headers=_h(client, *sa)).json()
    keys = [g["key"] for g in d["groups"]]
    assert "approvals" in keys and "receivable_overdue" in keys and "stuck" in keys


def test_approvals_count_matches_badge_and_submitted_shows_blocker(client, make_user):
    a = make_user("dm_a", role="sales", modules=["quotation"])
    b = make_user("dm_b", role="sales", modules=["quotation"])
    _seed("MQ-DM-002", ["dm_a"], requested_by="dm_b")
    DM.reset_cache()
    for u in (a, b):
        h = _h(client, *u)
        d = client.get("/api/dashboard/mine?fresh=1", headers=h).json()
        g = next(g for g in d["groups"] if g["key"] == "approvals")
        assert g["count"] == client.get("/api/approval-queue/count", headers=h).json()["count"]
    sent = next(g for g in client.get("/api/dashboard/mine?fresh=1", headers=_h(client, *b)).json()["groups"] if g["key"] == "submitted")
    assert "卡在：dm_a" in sent["items"][0]["sub"]
