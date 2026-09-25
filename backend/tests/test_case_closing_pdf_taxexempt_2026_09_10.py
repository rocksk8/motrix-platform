"""2026-09-10 稽核發現：結案報表 PDF 的收款明細漏傳 `pretax`。

`payment_item_amounts()` 在 2026-08-28 新增 `pretax` 參數，讓已核准稅額沖銷
（`taxExempt=True`）的款項換算成未稅金額——當時掃過 reports.py／dashboard.py
共 12 個呼叫點，但沒掃到 `pdf_gen.py::_case_closing_report_data()`。結果同一筆
已沖銷款項，畫面／Excel／營運報表顯示未稅、結案報表 PDF 顯示含稅。

本檔釘住兩件事：
  ① 已沖銷款項在結案報表資料裡就是未稅金額
  ② 未沖銷款項不受影響（沒有反過來把正常款項也打折）
並額外釘住「PDF 與營運報表對同一筆案件算出同一個數字」這個跨模組一致性。
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# 含稅 1,050,000 / 未稅 1,000,000（比例剛好 1/1.05，方便驗算）
TOTAL = 1050000
PRETAX = 1000000


def _seed_case(conn, quote_no, items):
    data_json = json.dumps({
        "dealTag": "已結案",
        "caseRecord": {"payment": {"items": items}},
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "沖銷測客", "沖銷測專", TOTAL, PRETAX, data_json,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案", "2026-03-01"),
    )


def test_closing_report_converts_tax_exempt_item_to_pretax(client, make_user):
    """核心：taxExempt 的款項在結案報表資料裡是未稅金額，不是原本的含稅金額。"""
    import db
    from pdf_gen import _case_closing_report_data

    make_user(role="admin")
    conn = db.get_db()
    try:
        _seed_case(conn, "MQ-TAXEX-001", [
            # 已核准沖銷：應收只剩未稅 → 1,050,000 * 1,000,000 / 1,050,000 = 1,000,000
            {"id": 1, "type": "訂金", "pct": 100, "amount": TOTAL,
             "received": False, "taxExempt": True},
        ])
        conn.commit()
    finally:
        conn.close()

    data = _case_closing_report_data("MQ-TAXEX-001")
    rows = data["paymentRows"] if "paymentRows" in data else data.get("payment_rows")
    assert rows, f"結案報表沒有收款明細：{list(data)}"
    amt = rows[0]["amount"]
    assert amt == PRETAX, (
        f"已沖銷款項應換算成未稅 {PRETAX:,}，實際 {amt:,}"
        f"（若等於 {TOTAL:,} 代表 pretax 沒有傳進 payment_item_amounts()）"
    )


def test_closing_report_leaves_normal_item_untouched(client, make_user):
    """反向釘住：沒有 taxExempt 的款項金額完全不變，別把正常款項也打折了。"""
    import db
    from pdf_gen import _case_closing_report_data

    make_user(role="admin")
    conn = db.get_db()
    try:
        _seed_case(conn, "MQ-TAXEX-002", [
            {"id": 1, "type": "訂金", "pct": 100, "amount": TOTAL, "received": True,
             "receivedAt": "2026-03-10T00:00:00"},
        ])
        conn.commit()
    finally:
        conn.close()

    data = _case_closing_report_data("MQ-TAXEX-002")
    rows = data["paymentRows"] if "paymentRows" in data else data.get("payment_rows")
    assert rows[0]["amount"] == TOTAL, "未沖銷款項不該被換算"


def test_closing_report_matches_operations_report(client, make_user):
    """跨模組一致性：同一筆已沖銷案件，結案報表 PDF 與營運報表算出同一個數字。
    這才是使用者實際會撞到的症狀——兩份文件擺在一起金額對不上。"""
    import db
    from pdf_gen import _case_closing_report_data
    from modules.analytics.api import reports

    make_user(role="admin")
    conn = db.get_db()
    try:
        _seed_case(conn, "MQ-TAXEX-003", [
            {"id": 1, "type": "訂金", "pct": 50, "amount": 525000,
             "received": True, "receivedAt": "2026-03-10T00:00:00", "taxExempt": True},
            {"id": 2, "type": "尾款", "pct": 50, "amount": 525000, "received": False},
        ])
        conn.commit()
    finally:
        conn.close()

    data = _case_closing_report_data("MQ-TAXEX-003")
    rows = data["paymentRows"] if "paymentRows" in data else data.get("payment_rows")
    pdf_total = sum(r["amount"] for r in rows)

    label, d0, d1 = reports._parse_period("2026")
    collected = reports._collect(d0, d1)
    ops_items = [i for i in collected["allItems"] if i["quoteNo"] == "MQ-TAXEX-003"]
    ops_total = sum(i["amount"] for i in ops_items)

    assert ops_items, "營運報表沒有收到這筆案件，測試前提不成立"
    assert pdf_total == ops_total, (
        f"結案報表 PDF 合計 {pdf_total:,} 與營運報表合計 {ops_total:,} 不一致"
    )
