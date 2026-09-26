"""關卡矩陣批次計算（CM6b，2026-09-24）。

原本 gate-matrix 對每一件案件各呼叫一次 _case_close_gates()（六張單據表各兩句＋階段＋額外支出）
再加兩句到期查詢，約每件 17 句 SQL。改成先批次取數（GROUP BY）、再逐件用同一份純計算
（_gates_from_facts）算出五關——單筆 close-gates 與擋結案也走同一條，判定仍只有一份。
- 查詢數：40 件的矩陣不超過固定上限（與件數無關）
- 特性：一組涵蓋各種狀態的案件，五關輸出與重構前（master 舊實作）逐字相同（GOLDEN 由舊實作產出）
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

MATRIX = "/api/quotations/gate-matrix"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _appr(*names, current=0, approved=()):
    return {"tiers": [{"order": 0, "approvers": [
        {"username": n, "displayName": n, "status": "approved" if n in approved else "pending"} for n in names]}],
        "currentTier": current}


def _seed_rich():
    """回傳要比對的單號清單。每件刻意落在不同的關卡狀態組合。"""
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()

    def case(no, data=None, tag="已成案"):
        d = {"dealTag": tag}
        d.update(data or {})
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "客戶", "專案", 1000, 952, json.dumps(d, ensure_ascii=False), now, now, tag, "2026-08-01"))

    def stage(no, done, due="", order=0, label="階段"):
        conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?)", (no, label, order, 1 if done else 0, due, now, now))

    def doc(table, no, n, status, appr=None):
        cols = {"shipping_notes": "note_no, quote_no, status, customer_name, items_json, data_json, created_at, updated_at",
                "completion_notes": "note_no, quote_no, status, data_json, created_at, updated_at",
                "payment_requests": None, "invoice_vouchers": None, "contractor_payment_vouchers": None}
        data = json.dumps({"approval": appr or {}}, ensure_ascii=False)
        if table == "shipping_notes":
            conn.execute(f"INSERT INTO shipping_notes ({cols[table]}) VALUES (?,?,?,?,?,?,?,?)",
                         (n, no, status, "客戶", "[]", data, now, now))
        elif table == "completion_notes":
            conn.execute(f"INSERT INTO completion_notes ({cols[table]}) VALUES (?,?,?,?,?,?)",
                         (n, no, status, data, now, now))
        elif table == "invoice_vouchers":
            conn.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, status, data_json, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?)", (n, no, status, data, now, now))

    def xe(no, status):
        conn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, status,"
                     " created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (no, "運費", "x", 100, status, now, now))

    try:
        case("MQ-GB-EMPTY")
        case("MQ-GB-PROG", {"caseRecord": {"payment": {"items": [{"id": 1, "received": True}]}}})
        stage("MQ-GB-PROG", True, order=0)
        stage("MQ-GB-PROG", False, due="2020-01-01", order=1, label="逾期中")
        stage("MQ-GB-PROG", False, due="2099-03-01", order=2, label="下一個")
        case("MQ-GB-PAY", {"caseRecord": {"payment": {"items": [
            {"id": 1, "received": True}, {"id": 2, "received": False}, {"id": 3}]}}})
        case("MQ-GB-DOCS")
        doc("shipping_notes", "MQ-GB-DOCS", "SN-GB-1", "簽核中", _appr("gb_a", "gb_b", approved=("gb_a",)))
        doc("shipping_notes", "MQ-GB-DOCS", "SN-GB-2", "已核准")
        doc("completion_notes", "MQ-GB-DOCS", "CN-GB-1", "待審核", _appr("gb_c"))
        doc("invoice_vouchers", "MQ-GB-DOCS", "IV-GB-1", "草稿")
        case("MQ-GB-SETTLE-DRAFT", {"settlement": {"status": "draft"}})
        case("MQ-GB-SETTLE-FINAL", {"settlement": {"status": "finalized"}})
        case("MQ-GB-XE")
        xe("MQ-GB-XE", "待審核")
        xe("MQ-GB-XE", "已核准")
        case("MQ-GB-XE-OK")
        xe("MQ-GB-XE-OK", "已核准")
        case("MQ-GB-ALLOK", {"caseRecord": {"payment": {"items": [{"id": 1, "received": True}]}},
                             "settlement": {"status": "finalized"}})
        stage("MQ-GB-ALLOK", True)
        doc("shipping_notes", "MQ-GB-ALLOK", "SN-GB-OK", "已核准")
        case("MQ-GB-CLOSED", {"caseRecord": {"payment": {"items": [{"id": 1, "received": True}]}}}, tag="已結案")
        stage("MQ-GB-CLOSED", True)
        conn.commit()
    finally:
        conn.close()


def _matrix(client, h):
    r = client.get(MATRIX, headers=h)
    assert r.status_code == 200, r.text
    return {it["quoteNo"]: it for it in r.json()["items"]}


def _essence(it):
    return {"gates": it["gates"], "readyCount": it["readyCount"], "naCount": it["naCount"],
            "blockedCount": it["blockedCount"], "canClose": it["canClose"], "blockedLabels": it["blockedLabels"],
            "stageOverdue": it["stageOverdue"], "nextDue": it["nextDue"], "nextDueLabel": it["nextDueLabel"]}


# 重構前 master（cb35ecc）舊實作對 _seed_rich() 的輸出，逐字固定
GOLDEN = json.loads(r'''{"MQ-GB-ALLOK": {"blockedCount": 0, "blockedLabels": [], "canClose": true, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1 期"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "2/2"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "已完結"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 1, "nextDue": null, "nextDueLabel": null, "readyCount": 4, "stageOverdue": 0}, "MQ-GB-CLOSED": {"blockedCount": 0, "blockedLabels": [], "canClose": true, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1 期"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 2, "nextDue": null, "nextDueLabel": null, "readyCount": 3, "stageOverdue": 0}, "MQ-GB-DOCS": {"blockedCount": 1, "blockedLabels": ["單據"], "canClose": false, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [{"count": 1, "label": "出貨單", "table": "shipping_notes"}, {"count": 1, "label": "完工單", "table": "completion_notes"}], "pendingUsernames": ["gb_b", "gb_c"], "ratio": 0.6, "reason": "出貨單尚有 1 筆簽核中；完工單尚有 1 筆簽核中", "state": "blocked", "value": "3/5"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 4, "nextDue": null, "nextDueLabel": null, "readyCount": 0, "stageOverdue": 0}, "MQ-GB-EMPTY": {"blockedCount": 0, "blockedLabels": [], "canClose": true, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 4, "nextDue": null, "nextDueLabel": null, "readyCount": 1, "stageOverdue": 0}, "MQ-GB-PAY": {"blockedCount": 1, "blockedLabels": ["收款"], "canClose": false, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": 0.3333333333333333, "reason": "款項明細尚有 2 期未收齊", "state": "blocked", "value": "1/3 期"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 3, "nextDue": null, "nextDueLabel": null, "readyCount": 1, "stageOverdue": 0}, "MQ-GB-PROG": {"blockedCount": 1, "blockedLabels": ["進度"], "canClose": false, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": 0.3333333333333333, "reason": "執行管理進度尚未 100%（1/3）", "state": "blocked", "value": "1/3"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1 期"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 2, "nextDue": "2020-01-01", "nextDueLabel": "逾期中", "readyCount": 2, "stageOverdue": 1}, "MQ-GB-SETTLE-DRAFT": {"blockedCount": 1, "blockedLabels": ["精算"], "canClose": false, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": 0.5, "reason": "成本精算尚未完結", "state": "blocked", "value": "草稿"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 3, "nextDue": null, "nextDueLabel": null, "readyCount": 1, "stageOverdue": 0}, "MQ-GB-SETTLE-FINAL": {"blockedCount": 0, "blockedLabels": [], "canClose": true, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "已完結"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無"}], "naCount": 3, "nextDue": null, "nextDueLabel": null, "readyCount": 2, "stageOverdue": 0}, "MQ-GB-XE": {"blockedCount": 1, "blockedLabels": ["變更"], "canClose": false, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": 0.0, "reason": "額外支出尚有 1 筆送審中", "state": "blocked", "value": "1 送審"}], "naCount": 3, "nextDue": null, "nextDueLabel": null, "readyCount": 1, "stageOverdue": 0}, "MQ-GB-XE-OK": {"blockedCount": 0, "blockedLabels": [], "canClose": true, "gates": [{"key": "progress", "label": "進度", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無階段"}, {"key": "payment", "label": "收款", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "無款項"}, {"key": "documents", "label": "單據", "pendingDocs": [], "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "1/1"}, {"key": "settlement", "label": "精算", "pendingUsernames": [], "ratio": null, "reason": null, "state": "na", "value": "未建"}, {"key": "extraExpense", "label": "變更", "pendingUsernames": [], "ratio": 1.0, "reason": null, "state": "ok", "value": "無送審中"}], "naCount": 3, "nextDue": null, "nextDueLabel": null, "readyCount": 2, "stageOverdue": 0}}''')


def test_matrix_output_is_unchanged_by_batching(client, make_user):
    h = _login(client, *make_user(username="gb_golden", role="admin"))
    _seed_rich()
    got = {no: _essence(it) for no, it in _matrix(client, h).items() if no.startswith("MQ-GB-")}
    assert set(got) == set(GOLDEN)
    for no in GOLDEN:
        assert got[no] == GOLDEN[no], no


def test_single_case_close_gates_matches_the_matrix(client, make_user):
    h = _login(client, *make_user(username="gb_single", role="admin"))
    _seed_rich()
    for no, exp in GOLDEN.items():
        r = client.get(f"/api/quotations/{no}/close-gates", headers=h)
        assert r.status_code == 200, r.text
        gates = [{k: v for k, v in g.items() if k != "pendingApprovers"} for g in r.json()["gates"]]
        assert gates == exp["gates"], no
        assert r.json()["canClose"] == exp["canClose"], no


def test_matrix_query_count_does_not_grow_with_cases(client, make_user, monkeypatch):
    import sqlite3
    import modules.case.api.quotations as rq
    h = _login(client, *make_user(username="gb_count", role="admin"))
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        for i in range(40):
            no = f"MQ-GBN-{i:03d}"
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", "客戶", "專案", 1000, 952, json.dumps({"dealTag": "已成案"}), now, now, "已成案",
                 "2026-08-01"))
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?,?)", (no, "s", 0, 0, "2099-01-01", now, now))
        conn.commit()
    finally:
        conn.close()
    stmts = []
    real = rq.get_db

    def counting():
        c = real()
        c.set_trace_callback(lambda sql: stmts.append(sql) if sql.lstrip().upper().startswith("SELECT") else None)
        return c
    monkeypatch.setattr(rq, "get_db", counting)
    r = client.get(MATRIX, headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) >= 40
    assert len(stmts) <= 30, f"40 件用了 {len(stmts)} 句 SELECT——應與件數無關"
