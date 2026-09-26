"""2026-09-10：叫料（材料訂購）API 迴歸測試。

這支端點在 2026-09-10 上線時零測試零前端，四個缺陷同時存在且互相遮蔽——
最外層的「漏 conn.commit()」讓端點永遠回 200 但資料庫一個字都沒寫進去，
所以底下另外三個（save_quotation_json 參數錯位會污染 status 欄位、_audit
簽名錯誤、已結案守門讀錯 key）在真實使用時全部看不出來。

因此這裡的每一題都刻意「寫完之後從別的路徑讀回來核對」，而不是只斷言
HTTP 200——回應本身正是當初最會騙人的東西。
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, deal_tag="已成案", sales_person_id=None, sales_person=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "total, pretax, data_json, created_at, updated_at, deal_tag, "
            "sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238,
             json.dumps({"caseRecord": {}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal_tag,
             sales_person_id, sales_person),
        )
        conn.commit()
    finally:
        conn.close()


def _order(name="交換器", qty=2, price=1500, paid_status="pending",
           paid_amount=0, paid_date=None):
    return {
        "itemId": f"mo-{name}", "itemName": name,
        "quantity": qty, "unit": "台", "unitPrice": price,
        "totalPrice": qty * price,
        "paidStatus": paid_status, "paidAmount": paid_amount,
        "paidDate": paid_date, "notes": "",
    }


def _row(quote_no):
    """直接讀資料庫，不透過剛剛寫入的那支 API——這是整份測試的重點：
    2026-09-10 的初版就是「API 說成功、資料庫沒東西」。"""
    import db
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT status, updated_at, data_json FROM quotations WHERE quote_no=?",
            (quote_no,)).fetchone()
    finally:
        conn.close()


@pytest.fixture()
def admin(client, make_user):
    username, password = make_user("mo_admin", role="admin")
    return _login(client, username, password)


def test_patch_actually_persists(client, admin):
    """核心迴歸：初版漏 conn.commit()，端點回 200 但交易在 conn.close() 被丟棄。"""
    _make_quotation("MQ-MO-001")
    r = client.patch("/api/quotations/MQ-MO-001/material-orders", headers=_auth(admin),
                     json={"materialOrders": [_order()]})
    assert r.status_code == 200, r.text
    assert r.json()["materialOrdersCount"] == 1

    saved = json.loads(_row("MQ-MO-001")["data_json"])
    orders = saved["caseRecord"]["materialOrders"]
    assert len(orders) == 1, "叫料沒有真的寫進 data_json（回 200 不代表有 commit）"
    assert orders[0]["itemName"] == "交換器"
    assert orders[0]["totalPrice"] == 3000


def test_patch_does_not_corrupt_status_or_updated_at(client, admin):
    """初版 save_quotation_json(conn, no, data, user_id, "更新叫料清單…") 參數錯位：
    第 4 個位置參數是 status、第 5 個是 updated_at，會把報價單狀態改成使用者 id、
    把中文說明寫進時間欄位。"""
    _make_quotation("MQ-MO-002")
    before = _row("MQ-MO-002")

    r = client.patch("/api/quotations/MQ-MO-002/material-orders", headers=_auth(admin),
                     json={"materialOrders": [_order()]})
    assert r.status_code == 200, r.text

    after = _row("MQ-MO-002")
    assert after["status"] == before["status"] == "已送出", "報價單 status 被叫料端點改掉了"
    # updated_at 應該是可解析的 ISO 時間字串，不是中文說明
    from datetime import datetime
    datetime.fromisoformat(after["updated_at"])


def test_audit_row_is_written(client, admin):
    """初版 _audit(conn, ...) 傳錯簽名（第一個參數是 token），例外被 audit 內部
    try 吞掉，稽核從來沒寫成功過。"""
    _make_quotation("MQ-MO-003")
    r = client.patch("/api/quotations/MQ-MO-003/material-orders", headers=_auth(admin),
                     json={"materialOrders": [_order()]})
    assert r.status_code == 200, r.text

    import db
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT action, target_id FROM audit_log WHERE action='material_orders.update'"
        ).fetchall()
    finally:
        conn.close()
    assert any(x["target_id"] == "MQ-MO-003" for x in rows), "稽核記錄沒寫成功"


def test_closed_case_is_rejected(client, admin):
    """初版讀 data_json 的 'deal_tag'，但 data_json 裡的鍵叫 'dealTag'、權威來源
    是資料表欄位——守門是死碼，已結案案件照樣改得動。"""
    _make_quotation("MQ-MO-004", deal_tag="已結案")
    r = client.patch("/api/quotations/MQ-MO-004/material-orders", headers=_auth(admin),
                     json={"materialOrders": [_order()]})
    assert r.status_code == 400, r.text
    assert "已結案" in r.json()["detail"]

    saved = json.loads(_row("MQ-MO-004")["data_json"])
    assert "materialOrders" not in saved.get("caseRecord", {})


def test_other_salespersons_case_is_not_accessible(client, make_user):
    """IDOR：quote_no 格式可列舉（MQ-YYYYMM-NNN），初版兩支端點都沒有擁有者
    檢查，任何登入使用者都能讀/改別的業務的案件叫料。"""
    owner_name, owner_pw = make_user("mo_owner", role="sales")
    other_name, other_pw = make_user("mo_other", role="sales")
    _make_quotation("MQ-MO-005", sales_person=owner_name)

    other = _login(client, other_name, other_pw)
    assert client.get("/api/quotations/MQ-MO-005/material-orders",
                      headers=_auth(other)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）
    assert client.patch("/api/quotations/MQ-MO-005/material-orders", headers=_auth(other),
                        json={"materialOrders": [_order()]}).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）

    owner = _login(client, owner_name, owner_pw)
    assert client.get("/api/quotations/MQ-MO-005/material-orders",
                      headers=_auth(owner)).status_code == 200


def test_get_tolerates_legacy_rows_without_amount_keys(client, admin):
    """GET 的合計原本直接索引 o["totalPrice"]／o["paidAmount"]，人工修過或
    早期格式的 data_json 少一個 key 就整支 500。"""
    _make_quotation("MQ-MO-006")
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE quotations SET data_json=? WHERE quote_no=?",
            (json.dumps({"caseRecord": {"materialOrders": [
                {"itemName": "沒有金額欄位的舊資料"},
                {"itemName": "有金額", "totalPrice": 500, "paidAmount": 200},
            ]}}, ensure_ascii=False), "MQ-MO-006"))
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/quotations/MQ-MO-006/material-orders", headers=_auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["totalAmount"] == 500
    assert r.json()["paidAmount"] == 200


def test_paid_status_validation_still_holds(client, admin):
    """初版就有的驗證邏輯，一併釘住避免修 commit 時改壞。"""
    _make_quotation("MQ-MO-007")
    bad = _order(paid_status="paid", paid_amount=99999, paid_date="2026-09-10")
    r = client.patch("/api/quotations/MQ-MO-007/material-orders", headers=_auth(admin),
                     json={"materialOrders": [bad]})
    assert r.status_code == 400
    assert "已付金額" in r.json()["detail"]

    mismatched = _order()
    mismatched["totalPrice"] = 1
    r = client.patch("/api/quotations/MQ-MO-007/material-orders", headers=_auth(admin),
                     json={"materialOrders": [mismatched]})
    assert r.status_code == 400
    assert "小計計算錯誤" in r.json()["detail"]
