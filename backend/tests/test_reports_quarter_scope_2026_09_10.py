"""2026-09-10：營運報表「季」範圍支援的規格測試。

背景：頂部 period-bar 有月/季/年三種期別，但「本期收支」KPI 區塊與
「已收款／未收款／月支出」三個分頁走的是獨立的 `/api/reports/expenses-monthly`
與 `/api/reports/receivables-monthly` 兩支端點，這兩支原本只吃 year + month
兩種範圍，沒有季的概念——使用者切到「季」時下方金額完全不動。

本檔驗證新增的 `quarter` 參數：
  ① 參數驗證（None／1-4 合法，其餘 400）
  ② 季的數字 == 該季三個月各自查詢的加總（這是「季」正確與否的唯一判準）
  ③ 季的恆等式 quarterReceivableTotal == quarterCollectedTotal + quarterOutstandingTotal
  ④ 不傳 quarter 時季欄位為空，且 month*/year* 兩套欄位行為完全不變
     （向後相容：Excel／PDF／每月結算寄信都是不傳 quarter 的既有呼叫端）
  ⑤ `_month_expense_slice()` 重構成 `_months_expense_slice()` 包裝後行為不變
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_case(conn, quote_no, quote_date, items, total=1000000, pretax=952381):
    """建一張已成案報價單，payment.items 直接給定。"""
    data_json = json.dumps({
        "dealTag": "已成案",
        "caseRecord": {"payment": {"items": items}},
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "測客", "測專", total, pretax, data_json,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", quote_date),
    )


# ── ① 參數驗證 ───────────────────────────────────────────────────────────────

def test_quarter_param_validation(client, make_user):
    """quarter 只接受 1-4。範圍外的整數由 _validate_quarter() 擋成 400；非整數
    字串則更早一步被 FastAPI 的 int 型別轉換擋成 422。兩者都是明確的用戶端錯誤，
    重點是都不會漏到 main.py 全域 handler 變成通用 500。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    for path in ("/api/reports/receivables-monthly", "/api/reports/expenses-monthly"):
        for bad in ("0", "5", "-1"):
            r = client.get(f"{path}?year=2026&month=2026-08&quarter={bad}", headers=_auth(token))
            assert r.status_code == 400, \
                f"{path} quarter={bad!r} 應被 _validate_quarter 擋成 400，實際 {r.status_code}: {r.text}"
        r = client.get(f"{path}?year=2026&month=2026-08&quarter=abc", headers=_auth(token))
        assert r.status_code == 422, \
            f"{path} quarter='abc' 應被型別轉換擋成 422，實際 {r.status_code}: {r.text}"
        for good in ("1", "2", "3", "4"):
            r = client.get(f"{path}?year=2026&month=2026-08&quarter={good}", headers=_auth(token))
            assert r.status_code == 200, \
                f"{path} quarter={good!r} 應被接受，實際 {r.status_code}: {r.text}"


def test_quarter_still_requires_admin(client, make_user):
    """帶 quarter 不會繞過既有的 admin+ 權限檢查。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)
    for path in ("/api/reports/receivables-monthly", "/api/reports/expenses-monthly"):
        r = client.get(f"{path}?year=2026&month=2026-08&quarter=3", headers=_auth(token))
        assert r.status_code == 403, f"{path} 非 admin 應 403，實際 {r.status_code}"


# ── ② 季 == 該季三個月加總（應收） ───────────────────────────────────────────

def test_receivables_quarter_equals_sum_of_its_months(client, make_user):
    """Q3 的應收 == 2026-07 + 2026-08 + 2026-09 三次月查詢的加總，
    且 2026-06（Q2）的案件不得混進來。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        _insert_case(conn, "MQ-Q3-JUL", "2026-07-05",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 100000,
                       "received": True, "receivedAt": "2026-07-20T00:00:00"}])
        # 2026-09-12：分月依據改成款項自己的日期，未收款看的是 expectedReceiptDate。
        # 不給日期的話這筆會落到 undated 那組（不屬於任何月份），季合計就對不起來
        # ——那是刻意的新行為，不是這支測試要驗的東西，所以補上預計收款日。
        _insert_case(conn, "MQ-Q3-AUG", "2026-08-05",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 200000,
                       "received": False, "expectedReceiptDate": "2026-08-25"}])
        _insert_case(conn, "MQ-Q3-SEP", "2026-09-05",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 300000,
                       "received": True, "receivedAt": "2026-09-20T00:00:00"}])
        # Q2 的案件——用來確認季的邊界沒有外溢
        _insert_case(conn, "MQ-Q2-JUN", "2026-06-05",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 999000,
                       "received": True, "receivedAt": "2026-06-20T00:00:00"}])
        conn.commit()
    finally:
        conn.close()

    months_total = 0
    for mo in ("2026-07", "2026-08", "2026-09"):
        r = client.get(f"/api/reports/receivables-monthly?year=2026&month={mo}", headers=_auth(token))
        assert r.status_code == 200, r.text
        months_total += r.json()["monthReceivableTotal"]

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-09&quarter=3",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["quarterReceivableTotal"] == months_total, \
        f"Q3 季合計 {data['quarterReceivableTotal']} 應等於七八九三個月加總 {months_total}"

    quote_nos = {it["quoteNo"] for it in data["quarterReceivableItems"]}
    assert {"MQ-Q3-JUL", "MQ-Q3-AUG", "MQ-Q3-SEP"} <= quote_nos
    assert "MQ-Q2-JUN" not in quote_nos, "Q2 的案件不應出現在 Q3 結果裡"

    # 已收/未收也要分對邊
    assert "MQ-Q3-JUL" in {it["quoteNo"] for it in data["quarterCollectedItems"]}
    assert "MQ-Q3-AUG" in {it["quoteNo"] for it in data["quarterOutstandingItems"]}


def test_receivables_quarter_identity_holds(client, make_user):
    """季版恆等式：quarterReceivableTotal == quarterCollectedTotal + quarterOutstandingTotal
    （比照既有月/年兩套欄位的規格）。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        _insert_case(conn, "MQ-QID-001", "2026-05-01",
                     [{"id": 1, "type": "訂金", "pct": 50, "amount": 400000,
                       "received": True, "receivedAt": "2026-05-10T00:00:00"},
                      {"id": 2, "type": "驗收款", "pct": 50, "amount": 400000,
                       "received": False}])
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-05&quarter=2",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["quarterReceivableTotal"] == d["quarterCollectedTotal"] + d["quarterOutstandingTotal"], \
        (f"quarterReceivableTotal({d['quarterReceivableTotal']}) 應等於 "
         f"quarterCollectedTotal({d['quarterCollectedTotal']}) + "
         f"quarterOutstandingTotal({d['quarterOutstandingTotal']})")


# ── ② 季 == 該季三個月加總（收支） ───────────────────────────────────────────

def test_expenses_quarter_income_equals_sum_of_its_months(client, make_user):
    """收支端點的季收入 == 該季三個月各自查詢的加總；季外的收款不得混入。
    收入是依 receivedAt（現金流口徑），與應收的 wonMonth 口徑不同，所以要分開驗。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        _insert_case(conn, "MQ-INC-JUL", "2026-07-01",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 110000,
                       "received": True, "receivedAt": "2026-07-15T00:00:00"}])
        _insert_case(conn, "MQ-INC-SEP", "2026-09-01",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 220000,
                       "received": True, "receivedAt": "2026-09-15T00:00:00"}])
        _insert_case(conn, "MQ-INC-OCT", "2026-10-01",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 888000,
                       "received": True, "receivedAt": "2026-10-15T00:00:00"}])
        conn.commit()
    finally:
        conn.close()

    months_total = 0
    for mo in ("2026-07", "2026-08", "2026-09"):
        # 2026-09-24 AC2：預設改權責口徑；本題驗的是「收入依收款日」＝現金口徑 ⇒ 明確帶 basis=cash
        r = client.get(f"/api/reports/expenses-monthly?year=2026&month={mo}&basis=cash", headers=_auth(token))
        assert r.status_code == 200, r.text
        months_total += r.json()["monthIncomeTotal"]

    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&quarter=3&basis=cash",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["quarterIncomeTotal"] == months_total, \
        f"Q3 季收入 {data['quarterIncomeTotal']} 應等於七八九三個月加總 {months_total}"

    quote_nos = {it["quoteNo"] for it in data["quarterIncomeItems"]}
    assert {"MQ-INC-JUL", "MQ-INC-SEP"} <= quote_nos
    assert "MQ-INC-OCT" not in quote_nos, "Q4 的收款不應出現在 Q3 結果裡"


def test_expenses_quarter_expense_equals_sum_of_its_months(client, make_user):
    """季支出 == 該季三個月支出加總（走 _months_expense_slice 的新路徑）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    months_total = 0
    for mo in ("2026-07", "2026-08", "2026-09"):
        # 2026-09-24 AC2：預設改權責口徑；本題驗的是「收入依收款日」＝現金口徑 ⇒ 明確帶 basis=cash
        r = client.get(f"/api/reports/expenses-monthly?year=2026&month={mo}&basis=cash", headers=_auth(token))
        assert r.status_code == 200, r.text
        months_total += r.json()["monthExpenseTotal"]

    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&quarter=3&basis=cash",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["quarterExpenseTotal"] == months_total


# ── ④ 向後相容：不傳 quarter 時的行為完全不變 ────────────────────────────────

def test_without_quarter_param_quarter_fields_are_empty(client, make_user):
    """不傳 quarter 時季欄位為空集合／0，且 quarter 欄位本身是 null。
    既有呼叫端（Excel／PDF／每月結算寄信）都不傳 quarter，行為必須零變化。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-08", headers=_auth(token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["receivablesQuarter"] is None
    assert d["quarterReceivableItems"] == []
    assert d["quarterReceivableTotal"] == 0
    assert d["quarterCollectedTotal"] == 0
    assert d["quarterOutstandingTotal"] == 0

    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-08", headers=_auth(token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["expenseQuarter"] is None
    assert d["quarterIncomeItems"] == []
    assert d["quarterIncomeTotal"] == 0
    assert d["quarterExpenseTotal"] == 0


def test_month_and_year_fields_unchanged_by_quarter_param(client, make_user):
    """帶不帶 quarter，month*/year* 兩套欄位的值必須一模一樣——季是純增量欄位，
    不能反過來影響既有欄位。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        _insert_case(conn, "MQ-UNCHANGED-01", "2026-08-05",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 150000,
                       "received": True, "receivedAt": "2026-08-20T00:00:00"}])
        conn.commit()
    finally:
        conn.close()

    keys_recv = ["monthReceivableTotal", "monthCollectedTotal", "monthOutstandingTotal",
                 "yearReceivableTotal", "yearCollectedTotal", "yearOutstandingTotal"]
    a = client.get("/api/reports/receivables-monthly?year=2026&month=2026-08",
                   headers=_auth(token)).json()
    b = client.get("/api/reports/receivables-monthly?year=2026&month=2026-08&quarter=3",
                   headers=_auth(token)).json()
    for k in keys_recv:
        assert a[k] == b[k], f"receivables 欄位 {k} 因為帶了 quarter 而改變：{a[k]} → {b[k]}"

    keys_exp = ["monthIncomeTotal", "monthExpenseTotal", "monthUnreceivedTotal", "yearIncomeTotal"]
    a = client.get("/api/reports/expenses-monthly?year=2026&month=2026-08",
                   headers=_auth(token)).json()
    b = client.get("/api/reports/expenses-monthly?year=2026&month=2026-08&quarter=3",
                   headers=_auth(token)).json()
    for k in keys_exp:
        assert a[k] == b[k], f"expenses 欄位 {k} 因為帶了 quarter 而改變：{a[k]} → {b[k]}"


# ── ⑤ _month_expense_slice 重構後行為不變 ────────────────────────────────────

def test_month_expense_slice_still_prefix_matches():
    """`_month_expense_slice()` 改成 `_months_expense_slice()` 的包裝之後，仍必須
    是「月份前綴字串比對」而不是日期區間比對——details 的 date 欄位長度不保證是
    完整 YYYY-MM-DD，改用區間比對會讓只有 YYYY-MM 的資料被靜默丟掉。"""
    from routers import reports

    expenses = {"details": {
        "contractor": [
            {"date": "2026-08-15", "amount": 100},
            {"date": "2026-08", "amount": 200},      # 只有 YYYY-MM，不能被丟掉
            {"date": "2026-09-01", "amount": 400},
        ],
        "equipment": [
            {"date": "2026-08-31", "amount": 800},
        ],
    }}

    one = reports._month_expense_slice(expenses, "2026-08")
    assert one["total"] == 100 + 200 + 800, one
    assert len(one["items"]) == 3

    many = reports._months_expense_slice(expenses, ["2026-08", "2026-09"])
    assert many["total"] == 100 + 200 + 400 + 800, many
    assert len(many["items"]) == 4

    # 每筆都帶回 cat，且依日期新到舊排序（既有行為）
    assert all("cat" in it for it in many["items"])
    dates = [it["date"] for it in many["items"]]
    assert dates == sorted(dates, reverse=True)


# ── ⑥ Excel／PDF 匯出的季範圍（2026-09-10 後續補上） ─────────────────────────
#
# 匯出原本完全不吃期別的「季」：不論 period 是 YYYY-Qn 還是 YYYY-MM，都只產
# 「當月收支」與「今年度收支」兩塊。這裡驗證新增的 quarter 參數。
# 慣例比照 test_reports_export_expenses.py：Excel 走完整 HTTP 端點（openpyxl
# 純 Python，不需外部依賴）；PDF 只測 _build_report_html() 產生的字串本身
# （真的轉檔需要 Edge headless）。

def _seed_quarter_export_data(conn):
    """Q3 內外各一筆已收款，供匯出內容比對。"""
    _insert_case(conn, "MQ-EXP-AUG", "2026-08-01",
                 [{"id": 1, "type": "訂金", "pct": 100, "amount": 130000,
                   "received": True, "receivedAt": "2026-08-12T00:00:00"}])
    _insert_case(conn, "MQ-EXP-DEC", "2026-12-01",
                 [{"id": 1, "type": "訂金", "pct": 100, "amount": 777000,
                   "received": True, "receivedAt": "2026-12-12T00:00:00"}])


def test_excel_export_gains_quarter_sheet(client, make_user):
    """帶 quarter 的 Excel 匯出多一張「本季收支」工作表，內容是該季的收入；
    不帶 quarter 時完全沒有這張表（既有匯出結果零變化）。"""
    import io as _io
    import db
    import openpyxl

    with_user, with_pw = make_user(username="q_exp_with", role="admin")
    without_user, without_pw = make_user(username="q_exp_without", role="admin")

    conn = db.get_db()
    try:
        _seed_quarter_export_data(conn)
        conn.commit()
    finally:
        conn.close()

    # 帶 quarter
    token = _login(client, with_user, with_pw)
    # 2026-09-24 AC2：預設改權責口徑；本題驗的是「收入依收款日」＝現金口徑 ⇒ 明確帶 basis=cash
    r = client.get("/api/reports/financial/excel?period=2026-Q3&expense_month=2026-09&quarter=3&basis=cash",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(_io.BytesIO(r.content))
    assert "本季收支" in wb.sheetnames, f"應有『本季收支』工作表，實際 {wb.sheetnames}"
    ws = wb["本季收支"]
    assert "第 3 季" in str(ws["A1"].value), ws["A1"].value
    flat = "\n".join(
        str(c.value) for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "MQ-EXP-AUG" in flat, "Q3 內的案件應出現在本季收支表"
    assert "MQ-EXP-DEC" not in flat, "Q4 的案件不應出現在本季收支表"

    # 不帶 quarter（另一個使用者，避開 helpers.xlsx_out.check_export_rate 的 per-user 冷卻）
    token2 = _login(client, without_user, without_pw)
    r2 = client.get("/api/reports/financial/excel?period=2026-Q3&expense_month=2026-09",
                    headers=_auth(token2))
    assert r2.status_code == 200, r2.text
    wb2 = openpyxl.load_workbook(_io.BytesIO(r2.content))
    assert "本季收支" not in wb2.sheetnames, \
        f"不帶 quarter 不該有『本季收支』工作表，實際 {wb2.sheetnames}"
    # 既有兩張表都還在
    assert "當月收支" in wb2.sheetnames and "今年度收支" in wb2.sheetnames


def test_excel_export_quarter_rejects_bad_value(client, make_user):
    """匯出端點的 quarter 同樣受 _validate_quarter 保護。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/reports/financial/excel?period=2026-Q3&quarter=9", headers=_auth(token))
    assert r.status_code == 400, r.text


def test_report_html_gains_quarter_section(client, make_user):
    """_build_report_html()：帶 quarter 時多出本季收支段落與合計列；不帶時完全
    不出現「本季」字樣。比照 test_reports_export_expenses.py 的慣例，資料用真實
    `_collect()` 組（不手搭 dict——欄位一漏就是 KeyError，而且會隨程式演進失效），
    只是不呼叫 _html_to_pdf()（真的轉檔需要 Edge headless）。"""
    from datetime import datetime
    import db
    from routers import reports

    make_user(role="admin")
    conn = db.get_db()
    try:
        _insert_case(conn, "MQ-HTML-AUG", "2026-08-01",
                     [{"id": 1, "type": "訂金", "pct": 100, "amount": 50000,
                       "received": True, "receivedAt": "2026-08-10T00:00:00"}])
        conn.commit()
    finally:
        conn.close()

    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    label, d0, d1 = reports._parse_period("2026-Q3")

    def _data(quarter):
        d = reports._augment_with_targets(reports._collect(d0, d1, None), d0)
        d["arAging"] = reports._compute_ar_aging()
        d.update(reports._build_income_expense_scopes(2026, "2026-09", None, quarter))
        return d

    # 不帶 quarter
    html_plain = reports._build_report_html(_data(None), label, gen_at)
    assert "本季" not in html_plain, "不帶 quarter 時不該出現任何『本季』字樣"

    # 帶 quarter
    html_q = reports._build_report_html(_data(3), label, gen_at)
    assert "第 3 季收支明細" in html_q
    assert "本季收入合計" in html_q and "本季支出合計" in html_q and "本季淨額" in html_q
    assert "MQ-HTML-AUG" in html_q, "Q3 內的收款應出現在本季段落"
    assert "50,000" in html_q
