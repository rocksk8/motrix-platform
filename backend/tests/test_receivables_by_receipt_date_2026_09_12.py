"""「已收款／未收款」分頁改用收款日期口徑（2026-09-12）。

**由來**：使用者連續兩次回報「案件資訊裡 9/1 已勾已收款，營運報表的『已收款』
卻是 0」。查證後資料與計算都沒錯——`MQ-202607-045` 的成案月份是 2026-07，而這兩
個分頁原本是**依成案月份分組**，所以那筆 9/1 收的錢一直被算在 7 月。

分頁標題只寫「已收款」，看不出它問的其實是「當月成案的案子收了多少」。使用者要
的是「當月收到多少錢」，所以改成：

    已收款 → receivedAt（錢實際進來那天）
    未收款 → expectedReceiptDate（預計哪天進來）

⚠️ **這次改動最危險的地方是「缺日期的會消失」**：實測開發機未收款 7 筆**全部
沒填預計收款日**，直接照日期分組會讓它們從每一個月份都撈不到。所以另外回傳
`undated*` 兩組固定顯示。下面的測試有一半是在守這件事。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _case(quote_no, pay_items, quote_date="2026-07-09", total=1000000):
    """建一張已成案報價單。`quote_date` 決定成案月份——刻意讓它跟收款月份不同，
    才測得出「不再依成案月份分組」。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, int(total / 1.05),
             json.dumps({"dealTag": "已成案",
                         "caseRecord": {"payment": {"items": pay_items}}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", quote_date),
        )
        conn.commit()
    finally:
        conn.close()


def _item(type_, *, received=False, received_at="", expected="", amount=None):
    return {"type": type_, "received": received, "receivedAt": received_at,
            "expectedReceiptDate": expected, "amount": amount, "invoiceNo": "", "note": ""}


def _recv(client, token, month="2026-09", year=2026):
    r = client.get(f"/api/reports/receivables-monthly?year={year}&month={month}",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


# ── 已收款：依收款日期 ──────────────────────────────────────────────────────

def test_collected_grouped_by_receipt_date_not_won_month(client, make_user):
    """**本輪最重要的一條**：7 月成案、9/1 收的錢，要出現在 9 月而不是 7 月。

    這正是使用者回報的那筆（MQ-202607-045 交貨款）的形狀。
    """
    username, password = make_user(username="recv1", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-001", [
        _item("訂金款", received=True, received_at="2026-07-15", amount=500000),
        _item("交貨款", received=True, received_at="2026-09-01", amount=263828),
    ], quote_date="2026-07-09")

    sep = _recv(client, token, "2026-09")
    hit = [i for i in sep["monthCollectedItems"] if i["type"] == "交貨款"]
    assert len(hit) == 1, f"9 月要看得到 9/1 收的那筆，實際 {sep['monthCollectedItems']}"
    assert hit[0]["amount"] == 263828
    assert sep["monthCollectedTotal"] == 263828

    jul = _recv(client, token, "2026-07")
    assert [i for i in jul["monthCollectedItems"] if i["type"] == "訂金款"], "7/15 那筆要在 7 月"
    assert not [i for i in jul["monthCollectedItems"] if i["type"] == "交貨款"], \
        "9/1 收的錢不能再被算進 7 月（那正是改這一版的原因）"


def test_year_and_quarter_also_use_receipt_date(client, make_user):
    """年／季範圍要跟月一致，不能只改月——三個範圍口徑不一致正是這類 bug 的溫床。"""
    username, password = make_user(username="recv2", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-002", [
        _item("訂金款", received=True, received_at="2026-09-01", amount=100000),
    ], quote_date="2026-02-10")   # 成案在 2 月、收款在 9 月

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-09&quarter=3",
                   headers=_auth(token))
    d = r.json()
    assert [i for i in d["yearCollectedItems"] if i["quoteNo"] == "MQ-RECV-002"], "年度要含它"
    assert [i for i in d["quarterCollectedItems"] if i["quoteNo"] == "MQ-RECV-002"], \
        "Q3（7~9 月）要含 9 月收的那筆"

    r2 = client.get("/api/reports/receivables-monthly?year=2026&month=2026-09&quarter=1",
                    headers=_auth(token))
    assert not [i for i in r2.json()["quarterCollectedItems"] if i["quoteNo"] == "MQ-RECV-002"], \
        "Q1 不該含它——成案在 2 月，但口徑已經不看成案月份了"


# ── 未收款：依預計收款日 ────────────────────────────────────────────────────

def test_outstanding_grouped_by_expected_date(client, make_user):
    username, password = make_user(username="recv3", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-003", [
        _item("驗收款", received=False, expected="2026-10-05", amount=300000),
    ], quote_date="2026-07-09")

    assert not _recv(client, token, "2026-09")["monthOutstandingItems"], "9 月不該有"
    oct_ = _recv(client, token, "2026-10")
    assert [i for i in oct_["monthOutstandingItems"] if i["quoteNo"] == "MQ-RECV-003"], \
        "預計 10/5 收的要出現在 10 月"


# ── 缺日期的不能消失 ────────────────────────────────────────────────────────

def test_undated_outstanding_is_surfaced_not_dropped(client, make_user):
    """**沒填預計收款日的未收款不能就這樣不見。**

    實測開發機：未收款 7 筆全部沒填預計收款日。少了 `undatedOutstandingItems`
    這一組，改成日期口徑之後整個未收款清單會憑空消失——那正是 §5.12 那個
    「錢無聲消失」的坑，這一版絕不能自己再製造一次。
    """
    username, password = make_user(username="recv4", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-004", [
        _item("驗收款", received=False, expected="", amount=444000),
    ], quote_date="2026-07-09")

    d = _recv(client, token, "2026-09")
    assert not d["monthOutstandingItems"], "沒填預計收款日就不屬於任何月份"
    hit = [i for i in d["undatedOutstandingItems"] if i["quoteNo"] == "MQ-RECV-004"]
    assert len(hit) == 1, f"但一定要出現在 undated 這一組，實際 {d['undatedOutstandingItems']}"
    assert d["undatedOutstandingTotal"] >= 444000


def test_undated_collected_is_surfaced_not_dropped(client, make_user):
    """反向：勾了已收款但沒填收款日期的，同樣要被點名。"""
    username, password = make_user(username="recv5", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-005", [
        _item("訂金款", received=True, received_at="", amount=88000),
    ], quote_date="2026-07-09")

    d = _recv(client, token, "2026-09")
    assert not d["monthCollectedItems"]
    assert [i for i in d["undatedCollectedItems"] if i["quoteNo"] == "MQ-RECV-005"]
    assert d["undatedCollectedTotal"] >= 88000


def test_undated_not_double_counted_into_month_totals(client, make_user):
    """undated 那兩組**不能**併進月份合計——併進去的話同一筆會在每個月被重複計算。"""
    username, password = make_user(username="recv6", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-006", [
        _item("訂金款", received=True, received_at="", amount=70000),
        _item("驗收款", received=False, expected="", amount=30000),
    ], quote_date="2026-07-09")

    for month in ("2026-07", "2026-08", "2026-09"):
        d = _recv(client, token, month)
        assert d["monthCollectedTotal"] == 0, f"{month} 的已收合計不該含 undated"
        assert d["monthOutstandingTotal"] == 0, f"{month} 的未收合計不該含 undated"
    # 但 undated 那組每次都看得到（它本來就不隨期別篩選）
    assert _recv(client, token, "2026-03")["undatedCollectedTotal"] >= 70000


def test_receivable_equals_collected_plus_outstanding(client, make_user):
    """`monthReceivableTotal == monthCollectedTotal + monthOutstandingTotal` 這個
    恆等式改口徑之後仍然要成立——兩半各用各的日期挑，但加起來還是那一包。"""
    username, password = make_user(username="recv7", role="superadmin")
    token = _login(client, username, password)
    _case("MQ-RECV-007", [
        _item("訂金款", received=True, received_at="2026-09-03", amount=200000),
        _item("交貨款", received=False, expected="2026-09-20", amount=300000),
        _item("驗收款", received=False, expected="2026-11-01", amount=500000),
    ], quote_date="2026-07-09")

    d = _recv(client, token, "2026-09")
    assert d["monthReceivableTotal"] == d["monthCollectedTotal"] + d["monthOutstandingTotal"]
    assert d["monthCollectedTotal"] == 200000
    assert d["monthOutstandingTotal"] == 300000


def test_requires_admin(client, make_user):
    username, password = make_user(username="recv8", role="engineer")
    token = _login(client, username, password)
    assert client.get("/api/reports/receivables-monthly", headers=_auth(token)).status_code == 403
