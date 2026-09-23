"""標記收款的資料驗證（2026-09-24）。

`PATCH /api/quotations/{no}/payment/{idx}`（mark_payment）與半解鎖審核通過後的
重播（`_apply_case_change_request()` 的 payment_mark 分支）原本照收：

- received=true 但 receivedAt 空白 ⇒ 這筆不屬於任何月份，所有收入報表漏算
- actualAmount／feeAmount 不驗型別 ⇒ 存進 "" 或 "abc"；報表以 `aa - fee` 加總，
  型別不對會丟例外（讀碼推論；2026-09-24 以 /api/reports/financial 探測時測試案件
  未被報表撈到，端到端未重現，所以這裡不放報表題）
- receivedBy 吃 body 傳的值 ⇒ 誰收的款可以被填成任何人

裁示（hichan-0a 代裁 D1～D5，待使用者確認）：
- receivedAt 必填、合法 YYYY-MM-DD；未來日期不擋
- actualAmount 不帶／null＝沿用「以應收金額計」；""、非數字、負數、NaN、布林 400
  （不把 "" 轉成 null——那是金額語意，不代裁）
- feeAmount ""／null 維持視為 0；非數字、負數 400
- receivedBy 一律伺服器記；半解鎖路徑記提出申請的人

觀測點打在資料庫落地值（被擋下的那筆必須仍是未收款）。
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, deal_tag="已成案", semi_unlocked=0):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({"caseRecord": {"payment": {"items": [
            {"type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": ""},
        ]}}})
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag, case_semi_unlocked) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag, semi_unlocked),
        )
        conn.commit()
    finally:
        conn.close()


def _item(quote_no, idx=0):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]["payment"]["items"][idx]


def _ok_body(**over):
    d = {"received": True, "receivedAt": "2026-09-01", "actualAmount": 30000, "feeAmount": 0}
    d.update(over)
    return d


@pytest.fixture
def cashier(client, make_user):
    u, p = make_user(username="rcv_admin", role="admin")
    return _login(client, u, p)


# ── receivedAt ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "", "   ", "2026/09/01", "2026-13-01", "2026-02-30", "昨天", 20260901])
def test_received_requires_valid_date(client, cashier, bad):
    no = "MQ-RCV-DATE"
    _make_quotation(no)
    body = _ok_body(receivedAt=bad)
    if bad is None:
        body.pop("receivedAt")
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier), json=body)
    assert r.status_code == 400, r.text
    assert _item(no)["received"] is False, "被擋下的那筆不可以變成已收款"


def test_future_date_is_accepted(client, cashier):
    no = "MQ-RCV-FUT"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(receivedAt="2099-01-01"))
    assert r.status_code == 200, r.text
    assert _item(no)["receivedAt"] == "2099-01-01"


def test_cancel_receipt_without_date_still_works(client, cashier):
    """cashier.js 的「取消收款」送 receivedAt:''——那條路要照常通過。"""
    no = "MQ-RCV-CANCEL"
    _make_quotation(no)
    assert client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                        json=_ok_body()).status_code == 200
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json={"received": False, "receivedAt": "", "receivedBy": ""})
    assert r.status_code == 200, r.text
    assert _item(no)["received"] is False


# ── actualAmount／feeAmount ────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "abc", "30000", -1, True, "NaN"])
def test_actual_amount_must_be_non_negative_number(client, cashier, bad):
    no = "MQ-RCV-ACT"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(actualAmount=bad))
    assert r.status_code == 400, r.text
    assert _item(no)["received"] is False


def test_actual_amount_null_keeps_existing_meaning(client, cashier):
    """不帶／null＝以應收金額計（既有語意，報表用 amount 補位）。"""
    no = "MQ-RCV-ACTNULL"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(actualAmount=None))
    assert r.status_code == 200, r.text
    assert _item(no)["actualAmount"] is None


@pytest.mark.parametrize("bad", ["abc", -5, True])
def test_fee_amount_must_be_non_negative_number(client, cashier, bad):
    no = "MQ-RCV-FEE"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(feeAmount=bad))
    assert r.status_code == 400, r.text
    assert _item(no)["received"] is False


@pytest.mark.parametrize("empty", ["", None])
def test_fee_amount_empty_still_means_zero(client, cashier, empty):
    no = "MQ-RCV-FEE0"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(feeAmount=empty))
    assert r.status_code == 200, r.text
    assert _item(no)["feeAmount"] == 0


# ── receivedBy ─────────────────────────────────────────────────────────────

def test_received_by_is_recorded_by_server(client, cashier):
    no = "MQ-RCV-BY"
    _make_quotation(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(receivedBy="冒名的人"))
    assert r.status_code == 200, r.text
    assert _item(no)["receivedBy"] == "rcv_admin"


# ── 半解鎖：送審與重播 ─────────────────────────────────────────────────────

def test_semi_unlocked_invalid_body_is_rejected_before_queueing(client, cashier):
    """不合法的內容不可以先排進審核佇列——否則審核人核准的是一筆壞資料。"""
    import db
    no = "MQ-RCV-SEMI1"
    _make_quotation(no, deal_tag="已結案", semi_unlocked=1)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(receivedAt=""))
    assert r.status_code == 400, r.text
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM case_change_requests WHERE quote_no=?", (no,)).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_semi_unlocked_records_requester_not_approver(client, make_user, cashier):
    no = "MQ-RCV-SEMI2"
    _make_quotation(no, deal_tag="已結案", semi_unlocked=1)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(receivedBy="冒名的人"))
    assert r.status_code == 200 and r.json().get("pending"), r.text
    cid = r.json()["changeRequestId"]

    sa, sp = make_user(username="rcv_sa", role="superadmin")
    r = client.post(f"/api/case-changes/{cid}/approve", headers=_auth(_login(client, sa, sp)))
    assert r.status_code == 200, r.text
    it = _item(no)
    assert it["received"] is True
    assert it["receivedBy"] == "rcv_admin", "要記提出申請的人，不是審核人，也不是 body 傳的值"


def test_replay_rejects_legacy_invalid_payload(client, make_user):
    """修正前排進佇列的壞資料，核准時也要擋下，不可以落地。"""
    import db
    no = "MQ-RCV-SEMI3"
    _make_quotation(no, deal_tag="已結案", semi_unlocked=1)
    conn = db.get_db()
    try:
        cid = conn.execute(
            "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
            "staged_files_json, status, requested_by, requested_by_display, requested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (no, "payment_mark", "標記已收款",
             json.dumps({"idx": 0, "body": {"received": True, "receivedAt": "", "actualAmount": ""}}),
             "[]", "pending", "someone_else", "申請人", "2026-09-15T01:00:00")).lastrowid
        conn.commit()
    finally:
        conn.close()

    sa, sp = make_user(username="rcv_sa3", role="superadmin")
    r = client.post(f"/api/case-changes/{cid}/approve", headers=_auth(_login(client, sa, sp)))
    assert r.status_code == 400, r.text
    assert _item(no)["received"] is False


# ── 期別定位（itemId）─────────────────────────────────────────────────────

def _make_with_ids(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案",
             json.dumps({"caseRecord": {"payment": {"items": [
                 {"id": 11, "type": "訂金款", "pct": 30, "amount": 30000, "received": False},
                 {"id": 12, "type": "尾款", "pct": 70, "amount": 70000, "received": False},
             ]}}}),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def test_item_id_mismatch_is_rejected(client, cashier):
    """畫面以為 idx=0 是 id 11，而那一格已經被換成別期——不可以標到別期去。"""
    no = "MQ-RCV-ID1"
    _make_with_ids(no)
    r = client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                     json=_ok_body(itemId=12))
    assert r.status_code == 409, r.text
    assert _item(no, 0)["received"] is False and _item(no, 1)["received"] is False


def test_item_id_match_and_absent_both_work(client, cashier):
    no = "MQ-RCV-ID2"
    _make_with_ids(no)
    assert client.patch(f"/api/quotations/{no}/payment/0", headers=_auth(cashier),
                        json=_ok_body(itemId=11)).status_code == 200
    assert client.patch(f"/api/quotations/{no}/payment/1", headers=_auth(cashier),
                        json=_ok_body()).status_code == 200
    assert _item(no, 0)["received"] is True and _item(no, 1)["received"] is True
    assert "itemId" not in _item(no, 0), "itemId 只用來比對，不可以寫進期別"
