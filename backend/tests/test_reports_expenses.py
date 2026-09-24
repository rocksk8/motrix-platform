"""營運報表「月支出金額及明細」（2026-08-26）API 層測試——
routers/reports.py::_collect_expenses()/GET /api/reports/expenses-monthly。"""
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


def test_non_admin_forbidden(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    r = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    assert r.status_code == 403, r.text


def test_empty_year_returns_zeroed_12_months(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/reports/expenses-monthly?year=2099", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == 2099
    assert len(body["expenses"]["monthly"]) == 12
    assert body["expenses"]["monthly"][0]["label"] == "1月"
    assert body["expenses"]["totals"]["total"] == 0
    assert body["expenses"]["details"] == {"contractor": [], "equipment": [], "material": [], "other": []}


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


def test_stock_purchase_bucketed_by_category(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO parts (part_no, name, category, active, created_at, updated_at) "
            "VALUES (?,?,?,1,?,?)",
            ("P-EQ-001", "測試設備", "網通設備", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO parts (part_no, name, category, active, created_at, updated_at) "
            "VALUES (?,?,?,1,?,?)",
            ("P-MAT-001", "測試料件", "線材配件", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        for sn, part_no, cost in (("SN1", "P-EQ-001", 5000), ("SN2", "P-EQ-001", 5000), ("SN3", "P-MAT-001", 300)):
            conn.execute(
                "INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (part_no, sn, "in_stock", "BATCH1", cost, "2026-05-10T00:00:00", "2026-05-10T00:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    body = r.json()
    may = next(m for m in body["expenses"]["monthly"] if m["month"] == "2026-05")
    assert may["equipment"] == 10000
    assert may["material"] == 300
    eq_detail = next(d for d in body["expenses"]["details"]["equipment"] if "測試設備" in d["desc"])
    assert eq_detail["amount"] == 10000
    assert "× 2" in eq_detail["desc"]


def test_settlement_extra_item_counted_as_other(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已結案",
            "editHistory": [{"type": "settlement_finalized", "at": "2026-07-20T00:00:00"}],
            "settlement": {
                "status": "finalized",
                "extraItems": [{"category": "運費", "name": "貨運費用", "totalCost": 2500}],
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MQ-EXP-002", "已送出", "測試客戶", "測試專案", 50000, 47619, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案"),
        )
        _sync_extra_to_table(conn, "MQ-EXP-002")
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    body = r.json()
    july = next(m for m in body["expenses"]["monthly"] if m["month"] == "2026-07")
    assert july["other"] == 2500
    assert any(d["quoteNo"] == "MQ-EXP-002" and d["amount"] == 2500 for d in body["expenses"]["details"]["other"])
