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
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import date
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')



def _sync_extra_to_table(conn, quote_no):
    """把剛種進 data_json 的 settlement.extraItems 搬進 case_extra_expenses。

    2026-09-11（migration v75）之後額外支出住在獨立資料表，data_json 裡那份只是
    唯讀備份、報表不再讀它。用 migration 自己那支搬移函式，欄位對應與歸月的
    fallback 才不會跟正式路徑漂移。"""
    import db as _db
    import json as _json
    row = conn.execute(
        "SELECT data_json, sales_person FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        return
    _db._move_extra_items_for_quote(
        conn, quote_no, _json.loads(row["data_json"] or "{}"), row["sales_person"] or "")

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
        _sync_extra_to_table(conn, quote_no)
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
    # 2026-09-11 語意變更：`pending` 從「精算未完結」改成「送審未核准」。
    # 額外支出搬到獨立資料表並接上簽核之後，精算的草稿/完結狀態不再決定這個旗標——
    # 這一筆是搬移過來的（視為已核准），所以 pending=False。真正的 pending 情境
    # 見 test_unapproved_extra_counts_but_is_flagged_pending()。
    assert row["pending"] is False, "已核准的項目不該被標成 pending"
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


def test_unapproved_extra_counts_but_is_flagged_pending(client, make_user, seed_extra_expense):
    """送審中的額外支出**照樣算進當月支出**，但要標 pending（2026-09-11 使用者指定的規則）。

    兩邊都重要：
      - 不算進去 → 當月已經花掉的錢在報表上消失，正是 2026-09-09 修過的問題
      - 不標 pending → 看報表的人不知道這個數字還可能被駁回而改變
    """
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    mo = _this_month()
    _make_case("MQ-EXP-PENDING", settlement={"status": "draft", "extraItems": []})
    seed_extra_expense("MQ-EXP-PENDING", total_cost=4200, category="外包",
                       description="臨時外包工", expense_date=f"{mo}-09",
                       status="待審核")

    total, details = _month_other_total(client, token, int(mo[:4]), mo)
    assert total == 4200, "送審中的項目也要計入當月支出"
    row = next(d for d in details if "臨時外包工" in d["desc"])
    assert row["pending"] is True, "尚未核准要標 pending，讓看報表的人知道數字還會變"
