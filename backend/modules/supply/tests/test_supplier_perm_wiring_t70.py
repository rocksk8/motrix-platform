# -*- coding: utf-8 -*-
"""T70 PM-S5（供應商）：能力宣告＋端點接線的**結構證明**與**預設等價（純函式）**。HTTP 等價在 test_supplier_perm_wiring_http_t70.py。

證明的結構（仿 T68 PM-S1 勞報單）：
① 宣告：`module.json` 的 `capabilities` 全部合法、全部非保留（＝有端點使用）、`legacy` 逐一等於今天的閘（`require_any_module(customer／procurement／inventory)`）。
② 接線：每個被接線的端點，第一道閘就是 `user = _require_user(authorization)` 緊接 `perm.require(user, <已宣告的鍵>)`；`suppliers.py` 沒有殘留舊的 `require_any_module`。
③ 預設等價：六個角色 × 勾選形狀，`perm.can()`（種子矩陣）＝今天的放行條件（逐字意義副本，不 import 會演進的程式）。
④ 矩陣改了行為就跟著變（角色格、個人禁止），且最高管理者不受影響。
"""
import ast
import itertools
import json
from pathlib import Path

import pytest

from core import capabilities as C
from helpers import auth as A
from helpers import module_registry as MR
from helpers import perm as P

MOD = Path(__file__).resolve().parents[1]
API = MOD / "api" / "suppliers.py"
PREFIX = "supply.supplier."
GATE_MODULES = frozenset({"customer", "procurement", "inventory"})
EXPECTED = {"view", "create", "edit", "delete"}


def _manifest():
    return json.loads((MOD / "module.json").read_text(encoding="utf-8"))


_REAL_ALL_CAPS = C.all_caps
CAPS, PROBLEMS = C.collect({"supply": _manifest()}, valid_roles=A.VALID_ROLES)


def _functions():
    return [fn for fn in ast.parse(API.read_text(encoding="utf-8")).body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _wired():
    """{函式名: 能力鍵}：函式本體含 `perm.require(user, "<鍵>")` 者。"""
    out = {}
    for fn in _functions():
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "require"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "perm"):
                out[fn.name] = n.args[1].value
    return out


def test_declarations_are_valid_and_every_one_is_used_by_an_endpoint():
    assert not PROBLEMS, PROBLEMS
    assert {k[len(PREFIX):] for k in CAPS} == EXPECTED and all(k.startswith(PREFIX) for k in CAPS)
    assert not [k for k, c in CAPS.items() if c.reserved], "保留的能力＝沒有端點使用"
    assert set(_wired().values()) == set(CAPS), sorted(set(_wired().values()) ^ set(CAPS))


def test_every_declared_legacy_is_exactly_todays_any_module_gate():
    for k, c in CAPS.items():
        assert c.legacy[0] == "any" and c.modules == GATE_MODULES and not c.roles, k
        assert {t[1] for t in c.legacy[1]} == GATE_MODULES and all(t[0] == "module" for t in c.legacy[1]), k


def test_delete_is_a_high_risk_action_by_the_framework():
    """框架規則（不變式④）：delete 一律至少 high ⇒ 之後放寬要原因＋確認期間＋第二位最高管理者。預設種子與今天相同。"""
    assert CAPS[PREFIX + "delete"].risk == "high"
    assert all(CAPS[PREFIX + a].risk != "high" for a in ("view", "create", "edit"))


def test_wired_gate_is_exactly_require_user_then_perm_require_and_no_old_gate_is_left():
    bad, wired = [], _wired()
    for fn in _functions():
        body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if fn.name in wired:
            texts = [ast.unparse(s) for s in body]
            i = texts.index("user = _require_user(authorization)") if "user = _require_user(authorization)" in texts else -1
            if i < 0 or not texts[i + 1].startswith("perm.require(user, '%s" % PREFIX):
                bad.append(fn.name)
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "require_any_module":
                bad.append("%s 殘留舊閘 require_any_module" % fn.name)
    assert not bad, bad
    assert len(wired) == 7, "供應商 7 支端點全部接線：%s" % sorted(wired)


# ── 預設等價（純函式）────────────────────────────────────────────────────────────────
ROLES = A.VALID_ROLES
KEYS = [k for k, _l, _g in MR.MODULES]


def _legacy_allows(role, modules):
    """`require_any_module(user, ('customer','procurement','inventory'), …)` 的放行條件（逐字意義副本）：最高管理者，或勾選含其中任一個（非財務鍵，不看角色）。"""
    return role == "superadmin" or bool(GATE_MODULES & set(modules))


def _shapes():
    yield []
    for k in KEYS:
        yield [k]
    yield list(KEYS)
    yield ["customer", "work_log"]
    yield ["procurement", "reports"]
    yield ["inventory"]
    yield ["cashier", "financial_view", "finance"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "t70-supply")
    monkeypatch.setattr(A, "_finance_mode", lambda: "off")
    monkeypatch.setattr(P, "_source", None)
    monkeypatch.setattr(P, "_last_good", {"m": None})
    monkeypatch.setattr(P, "_degraded", {"on": False})
    P._seed_cache.update(key=None, m=None)
    P.set_matrix_source(lambda: P.seed_from_legacy(CAPS))
    yield
    P._seed_cache.update(key=None, m=None)


def _user(role, modules, uid=7):
    return {"id": uid, "username": "u%d" % uid, "role": role, "modules": json.dumps(modules)}


def test_default_matrix_equals_todays_gate_for_every_role_and_tick_shape():
    n = 0
    for role, modules in itertools.product(ROLES, list(_shapes())):
        u = _user(role, modules)
        for key in CAPS:
            assert P.can(u, key) == _legacy_allows(role, modules), (role, modules, key)
            n += 1
    assert n >= len(ROLES) * len(CAPS) * (len(KEYS) + 3)


def test_seed_gives_no_role_anything_so_the_matrix_starts_as_todays_ticks():
    m = P.seed_from_legacy(CAPS)
    assert not any(k in g for g in m.role_grants.values() for k in CAPS)


def test_editing_the_matrix_changes_the_outcome_and_superadmin_is_unaffected():
    admin_no_tick = _user("admin", [], uid=21)
    ticked = _user("sales", ["customer"], uid=22)
    su = _user("superadmin", [], uid=1)
    key = PREFIX + "view"
    assert not P.can(admin_no_tick, key) and P.can(ticked, key)
    P.set_matrix_source(lambda: P.Matrix(role_grants={"admin": frozenset({key})}, deny={22: frozenset({key})}))
    assert P.can(admin_no_tick, key), "管理員角色勾選查看 ⇒ 沒有功能勾選的管理員也能看"
    assert not P.can(ticked, key), "個人禁止優先於功能勾選"
    assert P.can(ticked, PREFIX + "edit"), "沒被禁止的其他動作不受影響"
    P.set_matrix_source(lambda: P.Matrix(deny={1: frozenset(CAPS)}))
    assert all(P.can(su, k) for k in CAPS)


def test_real_registry_shows_the_supplier_group_in_the_permission_page(client, make_user, monkeypatch):
    """用真的模組登錄（不 patch）：權限頁列出供應商四項、全部『已接入』、種子沒有任何角色預設勾選。"""
    monkeypatch.setattr(C, "all_caps", _REAL_ALL_CAPS)
    monkeypatch.setattr(C, "get", lambda k: _REAL_ALL_CAPS().get(k))
    u, p = make_user(username="pm_s5_su", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    r = client.get("/api/permmatrix/matrix", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    rows = {c["key"]: c for c in r.json()["caps"] if c["key"].startswith(PREFIX)}
    assert set(rows) == set(CAPS) and all(x["wired"] for x in rows.values())
    assert all(not cell["granted"] for x in rows.values() for cell in x["cells"].values())
    assert all(x["label"] and x["desc"] and x["impact"] for x in rows.values())
