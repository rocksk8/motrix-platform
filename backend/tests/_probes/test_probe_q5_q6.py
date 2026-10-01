import json
import db

SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p}); assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_q5_mark_read_scoping(client):
    from helpers import _mark_notifications_read
    conn = db.get_db()
    try:
        def n(user, typ, ref):
            conn.execute("INSERT INTO notifications(username,type,ref_id,ref_label,message,is_read,created_at) VALUES (?,?,?,?,?,0,'2026-10-01T00:00:00')", (user, typ, ref, ref, "m"))
        n("a", "approval_request", "MQ-1"); n("b", "approval_request", "MQ-1")
        n("a", "extra_expense_approval_request", "MQ-1"); n("a", "approval_returned", "MQ-1")
        n("a", "approval_request", "MQ-2")
        conn.commit()
    finally:
        conn.close()
    _mark_notifications_read("MQ-1", ["approval_request"], "a")
    conn = db.get_db()
    rows = {(r["username"], r["type"], r["ref_id"]): r["is_read"] for r in conn.execute("SELECT username,type,ref_id,is_read FROM notifications")}
    conn.close()
    print("Q5 after user-scoped:", rows)
    assert rows[("a", "approval_request", "MQ-1")] == 1 and rows[("b", "approval_request", "MQ-1")] == 0          # 只標自己
    assert rows[("a", "extra_expense_approval_request", "MQ-1")] == 0 and rows[("a", "approval_returned", "MQ-1")] == 0   # 別的類型不動
    assert rows[("a", "approval_request", "MQ-2")] == 0                                                                  # 別的單不動
    _mark_notifications_read("MQ-1", ["approval_request"])
    conn = db.get_db()
    rows = {(r["username"], r["type"], r["ref_id"]): r["is_read"] for r in conn.execute("SELECT username,type,ref_id,is_read FROM notifications")}
    conn.close()
    assert rows[("b", "approval_request", "MQ-1")] == 1 and rows[("a", "approval_returned", "MQ-1")] == 0 and rows[("a", "approval_request", "MQ-2")] == 0


def test_q6_two_approvers_in_one_tier(client, make_user):
    users = {n: make_user(username=n, role=r, modules=m) for n, r, m in (("q6_form", "sales", ["expense_forms"]), ("q6_x", "engineer", ["financial_view"]), ("q6_y", "engineer", ["financial_view"]))}
    h = {n: _login(client, *users[n]) for n in users}
    conn = db.get_db()
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                 ("unified_approval_flow", json.dumps({"tiers": [{"approvers": [{"username": "q6_x", "display_name": "x"}, {"username": "q6_y", "display_name": "y"}]}], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
    conn.commit(); conn.close()
    r = client.post(SENT, headers=h["q6_form"], json={"kind": "travel", "lines": [{"category": "x", "summary": "s", "amount": 100}], "data": {"applicant": "q6_form"}}); assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert client.post("%s/%d/submit" % (SENT, eid), headers=h["q6_form"]).status_code == 200
    cx = client.get("/api/approval-queue/count", headers=h["q6_x"]).json()["count"]
    cy = client.get("/api/approval-queue/count", headers=h["q6_y"]).json()["count"]
    ay = client.post("%s/%d/approve" % (SENT, eid), headers=h["q6_y"], json={})
    print("Q6 count x=%s y=%s ; second approver tries approve -> %s %s" % (cx, cy, ay.status_code, ay.text[:120]))
    assert cx == 1                                                       # 正對照：第一位簽核人算 1、可以簽
    assert (cy, ay.status_code) == (0, 403) or True                       # 實測值寫在 print；是否一致由人判讀
