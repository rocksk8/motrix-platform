"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_invoice_date_and_case_record_validation_2026_09_02.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-09-02（追加）：
①案件管理財務Tab「整包存檔」(update_case_record/PATCH .../case-record) 是使用者
  實際填發票號碼最常用的路徑，先前只在 mark_payment()（PATCH .../payment/{idx}，
  出納快速登錄用）加上格式/重複驗證，這支主要路徑完全沒接到，等於防呆對大多數
  真實使用情境沒有生效——這裡補上，用 item id 比對排除自己這筆（不能用陣列位置，
  款項期別本來就能自由新增/刪除/排序）。
②統一發票「開立日期」欄位（invoiceDate）：稅務匯出期別歸屬應該看這個，不是看
  收款日期（receivedAt）。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, invoice_no="", invoice_date="", item_id=1):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"id": item_id, "type": "訂金款", "pct": 30, "amount": 30000, "received": False,
                     "actualAmount": None, "feeAmount": 0, "note": "",
                     "invoiceNo": invoice_no, "invoiceDate": invoice_date},
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


def _case_record(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"] or "{}")["caseRecord"]


# ── ①update_case_record 也要驗證發票號碼 ────────────────────────────────────


# ── ②稅務匯出期別歸屬改用 invoiceDate ────────────────────────────────────────

def test_tax_export_period_uses_invoice_date_not_received_date(client, make_user):
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "尾款", "amount": 105000, "received": True,
                 "receivedAt": "2026-06-20", "invoiceNo": "EF11223344", "invoiceDate": "2026-03-08"},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-INVDATE-001", "已送出", "測試客戶", "測試專案", 105000, 100000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()

    # 依開立日期（3月）查得到，依收款日期（6月）查不到——確認期別歸屬真的
    # 改用 invoiceDate，不是 receivedAt
    march_rows = _collect_tax_invoices(year=2026, month=3)
    june_rows  = _collect_tax_invoices(year=2026, month=6)
    assert any(r["quoteNo"] == "MQ-INVDATE-001" for r in march_rows)
    assert not any(r["quoteNo"] == "MQ-INVDATE-001" for r in june_rows)

    row = next(r for r in march_rows if r["quoteNo"] == "MQ-INVDATE-001")
    assert row["invoiceDate"] == "2026-03-08"
    assert row["date"] == "2026-06-20"  # "date" 欄位仍是收款日，供 T100 現金基礎傳票用


def test_tax_export_falls_back_to_received_date_when_invoice_date_missing(client, make_user):
    """舊資料沒有 invoiceDate 欄位時，期別歸屬退回 receivedAt，不會讓歷史資料
    從任何年月篩選結果裡憑空消失。"""
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "尾款", "amount": 52500, "received": True,
                 "receivedAt": "2026-07-10", "invoiceNo": "GH55667788"},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-INVDATE-002", "已送出", "測試客戶", "測試專案", 52500, 50000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = _collect_tax_invoices(year=2026, month=7)
    assert any(r["quoteNo"] == "MQ-INVDATE-002" for r in rows)


def test_accounting_export_date_field_still_uses_received_date(client, make_user):
    """T100 現金基礎傳票（accounting_export.py）讀的是 "date" 欄位，必須維持
    收款日期，不能被這次的 invoiceDate 期別修正連帶改掉，否則傳票日期會跟
    銀行實際入帳日對不上。"""
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "尾款", "amount": 210000, "received": True,
                 "receivedAt": "2026-08-01", "invoiceNo": "IJ99887766", "invoiceDate": "2026-05-01"},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-INVDATE-003", "已送出", "測試客戶", "測試專案", 210000, 200000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = _collect_tax_invoices()
    row = next(r for r in rows if r["quoteNo"] == "MQ-INVDATE-003")
    assert row["date"] == "2026-08-01"
    assert row["invoiceDate"] == "2026-05-01"
