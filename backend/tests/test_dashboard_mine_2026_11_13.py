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
    r = DM.build_mine({"id": 1, "username": "u", "role": "sales"})
    assert r["partial"] is True and "errors" not in r
    assert [g["key"] for g in r["groups"]] == ["approvals", "zz"]
    assert r["empty"] is False


def test_empty_when_all_zero(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    monkeypatch.setattr(DM, "_approval_groups", lambda u, now: [DM._group("approvals", "待我簽核", [], order=10)])
    assert DM.build_mine({"id": 2, "username": "u2", "role": "sales"})["empty"] is True


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
    assert set(d) >= {"groups", "empty", "partial", "generatedAt"} and d["partial"] is False
    keys = [g["key"] for g in d["groups"]]
    assert keys[0] == "approvals" and "my_cases" in keys
    assert "receivable_overdue" not in keys          # 業務沒有財務權限 ⇒ 沒有「錢」那一組
    h = _h(client, *u)
    assert client.get("/api/dashboard/mine", headers=h).json()["groups"] == d["groups"]   # 同一人連續讀（提供者分組命中快取）結果一致
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


def test_cache_is_per_user_never_shared(client, make_user):
    """30 秒快取以使用者為單位：A 剛讀過（命中快取）時 B 讀到的仍是 B 自己的，不是 A 的；B 看不到 A 才有的分組。"""
    sa = make_user("dm_cache_sa", role="superadmin")
    sales = make_user("dm_cache_sales", role="sales", modules=["quotation"])
    _seed("MQ-DM-CACHE", ["dm_cache_sa"], requested_by="dm_cache_sales")
    DM.reset_cache()
    a1 = client.get("/api/dashboard/mine", headers=_h(client, *sa)).json()
    b1 = client.get("/api/dashboard/mine", headers=_h(client, *sales)).json()
    a2 = client.get("/api/dashboard/mine", headers=_h(client, *sa)).json()          # 命中快取
    assert a1["groups"] == a2["groups"]
    ka, kb = {g["key"] for g in a1["groups"]}, {g["key"] for g in b1["groups"]}
    assert "receivable_overdue" in ka and "receivable_overdue" not in kb and "stuck" not in kb
    appr = next(g for g in a1["groups"] if g["key"] == "approvals")["count"]
    assert appr == 1 and next(g for g in b1["groups"] if g["key"] == "approvals")["count"] == 0
    assert any(g["key"] == "submitted" for g in b1["groups"]) and not any(g["key"] == "submitted" for g in a1["groups"])


def test_cache_key_changes_with_permissions(client, make_user):
    """改權限（模組勾選）後不需等 30 秒：快取鍵含權限指紋，下一次讀到新的分組。"""
    import db, json
    u = make_user("dm_perm", role="sales", modules=["customer"])
    h = _h(client, *u)
    DM.reset_cache()
    assert "my_cases" not in [g["key"] for g in client.get("/api/dashboard/mine", headers=h).json()["groups"]]
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET modules=? WHERE username=?", (json.dumps(["customer", "case_manage"]), "dm_perm"))
        conn.commit()
    finally:
        conn.close()
    assert "my_cases" in [g["key"] for g in client.get("/api/dashboard/mine", headers=h).json()["groups"]]


# ── 審查 hichan-12（2026-11-13）M1／M2／M3／L1／L2／L3／L5 ─────────────────────────────────────────
def test_m1_approvals_group_is_never_cached(client, make_user):
    """簽完回首頁：不等 30 秒，「待我簽核」數字立刻與角標一致。"""
    a = make_user("dm_m1_a", role="sales", modules=["quotation"])
    h = _h(client, *a)
    DM.reset_cache()
    _seed("MQ-DM-M1", ["dm_m1_a"], requested_by="dm_m1_x")
    n1 = next(g for g in client.get("/api/dashboard/mine", headers=h).json()["groups"] if g["key"] == "approvals")["count"]
    assert n1 == 1
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET status='已核准' WHERE quote_no='MQ-DM-M1'")        # 別人簽掉／退回／撤回
        conn.commit()
    finally:
        conn.close()
    g = next(g for g in client.get("/api/dashboard/mine", headers=h).json()["groups"] if g["key"] == "approvals")   # 沒帶 fresh
    assert g["count"] == 0 == client.get("/api/approval-queue/count", headers=h).json()["count"]


def test_m2_delegation_change_takes_effect_immediately(client, make_user, monkeypatch):
    """代理生效／撤銷後，立刻反映；撤銷後原代理人不會在快取期間還看到被代理人的單。"""
    make_user("dm_m2_boss", role="sales", modules=["quotation"])
    dele = make_user("dm_m2_dele", role="sales", modules=["quotation"])
    _seed("MQ-DM-M2", ["dm_m2_boss"], requested_by="dm_m2_x")
    hd = _h(client, *dele)
    DM.reset_cache()

    def cnt():
        return next(g for g in client.get("/api/dashboard/mine", headers=hd).json()["groups"] if g["key"] == "approvals")["count"]
    assert cnt() == 0
    from routers import approval_queue as AQ
    monkeypatch.setattr(AQ, "active_delegators_for", lambda conn, username: {"dm_m2_boss"} if username == "dm_m2_dele" else set())
    assert cnt() == 1
    monkeypatch.setattr(AQ, "active_delegators_for", lambda conn, username: set())
    assert cnt() == 0


def test_m3_failure_is_not_empty_and_not_cached(monkeypatch):
    from core import registry
    calls = {"n": 0}

    def flaky(u):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("x")
        return [{"key": "ok", "title": "好", "count": 3}]
    monkeypatch.setattr(registry, "providers", lambda cap: {"p": flaky} if cap == "dashboard.mine_groups" else {})
    monkeypatch.setattr(DM, "_approval_groups", lambda u, now: [DM._group("approvals", "待我簽核", [], order=10)])
    DM.reset_cache()
    u = {"id": 77, "username": "m3", "role": "sales"}
    r1 = DM.build_mine(u)
    assert r1["partial"] is True and r1["empty"] is False            # 讀不到 ≠ 沒事
    r2 = DM.build_mine(u)                                              # 失敗的結果沒進快取 ⇒ 馬上重試成功
    assert r2["partial"] is False and [g["key"] for g in r2["groups"]] == ["approvals", "ok"]
    DM.build_mine(u)
    assert calls["n"] == 2                                             # 成功的結果才進快取


def test_m3_approvals_failure_is_partial(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "providers", lambda cap: {})

    def boom(u, now):
        raise RuntimeError("x")
    monkeypatch.setattr(DM, "_approval_groups", boom)
    r = DM.build_mine({"id": 5, "username": "m3b", "role": "sales"})
    assert r["partial"] is True and r["empty"] is False


def test_review_cache_key_has_user_id_and_demo_flag(monkeypatch):
    k1 = DM._cache_key({"id": 1, "username": "x", "role": "sales", "modules": "[]"})
    k2 = DM._cache_key({"id": 2, "username": "x", "role": "sales", "modules": "[]"})
    assert k1 != k2                                                    # 刪掉重建同名帳號
    monkeypatch.setattr(DM, "is_demo_mode", lambda: True)
    assert DM._cache_key({"id": 1, "username": "x", "role": "sales", "modules": "[]"}) != k1       # 示範 vs 正式


def test_review_fresh_cannot_hammer_providers(monkeypatch):
    from core import registry
    calls = {"n": 0}

    def p(u):
        calls["n"] += 1
        return [{"key": "k", "title": "T", "count": 1}]
    monkeypatch.setattr(registry, "providers", lambda cap: {"p": p} if cap == "dashboard.mine_groups" else {})
    monkeypatch.setattr(DM, "_approval_groups", lambda u, now: [])
    DM.reset_cache()
    u = {"id": 9, "username": "l2", "role": "sales"}
    for _ in range(20):
        DM.build_mine(u, fresh=True)
    assert calls["n"] == 1                                             # 5 秒內不論帶不帶 fresh 都只算一次


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "JaVaScRiPt:x", "data:text/html,x", "//evil.example/x", "vbscript:x",
                                 "pages\\x", "pages/a\n.html", " javascript:x"])
def test_review_unsafe_hrefs_are_dropped(bad):
    g = DM._clean_group({"key": "k", "title": "T", "href": bad, "items": [{"title": "a", "href": bad}]})
    assert g["href"] == "" and g["items"][0]["href"] == ""


@pytest.mark.parametrize("good", ["pages/case-management.html?quick=mine,stage_overdue", "pages/approval-queue.html", "/pages/x.html#a",
                                  "https://example.com/a?b=c", "http://example.com/"])
def test_review_safe_hrefs_pass(good):
    assert DM._clean_group({"key": "k", "title": "T", "href": good})["href"] == good


def test_review_finance_without_case_module_gets_count_but_no_link(client, make_user):
    u = make_user("dm_l5_fin", role="finance", modules=[])
    DM.reset_cache()
    g = next((g for g in client.get("/api/dashboard/mine", headers=_h(client, *u)).json()["groups"] if g["key"] == "receivable_overdue"), None)
    assert g is not None, "財務角色應該有「應收款項追蹤」這一組"
    assert g["href"] == "" and all(i["href"] == "" for i in g["items"])
