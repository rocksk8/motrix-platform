"""自 `tests/test_case_closing_pdf_taxexempt_2026_09_10.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
import pytest
from tests.test_case_closing_pdf_taxexempt_2026_09_10 import (  # noqa: E402,F401  含 fixture
    _seed_case,
)


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
