"""`GET /api/quotations/last-received-bank-account` 只給執行得了標記收款的人（稽核 Y-1，2026-09-25）。

外人（沒有出納模組的業務）依客戶名稱可以探測「這個客戶有沒有已收款案件」⇒ 403。
出納與管理員照常拿到預帶值（正對照：值確實存在，不是空回應）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _tok(client, make_user, u, role, mods):
    name, pw = make_user(username=u, role=role, modules=mods)
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed():
    import db
    data = {"caseRecord": {"payment": {"items": [{"received": True, "receivedAt": "2026-09-01",
                                                  "bankAccountCode": "1113-Y1", "bankAccountName": "Y1銀行"}]}}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?)", ("MQ-Y1-0925", "已送出", "Y1客戶", json.dumps(data), "t", "t"))
        conn.commit()
    finally:
        conn.close()


def test_only_cashier_or_admin(client, make_user):
    _seed()
    url = "/api/quotations/last-received-bank-account?customerName=Y1客戶"
    out = _tok(client, make_user, "y1_out", "sales", ["dashboard", "quotation"])
    cash = _tok(client, make_user, "y1_cash", "engineer", ["cashier"])
    adm = _tok(client, make_user, "y1_adm", "admin", [])
    assert client.get(url, headers=out).status_code == 403
    for h in (cash, adm):
        r = client.get(url, headers=h)
        assert r.status_code == 200 and r.json() == {"name": "Y1銀行", "acctCode": "1113-Y1"}, r.text
