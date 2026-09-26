"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_reports_tax_compliance_2026_09_02.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-09-02（公司內控＋台灣國稅局視角複查）發現並修復的 4 項：
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


# ── ③稅額四捨五入（ROUND_HALF_UP） ──────────────────────────────────────────


# ── ④匯出稽核記錄 ────────────────────────────────────────────────────────────
