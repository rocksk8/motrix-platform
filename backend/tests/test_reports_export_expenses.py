"""營運報表 Excel/PDF 匯出納入「月支出」＋「案件清單依月份區分」（2026-08-26）。
PDF 實際轉檔需要 Edge headless，本機測試環境沒有（既有已知限制，pdf_gen 相關
程式碼本來就沒有自動化測試覆蓋），這裡只測 _build_report_html() 產生的 HTML
字串本身（純 Python 字串組裝，不需要 Edge）；Excel 因為是 openpyxl 純 Python
產生，走完整 HTTP 端點也不需要外部依賴，直接測。"""
import io
import json

import openpyxl


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case_with_expense(quote_no, month):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO vendor_contractors (name, active, created_at) VALUES (?,1,?)",
            (f"廠商{quote_no}", "2026-01-01T00:00:00"),
        )
        vendor_id = conn.execute(
            "SELECT id FROM vendor_contractors WHERE name=?", (f"廠商{quote_no}",)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, vendor_id, f"2026-{month:02d}-10", "amount", "[]", 8000, "confirmed",
             f"2026-{month:02d}-10T00:00:00", f"2026-{month:02d}-10T00:00:00"),
        )
        data_json = json.dumps({"dealTag": "已成案"})
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 30000, 28571, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", f"2026-{month:02d}-05"),
        )
        conn.commit()
    finally:
        conn.close()


def test_excel_export_includes_expenses_sheet_and_month_grouped_cases(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_case_with_expense("MQ-XLSX-001", 3)
    _make_case_with_expense("MQ-XLSX-002", 7)

    r = client.get("/api/reports/financial/excel?period=2026", headers=_auth(token))
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert "當月收支" in wb.sheetnames
    assert "今年度收支" in wb.sheetnames
    assert "月支出" not in wb.sheetnames  # 舊 sheet 已拆成上面兩張，不應再存在

    ws_exp = wb["今年度收支"]
    assert ws_exp["A1"].value == "2026年度收支總表"
    header_row = [ws_exp.cell(row=4, column=c).value for c in range(1, 7)]
    assert header_row == ["月份", "承攬商派發", "設備進貨", "料件進貨", "其他支出", "合計"]
    # 3月列（row 5=header, row 5+2=3月列）承攬商派發應含稅 8000*1.05=8400
    row_labels = [ws_exp.cell(row=r, column=1).value for r in range(5, 17)]
    march_row = 5 + row_labels.index("3月")
    assert ws_exp.cell(row=march_row, column=2).value == 8400

    ws_cases = wb["案件清單"]
    all_col_a = [ws_cases.cell(row=r, column=1).value for r in range(1, ws_cases.max_row + 1)]
    assert any(v and "2026年3月" in str(v) for v in all_col_a)
    assert any(v and "2026年7月" in str(v) for v in all_col_a)


def test_pdf_html_includes_expenses_and_month_grouped_cases(client, make_user):
    """不走 _html_to_pdf()（需要 Edge headless），直接呼叫 _build_report_html()
    驗證 HTML 字串本身正確組裝。"""
    from datetime import datetime
    from routers.reports import (
        _augment_with_targets, _build_income_expense_scopes, _build_report_html, _collect,
        _compute_ar_aging, _parse_period,
    )

    username, password = make_user(role="admin")
    _login(client, username, password)
    _make_case_with_expense("MQ-PDF-001", 5)

    label, d0, d1 = _parse_period("2026")
    data = _augment_with_targets(_collect(d0, d1, None), d0)
    data["arAging"] = _compute_ar_aging()
    data.update(_build_income_expense_scopes(2026, "2026-05", None))
    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = _build_report_html(data, label, gen_at)
    assert "2026年度收支總表" in html
    assert "年度月支出結構" in html
    assert "2026-05 當月收支明細" in html
    assert "當月支出明細" in html
    assert "今年度支出明細" in html
    assert "2026年5月" in html  # 案件清單依月份區分的月份標題列
    # 該月的承攬商派發（含稅 8000*1.05=8400）應該同時出現在《當月支出明細》
    assert "8,400" in html
