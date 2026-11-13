# -*- coding: utf-8 -*-
"""測試共用的登入小工具（原放在 test_stock_batch_payment_2026_09_01.py，該檔 0 題，test-prune 刪除後各處匯入失效）。"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}
