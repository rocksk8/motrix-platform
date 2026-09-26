"""2026-08-30（自我複查）：《當月/今年度收支》報表重構自我複查抓到並修復兩個
真實 bug，這裡補上回歸測試：
①PDF/HTML 收入明細的「實收淨額」欄用 `it['netAmount'] or aa_v`，手續費剛好等於
實收金額（netAmount 合法為 0）的品項會誤顯示成實收金額而不是 0（Excel 版本
`write_income_table()` 直接用 `item['netAmount']`，兩邊本來就會對不上）。
②`_build_income_expense_scopes()` 的 month 參數（YYYY-MM）沒有格式驗證，畸形值
會讓 `int(month[5:7])`/`monthrange()` 拋未接住的例外，變成 500 而不是 400。"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_month_expense_scope_rejects_malformed_month(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    for bad in ("2026", "2026-13", "2026-00", "abcd-ef", "2026/08"):
        r = client.get(f"/api/reports/expenses-monthly?year=2026&month={bad}", headers=_auth(token))
        assert r.status_code == 400, f"month={bad!r} should be rejected, got {r.status_code}: {r.text}"

    r_ok = client.get("/api/reports/expenses-monthly?year=2026&month=2026-08", headers=_auth(token))
    assert r_ok.status_code == 200, r_ok.text


def test_income_html_shows_zero_net_amount_not_actual_amount(client, make_user):
    """netAmount 合法為 0（手續費剛好等於實收金額）時，《當月收入明細》的
    「實收淨額」欄要顯示 NT$ 0，不是誤退回顯示實收金額。"""
    from datetime import datetime
    from modules.analytics.api.reports import _augment_with_targets, _build_income_expense_scopes, _build_report_html, _collect, _parse_period

    username, password = make_user(role="admin")
    _login(client, username, password)

    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {
                    "items": [{
                        "type": "訂金", "pct": 100, "amount": 5000,
                        "received": True, "receivedAt": "2026-06-15",
                        "actualAmount": 5000, "feeAmount": 5000,  # netAmount = 0
                    }]
                }
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-NET0-001", "已送出", "測試客戶", "測試專案", 5000, 4762, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-06-01"),
        )
        conn.commit()
    finally:
        conn.close()

    label, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    # 2026-09-24 AC2：預設改權責口徑；本題驗的是「收入依收款日」＝現金口徑 ⇒ 明確帶 basis=cash
    data.update(_build_income_expense_scopes(2026, "2026-06", None, basis="cash"))
    assert data["monthIncomeItems"], "測試資料應該要有一筆當月收入項目"
    assert data["monthIncomeItems"][0]["netAmount"] == 0

    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = _build_report_html(data, label, gen_at)
    # 精準鎖定這一列本身（到 </tr> 為止，不含下面的合計列，避免跟報表其他
    # 地方的 NT$ 5,000／NT$ 0 混淆）：修復前「實收淨額」欄會被 `or aa_v` 誤帶成
    # 實收金額 NT$ 5,000（这一列完全看不到 NT$ 0），修復後才看得到 NT$ 0。
    row_start = html.index("MQ-NET0-001")
    row_end   = html.index("</tr>", row_start)
    row_html  = html[row_start:row_end]
    assert "NT$ 5,000" in row_html   # 實收金額欄
    assert "NT$ 0" in row_html       # 實收淨額欄（bug 修復前這裡看不到）
