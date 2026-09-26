"""簽核佇列與「最近的變動」的可見範圍（2026-09-15 使用者要求）。

「沒有權限的使用者最近的變動只能看到自己的，如果沒有就不顯示；簽核佇列除了管理員
以上都只能看到自己的簽核佇列卡在哪邊，落實權限管制的機制」。

兩個洞的共同點是**清單端點只有 `_require_user()`**：功能本身正確、每個欄位都算得對，
但「誰能拿到這份清單」從來沒有被限制過。

- `GET /api/approval-queue`：任何登入者都拿得到全公司待簽核單據的客戶、專案、
  **金額**、送審人與整條簽核鏈
- `GET /api/dashboard/activity-feed` 的進出物料段：六個來源裡唯一沒有逐筆過濾的，
  只有 dashboard 模組的檢視者也看得到全公司的料件流向

觀測點一律挑「**清單裡到底有沒有那一筆**」，而且每一題都配一個看得到的正向控制
（admin 或有模組的人）——只斷言「看不到」的話，端點整個壞掉、回空清單也會通過。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import date, timedelta
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_pending_quotation(quote_no, requested_by, tiers):
    """插一張待審核報價單。`tiers` 是 [[username, ...], ...]（外層是層、內層是該層簽核人）。"""
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "approval": {
                "tiers": [
                    {"order": i, "approvers": [
                        {"username": u, "displayName": u, "status": "pending", "approvedAt": None}
                        for u in tier
                    ]}
                    for i, tier in enumerate(tiers)
                ],
                "currentTier": 0,
                "requestedBy": requested_by,
                "requestedByDisplay": requested_by,
                "requestedAt": "2026-09-01T00:00:00",
            },
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "祕密客戶", "祕密專案", 1234567, 1176730, data_json,
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()


def _queue_quote_nos(client, token):
    r = client.get("/api/approval-queue", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    return {it["quoteNo"] for g in body["queue"] for it in g["items"]}, body


# ── 簽核佇列 ────────────────────────────────────────────────────────────────

def test_non_admin_cannot_see_other_peoples_pending_documents(client, make_user):
    """跟自己完全無關的單據，非管理員不該在佇列裡看到——那上面有客戶、專案與金額。"""
    su, sp = make_user(username="sc_super", role="superadmin")
    outsider, op = make_user(username="sc_sales", role="sales")
    make_user(username="sc_owner", role="sales")
    make_user(username="sc_appr", role="admin")
    _insert_pending_quotation("MQ-SCOPE-001", "sc_owner", [["sc_appr"]])

    seen, body = _queue_quote_nos(client, _login(client, outsider, op))
    assert "MQ-SCOPE-001" not in seen, seen
    assert body["total"] == 0, body

    # 正向控制：同一筆資料，最高管理者看得到（證明不是端點壞掉回空清單）
    seen_su, _ = _queue_quote_nos(client, _login(client, su, sp))
    assert "MQ-SCOPE-001" in seen_su, seen_su


def test_non_admin_sees_their_own_submission_and_where_it_is_stuck(client, make_user):
    """自己送審的要看得到，而且要看得出卡在第幾關、卡在誰身上。"""
    owner, pw = make_user(username="sc_mine", role="sales")
    make_user(username="sc_boss1", role="admin")
    make_user(username="sc_boss2", role="admin")
    _insert_pending_quotation("MQ-SCOPE-002", "sc_mine", [["sc_boss1"], ["sc_boss2"]])

    seen, body = _queue_quote_nos(client, _login(client, owner, pw))
    assert "MQ-SCOPE-002" in seen, seen
    item = next(it for g in body["queue"] for it in g["items"] if it["quoteNo"] == "MQ-SCOPE-002")
    # 「卡在哪邊」靠這三個欄位表達，缺一個畫面就畫不出進度
    assert item["currentTier"] == 0
    assert item["tierCount"] == 2
    assert [a["username"] for a in item["currentApprovers"]] == ["sc_boss1"]


def test_non_admin_sees_items_waiting_on_them(client, make_user):
    """輪到自己簽的當然要看得到。"""
    appr, pw = make_user(username="sc_eng", role="engineer")
    make_user(username="sc_other", role="sales")
    _insert_pending_quotation("MQ-SCOPE-003", "sc_other", [["sc_eng"]])

    seen, _ = _queue_quote_nos(client, _login(client, appr, pw))
    assert "MQ-SCOPE-003" in seen, seen


def test_non_admin_sees_items_where_they_are_a_later_approver(client, make_user):
    """自己在第二關（還沒輪到）也要看得到。

    只比對**當前層**的話，下一關的人看不到即將輪到自己的單、已經簽過的人看不到
    後面卡住了——兩種都會讓人以為「沒我的事」，這正是這個功能要解決的問題。
    """
    later, pw = make_user(username="sc_second", role="engineer")
    make_user(username="sc_first", role="admin")
    make_user(username="sc_req", role="sales")
    _insert_pending_quotation("MQ-SCOPE-004", "sc_req", [["sc_first"], ["sc_second"]])

    seen, body = _queue_quote_nos(client, _login(client, later, pw))
    assert "MQ-SCOPE-004" in seen, seen
    item = next(it for g in body["queue"] for it in g["items"] if it["quoteNo"] == "MQ-SCOPE-004")
    assert item["currentTier"] == 0, "還沒輪到他，但他要看得到目前卡在第一關"


def test_non_admin_delegate_sees_the_delegators_items(client, make_user):
    """代理期間要看得到被代理人的單——代理人常常不是管理員。"""
    import db
    delegate, pw = make_user(username="sc_standin", role="sales")
    make_user(username="sc_absent", role="admin")
    make_user(username="sc_req2", role="sales")
    _insert_pending_quotation("MQ-SCOPE-005", "sc_req2", [["sc_absent"]])

    today = date.today()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, "
            "end_date, reason, active, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,1,?,?,?)",
            ("sc_absent", "sc_standin", (today - timedelta(days=1)).isoformat(),
             (today + timedelta(days=1)).isoformat(), "測試", "sc_absent",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    seen, body = _queue_quote_nos(client, _login(client, delegate, pw))
    assert "MQ-SCOPE-005" in seen, seen
    assert body["myDelegatedFor"] == ["sc_absent"]


def test_queue_filter_covers_every_document_type():
    """過濾必須是**一條**規則套在組好的 items 上，不是每種單據各寫一段。

    這支端點已經有 8 種單據類型，逐型各寫一段 WHERE 的話，下次新增類型時漏掉的
    那一種就是全開的。這題釘的是「過濾發生在分組之前、而且只有一處」。
    """
    import inspect
    import modules.case.api.quotations as q

    src = inspect.getsource(q.get_approval_queue)
    assert src.count("_queue_visible_to(") == 1, "過濾應該只有一處（套在 items 上）"
    filter_pos = src.index("_queue_visible_to(")
    group_pos = src.index("groups[item[")
    assert filter_pos < group_pos, "要先過濾再分組，否則會留下空群組"


# ── 最近的變動：進出物料 ────────────────────────────────────────────────────

def _insert_stock_item(serial_no, actor):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_items (part_no, serial_no, status, quote_no, consumed_by, "
            "created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("PART-X", serial_no, "已出貨", "MQ-FEED-001", actor, actor,
             "2026-09-01T00:00:00", "2026-09-14T10:00:00"))
        conn.commit()
    finally:
        conn.close()


def _feed_serials(client, token):
    r = client.get("/api/dashboard/activity-feed?limit=100", headers=_auth(token))
    assert r.status_code == 200, r.text
    return {i["itemLabel"] for i in r.json()["items"] if i["source"] == "stock"}


