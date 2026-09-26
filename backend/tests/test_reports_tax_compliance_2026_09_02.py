"""2026-09-02（公司內控＋台灣國稅局視角複查）發現並修復的 4 項：
①發票號碼格式驗證＋重複偵測（modules/case/quotations.py::validate_invoice_no()）
②稅務匯出不再讓「已核准稅額沖銷」回溯性地把已開立發票的稅額改成 0
③稅額計算改用四捨五入（ROUND_HALF_UP），不用 Python 內建的銀行家捨入
④營運報表/銷項發票清單/銀行對帳單匯出補上稽核記錄
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, invoice_no=""):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "caseRecord": {
                "payment": {"items": [
                    {"type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": invoice_no},
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


# ── ①發票號碼格式/重複驗證 ───────────────────────────────────────────────────

def test_invoice_no_rejects_malformed_format(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVFMT-001")
    r = client.patch("/api/quotations/MQ-INVFMT-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": "invoice-123"})
    assert r.status_code == 400, r.text


def test_invoice_no_accepts_valid_format_case_insensitive(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVFMT-002")
    r = client.patch("/api/quotations/MQ-INVFMT-002/payment/0", headers=_auth(token),
                      json={"invoiceNo": "ab12345678"})
    assert r.status_code == 200, r.text


def test_invoice_no_rejects_duplicate_across_quotes(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVDUP-001", invoice_no="AB12345678")
    _make_quotation("MQ-INVDUP-002")
    r = client.patch("/api/quotations/MQ-INVDUP-002/payment/0", headers=_auth(token),
                      json={"invoiceNo": "AB12345678"})
    assert r.status_code == 400, r.text
    assert "MQ-INVDUP-001" in r.text


def test_invoice_no_allows_reusing_same_slot(client, make_user):
    """修改自己這筆（同一張報價單同一期）不該跟自己比對出假警報。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVSAME-001", invoice_no="AB12345678")
    r = client.patch("/api/quotations/MQ-INVSAME-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": "AB12345678"})
    assert r.status_code == 200, r.text


def test_invoice_no_empty_string_still_allowed(client, make_user):
    """清空發票號碼（尚未開立）維持合法，不受格式檢查擋下。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_quotation("MQ-INVEMPTY-001", invoice_no="AB12345678")
    r = client.patch("/api/quotations/MQ-INVEMPTY-001/payment/0", headers=_auth(token),
                      json={"invoiceNo": ""})
    assert r.status_code == 200, r.text


# ── ②稅務匯出不再被稅額沖銷回溯改寫 ─────────────────────────────────────────


# ── ③稅額四捨五入（ROUND_HALF_UP） ──────────────────────────────────────────


# ── ④匯出稽核記錄 ────────────────────────────────────────────────────────────
