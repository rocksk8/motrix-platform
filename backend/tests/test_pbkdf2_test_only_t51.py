# -*- coding: utf-8 -*-
"""第 51 班（主持裁示）：測試行程把 PBKDF2 降到 1,000 次只准存在於測試——產品預設仍是 260,000 次，產品碼沒有任何開關。

守門：① 掛 real_pbkdf2 的題拿到產品真值（用固定 salt 對算 260,000 次）② helpers/auth.py 的原始碼仍是 260_000 且沒有讀環境變數
③ 降次數的代理（_FastHashlib／_FAST_PBKDF2_ITERATIONS）只出現在 conftest.py 與 tests/ ④ 沒掛標記的題確實走代理，且 make_user＋登入照常（e2e 的行程內伺服器讀同一個模組）。
"""
import hashlib
import inspect
import os
import re
import subprocess

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)


@pytest.mark.real_pbkdf2
def test_marked_tests_get_the_production_iteration_count(monkeypatch):
    import helpers.auth as auth
    assert auth.hashlib is hashlib, "標記 real_pbkdf2 的題不該套用降次數代理"
    salt = bytes(range(16))
    monkeypatch.setattr(auth.os, "urandom", lambda n: salt)
    stored = auth._hash_pw("Real-Pass-1")
    assert stored == salt.hex() + ":" + hashlib.pbkdf2_hmac("sha256", b"Real-Pass-1", salt, 260_000).hex()


def test_production_source_keeps_260k_and_has_no_switch():
    import helpers.auth as auth
    src = inspect.getsource(auth._hash_pw) + inspect.getsource(auth._verify_pw)
    assert src.count("260_000") == 2 and "environ" not in src and "getenv" not in src, src
    whole = inspect.getsource(auth)
    assert not re.search(r"pbkdf2_hmac\([^)]*,\s*(?!260_000)\d", whole), "helpers/auth.py 出現了 260_000 以外的 PBKDF2 次數"


def test_the_shim_exists_only_under_tests():
    out = subprocess.run(["git", "grep", "-l", "-E", "_FastHashlib|_FAST_PBKDF2_ITERATIONS", "--", "backend", "tools"],
                         capture_output=True, text=True, encoding="utf-8", cwd=REPO,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.split()
    allowed = ("backend/conftest.py",)
    stray = [f for f in out if f not in allowed and "/tests/" not in f and not f.startswith("backend/tests/")]
    assert not stray, "降次數的代理跑進了產品碼：%s" % stray


def test_unmarked_tests_run_with_the_shim_and_login_still_works(client, make_user):
    import os
    import helpers.auth as auth
    if os.environ.get("MOTRIX_TEST_REAL_PBKDF2") == "1":
        pytest.skip("A/B 對照跑：本機刻意關掉代理")
    assert type(auth.hashlib).__name__ == "_FastHashlib"
    u, p = make_user(username="pb51", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200 and r.json().get("token")
    assert client.post("/api/auth/login", json={"username": u, "password": "wrong-Pass-9"}).status_code in (400, 401, 403)
