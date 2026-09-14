"""2026-08-28（模組逐步檢查：簽核佇列）：簽核代理人在佇列/角標數字裡「隱形」的修正。

check_approve_permission() 早就支援代理人真的能完成核准動作，但
get_approval_queue()（佇列列表）／get_approval_queue_count()（topbar 角標）
原本只比對 currentApprovers 的 username 是否等於自己，代理人登入後完全看不到
任何項目被標成「輪到我」，等於代理人設定了也沒用（除非剛好知道確切單號直接
開頁面）。"""
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


def _insert_delegate(delegator, delegate, start_date, end_date):
    import db
    conn = db.get_db()
    try:
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, "
            "reason, active, created_by, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?,?)",
            (delegator, delegate, start_date, end_date, "測試", delegator, now, now),
        )
        conn.commit()
    finally:
        conn.close()


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
                "requestedByDisplay": "someone_else",
                "requestedAt": "2026-08-01T00:00:00",
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


def test_queue_includes_my_delegated_for(client, make_user):
    delegator, _ = make_user(username="corbin_q", role="superadmin")
    standin, standin_pw = make_user(username="standin_q", role="admin")
    _insert_delegate("corbin_q", "standin_q", _iso(-1), _iso(1))

    token = _login(client, standin, standin_pw)
    r = client.get("/api/approval-queue", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["myDelegatedFor"] == ["corbin_q"]


def test_queue_count_includes_delegated_items(client, make_user):
    delegator, _ = make_user(username="corbin_c", role="superadmin")
    standin, standin_pw = make_user(username="standin_c", role="admin")
    _insert_pending_quotation("MQ-DELQ-001", "corbin_c", "高晟耀")

    standin_token = _login(client, standin, standin_pw)
    r0 = client.get("/api/approval-queue/count", headers=_auth(standin_token))
    assert r0.status_code == 200, r0.text
    assert r0.json()["count"] == 0  # 還沒有代理設定時，不該算進來

    _insert_delegate("corbin_c", "standin_c", _iso(-1), _iso(1))
    r1 = client.get("/api/approval-queue/count", headers=_auth(standin_token))
    assert r1.status_code == 200, r1.text
    assert r1.json()["count"] == 1


def test_queue_items_show_up_for_delegate(client, make_user):
    delegator, _ = make_user(username="corbin_i", role="superadmin")
    standin, standin_pw = make_user(username="standin_i", role="admin")
    _insert_pending_quotation("MQ-DELQ-002", "corbin_i", "高晟耀")
    _insert_delegate("corbin_i", "standin_i", _iso(-1), _iso(1))

    standin_token = _login(client, standin, standin_pw)
    r = client.get("/api/approval-queue", headers=_auth(standin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    all_items = [it for g in body["queue"] for it in g["items"]]
    match = next(it for it in all_items if it["quoteNo"] == "MQ-DELQ-002")
    # 委託人 corbin_i 仍是 currentApprovers 裡登記的 username（tiers 本身不改）
    assert match["currentApprovers"][0]["username"] == "corbin_i"
    # 但 myDelegatedFor 讓前端 canApprove()/myPendingCount 知道 standin_i 現在也算數
    assert "corbin_i" in body["myDelegatedFor"]


def test_expired_delegation_not_counted(client, make_user):
    delegator, _ = make_user(username="corbin_e", role="superadmin")
    standin, standin_pw = make_user(username="standin_e", role="admin")
    _insert_pending_quotation("MQ-DELQ-003", "corbin_e", "高晟耀")
    _insert_delegate("corbin_e", "standin_e", _iso(-10), _iso(-5))  # 已過期

    standin_token = _login(client, standin, standin_pw)
    r = client.get("/api/approval-queue", headers=_auth(standin_token))
    assert r.status_code == 200, r.text
    assert r.json()["myDelegatedFor"] == []

    r2 = client.get("/api/approval-queue/count", headers=_auth(standin_token))
    assert r2.json()["count"] == 0
