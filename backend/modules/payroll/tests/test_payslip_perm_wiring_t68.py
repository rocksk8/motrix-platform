# -*- coding: utf-8 -*-
"""T68 PM-S1（勞報單）：能力宣告＋端點接線的**結構證明**與**預設等價（純函式）**。不開 HTTP、不碰資料庫、不跑端點。

證明的結構：
① 宣告：`module.json` 的 `capabilities` 全部合法（`core.capabilities.collect` 無問題）、全部非保留（＝有端點使用）、`legacy` 逐一等於今天的判斷式（模組勾選 `payslip`）。
② 接線：每個被接線的端點，第一道閘就是 `user = _require_user(authorization)` 緊接 `perm.require(user, <已宣告的鍵>)`；全部 `payroll/api` 裡不再有 `module="payslip"` 的舊閘（除登記的例外）。
③ 預設等價：六個角色 × 勾選形狀，`perm.can()`（種子矩陣）＝今天 `_require_user(require_superadmin=True, module="payslip")` 放行的條件（逐字副本，不 import 會演進的程式）。
④ 矩陣改了行為就跟著變（角色格、個人禁止），且最高管理者不受影響。
HTTP 層的等價關卡在 test_payslip_perm_wiring_http_t68.py（錢相關端點；整合者宣布安靜窗口後才跑）。
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
API = MOD / "api"
PREFIX = "payroll.payslip."
#: 仍保留舊的 `module="payslip"` 閘的函式。要新增例外必須寫理由。
_W1 = "簽核／退回一律要真正的最高管理者（W1，使用者裁示：核准是最高管理者的決定）：本體在閘之後立刻再檢查 role==superadmin，所以模組勾選閘只是第一層。接進矩陣會變成『矩陣說可以、本體仍拒絕』的假勾選，故不宣告、不接線。"
LEGACY_GATE_EXCEPTIONS = {("payslip_approval.py", "approve_payslip"): _W1, ("payslip_approval.py", "reject_payslip"): _W1}


def _manifest():
    return json.loads((MOD / "module.json").read_text(encoding="utf-8"))


_REAL_ALL_CAPS = C.all_caps
CAPS, PROBLEMS = C.collect({"payroll": _manifest()}, valid_roles=A.VALID_ROLES)


def _wired_functions():
    """{(檔名, 函式名): 能力鍵}：函式本體含 `perm.require(user, "<鍵>")` 者。"""
    out = {}
    for f in sorted(API.glob("payslip*.py")):
        for fn in ast.parse(f.read_text(encoding="utf-8")).body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "require"
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "perm"):
                    out[(f.name, fn.name)] = n.args[1].value
    return out


def test_declarations_are_valid_and_every_one_is_used_by_an_endpoint():
    assert not PROBLEMS, PROBLEMS
    assert set(CAPS) and all(k.startswith(PREFIX) for k in CAPS)
    assert not [k for k, c in CAPS.items() if c.reserved], "保留的能力＝沒有端點使用；S1 宣告的都必須已接線"
    used = set(_wired_functions().values())
    assert used == set(CAPS), ("接線用到但沒宣告：%s；宣告了但沒端點用：%s" % (sorted(used - set(CAPS)), sorted(set(CAPS) - used)))


def test_every_declared_legacy_is_exactly_todays_module_gate():
    """今天的閘：最高管理者，或持有 `payslip` 模組勾選（`_require_user(require_superadmin=True, module="payslip")`）。宣告若改了 legacy，等價證明就要重寫。"""
    for k, c in CAPS.items():
        assert c.legacy == ("module", "payslip") and c.modules == frozenset({"payslip"}) and not c.roles, k


def test_wired_gate_is_exactly_require_user_then_perm_require():
    bad = []
    for f in sorted(API.glob("payslip*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or (f.name, fn.name) not in _wired_functions():
                continue
            body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]      # 略過 docstring
            a, b = ast.unparse(body[0]), ast.unparse(body[1])
            if a != "user = _require_user(authorization)" or not b.startswith("perm.require(user, '%s" % PREFIX):
                bad.append("%s.%s：%s／%s" % (f.name, fn.name, a, b))
    assert not bad, bad


def test_no_old_module_gate_left_in_payslip_endpoints():
    left = []
    for f in sorted(API.glob("payslip*.py")):
        for fn in ast.parse(f.read_text(encoding="utf-8")).body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_require_user"
                        and any(k.arg == "module" and getattr(k.value, "value", None) == "payslip" for k in n.keywords)):
                    if (f.name, fn.name) not in LEGACY_GATE_EXCEPTIONS:
                        left.append("%s.%s" % (f.name, fn.name))
    assert not left, "還有舊的 module=\"payslip\" 閘（接線或登記例外並寫理由）：%s" % left


# ── 預設等價（純函式）────────────────────────────────────────────────────────────────
ROLES = A.VALID_ROLES
KEYS = [k for k, _l, _g in MR.MODULES]


def _legacy_allows(role, modules):
    """`_require_user(authorization, require_superadmin=True, module="payslip")` 的放行條件（逐字意義副本）：最高管理者，或勾選含 payslip（非財務鍵，不看角色）。"""
    return role == "superadmin" or "payslip" in modules


def _shapes():
    yield []
    for k in KEYS:
        yield [k]
    yield list(KEYS)
    yield ["payslip", "work_log"]
    yield ["cashier", "financial_view", "finance"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "t68-payroll")
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
    ticked = _user("sales", ["payslip"], uid=22)
    su = _user("superadmin", [], uid=1)
    key = PREFIX + "view"
    assert not P.can(admin_no_tick, key) and P.can(ticked, key)
    P.set_matrix_source(lambda: P.Matrix(role_grants={"admin": frozenset({key})}, deny={22: frozenset({key})}))
    assert P.can(admin_no_tick, key), "管理員角色勾選查看 ⇒ 沒有功能勾選的管理員也能看"
    assert not P.can(ticked, key), "個人禁止優先於功能勾選"
    assert P.can(ticked, PREFIX + "edit"), "沒被禁止的其他動作不受影響"
    P.set_matrix_source(lambda: P.Matrix(deny={1: frozenset(CAPS)}))
    assert all(P.can(su, k) for k in CAPS)


def test_real_registry_shows_the_payslip_group_in_the_permission_page(client, make_user, monkeypatch):
    """用真的模組登錄（不 patch）：權限頁的矩陣端點列出勞報單六項、全部『已接入』、種子＝沒有任何角色預設勾選。"""
    monkeypatch.setattr(C, "all_caps", _REAL_ALL_CAPS)                     # 換回真的登錄（模組載入後 module.json 的宣告）
    monkeypatch.setattr(C, "get", lambda k: _REAL_ALL_CAPS().get(k))
    u, p = make_user(username="pm_s1_su", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    r = client.get("/api/permmatrix/matrix", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    d = r.json()
    rows = {c["key"]: c for c in d["caps"] if c["key"].startswith(PREFIX)}
    assert set(rows) == set(CAPS) and all(r["wired"] for r in rows.values())
    assert all(not cell["granted"] for r in rows.values() for cell in r["cells"].values())
    assert {r["unitLabel"] for r in rows.values()} and all(r["label"] and r["desc"] and r["impact"] for r in rows.values())
