"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_case_finance_summary_2026_09_09.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-09-09：案件管理－財務 Tab 新增「應收應付總覽」。

GET /api/quotations/{quote_no}/finance-summary 把原本散在四個地方、從來沒有
被並排看過的錢一次算完：應收（caseRecord.payment.items）、應付（承攬商匯款
申請）、關聯文件（開票申請／請款單，唯讀不併入合計）、精算額外支出（只回
小計供參考，不當應付）。

這些測試同時是「哪些東西刻意不算進合計」的規格文件——開票申請/請款單被算進
應收、或精算額外支出被算進應付，都會讓同一筆錢被重複計算，是這個功能最容易
出錯的地方。
"""
import json


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


def test_payable_splits_paid_unpaid_and_pending(client, make_user):
    """已核准未匯款＝真正該付而未付；已核准已匯款＝已付；還在簽核流程中的
    只計筆數與參考金額，不混進未付合計（金額還可能被退回或改動）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-FINSUM-002")
    _make_voucher(client, token, "MQ-FINSUM-002", "PV-202601-001", 50000, status="已核准", is_paid=0)
    _make_voucher(client, token, "MQ-FINSUM-002", "PV-202601-002", 30000, status="已核准", is_paid=1)
    _make_voucher(client, token, "MQ-FINSUM-002", "PV-202601-003", 20000, status="簽核中", is_paid=0)

    r = client.get("/api/quotations/MQ-FINSUM-002/finance-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    payable = r.json()["payable"]

    assert payable["approvedUnpaidTotal"] == 50000
    assert payable["approvedPaidTotal"] == 30000
    assert payable["pendingTotal"] == 20000
    assert payable["pendingCount"] == 1
    assert len(payable["vouchers"]) == 3
    paid_row = next(v for v in payable["vouchers"] if v["voucherNo"] == "PV-202601-002")
    assert paid_row["isPaid"] is True
    assert paid_row["paidAt"] == "2026-02-01"
    assert paid_row["vendorName"] == "測試承攬商"


def test_settlement_extras_returned_with_doc_no_and_excluded_from_payable(client, make_user):
    """精算「額外支出」只回小計供參考：這個清單沒有已付/未付狀態，當成應付
    等於憑空發明一個系統從來沒追蹤過的狀態。順便驗證新增的單號欄位（docNo）
    有原樣帶出來（後端對 settlement 不做欄位白名單，所以只要有存就會回）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-FINSUM-004", settlement={
        "status": "draft",
        "extraItems": [
            {"category": "運費", "description": "吊車運費", "docNo": "AB12345678",
             "totalCost": 8000, "expenseDate": "2026-03-01"},
            {"category": "其他", "description": "臨時工資", "totalCost": 2000},
        ],
    })
    _make_voucher(client, token, "MQ-FINSUM-004", "PV-202601-004", 50000, status="已核准", is_paid=0)

    r = client.get("/api/quotations/MQ-FINSUM-004/finance-summary", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()

    extras = body["settlementExtras"]
    assert extras["total"] == 10000
    assert extras["items"][0]["docNo"] == "AB12345678"
    assert extras["items"][1]["docNo"] == ""          # 沒填就是空字串，不是 None
    # 額外支出沒有被混進應付
    assert body["payable"]["approvedUnpaidTotal"] == 50000
