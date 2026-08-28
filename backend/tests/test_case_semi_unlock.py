"""已結案案件解鎖／半解鎖機制（2026-08-26）+ 完結案防呆機制（2026-08-25 提出）
的 API 層整合測試。見 db.py::_m061_case_semi_unlock() 與
routers/quotations.py::_gate_case_edit()/_case_close_block_reasons() docstring。"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_closed_case(quote_no="MQ-CCR-001", all_stages_done=True, payment_received=True):
    """建立一張 deal_tag='已結案' 的報價單，預設完結案三項前置條件皆已達成
    （執行進度100%／款項全收齊／無單據簽核中），供測試「已結案且未半解鎖時
    應被擋下」與「解鎖後排隊審核」情境使用。"""
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已結案",
            "caseRecord": {
                "materials": [{"name": "測試料件A", "files": [], "invoiceFiles": []}],
                "payment": {"items": [
                    {"label": "全額", "received": payment_received, "receivedAt": "2026-08-01"},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案"),
        )
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (quote_no, "階段一", 0, 1 if all_stages_done else 0, now if all_stages_done else "", now, now),
        )
        conn.commit()
    finally:
        conn.close()


def test_update_case_record_blocked_when_locked(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_closed_case()

    r = client.patch(
        "/api/quotations/MQ-CCR-001/case-record", headers=_auth(token),
        json={"case_record": {"materials": [{"name": "改過的名字", "files": [], "invoiceFiles": []}]}},
    )
    assert r.status_code == 403, r.text


def test_unlock_then_edit_is_queued_not_applied(client, make_user):
    sa_user, sa_pw = make_user(username="sa1", role="superadmin")
    username, password = make_user(username="editor1", role="admin")
    sa_token = _login(client, sa_user, sa_pw)
    token = _login(client, username, password)
    _make_closed_case()

    r = client.post("/api/quotations/MQ-CCR-001/case-unlock", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["caseSemiUnlocked"] is True

    r = client.patch(
        "/api/quotations/MQ-CCR-001/case-record", headers=_auth(token),
        json={"case_record": {"materials": [{"name": "改過的名字", "files": [], "invoiceFiles": []}]}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending"] is True
    change_id = body["changeRequestId"]

    # 尚未套用：直接讀報價單，材料名稱應該還是原本的
    detail = client.get("/api/quotations/MQ-CCR-001", headers=_auth(token))
    mats = detail.json()["data"]["caseRecord"]["materials"]
    assert mats[0]["name"] == "測試料件A"

    # 出現在統一簽核佇列
    q = client.get("/api/approval-queue", headers=_auth(sa_token))
    items = [it for g in q.json()["queue"] for it in g["items"] if it["type"] == "case_change"]
    assert any(it["changeRequestId"] == change_id for it in items)

    count = client.get("/api/approval-queue/count", headers=_auth(sa_token))
    assert count.json()["count"] >= 1

    # 非 superadmin 不可核准
    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(token))
    assert r.status_code == 403, r.text

    # superadmin 核准 → 真正套用
    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(sa_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    detail = client.get("/api/quotations/MQ-CCR-001", headers=_auth(token))
    mats = detail.json()["data"]["caseRecord"]["materials"]
    assert mats[0]["name"] == "改過的名字"

    # 已核准的請求不能重複核准
    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(sa_token))
    assert r.status_code == 409, r.text


def test_reject_change_discards_it(client, make_user):
    sa_user, sa_pw = make_user(username="sa2", role="superadmin")
    username, password = make_user(username="editor2", role="admin")
    sa_token = _login(client, sa_user, sa_pw)
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-002")

    client.post("/api/quotations/MQ-CCR-002/case-unlock", headers=_auth(token))
    r = client.patch(
        "/api/quotations/MQ-CCR-002/case-record", headers=_auth(token),
        json={"case_record": {"materials": [{"name": "不該被套用", "files": [], "invoiceFiles": []}]}},
    )
    change_id = r.json()["changeRequestId"]

    r = client.post(f"/api/case-changes/{change_id}/reject", headers=_auth(sa_token),
                    json={"reason": "不同意"})
    assert r.status_code == 200, r.text

    detail = client.get("/api/quotations/MQ-CCR-002", headers=_auth(token))
    mats = detail.json()["data"]["caseRecord"]["materials"]
    assert mats[0]["name"] == "測試料件A"


def test_repeated_case_record_saves_dedupe_into_one_pending_request(client, make_user):
    """自我審查發現：case-record 是每次編輯 1.5 秒防抖自動存檔都會呼叫的端點，
    半解鎖期間若每次都新建一筆待審核記錄，編輯幾分鐘就會疊出幾十筆近乎重複的
    記錄，且核准順序錯了還會用舊快照蓋掉新內容。驗證修法：同一張案件同時只會
    有一筆 pending 的 case_record_update，內容永遠是最新一次編輯。"""
    sa_user, sa_pw = make_user(username="sa9", role="superadmin")
    username, password = make_user(username="editor9", role="admin")
    sa_token = _login(client, sa_user, sa_pw)
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-009")
    client.post("/api/quotations/MQ-CCR-009/case-unlock", headers=_auth(token))

    r1 = client.patch(
        "/api/quotations/MQ-CCR-009/case-record", headers=_auth(token),
        json={"case_record": {"materials": [{"name": "第一次編輯", "files": [], "invoiceFiles": []}]}},
    )
    r2 = client.patch(
        "/api/quotations/MQ-CCR-009/case-record", headers=_auth(token),
        json={"case_record": {"materials": [{"name": "第二次編輯", "files": [], "invoiceFiles": []}]}},
    )
    assert r1.json()["changeRequestId"] == r2.json()["changeRequestId"]
    change_id = r2.json()["changeRequestId"]

    q = client.get("/api/approval-queue", headers=_auth(sa_token))
    ccr_items = [it for g in q.json()["queue"] for it in g["items"]
                 if it["type"] == "case_change" and it["linkedQuoteNo"] == "MQ-CCR-009"]
    assert len(ccr_items) == 1

    client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(sa_token))
    detail = client.get("/api/quotations/MQ-CCR-009", headers=_auth(token))
    assert detail.json()["data"]["caseRecord"]["materials"][0]["name"] == "第二次編輯"


def test_requester_cannot_approve_own_change(client, make_user):
    """自我審查發現：core approve/reject 端點原本只檢查 role=='superadmin'，
    沒有擋自己審自己——若申請人本身就是 superadmin，能繞過前端隱藏按鈕直接呼叫
    API 核准自己提出的變更。比照既有 check_no_tier_self_approval() 補上。"""
    sa_user, sa_pw = make_user(username="sa10", role="superadmin")
    other_sa_user, other_sa_pw = make_user(username="sa11", role="superadmin")
    sa_token = _login(client, sa_user, sa_pw)
    other_sa_token = _login(client, other_sa_user, other_sa_pw)
    _make_closed_case("MQ-CCR-010")
    client.post("/api/quotations/MQ-CCR-010/case-unlock", headers=_auth(sa_token))

    r = client.patch(
        "/api/quotations/MQ-CCR-010/case-record", headers=_auth(sa_token),
        json={"case_record": {"materials": [{"name": "自己改的", "files": [], "invoiceFiles": []}]}},
    )
    change_id = r.json()["changeRequestId"]

    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(sa_token))
    assert r.status_code == 403, r.text

    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(other_sa_token))
    assert r.status_code == 200, r.text


def test_material_file_upload_staged_and_approved(client, make_user):
    sa_user, sa_pw = make_user(username="sa3", role="superadmin")
    username, password = make_user(username="editor3", role="admin")
    sa_token = _login(client, sa_user, sa_pw)
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-003")
    client.post("/api/quotations/MQ-CCR-003/case-unlock", headers=_auth(token))

    r = client.post(
        "/api/quotations/MQ-CCR-003/materials/0/files", headers=_auth(token),
        files={"files": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pending"] is True
    change_id = body["changeRequestId"]

    detail = client.get("/api/quotations/MQ-CCR-003", headers=_auth(token))
    assert detail.json()["data"]["caseRecord"]["materials"][0]["files"] == []

    r = client.post(f"/api/case-changes/{change_id}/approve", headers=_auth(sa_token))
    assert r.status_code == 200, r.text

    detail = client.get("/api/quotations/MQ-CCR-003", headers=_auth(token))
    files = detail.json()["data"]["caseRecord"]["materials"][0]["files"]
    assert len(files) == 1
    assert files[0]["filename"] == "test.pdf"


def test_lock_case_restores_full_lock(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-004")

    client.post("/api/quotations/MQ-CCR-004/case-unlock", headers=_auth(token))
    r = client.post("/api/quotations/MQ-CCR-004/case-lock", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["caseSemiUnlocked"] is False

    r = client.patch(
        "/api/quotations/MQ-CCR-004/case-record", headers=_auth(token),
        json={"case_record": {"materials": []}},
    )
    assert r.status_code == 403, r.text


def test_stage_granular_endpoint_always_blocked_when_closed(client, make_user):
    """§11 設計取捨：案件執行階段細項端點不支援排隊審核，已結案時一律 403，
    不論是否半解鎖。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-005")
    client.post("/api/quotations/MQ-CCR-005/case-unlock", headers=_auth(token))

    r = client.post("/api/quotations/MQ-CCR-005/stages", headers=_auth(token), json={"label": "新階段"})
    assert r.status_code == 403, r.text


# ── 完結案防呆機制（2026-08-25 提出，§11 🔴最優先）───────────────────────────

def _make_open_case(quote_no, all_stages_done=True, payment_received=True, pending_voucher=False):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {"items": [
                    {"label": "全額", "received": payment_received,
                     "receivedAt": "2026-08-01" if payment_received else ""},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (quote_no, "階段一", 0, 1 if all_stages_done else 0, now if all_stages_done else "", now, now),
        )
        if pending_voucher:
            conn.execute(
                "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, project_name, "
                "items_json, created_at, updated_at, data_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"SN-{quote_no}", quote_no, "待審核", "測試客戶", "測試專案", "[]", now, now,
                 json.dumps({"approval": {"tiers": [], "requestedBy": "someone",
                                          "requestedByDisplay": "someone", "requestedAt": now}})),
            )
        conn.commit()
    finally:
        conn.close()


def test_close_case_blocked_when_stage_incomplete(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case("MQ-CLOSE-001", all_stages_done=False)

    r = client.patch("/api/quotations/MQ-CLOSE-001/deal-tag", headers=_auth(token),
                     json={"deal_tag": "已結案"})
    assert r.status_code == 400, r.text
    assert "執行管理進度" in r.json()["detail"]


def test_close_case_blocked_when_payment_unpaid(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case("MQ-CLOSE-002", payment_received=False)

    r = client.patch("/api/quotations/MQ-CLOSE-002/deal-tag", headers=_auth(token),
                     json={"deal_tag": "已結案"})
    assert r.status_code == 400, r.text
    assert "款項明細" in r.json()["detail"]


def test_close_case_blocked_when_related_doc_pending(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case("MQ-CLOSE-003", pending_voucher=True)

    r = client.patch("/api/quotations/MQ-CLOSE-003/deal-tag", headers=_auth(token),
                     json={"deal_tag": "已結案"})
    assert r.status_code == 400, r.text
    assert "出貨單" in r.json()["detail"]


def test_close_case_succeeds_when_all_conditions_met(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case("MQ-CLOSE-004")

    r = client.patch("/api/quotations/MQ-CLOSE-004/deal-tag", headers=_auth(token),
                     json={"deal_tag": "已結案"})
    assert r.status_code == 200, r.text


def test_locked_edit_denial_is_audit_logged(client, make_user):
    """2026-08-28 新增：13 支不支援排隊審核的端點被已結案案件擋下時，現在會留一筆
    audit_log（action='case.locked_edit_denied'）——之後才有數據判斷這道限制實際
    被撞到的頻率，見 _deny_if_case_locked_unsupported() docstring。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_closed_case("MQ-CCR-AUDIT-001")

    r = client.post("/api/quotations/MQ-CCR-AUDIT-001/stages", headers=_auth(token), json={"label": "新階段"})
    assert r.status_code == 403, r.text

    r2 = client.get("/api/audit-log", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    actions = [it["action"] for it in r2.json()["items"]]
    assert "case.locked_edit_denied" in actions
