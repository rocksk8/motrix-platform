"""2026-09-09：案件管理－財務 Tab 新增「應收應付總覽」。

GET /api/quotations/{quote_no}/finance-summary 把原本散在四個地方、從來沒有
被並排看過的錢一次算完：應收（caseRecord.payment.items）、應付（承攬商匯款
申請）、關聯文件（開票申請／請款單，唯讀不併入合計）、精算額外支出（只回
小計供參考，不當應付）。

這些測試同時是「哪些東西刻意不算進合計」的規格文件——開票申請/請款單被算進
應收、或精算額外支出被算進應付，都會讓同一筆錢被重複計算，是這個功能最容易
出錯的地方。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _sync_extra_to_table(conn, quote_no):
    """把剛種進 data_json 的 settlement.extraItems 搬進 case_extra_expenses。

    2026-09-11（migration v75）之後額外支出住在獨立資料表，data_json 裡那份只是
    唯讀備份、財務總覽不再讀它。用 migration 自己那支搬移函式，欄位對應才不會漂移。"""
    import db as _db
    import json as _json
    row = conn.execute(
        "SELECT data_json, sales_person FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        return
    _db._move_extra_items_for_quote(
        conn, quote_no, _json.loads(row["data_json"] or "{}"), row["sales_person"] or "")

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, pay_items=None, settlement=None, total=100000, pretax=95238):
    import db
    conn = db.get_db()
    try:
        data = {"caseRecord": {"payment": {"items": pay_items or []}}}
        if settlement is not None:
            data["settlement"] = settlement
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, pretax,
             json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        _sync_extra_to_table(conn, quote_no)
        conn.commit()
    finally:
        conn.close()


def _make_voucher(client, token, quote_no, voucher_no, amount, status="已核准", is_paid=0):
    """承攬商＋派發用 HTTP 正規流程建立（FK 是真的，不用自己複製那兩張表的
    schema），匯款申請本身直接 SQL 插入——這裡測的是彙總邏輯，不是建立/簽核
    流程，走完整簽核 HTTP 流程只會讓「三種狀態的單據各一張」這件事變得難讀，
    且自簽自核會被 check_no_tier_self_approval() 擋下（見
    test_contractor_voucher_paid_date_2026_08_31.py 同款作法）。自己組
    snapshot_json 也讓 grandTotal 能填精確數字，斷言才好讀（真實流程的
    grandTotal 是含稅＋人員費用加總出來的）。"""
    r = client.post("/api/vendor-contractors", headers=_auth(token),
                    json={"name": f"廠商{voucher_no}", "data": {}})
    assert r.status_code == 201, r.text
    vendor_id = r.json()["id"]

    r = client.post("/api/contractor-dispatches", headers=_auth(token), json={
        "quote_no": quote_no, "vendor_id": vendor_id, "status": "completed",
        "items_json": [{"description": "測試品項", "qty": 1, "unit": "式",
                        "unitPrice": amount, "amount": amount}],
    })
    assert r.status_code == 201, r.text
    dispatch_id = r.json()["id"]

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, "
            "vendor_id, status, snapshot_json, data_json, is_paid, paid_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (voucher_no, dispatch_id, quote_no, vendor_id, status,
             json.dumps({"vendorName": "測試承攬商", "grandTotal": amount}, ensure_ascii=False),
             "{}", is_paid, "2026-02-01" if is_paid else "",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_receivable_totals_match_payment_items(client, make_user):
    """應收/已收/未收/手續費/實收淨額，語意要跟前端 case-management.js 的
    receivedTotal()/feeTotal()/netReceivedTotal()/outstandingTotal() 一致。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-FINSUM-001", pay_items=[
        # 已收，有實收金額（短收 500）＋手續費 30
        {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": True,
         "receivedAt": "2026-03-05T10:00:00", "actualAmount": 29500, "feeAmount": 30},
        # 已收，沒填實收金額 → 以應收金額計
        {"id": 2, "type": "交貨款", "pct": 40, "amount": 40000, "received": True,
         "receivedAt": "2026-04-10T10:00:00", "actualAmount": None, "feeAmount": 0},
        # 未收
        {"id": 3, "type": "尾款", "pct": 30, "amount": 30000, "received": False},
    ])

    r = client.get("/api/quotations/MQ-FINSUM-001/finance-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    recv = r.json()["receivable"]

    assert recv["receivableTotal"] == 100000
    assert recv["collectedTotal"] == 70000          # 應收金額口徑（非實收）
    assert recv["outstandingTotal"] == 30000
    assert recv["feeTotal"] == 30
    assert recv["netCollected"] == 29500 - 30 + 40000  # 實收 - 手續費
    assert len(recv["items"]) == 3
    assert recv["items"][0]["receivedAt"] == "2026-03-05"   # 只留日期
    assert recv["items"][2]["received"] is False


def test_related_documents_listed_but_not_summed_into_receivable(client, make_user):
    """開票申請／請款單只是唯讀清單：它們跟收款排程的期別不是一對一對應，
    併進應收會讓同一筆錢被算兩次。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-FINSUM-003", pay_items=[
        {"id": 1, "type": "全額", "pct": 100, "amount": 100000, "received": False},
    ])
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status, amount, "
            "snapshot_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("IV-202601-001", "MQ-FINSUM-003", "amount", "已核准", 100000, "{}", "{}",
             "2026-01-05T00:00:00", "2026-01-05T00:00:00"),
        )
        conn.execute(
            "INSERT INTO payment_requests (request_no, quote_no, scope, stage, status, amount, "
            "terms_json, snapshot_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("PR-202601-001", "MQ-FINSUM-003", "amount", "全額", "簽核中", 100000, "{}", "{}", "{}",
             "2026-01-06T00:00:00", "2026-01-06T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/quotations/MQ-FINSUM-003/finance-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()

    # 應收合計只認款項明細，不因為多了兩張單據就變成 30 萬
    assert body["receivable"]["receivableTotal"] == 100000
    assert body["receivable"]["outstandingTotal"] == 100000
    docs = body["relatedDocuments"]
    assert [d["voucherNo"] for d in docs["invoiceVouchers"]] == ["IV-202601-001"]
    assert docs["invoiceVouchers"][0]["amount"] == 100000
    assert [d["requestNo"] for d in docs["paymentRequests"]] == ["PR-202601-001"]
    assert docs["paymentRequests"][0]["stage"] == "全額"


def test_empty_case_returns_zeros_not_error(client, make_user):
    """完全沒有款項/派發/單據的新案件不該報錯，全部回 0 就好。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-FINSUM-005")

    r = client.get("/api/quotations/MQ-FINSUM-005/finance-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["receivable"]["receivableTotal"] == 0
    assert body["receivable"]["items"] == []
    assert body["payable"]["approvedUnpaidTotal"] == 0
    assert body["settlementExtras"]["total"] == 0


def test_unknown_quote_404_and_anonymous_401(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    r = client.get("/api/quotations/MQ-NOT-EXIST/finance-summary", headers=_auth(token))
    assert r.status_code == 404, r.text

    r = client.get("/api/quotations/MQ-NOT-EXIST/finance-summary")
    assert r.status_code == 401, r.text
