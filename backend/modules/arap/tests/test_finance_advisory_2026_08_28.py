"""需要應收應付（M05）的題：銀行對帳 POST /api/reports/bank-reconcile 已收回 M05（刪掉 modules/arap 時隨模組消失，PLAYBOOK §B-11）。

（2026-09-26 自 modules/analytics/tests/test_finance_advisory_2026_08_28.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-08-28 財務顧問優化：資金水位總覽（應收帳齡+應付承攬商待匯款）、
稅務匯出（銷項發票清單 Excel）、銀行對帳單 CSV 比對。三個新端點皆為
admin+ only，共用 routers/reports.py，見該檔案內對應函式的 docstring
說明各自的資料模型取捨（為何不含 payment_requests / 料件進貨等）。
"""
import io
import json

import openpyxl


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_ar_quotation(quote_no, amount, total=100000, received=False):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "customerTaxId": "12345678",
            "caseRecord": {
                "payment": {
                    "items": [
                        {"type": "訂金款", "amount": amount, "received": received,
                         "receivedAt": "2026-03-15" if received else "",
                         "invoiceNo": "INV-0001" if received else ""},
                    ]
                }
            },
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, round(total / 1.05), data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-05"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_approved_voucher(voucher_no, quote_no, grand_total, is_paid=0):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "amount", "[]", grand_total, "completed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        dispatch_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        snapshot = json.dumps({"vendorName": "測試承攬商", "grandTotal": grand_total}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO contractor_payment_vouchers "
            "(voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, data_json, "
            "is_paid, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (voucher_no, dispatch_id, quote_no, None, "已核准", snapshot, "{}",
             is_paid, "tester", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


# ── 資金水位總覽 ─────────────────────────────────────────────────────────────


# ── 稅務匯出（銷項發票清單）────────────────────────────────────────────────────


# ── 銀行對帳單比對 ───────────────────────────────────────────────────────────

def _csv_bytes(text):
    return io.BytesIO(text.encode("utf-8-sig"))


def test_bank_reconcile_matches_by_amount(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_approved_voucher("PV-BANK-001", "MQ-BANK-001", grand_total=45000)

    csv_text = "交易日期,金額,摘要\n2026-03-20,45000,匯款測試承攬商\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matchedCount"] == 1
    assert body["unmatchedBankCount"] == 0
    assert body["bankRows"][0]["match"]["voucherNo"] == "PV-BANK-001"
    assert body["unmatchedVouchers"] == []


def test_bank_reconcile_reports_unmatched_on_both_sides(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_approved_voucher("PV-BANK-002", "MQ-BANK-002", grand_total=60000)

    csv_text = "交易日期,金額,摘要\n2026-03-20,99999,不相符金額\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matchedCount"] == 0
    assert body["unmatchedBankCount"] == 1
    assert len(body["unmatchedVouchers"]) == 1
    assert body["unmatchedVouchers"][0]["voucherNo"] == "PV-BANK-002"


def test_bank_reconcile_same_amount_only_matches_once(client, make_user):
    """兩筆待匯款申請金額剛好相同時，一筆銀行紀錄只能配對其中一筆，
    不能讓同一筆申請被重複配對（見 bank_reconcile() docstring）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_approved_voucher("PV-BANK-003", "MQ-BANK-003", grand_total=30000)
    _insert_approved_voucher("PV-BANK-004", "MQ-BANK-004", grand_total=30000)

    csv_text = "交易日期,金額,摘要\n2026-03-20,30000,款項一\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matchedCount"] == 1
    assert len(body["unmatchedVouchers"]) == 1


def test_bank_reconcile_missing_amount_column_returns_400(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    csv_text = "日期,備註\n2026-03-20,無金額欄位\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 400


def test_bank_reconcile_requires_admin(client, make_user):
    username, password = make_user(role="viewer")
    token = _login(client, username, password)
    csv_text = "交易日期,金額,摘要\n2026-03-20,1000,x\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 403


def test_bank_reconcile_allows_cashier_module_2026_08_31(client, make_user):
    """2026-08-31（財務/出納權限分工）：銀行對帳單比對搬進出納模組，非
    admin+ 但具備 cashier 模組的使用者也要能存取（不需要完整管理員權限）。"""
    username, password = make_user(role="sales", modules=["cashier"])
    token = _login(client, username, password)
    csv_text = "交易日期,金額,摘要\n2026-03-20,1000,x\n"
    r = client.post(
        "/api/reports/bank-reconcile",
        headers=_auth(token),
        files={"file": ("bank.csv", _csv_bytes(csv_text), "text/csv")},
    )
    assert r.status_code == 200, r.text
