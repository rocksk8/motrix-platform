"""以案件為中心的獎金分潤 API（SPEC-BONUS §十一／§11.7／W1，2026-09-24）。

§11.6 驗收：金額與尾差、可見性、退回、早期案件手動指定、淨利 ≤ 0 不能建立。
§11.7：業務＝quotations.sales_person；專案＝roles.executor；後勤不自動帶；同名／查無不帶。
W1（使用者「簽核人只能是最高管理者」）：鏈上（含有效代理人）有非 superadmin ⇒ 送審 400。
"""
import json
from datetime import date, timedelta

import pytest
from tests._bonus_insure import insure_all  # noqa: E402


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _set_display(username, display):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (display, username))
        conn.commit()
    finally:
        conn.close()


def _seed_case(no, net=100, finalized=True, sales_id=None, sales_name="", executor=""):
    import db
    data = {"dealTag": "已結案",
            "caseRecord": {"roles": {"filler": "", "sales": "", "executor": executor}},
            "settlement": {"status": "finalized" if finalized else "draft",
                           "summary": {"netProfit": net}}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at,"
            " updated_at, deal_tag, sales_person, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "獎金客戶", "獎金專案", json.dumps(data, ensure_ascii=False),
             "2026-09-01", "2026-09-01", "已結案", sales_name, sales_id))
        conn.commit()
    finally:
        conn.close()


def _set_flow(approvers):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("bonus_approval_flow",
             json.dumps({"includeSubmitterManagerTier": False, "tiers": [
                 {"order": 0, "approvers": [{"username": u, "display_name": u} for u in approvers]}]}),
             "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _delegate(delegator, delegate):
    import db
    today = date.today()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date,"
            " active, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
            (delegator, delegate, (today - timedelta(days=1)).isoformat(),
             (today + timedelta(days=1)).isoformat(), "t", "t"))
        conn.commit()
    finally:
        conn.close()


def _log_actions(no):
    import db
    conn = db.get_db()
    try:
        aid = conn.execute("SELECT id FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone()["id"]
        return [r["action"] for r in conn.execute(
            "SELECT action FROM bonus_case_award_edit_log WHERE award_id=? ORDER BY id", (aid,))]
    finally:
        conn.close()


@pytest.fixture
def people(client, make_user):
    """sa：最高管理者；sa2：另一位（無鏈時核准不可自簽）；s1、p1、p2、a1～a3：名單；cashier：出納。"""
    toks = {}
    for u, role, mods in (("bc_sa", "superadmin", None), ("bc_sa2", "superadmin", None),
                          ("bc_s1", "sales", None), ("bc_p1", "engineer", None), ("bc_p2", "engineer", None),
                          ("bc_a1", "engineer", None), ("bc_a2", "engineer", None), ("bc_a3", "engineer", None),
                          ("bc_cash", "engineer", ["cashier"]), ("bc_other", "sales", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        toks[u] = _login(client, name, pw)
    return toks


def _members_spec():
    return {"sales": [{"username": "bc_s1"}],
            "project": [{"username": "bc_p1"}, {"username": "bc_p2"}],
            "admin": [{"username": "bc_a1"}, {"username": "bc_a2"}, {"username": "bc_a3"}]}


def _create(client, tok, no, **body):
    return client.post(f"/api/bonus/cases/{no}", headers=_auth(tok), json=body)


# ── §11.6 金額與尾差 ─────────────────────────────────────────────────────────

def test_spec_example_amounts_and_remainder(client, people):
    _seed_case("MQ-BC-001", net=100)
    r = _create(client, people["bc_sa"], "MQ-BC-001", members=_members_spec())
    assert r.status_code == 200, r.text
    d = client.get("/api/bonus/cases/MQ-BC-001", headers=_auth(people["bc_sa"])).json()
    got = {(l["category"], l["username"]): l["amount"] for l in d["lines"]}
    assert got == {("sales", "bc_s1"): 5, ("project", "bc_p1"): 1, ("project", "bc_p2"): 1,
                   ("admin", "bc_a1"): 0, ("admin", "bc_a2"): 0, ("admin", "bc_a3"): 0}
    assert d["summary"] == {"poolAmount": 10, "paidTotal": 7, "remainder": 3}
    assert d["status"] == "草稿"


def test_non_positive_net_profit_cannot_create(client, people):
    _seed_case("MQ-BC-002", net=0)
    d = client.get("/api/bonus/cases/MQ-BC-002", headers=_auth(people["bc_sa"])).json()
    assert d["canCreate"] is False and d["status"] == "已精算"
    r = _create(client, people["bc_sa"], "MQ-BC-002")
    assert r.status_code == 400 and "不大於 0" in r.json()["detail"]


def test_unsettled_case_cannot_create(client, people):
    _seed_case("MQ-BC-003", finalized=False)
    d = client.get("/api/bonus/cases/MQ-BC-003", headers=_auth(people["bc_sa"])).json()
    assert d["status"] == "未精算" and d["canCreate"] is False
    assert _create(client, people["bc_sa"], "MQ-BC-003").status_code == 400


def test_only_superadmin_creates(client, people):
    _seed_case("MQ-BC-004")
    assert _create(client, people["bc_s1"], "MQ-BC-004").status_code == 403


# ── §11.7 名單自動帶入 ───────────────────────────────────────────────────────

def test_auto_members_sales_and_executor(client, people):
    _set_display("bc_p1", "執行者甲")
    _seed_case("MQ-BC-010", sales_id=_uid("bc_s1"), executor="執行者甲")
    d = client.get("/api/bonus/cases/MQ-BC-010", headers=_auth(people["bc_sa"])).json()
    assert [m["username"] for m in d["autoMembers"]["sales"]] == ["bc_s1"]
    assert [m["username"] for m in d["autoMembers"]["project"]] == ["bc_p1"]
    assert d["autoMembers"]["admin"] == [] and "手動指定" in d["memberNotes"]["admin"]
    assert _create(client, people["bc_sa"], "MQ-BC-010").status_code == 200
    lines = client.get("/api/bonus/cases/MQ-BC-010", headers=_auth(people["bc_sa"])).json()["lines"]
    assert {(l["category"], l["username"], l["source"]) for l in lines} == {
        ("sales", "bc_s1", "auto_sales"), ("project", "bc_p1", "auto_executor")}


def test_duplicate_display_name_is_not_auto_filled(client, people):
    _set_display("bc_p1", "同名")
    _set_display("bc_p2", "同名")
    _seed_case("MQ-BC-011", executor="同名", sales_name="查無此人")
    d = client.get("/api/bonus/cases/MQ-BC-011", headers=_auth(people["bc_sa"])).json()
    assert d["autoMembers"]["project"] == [] and "請手動指定" in d["memberNotes"]["project"]
    assert d["autoMembers"]["sales"] == [] and "請手動指定" in d["memberNotes"]["sales"]


def test_early_case_without_roles_uses_manual_members(client, people):
    _seed_case("MQ-BC-012")
    r = _create(client, people["bc_sa"], "MQ-BC-012",
                members={"admin": [{"username": "bc_a1", "source": "group:7"}, {"username": "bc_a2", "source": "group:7"}]})
    assert r.status_code == 200, r.text
    lines = client.get("/api/bonus/cases/MQ-BC-012", headers=_auth(people["bc_sa"])).json()["lines"]
    assert {l["source"] for l in lines} == {"group:7"}


# ── 編輯 ──────────────────────────────────────────────────────────────────

def test_edit_draft_custom_ratio_and_log(client, people):
    _seed_case("MQ-BC-020", net=100000)
    _create(client, people["bc_sa"], "MQ-BC-020", members={"sales": [{"username": "bc_s1"}, {"username": "bc_other"}]})
    r = client.put("/api/bonus/cases/MQ-BC-020", headers=_auth(people["bc_sa"]),
                   json={"rate_bp": 1500, "members": {"sales": [{"username": "bc_s1", "person_bp": 7000},
                                                                {"username": "bc_other", "person_bp": 3000}]}})
    assert r.status_code == 200, r.text
    d = client.get("/api/bonus/cases/MQ-BC-020", headers=_auth(people["bc_sa"])).json()
    assert d["summary"]["poolAmount"] == 15000
    assert {l["username"]: l["amount"] for l in d["lines"]} == {"bc_s1": 5250, "bc_other": 2250}
    assert _log_actions("MQ-BC-020") == ["create", "edit"]


def test_bad_ratio_rejected(client, people):
    _seed_case("MQ-BC-021")
    _create(client, people["bc_sa"], "MQ-BC-021")
    r = client.put("/api/bonus/cases/MQ-BC-021", headers=_auth(people["bc_sa"]),
                   json={"split_bp": {"sales": 5000, "project": 3000, "admin": 1000}})
    assert r.status_code == 400 and "100%" in r.json()["detail"]


# ── W1：簽核人只能是最高管理者 ────────────────────────────────────────────────

def test_submit_blocked_when_chain_has_non_superadmin(client, people):
    _seed_case("MQ-BC-030")
    _create(client, people["bc_sa"], "MQ-BC-030", members=_members_spec())
    _set_flow(["bc_sa2", "bc_other"])
    r = client.post("/api/bonus/cases/MQ-BC-030/submit", headers=_auth(people["bc_sa"]))
    assert r.status_code == 400 and "只能是最高管理者" in r.json()["detail"] and "bc_other" in r.json()["detail"]


def test_submit_ok_when_chain_all_superadmin(client, people):
    _seed_case("MQ-BC-031")
    _create(client, people["bc_sa"], "MQ-BC-031", members=_members_spec())
    _set_flow(["bc_sa2"])
    assert client.post("/api/bonus/cases/MQ-BC-031/submit", headers=_auth(people["bc_sa"])).status_code == 200
    r = client.post("/api/bonus/cases/MQ-BC-031/approve", headers=_auth(people["bc_sa2"]))
    assert r.status_code == 200 and r.json()["status"] == "待發放"


def test_submit_blocked_when_delegate_is_non_superadmin(client, people):
    """對照組：鏈上的人都是 superadmin，但其中一位今天把代理權交給非 superadmin ⇒ 擋。"""
    _seed_case("MQ-BC-032")
    _create(client, people["bc_sa"], "MQ-BC-032", members=_members_spec())
    _set_flow(["bc_sa2"])
    _delegate("bc_sa2", "bc_other")
    r = client.post("/api/bonus/cases/MQ-BC-032/submit", headers=_auth(people["bc_sa"]))
    assert r.status_code == 400 and "bc_other" in r.json()["detail"]


def test_no_chain_self_approval_blocked(client, people):
    _seed_case("MQ-BC-033")
    _create(client, people["bc_sa"], "MQ-BC-033", members=_members_spec())
    assert client.post("/api/bonus/cases/MQ-BC-033/submit", headers=_auth(people["bc_sa"])).status_code == 200
    assert client.post("/api/bonus/cases/MQ-BC-033/approve", headers=_auth(people["bc_sa"])).status_code == 403
    assert client.post("/api/bonus/cases/MQ-BC-033/approve", headers=_auth(people["bc_sa2"])).status_code == 200


# ── §11.4 可見性 ─────────────────────────────────────────────────────────────

def _to_payout(client, people, no):
    _seed_case(no)
    _create(client, people["bc_sa"], no, members=_members_spec())
    client.post(f"/api/bonus/cases/{no}/submit", headers=_auth(people["bc_sa"]))


def test_member_cannot_see_before_payout(client, people):
    _to_payout(client, people, "MQ-BC-040")
    assert client.get("/api/bonus/cases/MQ-BC-040", headers=_auth(people["bc_s1"])).status_code == 404
    items = client.get("/api/bonus/cases", headers=_auth(people["bc_s1"])).json()["items"]
    assert all(i["quote_no"] != "MQ-BC-040" for i in items)


def test_member_sees_only_own_line_after_approval(client, people):
    _to_payout(client, people, "MQ-BC-041")
    client.post("/api/bonus/cases/MQ-BC-041/approve", headers=_auth(people["bc_sa2"]))
    r = client.get("/api/bonus/cases/MQ-BC-041", headers=_auth(people["bc_p1"]))
    assert r.status_code == 200, r.text
    raw = r.text
    d = r.json()
    assert d["scope"] == "self" and [l["username"] for l in d["lines"]] == ["bc_p1"]
    for leak in ("bc_s1", "bc_p2", "bc_a1", "poolAmount", "net_profit", "remainder"):
        assert leak not in raw, f"回應裡不可以有 {leak}"
    items = client.get("/api/bonus/cases", headers=_auth(people["bc_p1"])).json()["items"]
    assert [(i["quote_no"], i.get("myAmount")) for i in items] == [("MQ-BC-041", 1)]
    assert client.get("/api/bonus/cases/MQ-BC-041", headers=_auth(people["bc_other"])).status_code == 404


# ── 退回與發放 ───────────────────────────────────────────────────────────────

def test_superadmin_returns_from_payout_and_log_kept(client, people):
    _to_payout(client, people, "MQ-BC-050")
    client.post("/api/bonus/cases/MQ-BC-050/approve", headers=_auth(people["bc_sa2"]))
    assert client.post("/api/bonus/cases/MQ-BC-050/return", headers=_auth(people["bc_sa"]),
                       json={}).status_code == 400
    r = client.post("/api/bonus/cases/MQ-BC-050/return", headers=_auth(people["bc_sa"]), json={"reason": "比例要調"})
    assert r.status_code == 200 and r.json()["status"] == "草稿"
    assert _log_actions("MQ-BC-050") == ["create", "submit", "approve", "return"]


def test_mark_paid_by_cashier_then_cannot_return(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    _to_payout(client, people, "MQ-BC-051")
    client.post("/api/bonus/cases/MQ-BC-051/approve", headers=_auth(people["bc_sa2"]))
    assert client.post("/api/bonus/cases/MQ-BC-051/mark-paid", headers=_auth(people["bc_s1"])).status_code == 403
    r = client.post("/api/bonus/cases/MQ-BC-051/mark-paid", headers=_auth(people["bc_cash"]))
    assert r.status_code == 200 and r.json()["status"] == "已發放"
    r = client.post("/api/bonus/cases/MQ-BC-051/return", headers=_auth(people["bc_sa"]), json={"reason": "x"})
    assert r.status_code == 409


def test_mark_paid_only_from_payout_state(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    _to_payout(client, people, "MQ-BC-052")     # 待審核
    assert client.post("/api/bonus/cases/MQ-BC-052/mark-paid", headers=_auth(people["bc_cash"])).status_code == 409


def test_edit_blocked_once_approved(client, people):
    """原本是 `test_edit_only_in_draft`（待審核 ⇒ 409）。
    2026-09-25 使用者裁示（BN22）：「核准前都能改」——草稿與簽核中（待審核）可改、改了要重新簽；
    待發放以後不可改。⇒ 待審核改為可改（細節見 test_bonus_case_live_recalc_and_resign_2026_09_25.py），
    這一題改守「核准後不可改」。"""
    _to_payout(client, people, "MQ-BC-053")          # 這個 helper 只到待審核
    assert client.put("/api/bonus/cases/MQ-BC-053", headers=_auth(people["bc_sa"]),
                      json={"rate_bp": 2000}).status_code == 200
    assert client.post("/api/bonus/cases/MQ-BC-053/approve", headers=_auth(people["bc_sa2"])).status_code == 200
    r = client.put("/api/bonus/cases/MQ-BC-053", headers=_auth(people["bc_sa"]), json={"rate_bp": 2500})
    assert r.status_code == 409


def test_default_settings_superadmin_only(client, people):
    assert client.put("/api/bonus/cases/settings", headers=_auth(people["bc_s1"]),
                      json={"rate_bp": 2000, "split_bp": {"sales": 5000, "project": 3000, "admin": 2000}}).status_code == 403
    r = client.put("/api/bonus/cases/settings", headers=_auth(people["bc_sa"]),
                   json={"rate_bp": 2000, "split_bp": {"sales": 6000, "project": 2000, "admin": 2000}})
    assert r.status_code == 200, r.text
    assert client.get("/api/bonus/cases/settings", headers=_auth(people["bc_sa"])).json() == {
        "rate_bp": 2000, "split_bp": {"sales": 6000, "project": 2000, "admin": 2000}}
    bad = client.put("/api/bonus/cases/settings", headers=_auth(people["bc_sa"]),
                     json={"rate_bp": 2000, "split_bp": {"sales": 1, "project": 1, "admin": 1}})
    assert bad.status_code == 400


# ── 簽核佇列 ─────────────────────────────────────────────────────────────────

def _queue(client, tok):
    r = client.get("/api/approval-queue", headers=_auth(tok))
    assert r.status_code == 200, r.text
    return [it for g in r.json()["queue"] for it in g["items"] if it.get("type") == "bonus_case_award"]


def test_pending_case_bonus_shows_in_queue_until_approved(client, people):
    _seed_case("MQ-BC-060")
    _create(client, people["bc_sa"], "MQ-BC-060", members=_members_spec())
    _set_flow(["bc_sa2"])
    client.post("/api/bonus/cases/MQ-BC-060/submit", headers=_auth(people["bc_sa"]))
    q = _queue(client, people["bc_sa2"])
    assert [i["quoteNo"] for i in q] == ["MQ-BC-060"], q
    assert q[0]["total"] == 0, "佇列不放金額"
    assert [a["username"] for a in q[0]["currentApprovers"]] == ["bc_sa2"]
    client.post("/api/bonus/cases/MQ-BC-060/approve", headers=_auth(people["bc_sa2"]))
    assert _queue(client, people["bc_sa2"]) == []


def test_queue_badge_counts_pending_case_bonus(client, people):
    _seed_case("MQ-BC-061")
    _create(client, people["bc_sa"], "MQ-BC-061", members=_members_spec())
    _set_flow(["bc_sa2"])
    before = client.get("/api/approval-queue/count", headers=_auth(people["bc_sa2"])).json()
    client.post("/api/bonus/cases/MQ-BC-061/submit", headers=_auth(people["bc_sa"]))
    after = client.get("/api/approval-queue/count", headers=_auth(people["bc_sa2"])).json()
    key = next(k for k, v in after.items() if isinstance(v, int))
    assert after[key] == before.get(key, 0) + 1, (before, after)


# ── C1：出納可見範圍 ─────────────────────────────────────────────────────────

def test_cashier_sees_full_amounts_at_payout_without_profit_or_ratios(client, people):
    """使用者「待發放／已發放的整張，不含淨利與比率」。"""
    _to_payout(client, people, "MQ-BC-070")
    client.post("/api/bonus/cases/MQ-BC-070/approve", headers=_auth(people["bc_sa2"]))
    r = client.get("/api/bonus/cases/MQ-BC-070", headers=_auth(people["bc_cash"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["scope"] == "cashier"
    assert {(l["category"], l["username"]): l["amount"] for l in d["lines"]} == {
        ("sales", "bc_s1"): 5, ("project", "bc_p1"): 1, ("project", "bc_p2"): 1,
        ("admin", "bc_a1"): 0, ("admin", "bc_a2"): 0, ("admin", "bc_a3"): 0}
    assert d["summary"] == {"paidTotal": 7, "remainder": 3}
    for leak in ("net_profit", "rate_bp", "split_json", "split_bp", "person_bp", "pool_amount", "poolAmount",
                 "approval"):
        assert leak not in r.text, f"出納的回應裡不可以有 {leak}"
    items = client.get("/api/bonus/cases", headers=_auth(people["bc_cash"])).json()["items"]
    assert [(i["quote_no"], i.get("paidTotal")) for i in items] == [("MQ-BC-070", 7)]


def test_cashier_cannot_see_pending_approval(client, people):
    _to_payout(client, people, "MQ-BC-071")          # 待審核
    assert client.get("/api/bonus/cases/MQ-BC-071", headers=_auth(people["bc_cash"])).status_code == 404
    assert client.get("/api/bonus/cases", headers=_auth(people["bc_cash"])).json()["items"] == []


def test_member_still_sees_only_own_line_when_cashier_rule_exists(client, people):
    _to_payout(client, people, "MQ-BC-072")
    client.post("/api/bonus/cases/MQ-BC-072/approve", headers=_auth(people["bc_sa2"]))
    d = client.get("/api/bonus/cases/MQ-BC-072", headers=_auth(people["bc_a2"])).json()
    assert d["scope"] == "self" and [l["username"] for l in d["lines"]] == ["bc_a2"]
