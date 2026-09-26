"""自 `tests/test_reports_tax_compliance_2026_09_02.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
from tests.test_reports_tax_compliance_2026_09_02 import (  # noqa: E402,F401  含 fixture
    _auth,
    _login,
)


def test_ar_aging_still_uses_writeoff_adjusted_amount(client, make_user):
    """taxExempt 對「客戶還欠多少」的折算邏輯（AR帳齡/收款率）不受這次修復影響
    ——只有稅務匯出改用原始金額，AR 這條線本來就該用沖銷後的數字。"""
    from modules.analytics.api.reports import _compute_ar_aging
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


def test_round_half_up_matches_taiwan_invoice_convention():
    from modules.analytics.api.reports import _round_half_up
    assert _round_half_up(2.5) == 3   # Python 內建 round(2.5) 會是 2（銀行家捨入），這裡要是 3
    assert _round_half_up(3.5) == 4
    assert _round_half_up(-2.5) == -3  # Decimal ROUND_HALF_UP 對 .5 一律「遠離零」進位
    assert _round_half_up(100.4) == 100


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
