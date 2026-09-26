"""轉簽與簽核歷史（2026-09-14）。

使用者要求：「簽核代理人，增加最高權限人可以轉簽簽核佇列的內容，要註明原因跟註記
這筆簽核，並且增加簽核歷史的功能，可以回頭看每個月簽核哪些內容跟搜尋案件、簽核的
內容等等」。

**轉簽 vs 既有的簽核代理人**：代理人是事前、長期的授權（請假期間全部代簽）；轉簽是
事後、單筆的處置（這一張卡住了，改由別人簽）。兩者都需要。

**簽核歷史建在 `audit_log` 上**，不另開表——簽核動作本來就每一筆都寫了 audit，
再開一張表等於同一件事記兩次，兩份紀錄遲早對不起來。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _seed_quote_pending(quote_no, approver, status="待審核"):
    """一張卡在 `approver` 身上的待簽核報價單。"""
    import db
    data = {
        "quoteNo": quote_no,
        "approval": {
            "requestedBy": "sales_x",
            "requestedByDisplay": "業務X",
            "requestedAt": "2026-09-14T09:00:00",
            "currentTier": 0,
            "tiers": [{"approvers": [{"username": approver, "displayName": approver,
                                      "status": "pending"}]}],
        },
    }
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, status, "測試客戶", "測試專案", 50000, 47619,
             json.dumps(data, ensure_ascii=False), "2026-09-14T09:00:00",
             "2026-09-14T09:00:00", "", "業務X", "[]"),
        )
        conn.commit()
    finally:
        conn.close()


def _approval_of(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
    finally:
        conn.close()
    return (json.loads(row["data_json"])).get("approval") or {}


# ── 轉簽 ─────────────────────────────────────────────────────────────────────

def test_reassign_moves_pending_approver_and_records_reason(client, make_user):
    """轉簽要換掉當層待簽核人，並把原因留在這一筆簽核上。"""
    su, sp = make_user(username="rs_super", role="superadmin")
    make_user(username="rs_old", role="admin")
    make_user(username="rs_new", role="admin")
    _seed_quote_pending("MQ-RS-001", "rs_old")

    r = client.post("/api/approval-queue/reassign",
                    json={"type": "quotation", "id": "MQ-RS-001",
                          "to_username": "rs_new", "reason": "原簽核人出差兩週"},
                    headers=_auth(_login(client, su, sp)))
    assert r.status_code == 200, r.text

    appr = _approval_of("MQ-RS-001")
    a = appr["tiers"][0]["approvers"][0]
    assert a["username"] == "rs_new", a
    # 註記留在這一筆簽核上（詳情頁與 PDF 讀得到，不必回頭翻 audit）
    assert a["reassignedFrom"] == "rs_old"
    assert a["reassignReason"] == "原簽核人出差兩週"
    assert appr["reassignLog"][-1]["reason"] == "原簽核人出差兩週"
    assert appr["reassignLog"][-1]["to"] == "rs_new"


def test_reassign_requires_reason(client, make_user):
    """原因必填——轉簽等於把待辦從 A 身上拿走塞給 B，沒有理由就無從追究。"""
    su, sp = make_user(username="rs_super2", role="superadmin")
    make_user(username="rs_old2", role="admin")
    make_user(username="rs_new2", role="admin")
    _seed_quote_pending("MQ-RS-002", "rs_old2")

    r = client.post("/api/approval-queue/reassign",
                    json={"type": "quotation", "id": "MQ-RS-002",
                          "to_username": "rs_new2", "reason": "   "},
                    headers=_auth(_login(client, su, sp)))
    assert r.status_code == 400, r.text
    # 觀測點在下游：被擋下來時簽核人不能被動到
    assert _approval_of("MQ-RS-002")["tiers"][0]["approvers"][0]["username"] == "rs_old2"


def test_reassign_is_superadmin_only(client, make_user):
    """一般管理員不能轉簽（使用者指定「最高權限人」）。"""
    au, ap = make_user(username="rs_admin", role="admin")
    make_user(username="rs_old3", role="admin")
    make_user(username="rs_new3", role="admin")
    _seed_quote_pending("MQ-RS-003", "rs_old3")

    r = client.post("/api/approval-queue/reassign",
                    json={"type": "quotation", "id": "MQ-RS-003",
                          "to_username": "rs_new3", "reason": "測試"},
                    headers=_auth(_login(client, au, ap)))
    assert r.status_code == 403, r.text


def test_reassign_rejects_inactive_or_same_user(client, make_user):
    su, sp = make_user(username="rs_super4", role="superadmin")
    make_user(username="rs_old4", role="admin")
    _seed_quote_pending("MQ-RS-004", "rs_old4")
    tok = _login(client, su, sp)

    same = client.post("/api/approval-queue/reassign",
                       json={"type": "quotation", "id": "MQ-RS-004",
                             "to_username": "rs_old4", "reason": "同一人"},
                       headers=_auth(tok))
    assert same.status_code == 400, same.text

    ghost = client.post("/api/approval-queue/reassign",
                        json={"type": "quotation", "id": "MQ-RS-004",
                              "to_username": "nobody_here", "reason": "查無此人"},
                        headers=_auth(tok))
    assert ghost.status_code == 404, ghost.text


def test_reassign_rejects_completed_document(client, make_user):
    """已核准的單不能轉簽——那會讓已完成的簽核紀錄失真。"""
    su, sp = make_user(username="rs_super5", role="superadmin")
    make_user(username="rs_old5", role="admin")
    make_user(username="rs_new5", role="admin")
    _seed_quote_pending("MQ-RS-005", "rs_old5", status="已送出")

    r = client.post("/api/approval-queue/reassign",
                    json={"type": "quotation", "id": "MQ-RS-005",
                          "to_username": "rs_new5", "reason": "測試"},
                    headers=_auth(_login(client, su, sp)))
    assert r.status_code == 409, r.text


def test_reassign_notifies_the_new_approver(client, make_user):
    """被轉到的人要收到通知，否則這張會靜靜卡在他的佇列裡。"""
    import db
    su, sp = make_user(username="rs_super6", role="superadmin")
    make_user(username="rs_old6", role="admin")
    make_user(username="rs_new6", role="admin")
    _seed_quote_pending("MQ-RS-006", "rs_old6")

    client.post("/api/approval-queue/reassign",
                json={"type": "quotation", "id": "MQ-RS-006",
                      "to_username": "rs_new6", "reason": "臨時接手"},
                headers=_auth(_login(client, su, sp)))

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT message FROM notifications WHERE username='rs_new6'").fetchall()
    finally:
        conn.close()
    assert any("臨時接手" in (r["message"] or "") for r in rows), [dict(r) for r in rows]


# ── 簽核歷史 ─────────────────────────────────────────────────────────────────

def _seed_audit(username, display, action, target_id, label, detail=None, at="2026-09-05T10:00:00"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at, user_id, username, display_name, action, target_type, "
            "target_id, target_label, detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (at, 0, username, display, action, "quotation", target_id, label,
             json.dumps(detail or {}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def test_history_lists_own_approvals_by_month(client, make_user):
    """任何人都看得到自己簽過什麼，並且能依月份回頭看。"""
    u, p = make_user(username="hist_a", role="admin")
    _seed_audit("hist_a", "簽核甲", "quotation.approve", "MQ-H-001", "MQ-H-001（客戶甲）",
                {"allDone": True}, "2026-09-05T10:00:00")
    _seed_audit("hist_a", "簽核甲", "quotation.reject", "MQ-H-002", "MQ-H-002（客戶乙）",
                {"note": "金額有誤"}, "2026-08-20T10:00:00")

    tok = _login(client, u, p)
    d = client.get("/api/approval-history", headers=_auth(tok)).json()
    assert {i["docNo"] for i in d["items"]} >= {"MQ-H-001", "MQ-H-002"}
    assert {m["month"] for m in d["months"]} >= {"2026-09", "2026-08"}

    sep = client.get("/api/approval-history?month=2026-09", headers=_auth(tok)).json()
    assert [i["docNo"] for i in sep["items"]] == ["MQ-H-001"], sep["items"]
    assert sep["items"][0]["actionLabel"] == "核准"


def test_history_search_matches_case_and_note(client, make_user):
    """同一個搜尋框要同時打得到案件與簽核內容——使用者不必先想清楚要搜哪一種。"""
    u, p = make_user(username="hist_b", role="admin")
    _seed_audit("hist_b", "簽核乙", "quotation.approve", "MQ-H-010", "MQ-H-010（台積電）", {})
    _seed_audit("hist_b", "簽核乙", "quotation.reject", "MQ-H-011", "MQ-H-011（聯電）",
                {"note": "報價單漏了運費"})

    tok = _login(client, u, p)
    by_case = client.get("/api/approval-history?q=台積電", headers=_auth(tok)).json()
    assert [i["docNo"] for i in by_case["items"]] == ["MQ-H-010"], by_case["items"]

    by_note = client.get("/api/approval-history?q=運費", headers=_auth(tok)).json()
    assert [i["docNo"] for i in by_note["items"]] == ["MQ-H-011"], by_note["items"]
    assert by_note["items"][0]["note"] == "報價單漏了運費"


def test_history_scope_all_requires_admin(client, make_user):
    """看自己的不限角色；看全公司的限 admin+。"""
    u, p = make_user(username="hist_viewer", role="viewer", modules=["dashboard"])
    tok = _login(client, u, p)
    assert client.get("/api/approval-history", headers=_auth(tok)).status_code == 200
    assert client.get("/api/approval-history?scope=all", headers=_auth(tok)).status_code == 403

    au, ap = make_user(username="hist_admin", role="admin")
    assert client.get("/api/approval-history?scope=all",
                      headers=_auth(_login(client, au, ap))).status_code == 200


def test_history_scope_mine_excludes_others(client, make_user):
    """`mine` 真的只回自己的——否則「看自己簽過什麼」會變成看到全公司。"""
    a_u, a_p = make_user(username="hist_me", role="admin")
    make_user(username="hist_other", role="admin")
    _seed_audit("hist_me", "我", "quotation.approve", "MQ-H-020", "MQ-H-020（我的）", {})
    _seed_audit("hist_other", "別人", "quotation.approve", "MQ-H-021", "MQ-H-021（別人的）", {})

    d = client.get("/api/approval-history", headers=_auth(_login(client, a_u, a_p))).json()
    docs = {i["docNo"] for i in d["items"]}
    assert "MQ-H-020" in docs and "MQ-H-021" not in docs, docs


def test_history_includes_reassign_entries(client, make_user):
    """轉簽也要進歷史——那是簽核流程上的處置，事後最需要追的就是它。"""
    su, sp = make_user(username="hist_su", role="superadmin")
    make_user(username="hist_old", role="admin")
    make_user(username="hist_new", role="admin")
    _seed_quote_pending("MQ-H-030", "hist_old")
    tok = _login(client, su, sp)
    client.post("/api/approval-queue/reassign",
                json={"type": "quotation", "id": "MQ-H-030",
                      "to_username": "hist_new", "reason": "原簽核人離職"},
                headers=_auth(tok))

    d = client.get("/api/approval-history?q=MQ-H-030", headers=_auth(tok)).json()
    hit = [i for i in d["items"] if i["action"] == "reassign"]
    assert hit, d["items"]
    assert hit[0]["actionLabel"] == "轉簽"
    assert hit[0]["note"] == "原簽核人離職", hit[0]
def test_history_month_counts_follow_the_search(client, make_user):
    """月份籤要跟著搜尋走——帶關鍵字時它回答的是「這個東西出現在哪幾個月」。

    不套 `q` 的話，搜到一筆結果卻看到「2026-09（8）」，人會以為還有七筆沒顯示。
    """
    u, p = make_user(username="hist_m", role="admin")
    _seed_audit("hist_m", "簽核丙", "quotation.approve", "MQ-M-001", "MQ-M-001（甲客戶）",
                {}, "2026-09-05T10:00:00")
    _seed_audit("hist_m", "簽核丙", "quotation.approve", "MQ-M-002", "MQ-M-002（乙客戶）",
                {}, "2026-09-06T10:00:00")
    _seed_audit("hist_m", "簽核丙", "quotation.reject", "MQ-M-003", "MQ-M-003（甲客戶）",
                {"note": "規格要改"}, "2026-08-06T10:00:00")

    tok = _login(client, u, p)
    all_months = {m["month"]: m["count"]
                  for m in client.get("/api/approval-history", headers=_auth(tok)).json()["months"]}
    assert all_months == {"2026-09": 2, "2026-08": 1}, all_months

    d = client.get("/api/approval-history", params={"q": "甲客戶"}, headers=_auth(tok)).json()
    assert len(d["items"]) == 2, d["items"]
    got = {m["month"]: m["count"] for m in d["months"]}
    assert got == {"2026-09": 1, "2026-08": 1}, got


def test_history_rejects_malformed_month(client, make_user):
    """`month` 亂打要回 400 而不是 500——錯的是請求，不是伺服器。"""
    u, p = make_user(username="hist_bad", role="admin")
    tok = _login(client, u, p)
    for bad in ("2026", "abcd-ef", "2026-13", "2026-00"):
        r = client.get("/api/approval-history", params={"month": bad}, headers=_auth(tok))
        assert r.status_code == 400, (bad, r.status_code, r.text)
    ok = client.get("/api/approval-history", params={"month": "2026-09"}, headers=_auth(tok))
    assert ok.status_code == 200, ok.text
