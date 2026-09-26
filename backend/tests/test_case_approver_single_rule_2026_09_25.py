"""案件簽核人放行只有一份規則（稽核 Y-5，2026-09-25）。

router 版 `_is_case_approver` 與 helpers 版 `is_document_approver` 原本是兩份，已漂移：
額外支出的 `approval_json` 沒有外層 `approval` 包裝，router 版認不得 ⇒ 額外支出的簽核人
（不是案件成員）在簽核佇列打開詳情會被 403、也看不到金額。
"""
import json


def _tok(client, make_user, u, role, mods):
    name, pw = make_user(username=u, role=role, modules=mods)
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(approver):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?)", ("MQ-Y5-0925", "已送出", "Y5客戶", "{}", "t", "t"))
        appr = {"tiers": [{"approvers": [{"username": approver}]}], "currentTier": 0, "requestedBy": "someone"}
        cur = conn.execute("INSERT INTO case_extra_expenses (quote_no, description, total_cost, status, approval_json)"
                           " VALUES (?,?,?,?,?)", ("MQ-Y5-0925", "吊車", 1234, "待審核", json.dumps(appr)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_extra_expense_approver_opens_queue_detail_and_sees_money(client, make_user):
    h = _tok(client, make_user, "y5_appr", "engineer", ["dashboard"])
    out = _tok(client, make_user, "y5_out", "engineer", ["dashboard"])
    eid = _seed("y5_appr")
    r = client.get("/api/approval-queue/detail?type=extra_expense&id=%d" % eid, headers=h)
    assert r.status_code == 200, r.text
    vals = {f["label"]: f["value"] for f in r.json()["fields"]}
    assert vals.get("小計") == "1,234", vals                         # 簽核人看得到金額
    # 反向：不在簽核名單、也不是案件成員 ⇒ 仍然擋
    assert client.get("/api/approval-queue/detail?type=extra_expense&id=%d" % eid, headers=out).status_code == 404   # M01-O1


def test_router_uses_the_helper_rule():
    import modules.case.api.quotations as rq
    from modules.case.quotations import is_document_approver
    assert rq._is_case_approver is is_document_approver
