"""2026-08-31（安全稽核發現）：PATCH /api/quotations/{no}/payment/{idx}
（標記款項收款）原本完全沒有角色門檻，任何登入使用者（含 viewer）都能標記
任意案件的任意期款項為已收款、任意填實收金額/手續費。已比照同檔案
request_payment_writeoff()/cancel_payment_writeoff() 補上 admin+ 門檻——
只針對「received」「actualAmount」「feeAmount」這幾個真正碰觸金流狀態的
欄位，純登錄發票號碼（invoiceNo）維持任何登入使用者皆可（跟其他模組發票
號碼登錄的既有寬鬆慣例一致）。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": ""},
                ]},
            },
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _payment_item(quote_no, idx=0):
    """直接查資料庫確認落地狀態，不透過 GET /api/quotations/{no}（該端點對
    非 admin/superadmin 有擁有者限制，測試用的假案件沒有掛對業務員/成員，
    會 403，跟本測試要驗證的權限主題無關）。"""
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    data = json.loads(row["data_json"] or "{}")
    return data["caseRecord"]["payment"]["items"][idx]


def test_viewer_cannot_mark_payment_received(client, make_user):
    username, password = make_user(role="viewer", modules=[])
    token = _login(client, username, password)
    _make_quotation("MQ-MARKPAY-001")

    r = client.patch(
        "/api/quotations/MQ-MARKPAY-001/payment/0", headers=_auth(token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 30000, "feeAmount": 0},
    )
    assert r.status_code == 403, r.text
    assert _payment_item("MQ-MARKPAY-001")["received"] is False


def test_sales_cannot_mark_payment_received_or_set_amounts(client, make_user):
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-MARKPAY-002")

    for body in (
        {"received": True, "actualAmount": 30000},
        {"actualAmount": 30000},   # 沒帶 received，但碰到金額欄位一樣要擋
        {"feeAmount": 500},
    ):
        r = client.patch("/api/quotations/MQ-MARKPAY-002/payment/0", headers=_auth(token), json=body)
        assert r.status_code == 403, f"body={body!r} should be forbidden, got {r.status_code}: {r.text}"


def test_admin_can_mark_payment_received(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-MARKPAY-003")

    r = client.patch(
        "/api/quotations/MQ-MARKPAY-003/payment/0", headers=_auth(token),
        json={"received": True, "receivedAt": "2026-08-31", "actualAmount": 30000, "feeAmount": 0},
    )
    assert r.status_code == 200, r.text

    detail = client.get("/api/quotations/MQ-MARKPAY-003", headers=_auth(token))
    item = detail.json()["data"]["caseRecord"]["payment"]["items"][0]
    assert item["received"] is True
    assert item["actualAmount"] == 30000

    # 取消收款一樣要求 admin+，非單向限制
    r2 = client.patch(
        "/api/quotations/MQ-MARKPAY-003/payment/0", headers=_auth(token), json={"received": False}
    )
    assert r2.status_code == 200, r2.text


def test_non_admin_can_still_register_invoice_number_only(client, make_user):
    """純登錄發票號碼不碰金流狀態，維持任何登入使用者皆可（既有慣例）。"""
    username, password = make_user(role="sales")
    token = _login(client, username, password)
    _make_quotation("MQ-MARKPAY-004")

    r = client.patch(
        "/api/quotations/MQ-MARKPAY-004/payment/0", headers=_auth(token),
        json={"invoiceNo": "AB12345678"},
    )
    assert r.status_code == 200, r.text
    assert _payment_item("MQ-MARKPAY-004")["invoiceNo"] == "AB12345678"
