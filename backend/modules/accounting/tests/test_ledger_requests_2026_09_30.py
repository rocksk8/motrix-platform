# -*- coding: utf-8 -*-
"""總帳申請（會計規定 C 類）：財務人員的結帳／重開期間／年度決算／期初批次送申請，最高管理者核准後自動執行。
涵蓋：直接動作端點對財務回 pending（不執行）、最高管理者仍直接執行、核准＝執行、退回要原因、撤回只限申請人、
重複申請擋、核准時執行失敗申請維持待核准、可見範圍、待我簽核佇列提供者、通知信對象、migration 冪等。"""
import pytest

import db
from modules.accounting.api import ledger_requests as LR
from modules.accounting.ledger import periods as P

_YEAR = [2140]


def _login(client, make_user, name, role="staff", modules=("finance",)):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = list(modules)
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def world(client, make_user, monkeypatch):
    sent = []
    for n in ("notify_ledger_action_submitted", "notify_ledger_action_approved", "notify_ledger_action_returned"):
        monkeypatch.setattr(LR._notify, n, (lambda name: lambda *a: sent.append((name, a)))(n))
    fu, fin = _login(client, make_user, "rq_fin")
    su, sup = _login(client, make_user, "rq_sup", role="superadmin")
    ou, oth = _login(client, make_user, "rq_oth")
    _YEAR[0] += 1
    c = db.get_db()
    try:
        P.create_year(c, _YEAR[0], "t")
        c.commit()
        pid = c.execute("SELECT id FROM gl_periods WHERE year=? AND period_no=1", (_YEAR[0],)).fetchone()[0]
    finally:
        c.close()
    return {"fin": fin, "sup": sup, "oth": oth, "fu": fu, "su": su, "ou": ou, "pid": pid, "year": _YEAR[0], "sent": sent}


def _pstatus(pid):
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM gl_periods WHERE id=?", (pid,)).fetchone()[0]
    finally:
        c.close()


def test_finance_close_becomes_a_pending_request_and_nothing_is_executed(client, world):
    r = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={})
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["request_no"].startswith("LA-")
    assert _pstatus(world["pid"]) == "open"
    assert [n for n, _ in world["sent"]] == ["notify_ledger_action_submitted"] and world["su"] in world["sent"][0][1][3]      # 通知最高管理者
    dup = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={})
    assert dup.status_code == 409 and "已經送出同一個申請" in dup.json()["detail"]


def test_superadmin_still_executes_directly(client, world):
    r = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["sup"], json={})
    assert r.status_code == 200 and r.json().get("pending") is None and _pstatus(world["pid"]) == "closed"
    assert world["sent"] == []


def test_approve_executes_the_action_and_notifies_the_requester(client, world):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    assert client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["fin"]).status_code == 403          # 申請人不能自己核准
    r = client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"])
    assert r.status_code == 200 and r.json()["allDone"] is True and r.json()["request"]["status"] == "已核准"
    assert _pstatus(world["pid"]) == "closed"
    assert world["sent"][-1][0] == "notify_ledger_action_approved" and world["sent"][-1][1][3] == world["fu"]
    assert client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"]).status_code == 409           # 不能重複核准


def test_send_back_needs_a_reason_and_executes_nothing(client, world):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    assert client.post("/api/ledger/action-requests/%d/send-back" % rid, headers=world["sup"], json={}).status_code == 400
    r = client.post("/api/ledger/action-requests/%d/send-back" % rid, headers=world["sup"], json={"reason": "本月還有傳票沒過帳"})
    assert r.status_code == 200 and r.json()["request"]["status"] == "已退回" and _pstatus(world["pid"]) == "open"
    assert world["sent"][-1][0] == "notify_ledger_action_returned" and "沒過帳" in world["sent"][-1][1][2]
    assert client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"]).status_code == 409           # 退回後不能再核准


def test_withdraw_only_by_the_requester_while_pending(client, world):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    assert client.post("/api/ledger/action-requests/%d/withdraw" % rid, headers=world["oth"]).status_code == 400            # 別人不能撤回
    r = client.post("/api/ledger/action-requests/%d/withdraw" % rid, headers=world["fin"])
    assert r.status_code == 200 and r.json()["request"]["status"] == "已撤回"
    assert client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"]).status_code == 409
    again = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={})                        # 撤回後可以重新申請
    assert again.status_code == 200 and again.json()["pending"] is True


def test_approve_that_cannot_execute_stays_pending_with_the_reason(client, world):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    assert client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["sup"], json={}).status_code == 200      # 送出後，期間被別人直接結掉了
    r = client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"])                                   # 核准時做不了
    assert r.status_code == 400 and "只有開放的期間" in r.json()["detail"]
    row = client.get("/api/ledger/action-requests/%d" % rid, headers=world["sup"]).json()
    assert row["status"] == "待審核" and row["decided_by"] == ""                                     # 沒有「已核准但沒執行」


def test_impossible_requests_are_refused_up_front(client, world):
    fin = world["fin"]
    assert client.post("/api/ledger/periods/%d/reopen" % world["pid"], headers=fin, json={"reason": "補帳"}).status_code == 400     # 開放的期間不需要重開
    assert client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["sup"], json={}).status_code == 200
    assert client.post("/api/ledger/periods/%d/close" % world["pid"], headers=fin, json={}).status_code == 400                      # 已結帳不能再結
    r = client.post("/api/ledger/years/1234/close", headers=fin, json={})
    assert r.status_code == 400 and "不存在" in r.json()["detail"]


def test_reopen_needs_a_reason_up_front_and_year_close_and_opening_validate(client, world):
    assert client.post("/api/ledger/periods/%d/reopen" % world["pid"], headers=world["fin"], json={}).status_code == 400
    r = client.post("/api/ledger/years/%d/close" % world["year"], headers=world["fin"], json={})
    assert r.status_code == 200 and r.json()["pending"] is True
    assert client.post("/api/ledger/opening", headers=world["fin"], json={"year": world["year"], "opening_date": "x", "rows": [], "items": []}).status_code == 400
    ok = client.post("/api/ledger/opening", headers=world["fin"], json={"year": world["year"], "opening_date": "%d-01-01" % world["year"], "rows": [{"account_code": "1113", "debit": 100, "credit": 0}, {"account_code": "3111", "debit": 0, "credit": 100}]})
    assert ok.status_code == 200 and ok.json()["pending"] is True


def test_visibility_queue_provider_and_permissions(client, world, make_user):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    mine = client.get("/api/ledger/action-requests", headers=world["fin"]).json()
    assert [x["id"] for x in mine["requests"]] == [rid] and mine["is_superadmin"] is False
    assert client.get("/api/ledger/action-requests", headers=world["oth"]).json()["requests"] == []                         # 別人看不到
    assert client.get("/api/ledger/action-requests/%d" % rid, headers=world["oth"]).status_code == 404
    assert [x["id"] for x in client.get("/api/ledger/action-requests", headers=world["sup"]).json()["requests"]] == [rid]
    _, nomod = _login(client, make_user, "rq_none", modules=())
    assert client.get("/api/ledger/action-requests", headers=nomod).status_code == 403
    c = db.get_db()
    try:
        items = [i for i in LR.queue_items(c) if i["requestId"] == rid]
    finally:
        c.close()
    assert len(items) == 1 and items[0]["type"] == "ledger_action" and items[0]["tierCount"] == 1 and items[0]["requestedBy"] == world["fu"]
    assert any(a["username"] == world["su"] for a in items[0]["currentApprovers"])
    q = client.get("/api/approval-queue", headers=world["sup"]).json()
    groups = q if isinstance(q, list) else (q.get("queue") or q.get("groups") or [])
    rows = [it for g in groups for it in (g.get("items") or [])]                                       # 佇列依申請人分組
    assert any(i.get("type") == "ledger_action" and i.get("requestId") == rid for i in rows)


def test_migration_0002_is_idempotent(client):
    import importlib
    m = importlib.import_module("modules.accounting.migrations.0002_ledger_action_requests")
    c = db.get_db()
    try:
        m.up(c)
        m.up(c)
        cols = [r[1] for r in c.execute("PRAGMA table_info(gl_action_requests)")]
        assert cols.count("request_no") == 1 and "approval_json" in cols
    finally:
        c.close()


def test_executes_as_the_requester_not_the_approver(client, world):
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    client.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"])
    c = db.get_db()
    try:
        by = c.execute("SELECT closed_by FROM gl_periods WHERE id=?", (world["pid"],)).fetchone()[0]
        who = c.execute("SELECT decided_by FROM gl_action_requests WHERE id=?", (rid,)).fetchone()[0]
    finally:
        c.close()
    assert by == world["fu"] and who == world["su"]                     # 帳上結帳人＝申請人；核准人記在申請上


def test_concurrent_approves_execute_once_and_only_one_wins(client, world):
    import threading
    from starlette.testclient import TestClient
    rid = client.post("/api/ledger/opening", headers=world["fin"], json={"year": world["year"], "opening_date": "%d-01-01" % world["year"],
                                                                       "rows": [{"account_code": "1113", "debit": 100, "credit": 0}, {"account_code": "3111", "debit": 0, "credit": 100}]}).json()["request_id"]
    codes, gate = [], threading.Barrier(5)

    def go():
        with TestClient(client.app) as c:
            gate.wait(timeout=20)
            codes.append(c.post("/api/ledger/action-requests/%d/approve" % rid, headers=world["sup"]).status_code)
    ts = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert codes.count(200) == 1 and all(c in (400, 409) for c in codes if c != 200), codes
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM gl_opening_batches WHERE year=?", (world["year"],)).fetchone()[0]
    finally:
        c.close()
    assert n == 1                                                       # 期初批次只建一次（不是每個並行核准都建一次）


def test_migration_0002_recovers_from_a_partial_earlier_shape(client):
    import importlib
    m = importlib.import_module("modules.accounting.migrations.0002_ledger_action_requests")
    c = db.get_db()
    try:
        c.execute("DROP TABLE gl_action_requests")                       # 模擬半成品：少 approval_json 欄、沒索引
        c.execute("CREATE TABLE gl_action_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, request_no TEXT NOT NULL UNIQUE, action TEXT NOT NULL,"
                  " label TEXT NOT NULL DEFAULT '', params_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT '待審核',"
                  " requested_by TEXT NOT NULL DEFAULT '', requested_by_display TEXT NOT NULL DEFAULT '', requested_at TEXT NOT NULL DEFAULT '',"
                  " decided_by TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL DEFAULT '', decision_note TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '{}')")
        c.execute("INSERT INTO gl_action_requests(request_no, action) VALUES ('LA-OLD-1','year_close')")
        m.up(c)
        m.up(c)                                                          # 再跑一次也不變
        cols = [r[1] for r in c.execute("PRAGMA table_info(gl_action_requests)")]
        idx = [r[1] for r in c.execute("PRAGMA index_list(gl_action_requests)")]
        assert "approval_json" in cols and any("status" in i for i in idx) and any("user" in i for i in idx)
        assert c.execute("SELECT COUNT(*) FROM gl_action_requests").fetchone()[0] == 1          # 舊資料還在
        c.commit()
    finally:
        c.close()


def test_decision_is_a_conditional_update_and_takes_the_write_lock(client, world, monkeypatch):
    """決定寫入要條件式（狀態仍是待審核才寫），且讀狀態前先拿寫鎖——用『執行過程中狀態被改走』與『讀完後在寫交易裡』兩個確定的觀測證明。"""
    from modules.accounting.ledger import requests as R
    rid = client.post("/api/ledger/periods/%d/close" % world["pid"], headers=world["fin"], json={}).json()["request_id"]
    c = db.get_db()
    try:
        assert c.in_transaction is False
        R._load_pending(c, rid)
        assert c.in_transaction is True                                   # 讀之前先 BEGIN IMMEDIATE（寫鎖）
        c.rollback()
        def flip(conn, row):
            conn.execute("UPDATE gl_action_requests SET status='已撤回' WHERE id=?", (row["id"],))          # 執行當中，申請被別人撤回了
            return {}
        monkeypatch.setattr(R, "_execute", flip)
        with pytest.raises(R.RequestConflict):
            R.approve(c, rid, {"username": world["su"]})                  # 條件式更新 rowcount==0 ⇒ 衝突（不會把已撤回蓋成已核准）
        c.rollback()
        assert c.execute("SELECT status FROM gl_action_requests WHERE id=?", (rid,)).fetchone()[0] == "待審核"
    finally:
        c.close()
