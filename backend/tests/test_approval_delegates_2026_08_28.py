"""2026-08-28 企業管理優化：簽核代理人機制。CRUD 端點 + 核心整合測試（證明
代理人真的能在報價單簽核流程裡代替委託人完成簽核，不是只有 CRUD 資料表能動）。"""
import json
from datetime import date, timedelta


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _iso(days_offset):
    return (date.today() + timedelta(days=days_offset)).isoformat()


def _insert_pending_quotation(quote_no, approver_username, approver_display="approver"):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "approval": {
                "tiers": [
                    {"order": 0, "approvers": [
                        {"username": approver_username, "displayName": approver_display,
                         "status": "pending", "approvedAt": None},
                    ]},
                ],
                "currentTier": 0,
                "requestedBy": "someone_else",
            },
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "測試客戶", "測試專案", 100000, 95238, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "2026-01-05"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_delegate(delegator, delegate, start_date, end_date, active=1):
    import db
    conn = db.get_db()
    try:
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, "
            "reason, active, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (delegator, delegate, start_date, end_date, "測試", active, delegator, now, now),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


# ── 核心整合：代理人真的能代替委託人完成簽核 ─────────────────────────────────

def test_delegate_can_approve_on_behalf_of_delegator(client, make_user):
    corbin, corbin_pw = make_user(username="corbin", role="superadmin")
    standin, standin_pw = make_user(username="standin", role="admin")
    standin_token = _login(client, standin, standin_pw)

    _insert_pending_quotation("MQ-DELEGATE-001", "corbin", "高晟耀")

    # 沒有代理設定時，standin 不能代替 corbin 簽核
    r0 = client.post("/api/quotations/MQ-DELEGATE-001/approve", headers=_auth(standin_token), json={})
    assert r0.status_code == 403, r0.text

    _insert_delegate("corbin", "standin", _iso(-1), _iso(1))

    r1 = client.post("/api/quotations/MQ-DELEGATE-001/approve", headers=_auth(standin_token), json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["allDone"] is True

    r2 = client.get("/api/quotations/MQ-DELEGATE-001", headers=_auth(standin_token))
    assert r2.json()["status"] == "已送出"


def test_delegate_outside_date_range_cannot_approve(client, make_user):
    corbin, corbin_pw = make_user(username="corbin2", role="superadmin")
    standin, standin_pw = make_user(username="standin2", role="admin")
    standin_token = _login(client, standin, standin_pw)

    _insert_pending_quotation("MQ-DELEGATE-002", "corbin2", "高晟耀")
    _insert_delegate("corbin2", "standin2", _iso(-10), _iso(-5))  # 已過期

    r = client.post("/api/quotations/MQ-DELEGATE-002/approve", headers=_auth(standin_token), json={})
    assert r.status_code == 403, r.text


def test_inactive_delegate_cannot_approve(client, make_user):
    corbin, corbin_pw = make_user(username="corbin3", role="superadmin")
    standin, standin_pw = make_user(username="standin3", role="admin")
    standin_token = _login(client, standin, standin_pw)

    _insert_pending_quotation("MQ-DELEGATE-003", "corbin3", "高晟耀")
    _insert_delegate("corbin3", "standin3", _iso(-1), _iso(1), active=0)  # 已停用

    r = client.post("/api/quotations/MQ-DELEGATE-003/approve", headers=_auth(standin_token), json={})
    assert r.status_code == 403, r.text


def test_delegate_can_reject_on_behalf_of_delegator(client, make_user):
    corbin, corbin_pw = make_user(username="corbin4", role="superadmin")
    standin, standin_pw = make_user(username="standin4", role="admin")
    standin_token = _login(client, standin, standin_pw)

    _insert_pending_quotation("MQ-DELEGATE-004", "corbin4", "高晟耀")
    _insert_delegate("corbin4", "standin4", _iso(-1), _iso(1))

    r = client.post("/api/quotations/MQ-DELEGATE-004/reject", headers=_auth(standin_token),
                     json={"reason": "測試退回"})
    assert r.status_code == 200, r.text


# ── CRUD 端點 ────────────────────────────────────────────────────────────────

def test_self_service_create_delegate(client, make_user):
    username, password = make_user(role="sales")
    make_user(username="colleague", role="sales")
    token = _login(client, username, password)

    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": "colleague", "startDate": _iso(0), "endDate": _iso(7), "reason": "休假",
    })
    assert r.status_code == 201, r.text

    r2 = client.get("/api/approval-delegates", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["delegatorUsername"] == username
    assert rows[0]["delegateUsername"] == "colleague"


def test_cannot_set_delegator_to_someone_else_unless_superadmin(client, make_user):
    username, password = make_user(role="sales")
    make_user(username="othercolleague", role="sales")
    make_user(username="thirdparty", role="sales")
    token = _login(client, username, password)

    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegatorUsername": "othercolleague", "delegateUsername": "thirdparty",
        "startDate": _iso(0), "endDate": _iso(7),
    })
    assert r.status_code == 403, r.text


def test_superadmin_can_set_delegate_for_others(client, make_user):
    sa_username, sa_password = make_user(role="superadmin")
    make_user(username="onleave", role="admin")
    make_user(username="fillin", role="admin")
    sa_token = _login(client, sa_username, sa_password)

    r = client.post("/api/approval-delegates", headers=_auth(sa_token), json={
        "delegatorUsername": "onleave", "delegateUsername": "fillin",
        "startDate": _iso(0), "endDate": _iso(7),
    })
    assert r.status_code == 201, r.text


def test_cannot_delegate_to_self(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": username, "startDate": _iso(0), "endDate": _iso(7),
    })
    assert r.status_code == 400, r.text


def test_end_date_before_start_date_rejected(client, make_user):
    username, password = make_user(role="sales")
    make_user(username="colleague2", role="sales")
    token = _login(client, username, password)
    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": "colleague2", "startDate": _iso(7), "endDate": _iso(0),
    })
    assert r.status_code == 400, r.text


def test_unknown_delegate_username_rejected(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": "no_such_user", "startDate": _iso(0), "endDate": _iso(7),
    })
    assert r.status_code == 404, r.text


def test_deactivate_by_delegator(client, make_user):
    username, password = make_user(role="sales")
    make_user(username="colleague3", role="sales")
    token = _login(client, username, password)
    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": "colleague3", "startDate": _iso(0), "endDate": _iso(7),
    })
    delegate_id = r.json()["id"]

    r2 = client.patch(f"/api/approval-delegates/{delegate_id}/deactivate", headers=_auth(token))
    assert r2.status_code == 200, r2.text

    r3 = client.get("/api/approval-delegates", headers=_auth(token))
    assert r3.json()[0]["active"] is False


def test_deactivate_by_unrelated_user_forbidden(client, make_user):
    username, password = make_user(role="sales")
    make_user(username="colleague4", role="sales")
    token = _login(client, username, password)
    r = client.post("/api/approval-delegates", headers=_auth(token), json={
        "delegateUsername": "colleague4", "startDate": _iso(0), "endDate": _iso(7),
    })
    delegate_id = r.json()["id"]

    outsider, outsider_pw = make_user(username="outsider", role="sales")
    outsider_token = _login(client, outsider, outsider_pw)
    r2 = client.patch(f"/api/approval-delegates/{delegate_id}/deactivate", headers=_auth(outsider_token))
    assert r2.status_code == 403, r2.text
