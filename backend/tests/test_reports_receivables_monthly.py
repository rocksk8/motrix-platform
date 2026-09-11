"""應收明細表端點 `/api/reports/receivables-monthly` 的規格測試。

⚠️ **2026-09-12 規格變更：分組口徑從「成案月份」改成「收款日期」。**

原本（2026-09-09 初版）是依成案月份分組。使用者連續兩次回報「案件資訊裡 9/1 已勾
已收款，營運報表的『已收款』卻是 0」——查證後資料與計算都沒錯，是那筆款項所屬案件
在 7 月成案，所以錢被算在 7 月。分頁標題只寫「已收款」，看不出它問的其實是「當月
成案的案子收了多少」。使用者要的是「當月收到多少錢」，於是改成：

    已收款 → receivedAt（錢實際進來那天）
    未收款 → expectedReceiptDate（預計哪天進來）

`monthReceivableTotal == monthCollectedTotal + monthOutstandingTotal` 這個恆等式
在改版後仍然成立（兩半各用各的日期挑，但加起來還是那一包）。

缺日期者另外回傳 `undated*` 兩組（不隨期別篩選）——少了那兩組，改口徑之後沒填日期
的款項會從每一個月份都撈不到。那部分的測試在
`test_receivables_by_receipt_date_2026_09_12.py`。
"""
import json
from datetime import datetime


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_forbidden(client, make_user):
    """非 admin 角色無法存取應收報表。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-08", headers=_auth(token))
    assert r.status_code == 403


def test_month_param_rejects_malformed_month(client, make_user):
    """month 參數（YYYY-MM）格式檢驗，畸形值回 400。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    for bad in ("2026", "2026-13", "2026-00", "abcd-ef", "2026/08"):
        r = client.get(f"/api/reports/receivables-monthly?year=2026&month={bad}", headers=_auth(token))
        assert r.status_code == 400, f"month={bad!r} should be rejected, got {r.status_code}: {r.text}"

    r_ok = client.get("/api/reports/receivables-monthly?year=2026&month=2026-08", headers=_auth(token))
    assert r_ok.status_code == 200, r_ok.text


def test_grouped_by_receipt_date_not_won_month(client, make_user):
    """核心規格（2026-09-12 起）：**依收款日期分組，不是成案月份**。

    測試情景刻意讓兩者不同：這案的成案月份是 2026-03（quote_date 缺漏、改用
    audit_log 的成案時間戳解析），但款項的 receivedAt 是 2026-05——錢要算在
    **2026-05**，2026-03 不該看到。

    這支測試在改版前是反過來斷言的（那是 2026-09-09 的規格）。留著 audit_log
    那段 fixture 是刻意的：它同時證明「就算成案月份解析得出來，也不再用它分組」。
    """
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        # 建一個沒有 quote_date 的報價單
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {
                    "items": [{
                        "id": 1, "type": "訂金", "pct": 30, "amount": 100000,
                        "received": True, "receivedAt": "2026-05-10T00:00:00",
                    }]
                }
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-WONFALL-001", "已送出", "測客", "測專", 100000, 95238, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", None),  # quote_date = NULL
        )

        # 塞入 audit_log 表示此案在 2026-03-15 成案（match quote_won_month_map 的預期形狀）
        conn.execute(
            "INSERT INTO audit_log (at, action, target_type, target_id, target_label, detail) "
            "VALUES (?,?,?,?,?,?)",
            ("2026-03-15T10:30:00", "deal_tag.change", "quotation", "MQ-WONFALL-001",
             "MQ-WONFALL-001", json.dumps({"to": "已成案"}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()

    # 查詢 2026-05（實際收款月份）——錢是那個月進來的，就算在那個月
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-05", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert any(it["quoteNo"] == "MQ-WONFALL-001" for it in data.get("monthCollectedItems", [])), \
        f"該案應該在 2026-05（收款月份）結果，但看到的 monthCollectedItems={data.get('monthCollectedItems')}"

    # 查詢 2026-03（成案月份）不該再看到它——這正是 2026-09-12 改掉的東西
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-03", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert not any(it["quoteNo"] == "MQ-WONFALL-001" for it in data.get("monthReceivableItems", [])), \
        f"該案不該再算進 2026-03（成案月份），錢是 2026-05 才收到的"


def test_month_receivable_equals_collected_plus_outstanding(client, make_user):
    """驗證 monthReceivableTotal == monthCollectedTotal + monthOutstandingTotal。

    2026-09-12：改成日期口徑之後，這兩半各用各的日期挑——已收看 receivedAt、
    未收看 expectedReceiptDate。測試資料刻意讓兩者都落在 2026-04，恆等式才有
    東西可驗（各自落在不同月的情形由 test_different_month_items_do_not_leak 守）。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {
                    "items": [
                        {"id": 1, "type": "訂金", "pct": 50, "amount": 500000,
                         "received": True, "receivedAt": "2026-04-10T00:00:00"},
                        {"id": 2, "type": "驗收款", "pct": 50, "amount": 500000,
                         "received": False, "expectedReceiptDate": "2026-04-25"},
                    ]
                }
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-MIXED-001", "已送出", "測客", "測專", 1000000, 952381, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-04-01"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-04", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()

    month_rec = data["monthReceivableTotal"]
    month_col = data["monthCollectedTotal"]
    month_out = data["monthOutstandingTotal"]
    assert month_rec == month_col + month_out, \
        f"monthReceivableTotal ({month_rec}) should equal monthCollectedTotal ({month_col}) + " \
        f"monthOutstandingTotal ({month_out})"
    assert month_rec == 1000000, f"應總應收 NT$1,000,000，但得 {month_rec}"
    assert month_col == 500000, f"應總已收 NT$500,000，但得 {month_col}"
    assert month_out == 500000, f"應總未收 NT$500,000，但得 {month_out}"


def test_different_month_items_do_not_leak(client, make_user):
    """確保跨月資料互不污染：A 月的款項不會誤出現在 B 月的查詢結果。

    2026-09-12：分月依據從 quote_date（成案月份）改成款項自己的日期，所以這裡的
    兩筆未收款項要各自帶 expectedReceiptDate；沒帶日期的會被歸到 `undated*`
    那一組（不屬於任何月份），那是另一支測試的守備範圍。"""
    import db

    username, password = make_user(role="admin")
    token = _login(client, username, password)

    conn = db.get_db()
    try:
        # 案件 1：2026-03 成案
        data_json_1 = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"id": 1, "type": "訂金", "pct": 100, "amount": 300000, "received": False,
                 "expectedReceiptDate": "2026-03-20"}
            ]}},
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-MAR-001", "已送出", "客A", "專A", 300000, 285714, data_json_1,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-03-05"),
        )

        # 案件 2：2026-04 成案
        data_json_2 = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {"payment": {"items": [
                {"id": 1, "type": "訂金", "pct": 100, "amount": 400000, "received": False,
                 "expectedReceiptDate": "2026-04-20"}
            ]}},
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-APR-001", "已送出", "客B", "專B", 400000, 380952, data_json_2,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-04-10"),
        )
        conn.commit()
    finally:
        conn.close()

    # 查詢 2026-03，應只見 MQ-MAR-001
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-03", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    march_items = [it["quoteNo"] for it in data.get("monthReceivableItems", [])]
    assert "MQ-MAR-001" in march_items, "2026-03 應該有 MQ-MAR-001"
    assert "MQ-APR-001" not in march_items, "2026-03 不應該有 MQ-APR-001"

    # 查詢 2026-04，應只見 MQ-APR-001
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-04", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    april_items = [it["quoteNo"] for it in data.get("monthReceivableItems", [])]
    assert "MQ-APR-001" in april_items, "2026-04 應該有 MQ-APR-001"
    assert "MQ-MAR-001" not in april_items, "2026-04 不應該有 MQ-MAR-001"


def test_department_id_param_accepted(client, make_user):
    """驗證 department_id 參數能被接受（雖然本測試環境中部門設定可能為空）。
    詳細的部門過濾邏輯由既有 _collect_income_items() 測試已涵蓋；此處只驗證
    參數傳遞與簽名一致。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    # 不帶 department_id 應成功
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-04", headers=_auth(token))
    assert r.status_code == 200, r.text

    # 帶上 department_id 也應成功（API 簽名接受）
    r = client.get("/api/reports/receivables-monthly?year=2026&month=2026-04&department_id=1",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
