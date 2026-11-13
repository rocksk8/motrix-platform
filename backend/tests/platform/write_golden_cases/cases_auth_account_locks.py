# -*- coding: utf-8 -*-
"""外網登入強化（2026-11-12）：超管手動解除帳號鎖定的寫入類路由金標案例。
`POST /api/auth/account-locks/unlock`——setup 在行程內先把帳號 wg_locked 從外網打錯到鎖定（鎖定狀態在 helpers.account_lock，與 TestClient 同行程）。"""


def _setup(conn):
    from helpers import account_lock
    for _ in range(account_lock.config()["threshold"] + 1):
        account_lock.record_failure("wg_locked", "203.0.113.50", True)


CASES = [
    {"key": "POST /api/auth/account-locks/unlock",
     "url": "/api/auth/account-locks/unlock",
     "body": {"username": "wg_locked"},
     "setup": _setup},
]
WAIVE = {}
