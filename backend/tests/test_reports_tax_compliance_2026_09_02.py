"""2026-09-02（公司內控＋台灣國稅局視角複查）發現並修復的 4 項：
①發票號碼格式驗證＋重複偵測（helpers/quotations.py::validate_invoice_no()）
②稅務匯出不再讓「已核准稅額沖銷」回溯性地把已開立發票的稅額改成 0
③稅額計算改用四捨五入（ROUND_HALF_UP），不用 Python 內建的銀行家捨入
④營運報表/銷項發票清單/銀行對帳單匯出補上稽核記錄
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, invoice_no=""):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": invoice_no},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


# ── ①發票號碼格式/重複驗證 ───────────────────────────────────────────────────

def test_invoice_no_rejects_malformed_format(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVFMT-001")
    r = client.patch("/api/quotations/MQ-INVFMT-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": "invoice-123"})
    assert r.status_code == 400, r.text


def test_invoice_no_accepts_valid_format_case_insensitive(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVFMT-002")
    r = client.patch("/api/quotations/MQ-INVFMT-002/payment/0", headers=_auth(token),
                      json={"invoiceNo": "ab12345678"})
    assert r.status_code == 200, r.text


def test_invoice_no_rejects_duplicate_across_quotes(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVDUP-001", invoice_no="AB12345678")
    _make_quotation("MQ-INVDUP-002")
    r = client.patch("/api/quotations/MQ-INVDUP-002/payment/0", headers=_auth(token),
                      json={"invoiceNo": "AB12345678"})
    assert r.status_code == 400, r.text
    assert "MQ-INVDUP-001" in r.text


def test_invoice_no_allows_reusing_same_slot(client, make_user):
    """修改自己這筆（同一張報價單同一期）不該跟自己比對出假警報。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVSAME-001", invoice_no="AB12345678")
    r = client.patch("/api/quotations/MQ-INVSAME-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": "AB12345678"})
    assert r.status_code == 200, r.text


def test_invoice_no_empty_string_still_allowed(client, make_user):
    """清空發票號碼（尚未開立）維持合法，不受格式檢查擋下。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVEMPTY-001", invoice_no="AB12345678")
    r = client.patch("/api/quotations/MQ-INVEMPTY-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": ""})
    assert r.status_code == 200, r.text


# ── ②稅務匯出不再被稅額沖銷回溯改寫 ─────────────────────────────────────────

def test_tax_export_uses_original_amount_ignoring_writeoff(client, make_user):
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "尾款", "amount": 210000, "received": True,
                 "receivedAt": "2026-05-10", "invoiceNo": "CD98765432", "taxExempt": True},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-TAXFIX-001", "已送出", "測試客戶", "測試專案", 210000, 200000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-05-01"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = _collect_tax_invoices(year=2026)
    row = next(r for r in rows if r["quoteNo"] == "MQ-TAXFIX-001")
    # 原始開立金額 210000 含稅，不是沖銷後的客戶應付金額
    assert row["amountTotal"] == 210000
    assert row["taxAmount"] == 10000
    assert row["amountPretax"] == 200000


def test_ar_aging_still_uses_writeoff_adjusted_amount(client, make_user):
    """taxExempt 對「客戶還欠多少」的折算邏輯（AR帳齡/收款率）不受這次修復影響
    ——只有稅務匯出改用原始金額，AR 這條線本來就該用沖銷後的數字。"""
    from routers.reports import _compute_ar_aging
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "尾款", "amount": 210000, "received": False, "taxExempt": True},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-TAXFIX-002", "已送出", "測試客戶", "測試專案", 210000, 200000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2020-01-01"),
        )
        conn.commit()
    finally:
        conn.close()

    ar = _compute_ar_aging()
    item = next(i for band in ar["bands"] for i in band["items"] if i["quoteNo"] == "MQ-TAXFIX-002")
    assert item["amount"] == 200000  # 沖銷後的未稅等值金額，不是原始 210000


# ── ③稅額四捨五入（ROUND_HALF_UP） ──────────────────────────────────────────

def test_round_half_up_matches_taiwan_invoice_convention():
    from routers.reports import _round_half_up
    assert _round_half_up(2.5) == 3   # Python 內建 round(2.5) 會是 2（銀行家捨入），這裡要是 3
    assert _round_half_up(3.5) == 4
    assert _round_half_up(-2.5) == -3  # Decimal ROUND_HALF_UP 對 .5 一律「遠離零」進位
    assert _round_half_up(100.4) == 100


# ── ④匯出稽核記錄 ────────────────────────────────────────────────────────────

def test_excel_export_writes_audit_log(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/reports/financial/excel?period=2026", headers=_auth(token))
    assert r.status_code == 200, r.text
    r2 = client.get("/api/audit-log?action=reports.export", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    items = r2.json()["items"]
    assert any(e["target_id"] == "financial" for e in items)


def test_tax_export_writes_audit_log(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/reports/tax-export", headers=_auth(token))
    assert r.status_code == 200, r.text
    r2 = client.get("/api/audit-log?action=reports.export", headers=_auth(token))
    items = r2.json()["items"]
    assert any(e["target_id"] == "tax-export" and "銷項發票清單" in (e.get("target_label") or "") for e in items)
