# -*- coding: utf-8 -*-
"""T68 PM-S1（勞報單）HTTP 等價關卡：接線前後，同一個人打同一支端點，『被擋（403）』與否必須逐一相同。

**錢相關端點——整合者宣布安靜窗口後才跑（本檔寫好、作者沒有跑）。** 結構證明與純函式等價在 test_payslip_perm_wiring_t68.py（已跑）。

做法：六個角色 × 勾選形狀各建一個帳號，對『讀取端點＋對不存在的單據做寫入』打請求；
放行的人會得到 404／400／422 這類『過了閘之後』的狀態，被擋的人是 403。比對『是不是 403』與今天的判斷式（逐字副本）。
寫入端點一律打不存在的單號，所以不會改到任何資料；沒有送合法的 payload 的端點，422 也算『過了閘』（FastAPI 先驗 body 再進函式 ⇒ 這類端點只在有合法 body 時才測得到閘，
所以只選 body 簡單的：空 body 的 POST／DELETE／GET）。
"""
import itertools

import pytest

from helpers import auth as A

ROLES = A.VALID_ROLES
SHAPES = [[], ["payslip"], ["payslip", "work_log"], ["cashier", "financial_view"], ["work_log"]]
NONE = "ZZ-NOSUCH-0000"
#: (方法, 路徑, 能力動作) —— 空 body 或只需 query 的端點
PROBES = [
    ("get", "/api/payslips", "view"),
    ("get", "/api/payslips/" + NONE, "view"),
    ("get", "/api/tax-rules", "view"),
    ("get", "/api/next-slip-no", "create"),
    ("get", "/api/payslips/" + NONE + "/dispatch-links", "view"),
    ("get", "/api/payslip-person-dispatches", "view"),
    ("post", "/api/payslips/" + NONE + "/export", "export"),
    ("post", "/api/payslips/" + NONE + "/unsign", "edit"),
    ("get", "/api/payslips/" + NONE + "/pdf-download", "export"),
    ("delete", "/api/payslips/" + NONE + "/signed-files/zz", "attach"),
    ("delete", "/api/payslips/" + NONE + "/dispatch-links/1", "edit"),
]


def _legacy_allows(role, modules):
    return role == "superadmin" or "payslip" in modules


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, (username, r.text)
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_http_gate_is_403_exactly_when_todays_gate_would_block(client, make_user):
    seen = {"allowed": 0, "blocked": 0}
    for i, (role, modules) in enumerate(itertools.product(ROLES, SHAPES)):
        name = "pw_%s_%d" % (role, i)
        make_user(username=name, password="Test-Pass-123", role=role, modules=list(modules))
        h = _login(client, name, "Test-Pass-123")
        want_allowed = _legacy_allows(role, modules)
        for method, path, action in PROBES:
            r = getattr(client, method)(path, headers=h)
            got_blocked = r.status_code == 403
            assert got_blocked == (not want_allowed), (role, modules, method, path, r.status_code, r.text[:120])
            seen["allowed" if want_allowed else "blocked"] += 1
    assert seen["allowed"] and seen["blocked"], "兩邊都要有樣本，否則這題量不到東西：%s" % seen


def test_http_unauthenticated_is_still_401(client):
    for method, path, _a in PROBES:
        assert getattr(client, method)(path).status_code == 401, (method, path)
