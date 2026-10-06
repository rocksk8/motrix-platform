# -*- coding: utf-8 -*-
"""職責角色化 R1 **上線關卡**：零行為變更的證明（DUTY-ROLES-DESIGN §3.2；使用者 2026-10-06「equivalence matrix 永不砍」）。

沒有綁定、沒有扣項的人（＝遷移完成當天的所有人）：
- `effective_modules(role, modules, user_id=…)` 與「第42班出貨的演算法」（本檔內嵌一份逐字副本，不 import 會演進的程式）對
  **所有角色 × 所有模組鍵（單鍵、空、全部、含惰性財務勾選）** 逐字相同；
- `_require_user` 回傳的 `modules` 字串與資料庫原值**逐字相同**；`user_has_module` 對所有鍵相同；`has_finance_access` 相同；
- 遷移建立了表與種子角色，但**沒有任何綁定、扣項、變更紀錄**；遷移重跑冪等、不覆蓋改過的角色。
"""
import json

import pytest

import db
from helpers import auth as A
from helpers import module_registry as MR

ROLES = A.VALID_ROLES
KEYS = [k for k, _l, _g in MR.MODULES]


def _legacy_effective(role, modules):
    """第42班出貨的 `effective_modules`（逐字副本；不可改成呼叫現行函式，否則證明變成自證）。"""
    if isinstance(modules, str):
        try:
            modules = json.loads(modules or "[]")
        except Exception:
            modules = []
    mods = [m for m in (modules or []) if m not in ("cashier", "finance", "financial_view")]
    if role in ("superadmin", "finance"):
        mods += [k for k in ("cashier", "finance", "financial_view")]
    return mods


def _shapes():
    yield []
    for k in KEYS:
        yield [k]
    yield list(KEYS)
    yield ["cashier", "finance", "financial_view"]                       # 惰性財務勾選
    yield ["dashboard", "cashier"]
    yield list(reversed(KEYS))                                           # 順序也要一樣


def test_effective_modules_identical_for_every_role_and_module_shape(client, make_user):
    conn = db.get_db()
    try:
        n = 0
        for role in ROLES:
            for i, shape in enumerate(_shapes()):
                for raw in (shape, json.dumps(shape)):
                    want = _legacy_effective(role, raw)
                    # 有 user_id（真實資料庫：表在、角色種子在、沒有綁定／扣項）
                    assert A.effective_modules(role, raw, user_id=987654, conn=conn) == want, (role, shape)
                    # 沒有 user_id（舊呼叫方式）
                    assert A.effective_modules(role, raw) == want, (role, shape)
                    n += 1
        assert n == len(ROLES) * (len(KEYS) + 5) * 2
    finally:
        conn.close()


def test_require_user_modules_string_is_byte_identical_for_users_without_duty_data(client, make_user):
    from fastapi import HTTPException  # noqa: F401
    for role in ROLES:
        for j, shape in enumerate(([], ["dashboard", "case_manage"], list(KEYS), ["cashier", "finance"])):
            name = "eq_%s_%d" % (role, j)
            u, p = make_user(username=name, role=role, modules=shape, legacy_finance_flag=False)
            r = client.post("/api/auth/login", json={"username": u, "password": p})
            assert r.status_code == 200, r.text
            tok = r.json()["token"]
            assert r.json()["modules"] == _legacy_effective(role, json.dumps(shape)), (role, shape)
            raw = db.get_db().execute("SELECT modules FROM users WHERE username=?", (name,)).fetchone()[0]
            user = A._require_user("Bearer " + tok)
            assert user["modules"] == raw, "沒有綁定／扣項的人，user['modules'] 必須與資料庫原值逐字相同"
            me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + tok})
            assert me.status_code == 200 and me.json()["modules"] == _legacy_effective(role, raw)
            for k in KEYS:
                want = (A.has_finance_access(user) if k in ("cashier", "finance", "financial_view") else k in shape)
                assert A.user_has_module(user, k) is want, (role, shape, k)


def test_has_finance_access_is_the_train42_rule():
    for role in ROLES:
        assert A.has_finance_access({"role": role, "modules": "[]"}) is (role in ("superadmin", "finance"))
        assert A.has_cashier_access({"role": role, "modules": json.dumps(["cashier", "finance"])}) is (role in ("superadmin", "finance"))


def test_migration_creates_tables_and_seed_but_no_bindings_subtracts_or_changes(client):
    conn = db.get_db()
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"duty_roles", "user_duty_roles", "user_perm_subtracts", "permission_changes"} <= names
        assert conn.execute("SELECT COUNT(*) FROM duty_roles WHERE is_system=1").fetchone()[0] == 8
        for t in ("user_duty_roles", "user_perm_subtracts", "permission_changes"):
            assert conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] == 0, t
    finally:
        conn.close()


def test_migration_is_idempotent_and_does_not_overwrite_edited_roles(client):
    from core import migrations as M
    conn = db.get_db()
    try:
        conn.execute("UPDATE duty_roles SET name='被改過', permissions='[\"dashboard\"]', version=5 WHERE key='sales'")
        conn.commit()
        for fn in M._PENDING:
            fn(conn)
        for fn in M._PENDING:
            fn(conn)
        row = conn.execute("SELECT name, permissions, version FROM duty_roles WHERE key='sales'").fetchone()
        assert (row[0], row[1], row[2]) == ("被改過", '["dashboard"]', 5)
        assert conn.execute("SELECT COUNT(*) FROM duty_roles").fetchone()[0] == 8
    finally:
        conn.close()


def test_seed_roles_only_use_known_module_keys():
    from core import migrations as M
    known = set(KEYS)
    for key, _n, _d, perms in M._DUTY_SEED:
        assert set(perms) <= known, (key, sorted(set(perms) - known))


def test_finance_key_constants_match_auth():
    from helpers import duty_roles as DR
    assert tuple(sorted(DR.FINANCE_KEYS)) == tuple(sorted(A.FINANCE_MODULE_KEYS))


@pytest.mark.parametrize("role", ["superadmin"])
def test_superadmin_never_goes_through_duty_resolution(client, role, monkeypatch):
    from helpers import duty_roles as DR

    def boom(*a, **k):
        raise AssertionError("superadmin 不應經過角色／扣項解析")
    monkeypatch.setattr(DR, "resolve_raw_modules", boom)
    assert A.effective_modules(role, json.dumps(["dashboard"]), user_id=1) == _legacy_effective(role, ["dashboard"])
