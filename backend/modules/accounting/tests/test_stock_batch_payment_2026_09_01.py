"""T100 設定的預設銀行帳號（M06 搬遷自 tests/ 同名檔；進貨批次付款的題在 M03）。

2026-09-26 自 `backend/tests/test_stock_batch_payment_2026_09_01.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
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
