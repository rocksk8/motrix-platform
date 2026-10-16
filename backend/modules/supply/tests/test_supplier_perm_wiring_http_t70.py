# -*- coding: utf-8 -*-
"""T70 PM-S5（供應商）HTTP 等價關卡：接線前後，同一個人打同一支端點，『被擋（403）』與否必須逐一相同。

真實帳號（make_user）＋真的 HTTP；六個角色 × 勾選形狀。放行的人會得到 404／422 這類『過了閘之後』的狀態，被擋的人是 403。
寫入端點一律打不存在的供應商（或不合法的前置時間），不會改到任何資料。
注意：make_user 預設會把『明確勾財務三鍵的一般帳號』換成 finance 角色；這裡以實際存進資料庫的角色比對今天的閘，財務鍵形狀用 legacy_finance_flag=False 保留原角色。
"""
import itertools

import db
from helpers import auth as A

ROLES = A.VALID_ROLES
SHAPES = [[], ["customer"], ["procurement"], ["inventory"], ["customer", "work_log"], ["reports", "work_log"], ["cashier", "financial_view"]]
GATE = {"customer", "procurement", "inventory"}
NOSUCH = 987654
#: (方法, 路徑, 內容, 能力動作)。POST 用不合法的前置時間（-1）⇒ 過閘後 422，不會新增；其餘打不存在的 id。
PROBES = [
    ("get", "/api/suppliers", None, "view"),
    ("get", "/api/suppliers/%d/privacy-notice" % NOSUCH, None, "view"),
    ("post", "/api/suppliers", {"name": "T70探針", "lead_time_days": -1}, "create"),
    ("put", "/api/suppliers/%d" % NOSUCH, {"name": "T70探針"}, "edit"),
    ("patch", "/api/suppliers/%d/visits" % NOSUCH, {}, "edit"),
    ("post", "/api/suppliers/%d/contacts/zz/privacy-notice/ack" % NOSUCH, None, "edit"),
    ("delete", "/api/suppliers/%d" % NOSUCH, None, "delete"),
]


def _legacy_allows(role, modules):
    return role == "superadmin" or bool(GATE & set(modules))


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, (username, r.text)
    return {"Authorization": "Bearer " + r.json()["token"]}


def _stored_role(username):
    conn = db.get_db()
    try:
        return conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()["role"]
    finally:
        conn.close()


def _count():
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
    finally:
        conn.close()


def test_http_gate_is_403_exactly_when_todays_gate_would_block(client, make_user):
    before = _count()
    seen = {"allowed": 0, "blocked": 0}
    for i, (role, modules) in enumerate(itertools.product(ROLES, SHAPES)):
        name = "sp_%s_%d" % (role, i)
        make_user(username=name, password="Test-Pass-123", role=role, modules=list(modules), legacy_finance_flag=False)
        assert _stored_role(name) == role, "帳號角色被改了，等價比對會量錯"
        h = _login(client, name, "Test-Pass-123")
        want_allowed = _legacy_allows(role, modules)
        for method, path, body, action in PROBES:
            kw = {"headers": h}
            if body is not None:
                kw["json"] = body
            r = getattr(client, method)(path, **kw)
            assert (r.status_code == 403) == (not want_allowed), (role, modules, method, path, r.status_code, r.text[:120])
            seen["allowed" if want_allowed else "blocked"] += 1
    assert seen["allowed"] and seen["blocked"], "兩邊都要有樣本：%s" % seen
    assert _count() == before, "探針不得新增或刪除任何供應商"


def test_http_unauthenticated_is_still_401(client):
    for method, path, body, _a in PROBES:
        kw = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kw).status_code == 401, (method, path)


def test_http_matrix_edit_changes_the_outcome_with_real_users(client, make_user):
    """真實帳號＋真的權限頁路由：最高管理者對『管理員』角色勾選『查看供應商』後，沒有功能勾選的管理員立刻打得開清單；取消後恢復。"""
    su, sp = make_user(username="sp_matrix_su", role="superadmin")
    ad, ap = make_user(username="sp_matrix_admin", role="admin", modules=[])
    hs, ha = _login(client, su, sp), _login(client, ad, ap)
    assert client.get("/api/suppliers", headers=ha).status_code == 403
    r = client.post("/api/permmatrix/role-cap", json={"role": "admin", "cap": "supply.supplier.view", "granted": True, "reason": "T70 測試"}, headers=hs)
    assert r.status_code == 200, r.text
    assert client.get("/api/suppliers", headers=ha).status_code == 200
    assert client.post("/api/suppliers", json={"name": "T70探針", "lead_time_days": -1}, headers=ha).status_code == 403, "只勾了『查看』，新增仍被擋"
    r = client.post("/api/permmatrix/role-cap", json={"role": "admin", "cap": "supply.supplier.view", "granted": False, "reason": "T70 測試還原"}, headers=hs)
    assert r.status_code == 200, r.text
    assert client.get("/api/suppliers", headers=ha).status_code == 403
