"""2026-09-01：料件/設備進貨批次新增供應商/發票號/付款狀態追蹤（DB v70
`stock_batches`），供 T100 傳票批次匯出（accounting_export.py）納入現金基礎
的付款事件來源。過去系統完全沒有追蹤進貨是否已付款（見
db.py::_m070_stock_batches() docstring），這是本輪要補的前置功能。
"""

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_default_bank_account_config_field(client, make_user):
    """2026-09-02：T100 設定新增 defaultBankAccountCode（系統預設帳戶），
    找不到對象上次使用紀錄時的第二層 fallback。"""
    username, password = make_user(username="stk_admin8", role="superadmin")
    token = _login(client, username, password)

    r0 = client.get("/api/settings/t100-export-config", headers=_auth(token))
    assert r0.json()["defaultBankAccountCode"] == ""

    r1 = client.put(
        "/api/settings/t100-export-config", headers=_auth(token),
        json={"bankAccounts": [{"name": "主要帳戶", "acctCode": "1101"}],
              "defaultBankAccountCode": "1101"},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.get("/api/settings/t100-export-config", headers=_auth(token))
    assert r2.json()["defaultBankAccountCode"] == "1101"
