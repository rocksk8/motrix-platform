"""2026-09-02（追加）：
①案件管理財務Tab「整包存檔」(update_case_record/PATCH .../case-record) 是使用者
  實際填發票號碼最常用的路徑，先前只在 mark_payment()（PATCH .../payment/{idx}，
  出納快速登錄用）加上格式/重複驗證，這支主要路徑完全沒接到，等於防呆對大多數
  真實使用情境沒有生效——這裡補上，用 item id 比對排除自己這筆（不能用陣列位置，
  款項期別本來就能自由新增/刪除/排序）。
②統一發票「開立日期」欄位（invoiceDate）：稅務匯出期別歸屬應該看這個，不是看
  收款日期（receivedAt）。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, invoice_no="", invoice_date="", item_id=1):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"id": item_id, "type": "訂金款", "pct": 30, "amount": 30000, "received": False,
                     "actualAmount": None, "feeAmount": 0, "note": "",
                     "invoiceNo": invoice_no, "invoiceDate": invoice_date},
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


def _case_record(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"] or "{}")["caseRecord"]


# ── ①update_case_record 也要驗證發票號碼 ────────────────────────────────────

def test_case_record_save_rejects_malformed_invoice_no(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-CRINV-001")

    cr = _case_record("MQ-CRINV-001")
    cr["payment"]["items"][0]["invoiceNo"] = "not-a-real-invoice"

    r = client.patch("/api/quotations/MQ-CRINV-001/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 400, r.text
    assert _case_record("MQ-CRINV-001")["payment"]["items"][0]["invoiceNo"] == ""


def test_case_record_save_rejects_duplicate_invoice_no(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-CRINV-002", invoice_no="AB12345678")
    _make_quotation("MQ-CRINV-003")

    cr = _case_record("MQ-CRINV-003")
    cr["payment"]["items"][0]["invoiceNo"] = "AB12345678"

    r = client.patch("/api/quotations/MQ-CRINV-003/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 400, r.text
    assert "MQ-CRINV-002" in r.text


def test_case_record_save_allows_unchanged_invoice_no(client, make_user):
    """沒有動過發票號碼的品項不該被重新驗證（否則舊資料格式不合規會讓所有
    後續存檔全部卡死）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    # 舊資料格式不合規（沒有連字號驗證前留下的資料）
    _make_quotation("MQ-CRINV-004", invoice_no="legacy-format-no")

    cr = _case_record("MQ-CRINV-004")
    cr["note"] = cr.get("note", "") + ""  # no-op 觸發存檔但不動 invoiceNo
    cr.setdefault("materials", [])

    r = client.patch("/api/quotations/MQ-CRINV-004/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text


def test_case_record_save_allows_reusing_same_id_invoice_no(client, make_user):
    """用 item id 比對排除自己這筆——同一品項的發票號碼原封不動存檔，或款項
    期別陣列因為新增/刪除其他期別而重新排序，都不該誤判成跟自己重複。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-CRINV-005", invoice_no="AB12345678", item_id=1)

    cr = _case_record("MQ-CRINV-005")
    # 在前面插入一筆新期別，讓原本 id=1 的品項陣列位置往後移動
    cr["payment"]["items"].insert(0, {
        "id": 2, "type": "訂金款", "pct": 10, "amount": 10000, "received": False,
        "actualAmount": None, "feeAmount": 0, "note": "", "invoiceNo": "", "invoiceDate": "",
    })
    r = client.patch("/api/quotations/MQ-CRINV-005/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = _case_record("MQ-CRINV-005")
    assert len(saved["payment"]["items"]) == 2


def test_case_record_save_accepts_valid_invoice_no_and_date(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-CRINV-006")

    cr = _case_record("MQ-CRINV-006")
    cr["payment"]["items"][0]["invoiceNo"] = "AB12345678"
    cr["payment"]["items"][0]["invoiceDate"] = "2026-03-15"

    r = client.patch("/api/quotations/MQ-CRINV-006/case-record", headers=_auth(token), json={"case_record": cr})
    assert r.status_code == 200, r.text
    saved = _case_record("MQ-CRINV-006")
    assert saved["payment"]["items"][0]["invoiceNo"] == "AB12345678"
    assert saved["payment"]["items"][0]["invoiceDate"] == "2026-03-15"


# ── ②稅務匯出期別歸屬改用 invoiceDate ────────────────────────────────────────
