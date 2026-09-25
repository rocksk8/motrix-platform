"""自 `tests/test_case_management_logic_fixes_2026_08_28.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json


def test_ar_aging_excludes_tax_exempt_portion(client, make_user):
    """整合測試：已核准沖銷的未收款項目，帳齡分析裡的應收金額要是未稅價，
    不是原始含稅金額——直接用真實案件（MQ-202608-007）發現的落差重現。"""
    from modules.analytics.api.reports import _compute_ar_aging
    import db
    conn = db.get_db()
    try:
        data = {
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"type": "訂金款", "amount": 105000, "received": False, "taxExempt": True},
            ]}},
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-TAXEX-001", "已送出", "測試客戶", "測試專案", 105000, 100000,
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             "已成案", "2026-08-01"),
        )
        conn.commit()
    finally:
        conn.close()

    aging = _compute_ar_aging()
    all_items = [it for band in aging["bands"] for it in band["items"] if it["quoteNo"] == "MQ-TAXEX-001"]
    assert len(all_items) == 1
    assert all_items[0]["amount"] == 100000  # 未稅價，不是 105000
