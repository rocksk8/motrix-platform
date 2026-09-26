"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/test_case_management_logic_fixes_2026_08_28.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-08-28（案件管理邏輯稽核）發現並修復的 2 個問題：
①payment_item_amounts() 沒有處理已核准稅額沖銷（taxExempt），導致沖銷後
  營運報表/AR帳齡/dashboard應收帳款仍把已沖銷的稅額算進已收/應收金額
②list_case_updates()（案件管理「動態」Tab）合併 5 種來源時，只有其中一種
  （audit_log）做了跨表時間格式正規化，dev_logs 用空白分隔格式，跟其餘多數
  來源的 'T' 分隔格式排序時永遠排在前面（不管實際時間點），已抽成共用的
  helpers/quotations.py::norm_at() 套用到全部來源。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── ①payment_item_amounts() taxExempt 換算 ──────────────────────────────────


def test_tax_export_shows_original_invoiced_tax_for_exempt_item(client, make_user):
    """稅務匯出：taxExempt（已核准稅額沖銷）是「開立發票之後」才發生的內部應收
    帳款減讓（公司決定不跟客戶收那筆稅額），不會、也不能追溯改變開立當下就已
    確定的法定稅捐義務——這個品項既然填了 invoiceNo，代表發票早已按原始金額
    （105,000 含稅）開立，稅務匯出該照原始金額算出稅額 5,000，不是沖銷後的
    customer 應付金額（100,000）。2026-09-02 修復：舊版把這種情況的稅額列成
    0，等於讓已開立、已產生銷項稅額的發票在申報文件上憑空消失（見
    reports.py::_collect_tax_invoices() docstring）。taxExempt 對「客戶還欠
    多少」（AR帳齡/收款率）的折算邏輯不受影響，只是不再連動改寫這裡。"""
    from helpers.receivables import collect_tax_invoices as _collect_tax_invoices
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "訂金款", "amount": 105000, "received": True,
                 "receivedAt": "2026-08-05", "invoiceNo": "AB12345678", "taxExempt": True},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-TAXEX-002", "已送出", "測試客戶", "測試專案", 105000, 100000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-08-01"),
        )
        conn.commit()
    finally:
        conn.close()

    rows = _collect_tax_invoices(year=2026)
    row = next(r for r in rows if r["quoteNo"] == "MQ-TAXEX-002")
    assert row["taxAmount"] == 5000
    assert row["amountPretax"] == 100000
    assert row["amountTotal"] == 105000


# ── ②norm_at() 跨來源時間格式正規化 ──────────────────────────────────────────
