"""庫存自動採購建議清單測試（2026-09-07，架構地圖 §6.6）。見
routers/inventory.py::purchase_suggestions() docstring——依安全庫存缺口計算
建議採購量，供應商/單價來源是該料號最近一筆進貨批次；系統沒有追蹤供應商前置
時間，刻意不做 ETA 預估，只回答「該補多少、上次跟誰買、大概要花多少」。
"""
from datetime import datetime


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_part(client, token, part_no, safety_stock, cost=100):
    r = client.post("/api/parts", headers=_auth(token), json={
        "partNo": part_no, "name": f"{part_no} 測試料件", "category": "其他",
        "safetyStock": safety_stock, "cost": cost,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_stock(part_no, qty, status="in_stock"):
    import uuid
    import db
    conn = db.get_db()
    now = datetime.now().isoformat()
    try:
        for _ in range(qty):
            conn.execute(
                "INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (part_no, f"{part_no}-{uuid.uuid4().hex[:8]}", status, "PO-TEST", 100, now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _add_batch(part_no, batch_no, supplier_id, supplier_name, created_at):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (batch_no, part_no, supplier_id, supplier_name, created_at, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_requires_auth(client):
    r = client.get("/api/inventory/purchase-suggestions")
    assert r.status_code in (401, 403), r.text


def test_no_suggestion_when_no_safety_stock_set(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "NOTHRESH", safety_stock=0)

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


def test_red_level_part_suggests_topping_up_to_yellow_threshold(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "RED-PART", safety_stock=10, cost=50)
    _add_stock("RED-PART", 3)  # 3 < 10 -> red

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["stockLevel"] == "red"
    assert item["inStockCount"] == 3
    # 補到黃燈門檻 ceil(10*1.5)=15，缺口 15-3=12
    assert item["suggestedQty"] == 12
    assert item["unitCost"] == 50
    assert item["estimatedCost"] == 600


def test_yellow_level_part_included_green_excluded(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "YEL-PART", safety_stock=10)
    _add_stock("YEL-PART", 12)  # 10 <= 12 < 15 -> yellow
    _create_part(client, token, "GRN-PART", safety_stock=10)
    _add_stock("GRN-PART", 20)  # >= 15 -> green, 不該出現

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    part_nos = {i["part_no"] for i in r.json()["items"]}
    assert "YEL-PART" in part_nos
    assert "GRN-PART" not in part_nos
    yel = next(i for i in r.json()["items"] if i["part_no"] == "YEL-PART")
    assert yel["stockLevel"] == "yellow"
    assert yel["suggestedQty"] == 3  # ceil(15) - 12


def test_last_supplier_picked_from_most_recent_batch(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "SUP-PART", safety_stock=10)
    _add_stock("SUP-PART", 2)
    _add_batch("SUP-PART", "PO-OLD", 1, "舊供應商", "2026-01-01T00:00:00")
    _add_batch("SUP-PART", "PO-NEW", 2, "新供應商", "2026-06-01T00:00:00")

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["part_no"] == "SUP-PART")
    assert item["lastSupplierName"] == "新供應商"
    assert item["lastSupplierId"] == 2
    assert item["lastPurchaseAt"] == "2026-06-01T00:00:00"


def test_no_purchase_history_leaves_supplier_blank(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "NOHIST-PART", safety_stock=10, cost=80)
    _add_stock("NOHIST-PART", 1)

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["part_no"] == "NOHIST-PART")
    assert item["lastSupplierName"] == ""
    assert item["lastSupplierId"] is None
    assert item["unitCost"] == 80  # 退回 parts.cost


def test_sorted_red_first_then_by_estimated_cost_desc(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "CHEAP-YEL", safety_stock=10, cost=10)
    _add_stock("CHEAP-YEL", 12)  # yellow, small cost
    _create_part(client, token, "EXPENSIVE-RED", safety_stock=10, cost=1000)
    _add_stock("EXPENSIVE-RED", 1)  # red, big cost
    _create_part(client, token, "CHEAP-RED", safety_stock=10, cost=5)
    _add_stock("CHEAP-RED", 1)  # red, small cost

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    part_nos = [i["part_no"] for i in r.json()["items"]]
    # 紅燈優先於黃燈，紅燈內再依預估金額由高到低
    assert part_nos == ["EXPENSIVE-RED", "CHEAP-RED", "CHEAP-YEL"]


def test_total_estimated_cost_and_count_aggregate(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "AGG-A", safety_stock=10, cost=10)
    _add_stock("AGG-A", 0)  # suggest 15 * 10 = 150
    _create_part(client, token, "AGG-B", safety_stock=10, cost=20)
    _add_stock("AGG-B", 0)  # suggest 15 * 20 = 300

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    body = r.json()
    assert body["count"] == 2
    assert body["totalEstimatedCost"] == 450


def test_shipped_and_void_items_do_not_count_as_in_stock(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _create_part(client, token, "SHIP-PART", safety_stock=10)
    _add_stock("SHIP-PART", 5, status="shipped")
    _add_stock("SHIP-PART", 2, status="in_stock")

    r = client.get("/api/inventory/purchase-suggestions", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["part_no"] == "SHIP-PART")
    assert item["inStockCount"] == 2  # 已出貨的 5 台不計入在庫
