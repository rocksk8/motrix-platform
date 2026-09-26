"""2026-08-31：出納併入營運報表過程中，稽核案件管理/出納/營運報表三處金額
計算是否連動一致，發現 dashboard.py::dashboard_monthly()（首頁「銷售收入
趨勢/實際收款」月度圖表）用了裸的 `WHERE deal_tag IN (...)`，沒有比照同檔案
其餘 5 處用 `COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')`
寬鬆判斷——只有 data_json.dealTag 有值、DB 欄位 deal_tag 留空的舊格式報價單
（pre-v6 資料）會被這張圖表靜默漏算，但 cashier.py／_compute_ar_aging／
_collect_income_items／dashboard_stats.receivableSummary 都算得到，數字對
不起來。這題驗證修復後 dashboard_monthly() 也能正確算進這類舊格式資料。
"""
import json
from datetime import date


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_monthly_counts_quotation_with_dealtag_only_in_json(client, make_user):
    username, password = make_user(username="dm_admin1", role="superadmin")
    token = _login(client, username, password)

    received_month = date.today().isoformat()[:7]
    data_json = json.dumps({
        # dealTag 只寫在 JSON 裡，比照舊格式（pre-v6，deal_tag 欄位未回填）
        "dealTag": "已成案",
        "caseRecord": {
            "payment": {"items": [
                {"type": "訂金款", "pct": 100, "amount": 50000, "received": True,
                 "receivedAt": f"{received_month}-15", "actualAmount": 49500, "feeAmount": 500},
            ]},
        },
    })
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-DMFALLBACK-001", "已送出", "測試客戶", "測試專案", 50000, 47619, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "2026-01-01"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/dashboard/monthly", headers=_auth(token))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    this_month = [i for i in items if i["month"] == received_month]
    assert len(this_month) == 1
    assert this_month[0]["amount"] >= 49500
    assert this_month[0]["count"] >= 1
