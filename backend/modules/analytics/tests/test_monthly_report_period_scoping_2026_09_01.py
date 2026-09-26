"""_send_monthly_report_for()（自動月報寄送，見 reports.py）修復：使用者回報
8月月報「總應收/已收/未收/實收/合約總案」全是零，根因是舊版用「案件本身
quote_date 是否落在當月」（casesPeriod）過濾款項明細，當月若剛好沒有新
報價/成案的案件就會把這些 KPI 全部清空——即使當月真的有收到舊案件的款項
也一樣。修法改直接沿用 _collect() 已經依 receivedAt 算好的
summary.periodReceived/periodFee/periodNet。這裡驗證：案件是舊月份報價，
但款項在目標月份收款時，月報 KPI 不會被錯誤歸零。"""
import json


def _make_old_case_with_payment_received_this_month(quote_no, quote_date, received_at,
                                                     total=100000, pretax=95238):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 50, "received": True, "receivedAt": received_at,
                     "actualAmount": None, "feeAmount": 0},
                    {"type": "尾款", "pct": 50, "received": False},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "quote_date, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, pretax, quote_date, data_json,
             f"{quote_date}T00:00:00", f"{quote_date}T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def test_monthly_report_kpis_not_zeroed_when_no_new_cases_this_month(client, monkeypatch):
    """案件是 7 月報價（不在 8 月 casesPeriod 裡），但其中一期款項是 8 月
    收的——8 月月報的總應收/已收/實收 應該反映這筆實際收款，不是 0。"""
    _make_old_case_with_payment_received_this_month(
        "MQ-MRPT-001", quote_date="2026-07-10", received_at="2026-08-15",
    )

    import modules.analytics.api.reports as reports
    captured = {}

    def fake_build_excel(data, label, gen_at):
        captured["excel_data"] = data
        return b"fake-xlsx"

    def fake_html_to_pdf(html):
        return b"fake-pdf"

    def fake_notify(label, period_str, excel_bytes, pdf_bytes):
        captured["notified"] = True

    monkeypatch.setattr(reports, "_build_excel", fake_build_excel)
    monkeypatch.setattr(reports, "_html_to_pdf", fake_html_to_pdf)
    monkeypatch.setattr("helpers.email_notify.notify_monthly_report", fake_notify)

    reports._send_monthly_report_for("2026-08")

    data = captured["excel_data"]
    assert data is not None, "月報 Excel 產製沒有被呼叫到"
    s = data["summary"]

    # 8 月確實沒有新報價/成案的案件（quote_date 是 7 月）
    assert s["periodCases"] == 0

    # 但 8 月實際收到的款項不應該被歸零
    assert s["totalReceivable"] > 0
    assert s["totalCollected"] > 0
    assert s["netCollected"] > 0
    assert s["totalReceivable"] == s["periodReceived"]

    # 未收款清單（尾款尚未收）不應該因為案件不在 casesPeriod 就被濾空
    assert any(i["quoteNo"] == "MQ-MRPT-001" for i in data["outstanding"])

    # 合約總案數（累計）也不應該被錯誤歸零成 0（案件確實存在，只是不是本月新案）
    assert s["totalCases"] >= 1


def test_monthly_report_period_received_matches_actual_month(client, monkeypatch):
    """款項收在 7 月（不是報表目標的 8 月）時，8 月月報不該把它算進本期收款。"""
    _make_old_case_with_payment_received_this_month(
        "MQ-MRPT-002", quote_date="2026-06-01", received_at="2026-07-20",
    )

    import modules.analytics.api.reports as reports
    captured = {}
    monkeypatch.setattr(reports, "_build_excel", lambda data, label, gen_at: captured.setdefault("excel_data", data) or b"x")
    monkeypatch.setattr(reports, "_html_to_pdf", lambda html: b"x")
    monkeypatch.setattr("helpers.email_notify.notify_monthly_report", lambda *a, **k: None)

    reports._send_monthly_report_for("2026-08")

    s = captured["excel_data"]["summary"]
    assert s["totalReceivable"] == 0
    assert s["totalCollected"] == 0
