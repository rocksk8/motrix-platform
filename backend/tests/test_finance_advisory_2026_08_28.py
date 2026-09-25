"""2026-08-28 財務顧問優化：資金水位總覽（應收帳齡+應付承攬商待匯款）、
稅務匯出（銷項發票清單 Excel）、銀行對帳單 CSV 比對。三個新端點皆為
admin+ only，共用 routers/reports.py，見該檔案內對應函式的 docstring
說明各自的資料模型取捨（為何不含 payment_requests / 料件進貨等）。"""
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

def test_cash_position_combines_ar_and_ap(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_ar_quotation("MQ-CASH-001", amount=30000, total=100000, received=False)
    _insert_approved_voucher("PV-CASH-001", "MQ-CASH-001", grand_total=12000)

    r = client.get("/api/reports/cash-position", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ar"]["total"] == 30000
    assert body["ap"]["total"] == 12000
    assert body["ap"]["count"] == 1
    assert body["ap"]["items"][0]["voucherNo"] == "PV-CASH-001"
    assert body["net"] == 30000 - 12000


def test_cash_position_excludes_paid_vouchers(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_ar_quotation("MQ-CASH-002", amount=5000, total=50000)
    _insert_approved_voucher("PV-CASH-002", "MQ-CASH-002", grand_total=9000, is_paid=1)

    r = client.get("/api/reports/cash-position", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ap"]["total"] == 0
    assert r.json()["ap"]["count"] == 0


def test_cash_position_requires_admin(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    r = client.get("/api/reports/cash-position", headers=_auth(token))
    assert r.status_code == 403


# ── 稅務匯出（銷項發票清單）────────────────────────────────────────────────────

def test_tax_export_lists_invoiced_items_with_tax_breakdown_and_year_filter(client, make_user):
    """單一呼叫涵蓋：已開發票品項正確列出＋稅額拆算正確／未開發票品項不列入／
    年份篩選排除不同年份資料——三個 tax-export 情境合併成一次匯出呼叫，避免連續
    呼叫觸發 helpers.xlsx_out.check_export_rate() 的 5 秒匯出冷卻（同一 pytest 進程內測試 user_id
    常常重複，見 test_cash_position 等其他檔案的既有慣例）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _insert_ar_quotation("MQ-TAX-001", amount=21000, total=100000, received=True)
    # 未開發票的品項（invoiceNo 空）不應出現
    _insert_ar_quotation("MQ-TAX-002", amount=8000, total=80000, received=False)
    # 2025 年收款的品項，year=2026 篩選時不應出現
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案", "customerTaxId": "87654321",
            "caseRecord": {"payment": {"items": [
                {"type": "全額", "amount": 5000, "received": True,
                 "receivedAt": "2025-11-01", "invoiceNo": "INV-OLD"},
            ]}},
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-TAX-003", "已送出", "測試客戶", "測試專案", 50000, 47619, data_json,
             "2025-01-01T00:00:00", "2025-01-01T00:00:00", "已成案", "2025-01-05"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/tax-export?year=2026", headers=_auth(token))
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["銷項發票清單"]
    # 2026-09-02 新增「發票開立日期」欄（期別歸屬改用這個欄位，見
    # reports.py::_collect_tax_invoices() docstring），欄位數由 8 變 9。
    header = [ws.cell(row=3, column=c).value for c in range(1, 10)]
    assert header == ["發票號碼", "發票開立日期", "收款日期", "案件號", "客戶名稱", "統一編號",
                       "金額（未稅）", "稅額", "金額（含稅）"]
    data_row = [ws.cell(row=4, column=c).value for c in range(1, 10)]
    assert data_row[0] == "INV-0001"
    assert data_row[2] == "2026-03-15"  # 沒填 invoiceDate，退回收款日期
    assert data_row[3] == "MQ-TAX-001"
    assert data_row[5] == "12345678"
    assert data_row[6] == 20000   # 未稅
    assert data_row[7] == 1000    # 稅額
    assert data_row[8] == 21000   # 含稅
    # 只有一筆符合 2026 年的已開發票品項，第 5 列應為合計列（2025 年那筆被篩掉）
    assert ws.cell(row=5, column=1).value == "合計"
    assert ws.cell(row=5, column=9).value == 21000


def test_tax_export_requires_admin(client, make_user):
    username, password = make_user(role="engineer")
    token = _login(client, username, password)
    r = client.get("/api/reports/tax-export", headers=_auth(token))
    assert r.status_code == 403


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
