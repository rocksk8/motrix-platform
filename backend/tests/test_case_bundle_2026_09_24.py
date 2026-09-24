"""開案件的合併端點 GET /api/quotations/{no}/case-bundle（CM8，2026-09-24）。

每一段都是直接呼叫既有端點函式 ⇒ 內容與權限必須與分開打逐字相同。這裡用「分開打一次、合併打一次、
比對」驗，不重寫預期值（預期值寫死的話，端點改了兩邊一起錯也看不出來）。
"""
import json

import pytest

NO = "MQ-BUNDLE-001"
PARTS = {
    "health": "/api/quotations/{no}/close-gates",
    "vouchers": "/api/vouchers/by-case/{no}",
    "dispatches": "/api/contractor-dispatches?quote_no={no}",
    "shippingNotes": "/api/shipping-notes?quote_no={no}",
    "completionNotes": "/api/completion-notes?quote_no={no}",
    "updates": "/api/quotations/{no}/updates",
    "extraExpenses": "/api/quotations/{no}/extra-expenses",
}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(assigned=()):
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100, "received": False}]}}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", json.dumps([_uid(u) for u in assigned])))
        conn.execute("INSERT INTO case_updates (quote_no, author, content, type, created_at) VALUES (?,?,?,?,?)",
                     (NO, "someone", "第一則動態", "comment", now))
        conn.commit()
    finally:
        conn.close()


def _separately(client, h):
    out = {}
    for k, url in PARTS.items():
        r = client.get(url.format(no=NO), headers=h)
        out[k] = {"ok": True, "data": r.json()} if r.status_code == 200 else {"ok": False, "status": r.status_code}
    return out


@pytest.mark.parametrize("role,modules", [("admin", None), ("sales", None),
                                          ("engineer", ["case_manage"]), ("engineer", ["case_manage", "cashier"])])
def test_every_part_equals_the_separate_endpoint(client, make_user, role, modules):
    u = make_user(username=f"bd_{role}_{len(modules or [])}", role=role, modules=modules)
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    b = client.get(f"/api/quotations/{NO}/case-bundle", headers=h)
    assert b.status_code == 200, b.text
    body = b.json()
    assert body["quotation"] == client.get(f"/api/quotations/{NO}", headers=h).json()
    sep = _separately(client, h)
    for k, want in sep.items():
        got = body["parts"][k]
        assert got["ok"] == want["ok"], (k, got, want)
        if want["ok"]:
            assert got["data"] == want["data"], k
        else:
            assert got["status"] == want["status"], (k, got, want)
    assert set(body["parts"]) == set(PARTS)


def test_updates_part_has_the_seeded_comment(client, make_user):
    """量尺：上面那題若每段都是空的也會綠——這裡確認真的帶到了資料。"""
    u = make_user(username="bd_probe", role="admin")
    _seed()
    body = client.get(f"/api/quotations/{NO}/case-bundle", headers=_login(client, *u)).json()
    assert any("第一則動態" in json.dumps(x, ensure_ascii=False) for x in body["parts"]["updates"]["data"])


def test_no_access_to_the_case_means_no_bundle(client, make_user):
    u = make_user(username="bd_out", role="engineer", modules=["case_manage"])
    _seed()
    h = _login(client, *u)
    assert client.get(f"/api/quotations/{NO}", headers=h).status_code == 403
    assert client.get(f"/api/quotations/{NO}/case-bundle", headers=h).status_code == 403
