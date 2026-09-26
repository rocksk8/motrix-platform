"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_reports_expenses.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
營運報表「月支出金額及明細」（2026-08-26）API 層測試——
routers/reports.py::_collect_expenses()/GET /api/reports/expenses-monthly。
"""
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


def test_contractor_dispatch_counted(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO vendor_contractors (name, active, created_at) VALUES (?,1,?)",
            ("測試承攬商", "2026-01-01T00:00:00"),
        )
        vendor_id = conn.execute("SELECT id FROM vendor_contractors WHERE name='測試承攬商'").fetchone()["id"]
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("MQ-EXP-001", vendor_id, "2026-03-15", "amount", "[]", 10000, "confirmed",
             "2026-03-15T00:00:00", "2026-03-15T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    body = r.json()
    march = next(m for m in body["expenses"]["monthly"] if m["month"] == "2026-03")
    # 2026-09-24 AC2（使用者裁示）：預設權責口徑＝未稅（原本 10500 含稅）；沒登錄發票日、
    # 沒有驗收日 ⇒ 暫用派工月（仍是 3 月）。現金口徑的含稅金額見 test_report_recognition_basis。
    assert march["contractor"] == 10000
    assert body["expenses"]["totals"]["contractor"] == 10000
    assert any(d["desc"] == "測試承攬商" and d["amount"] == 10000 for d in body["expenses"]["details"]["contractor"])
