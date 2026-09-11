"""收款資料異常偵測（2026-09-11）。

**這支測試的由來**：使用者回報「案件資訊有一筆 2026/09/01 收款，營運報表當月收入
沒有算進去」（MQ-202607-045 交貨款）。在 db 副本上把那筆設成
`received=true` / `receivedAt=2026-09-01` 之後，`_collect_income_items()` 與
`_collect()` 兩支**都撈得到**——報表的計算邏輯沒有錯。所以問題是那兩個欄位沒有
同時到位，而這個系統對那個狀態原本完全沒有提示。

「已收款」勾選與「收款日期」是兩個獨立欄位，只填一個的話：

| 狀況 | 收入報表 | 未收報表 |
|------|---------|---------|
| `received=1`、`receivedAt` 空 | ❌ 不屬於任何月份 | ❌（已收，不算未收） |
| `receivedAt` 有值、`received=0` | ❌（未收） | ❌ 未收看的是預計收款日 |

兩種都是**兩邊都撈不到**，錢從所有月報表上消失，而且沒有任何錯誤訊息。下面的
測試就是在守「這個狀態一定要被點名出來」，以及「正常資料不能被誤報」。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case_with_payments(quote_no, pay_items, deal_tag="已成案", total=1000000):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, int(total / 1.05),
             json.dumps({"dealTag": deal_tag,
                         "caseRecord": {"payment": {"items": pay_items}}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag),
        )
        conn.commit()
    finally:
        conn.close()


def _item(type_, *, received=False, received_at="", amount=None, expected=""):
    return {"type": type_, "received": received, "receivedAt": received_at,
            "amount": amount, "expectedReceiptDate": expected, "invoiceNo": "", "note": ""}


def _anomalies(client, token):
    r = client.get("/api/reports/payment-anomalies", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


# ── 兩種異常形狀 ────────────────────────────────────────────────────────────

def test_date_filled_but_not_marked_received_is_flagged(client, make_user):
    """使用者回報那一筆最可能的形狀：日期填了、「已收款」沒勾。

    這種在收入報表（要 received=true）與未收報表（看預計收款日）**兩邊都不算**。
    """
    username, password = make_user(username="anom1", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-001", [
        _item("交貨款", received=False, received_at="2026-09-01", amount=263828),
    ])

    d = _anomalies(client, token)
    hit = [i for i in d["items"] if i["quoteNo"] == "MQ-ANOM-001"]
    assert len(hit) == 1, d
    assert hit[0]["kind"] == "date_not_received"
    assert hit[0]["type"] == "交貨款"
    assert hit[0]["amount"] == 263828
    assert hit[0]["receivedAt"] == "2026-09-01"
    assert "收款日期" in hit[0]["hint"] and "已收款" in hit[0]["hint"]


def test_marked_received_without_date_is_flagged(client, make_user):
    """反向：勾了已收款但沒填日期——這筆不屬於任何月份，所有月報表都撈不到。"""
    username, password = make_user(username="anom2", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-002", [
        _item("訂金款", received=True, received_at="", amount=500000),
    ])

    d = _anomalies(client, token)
    hit = [i for i in d["items"] if i["quoteNo"] == "MQ-ANOM-002"]
    assert len(hit) == 1, d
    assert hit[0]["kind"] == "received_no_date"
    assert hit[0]["amount"] == 500000


def test_healthy_payments_are_not_flagged(client, make_user):
    """兩個欄位都齊、或兩個都空，都是正常狀態，不能誤報。

    誤報比漏報更糟——這一區一旦常態性列出一堆沒問題的東西，使用者就會開始無視它，
    真的有問題的那筆也就跟著被忽略了。
    """
    username, password = make_user(username="anom3", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-003", [
        _item("訂金款", received=True, received_at="2026-08-01", amount=300000),   # 正常已收
        _item("交貨款", received=False, received_at="", amount=400000,
              expected="2026-10-01"),                                              # 正常未收
        _item("驗收款", received=False, received_at="", amount=300000),            # 未收、沒填預計日
    ])

    d = _anomalies(client, token)
    assert [i for i in d["items"] if i["quoteNo"] == "MQ-ANOM-003"] == [], d


def test_amount_falls_back_to_actual_amount(client, make_user):
    """有填實收金額就用實收——顯示的數字要跟使用者在案件裡看到的一致。"""
    username, password = make_user(username="anom4", role="superadmin")
    token = _login(client, username, password)
    items = [_item("訂金款", received=True, received_at="", amount=500000)]
    items[0]["actualAmount"] = 495000
    _make_case_with_payments("MQ-ANOM-004", items)

    hit = [i for i in _anomalies(client, token)["items"] if i["quoteNo"] == "MQ-ANOM-004"]
    assert hit[0]["amount"] == 495000


def test_non_won_cases_are_out_of_scope(client, make_user):
    """還沒成案的報價單不在收入報表的範圍內，也就不該出現在異常清單。

    範圍要跟 `_collect_income_items()` 完全一致，否則使用者會看到一堆
    「這筆為什麼要我處理」的東西。
    """
    username, password = make_user(username="anom5", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-005", [
        _item("訂金款", received=True, received_at="", amount=100000),
    ], deal_tag="已提供")

    assert [i for i in _anomalies(client, token)["items"] if i["quoteNo"] == "MQ-ANOM-005"] == []


# ── 接進報表 ────────────────────────────────────────────────────────────────

def test_anomalies_ride_along_with_income_expense_report(client, make_user):
    """收支報表的回應要帶這份清單——不然前端得多打一支 API，或乾脆沒人接。"""
    username, password = make_user(username="anom6", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-006", [
        _item("交貨款", received=False, received_at="2026-09-01", amount=263828),
    ])

    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09", headers=_auth(token))
    assert r.status_code == 200, r.text
    d = r.json()
    hit = [i for i in d["paymentAnomalyItems"] if i["quoteNo"] == "MQ-ANOM-006"]
    assert len(hit) == 1, d.get("paymentAnomalyItems")
    assert d["paymentAnomalyTotal"] >= 263828

    # 同一筆確實不在當月收入裡——這就是使用者回報的現象本身
    assert not [i for i in d["monthIncomeItems"] if i["quoteNo"] == "MQ-ANOM-006"]
    assert not [i for i in d["monthUnreceivedItems"] if i["quoteNo"] == "MQ-ANOM-006"]


def test_anomalies_are_not_filtered_by_period(client, make_user):
    """異常清單刻意不隨期別篩選。

    這些款項正是因為欄位不完整而不屬於任何月份，再用期別去篩就又看不見了
    ——那正是這一區要解決的問題本身。
    """
    username, password = make_user(username="anom7", role="superadmin")
    token = _login(client, username, password)
    _make_case_with_payments("MQ-ANOM-007", [
        _item("訂金款", received=True, received_at="", amount=88000),
    ])

    # 查一個跟這筆完全無關的月份，照樣要看得到
    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-02", headers=_auth(token))
    assert [i for i in r.json()["paymentAnomalyItems"] if i["quoteNo"] == "MQ-ANOM-007"]


def test_requires_admin(client, make_user):
    username, password = make_user(username="anom8", role="engineer")
    token = _login(client, username, password)
    assert client.get("/api/reports/payment-anomalies", headers=_auth(token)).status_code == 403
    assert client.get("/api/reports/payment-anomalies").status_code in (401, 403)
