"""2026-09-01：料件/設備進貨批次新增供應商/發票號/付款狀態追蹤（DB v70
`stock_batches`），供 T100 傳票批次匯出（accounting_export.py）納入現金基礎
的付款事件來源。過去系統完全沒有追蹤進貨是否已付款（見
db.py::_m070_stock_batches() docstring），這是本輪要補的前置功能。
"""

# 2026-09-26（A，M06 搬遷）：本檔唯一的題（T100 預設銀行帳號）搬進 modules/accounting/tests/ 同名檔；
# 下面兩個小工具留在這裡，因為 M03 的 modules/supply/tests/test_stock_batch_payment.py 從本檔匯入。


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}
