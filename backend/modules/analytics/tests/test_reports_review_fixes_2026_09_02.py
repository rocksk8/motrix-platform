"""自 `tests/test_reports_review_fixes_2026_09_02.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import pytest
from fastapi import HTTPException
from tests.test_reports_review_fixes_2026_09_02 import (  # noqa: E402,F401  含 fixture
    _auth,
    _insert_case,
    _login,
    _sync_extra_to_table,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def test_report_excel_export_neutralizes_malicious_customer_name(client, make_user):
    """端到端：客戶名稱帶惡意公式字串，匯出的 Excel 不應含真正的公式儲存格。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-INJ-001", "已送出", "=HYPERLINK(\"http://evil.example\",\"click\")", "測試專案",
             100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
             "2026-01-01T00:00:00", "已成案", "2026-01-05"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/financial/excel?period=2026", headers=_auth(token))
    assert r.status_code == 200, r.text
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["案件清單"]
    found = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and "evil.example" in str(cell.value):
                found = True
                assert cell.data_type != "f", "惡意客戶名稱被寫成真正的公式儲存格"
    assert found, "測試資料應該要出現在案件清單分頁裡"


def test_other_expense_bucketed_by_expense_date_not_finalize_date(client, make_user):
    """精算 9 月才完結，但額外支出憑證日期是 3 月——月度加總跟明細都該算進 3 月。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已結案",
            "editHistory": [{"type": "settlement_finalized", "at": "2026-09-10T00:00:00"}],
            "settlement": {
                "status": "finalized",
                "extraItems": [{"category": "運費", "name": "貨運費用",
                                 "totalCost": 3000, "expenseDate": "2026-03-08"}],
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MQ-EXPDATE-001", "已送出", "測試客戶", "測試專案", 50000, 47619, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案"),
        )
        _sync_extra_to_table(conn, "MQ-EXPDATE-001")
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    body = r.json()
    march = next(m for m in body["expenses"]["monthly"] if m["month"] == "2026-03")
    sept  = next(m for m in body["expenses"]["monthly"] if m["month"] == "2026-09")
    assert march["other"] == 3000
    assert sept["other"] == 0
    detail = next(d for d in body["expenses"]["details"]["other"] if d["quoteNo"] == "MQ-EXPDATE-001")
    assert detail["date"] == "2026-03-08"

    # 「當月收支」明細切片跟月度加總必須一致：查 3 月時兩者都要看得到這筆
    r2 = client.get("/api/reports/expenses-monthly?year=2026&month=2026-03", headers=_auth(token))
    body2 = r2.json()
    assert body2["monthExpenseTotal"] == 3000
    assert any(it["quoteNo"] == "MQ-EXPDATE-001" for it in body2["monthExpenseItems"])


@pytest.mark.parametrize("bad_period", ["2026-13", "abc", "Q", "2026-Q9", "2026-00"])
def test_parse_period_rejects_malformed_input(bad_period):
    from modules.analytics.api.reports import _parse_period
    with pytest.raises(HTTPException) as exc:
        _parse_period(bad_period)
    assert exc.value.status_code == 400


def test_parse_period_still_accepts_valid_forms():
    from modules.analytics.api.reports import _parse_period
    assert _parse_period("2026")[0] == "2026 年度"
    assert _parse_period("2026-03")[0] == "2026 年 3 月"
    assert _parse_period("2026-Q2")[0] == "2026 年第 2 季"


def test_financial_endpoint_returns_400_not_500_on_bad_period(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/reports/financial?period=2026-13", headers=_auth(token))
    assert r.status_code == 400, r.text


def test_salesperson_rename_does_not_fragment_performance(client, make_user):
    from modules.analytics.api.reports import _collect
    username, password = make_user(username="sp_rename_test", role="sales")
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()

    # 案件是在「舊名字」時期建立的快照
    _insert_case("MQ-RENAME-001", sales_person="舊名字", sales_person_id=uid, total=100000)

    # 使用者之後改名
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE id=?", ("新名字", uid))
        conn.commit()
    finally:
        conn.close()

    _insert_case("MQ-RENAME-002", sales_person="新名字", sales_person_id=uid, total=200000)

    data = _collect("2026-01-01", "2026-12-31")
    matched = [s for s in data["salesPerf"] if s["salesPerson"] == "新名字"]
    assert len(matched) == 1, "改名前後的案件應歸併成同一位業務員（用 id 分組），不是拆成兩列"
    assert matched[0]["caseCount"] == 2
    assert matched[0]["totalAmount"] == 300000
    assert not any(s["salesPerson"] == "舊名字" for s in data["salesPerf"])


def test_achievement_matches_by_id_after_salesperson_rename(client, make_user):
    from modules.analytics.api.reports import _collect, _compute_achievement
    username, password = make_user(username="sp_rename_test2", role="sales")
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()

    _insert_case("MQ-RENAME-003", sales_person="舊名字2", sales_person_id=uid, total=150000)

    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE id=?", ("新名字2", uid))
        conn.commit()
    finally:
        conn.close()

    data = _collect("2026-01-01", "2026-12-31")
    targets = {"year": 2026, "annual": {}, "salesperson": [{"name": "新名字2", "revenue": 500000, "cases": 5}]}
    ach = _compute_achievement(2026, targets, data["casesAll"])
    sp = next(s for s in ach["salesperson"] if s["name"] == "新名字2")
    assert sp["ytdRevenue"] == 150000, "目標設定用現在的名字，應該要能對應到改名前建立的案件（用 salesPersonId 比對）"
    assert sp["ytdCases"] == 1
