"""確認精算「額外支出」附件（見 quotations.py::_load_settlement_extra_item()／
settlement.html「發票/收據」欄）有被兩份匯出涵蓋：
①案件結案報表 PDF（pdf_gen.py::_build_case_closing_html()）
②財務營運報表《月支出》明細（reports.py::_collect_expenses()/_build_report_html()）
PDF 產生本身需要 Edge headless（本機測試環境沒有，見既有 test_reports_expenses.py
同類先例），所以只驗證到 HTML 字串組裝這一層，不驗證真的轉出 PDF bytes。"""
import json


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


def _make_closed_quotation(quote_no):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已結案",
            "editHistory": [{"type": "settlement_finalized", "at": "2026-07-20T00:00:00"}],
            "settlement": {
                "status": "finalized",
                "items": [],
                "extraItems": [{
                    "id": 1, "category": "運費", "description": "貨運費用",
                    "totalCost": 2500, "expenseDate": "2026-07-15",
                    "files": [{"id": "f1", "filename": "receipt.pdf", "path": "quotation_settlement_extra/x/f1.pdf"}],
                }],
                "summary": {},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, settle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 50000, 47619, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案", "finalized"),
        )
        _sync_extra_to_table(conn, quote_no)
        conn.commit()
    finally:
        conn.close()


def test_case_closing_report_html_includes_extra_expense_files(client):
    import pdf_gen
    _make_closed_quotation("MQ-EXPFILE-001")
    data = pdf_gen._case_closing_report_data("MQ-EXPFILE-001")
    html = pdf_gen._build_case_closing_html(data)
    assert "receipt.pdf" in html
    assert "2026-07-15" in html


