"""2026-09-09：精算「額外支出」只要填了就要計入月度支出，不必等精算完結。

原本 `dashboard.py::dashboard_monthly()`（首頁本月支出）與
`reports.py::_collect_expenses()`（營運報表月支出）都只撈
`settlement.status='finalized'` 的案件，草稿階段填的額外支出完全不算——但實際
作業順序是支出當下就先填進精算表單、案件全部結束後才做完結，中間可能隔好幾個
月，當月已經花掉的錢在報表與首頁上等於不存在。

兩處的歸月邏輯也曾經分岔（reports.py 2026-09-02 已改用 expenseDate，
dashboard.py 還在用精算完結時間），現在統一走
`helpers.settlement_extra_expenses()`，這裡一併把兩邊釘在一起測。
"""
import json
from datetime import date


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no, settlement, edit_history=None):
    import db
    conn = db.get_db()
    try:
        data = {"settlement": settlement, "caseRecord": {"payment": {"items": []}}}
        if edit_history is not None:
            data["editHistory"] = edit_history
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238,
             json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _this_month():
    return date.today().strftime("%Y-%m")


def _month_other_total(client, token, year, month):
    r = client.get(f"/api/reports/expenses-monthly?year={year}&month={month}", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(m for m in body["expenses"]["monthly"] if m["month"] == month)
    return row["other"], body["expenses"]["details"]["other"]


def test_draft_settlement_extra_counts_toward_monthly_expenses(client, make_user):
    """精算還是草稿，只要額外支出填了憑證日期在當月，就要算進當月「其他支出」。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-DRAFT", settlement={
        "status": "draft",
        "extraItems": [
            {"category": "運費", "description": "吊車運費", "docNo": "AB12345678",
             "totalCost": 8000, "expenseDate": f"{mo}-05"},
        ],
    })

    total, details = _month_other_total(client, token, int(mo[:4]), mo)
    assert total == 8000, "草稿精算的額外支出也要計入當月"
    row = next(d for d in details if "吊車運費" in d["desc"])
    assert row["pending"] is True, "精算未完結要標示 pending，讓報表看得出數字還會變"
    assert "AB12345678" in row["desc"], "單號要帶進明細，會計才對得回實體憑證"


def test_finalized_settlement_extra_still_counts_and_not_pending(client, make_user):
    """已完結的照舊要算，且 pending=False（既有行為不可回歸）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-FINAL", settlement={
        "status": "finalized",
        "extraItems": [
            {"category": "差旅", "description": "南下住宿", "totalCost": 5000,
             "expenseDate": f"{mo}-12"},
        ],
    }, edit_history=[{"type": "settlement_finalized", "at": f"{mo}-28T10:00:00"}])

    total, details = _month_other_total(client, token, int(mo[:4]), mo)
    assert total == 5000
    row = next(d for d in details if "南下住宿" in d["desc"])
    assert row["pending"] is False


def test_draft_extra_without_expense_date_falls_back_to_save_time(client, make_user):
    """草稿、沒填憑證日期：退回「最後一次精算存檔時間」歸月——對應使用者說的
    「當月有填寫就要彙整進去」。三種日期都沒有才會被略過（無從判斷月份）。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-NODATE", settlement={
        "status": "draft",
        "extraItems": [{"category": "其他", "description": "臨時工資", "totalCost": 3000}],
    }, edit_history=[{"type": "settlement_draft", "at": f"{mo}-20T09:00:00"}])

    total, details = _month_other_total(client, token, int(mo[:4]), mo)
    assert total == 3000, "沒填憑證日期時要用精算存檔時間歸月，不能整筆消失"
    assert any("臨時工資" in d["desc"] for d in details)


def test_extra_with_no_date_at_all_is_skipped(client, make_user):
    """完全沒有任何日期可用（草稿、沒憑證日期、連存檔歷程都沒有）就跳過——
    硬塞進某個月會污染月報，寧可不算。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-NOWHERE", settlement={
        "status": "draft",
        "extraItems": [{"category": "其他", "description": "來源不明", "totalCost": 9999}],
    })

    total, details = _month_other_total(client, token, int(mo[:4]), mo)
    assert total == 0
    assert not any("來源不明" in d["desc"] for d in details)


def test_dashboard_monthly_matches_reports_for_draft_extra(client, make_user):
    """首頁支出趨勢（/api/dashboard/expenses-monthly）跟營運報表月支出，對同一筆
    草稿額外支出要算出同一個數字
    ——這兩處過去各寫一份邏輯、連歸月依據都不同（dashboard 用精算完結時間、
    reports 用憑證日期），本來就對不起來。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-BOTH", settlement={
        "status": "draft",
        "extraItems": [{"category": "運費", "description": "貨運", "totalCost": 12000,
                        "expenseDate": f"{mo}-08"}],
    })

    reports_total, _ = _month_other_total(client, token, int(mo[:4]), mo)

    r = client.get("/api/dashboard/expenses-monthly", headers=_auth(token))
    assert r.status_code == 200, r.text
    dash = r.json()
    dash_row = next(m for m in dash["items"] if m["month"] == mo)

    assert reports_total == 12000
    assert dash_row["other"] == reports_total, \
        f"首頁與營運報表的當月其他支出必須一致：dashboard={dash_row['other']} reports={reports_total}"
