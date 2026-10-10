# -*- coding: utf-8 -*-
"""權限矩陣 **關卡 A（判斷層等價）**——上線當天零行為變更的證明之一（設計稿 §3；仿 test_duty_roles_equivalence，永不砍）。

對一組涵蓋 legacy DSL 全部形狀的合成能力目錄，窮舉「六個角色 × 模組勾選形狀」，要求 `perm.can()` 與**今天的判斷式**（本檔內嵌的逐字副本——
`user_has_module`／角色集合；不 import 會演進的程式，否則證明變成自證）逐一相同。矩陣被編輯（個人允許／禁止、角色格增減）時行為依設計變化——另有題釘住。
"""
import itertools
import json

import pytest

from core import capabilities as C
from helpers import auth as A
from helpers import module_registry as MR
from helpers import perm as P

ROLES = A.VALID_ROLES
KEYS = [k for k, _l, _g in MR.MODULES]
FIN = ("cashier", "finance", "financial_view")


def _decl(key, legacy, **kw):
    return dict(key=key, label=key, legacy=legacy, **kw)


CATALOG = [
    _decl("zz.doc.view", {"module": "payslip"}),
    _decl("zz.doc.edit", {"any": [{"role": ["admin"]}, {"module": "payslip"}]}),
    _decl("zz.doc.submit", {"role": ["admin", "finance"]}),
    _decl("zz.doc.approve", {"superadmin": True}),
    _decl("zz.doc.pay", {"module": "cashier"}),                                   # 財務鍵：由角色推導，不看勾選
    _decl("zz.doc.view_money", {"module": "financial_view"}),
    _decl("zz.doc.delete", {"any": [{"role": ["sales"]}, {"module": "work_log"}, {"module": "cashier"}]}),
    _decl("zz.doc.export", {"any": [{"role": ["admin"]}, {"any": [{"module": "reports"}, {"role": ["finance", "engineer"]}]}]}),
    _decl("zz.doc.void", {"role": ["viewer"]}, delegable=False),
    _decl("zz.doc.config", {"role": ["admin"]}, delegable=False),
]
CAPS, PROBLEMS = C.collect({"zz": {"capabilities": CATALOG}}, valid_roles=ROLES)


def _legacy_module(role, modules, key):
    """第42班出貨的 `user_has_module`（逐字副本；財務三鍵只看角色、其餘看勾選）。"""
    if role == "superadmin":
        return True
    if key in FIN:
        return role in ("superadmin", "finance")
    return key in modules


def _legacy(node, role, modules):
    (kind, val), = node.items()
    if kind == "superadmin":
        return role == "superadmin"
    if kind == "role":
        return role in val or role == "superadmin"
    if kind == "module":
        return _legacy_module(role, modules, val)
    if kind == "any":
        return role == "superadmin" or any(_legacy(n, role, modules) for n in val)
    raise AssertionError(kind)


def _shapes():
    yield []
    for k in KEYS:
        yield [k]
    yield list(KEYS)
    yield list(FIN)                                                               # 惰性財務勾選
    yield ["payslip", "work_log"]
    yield ["reports", "cashier", "payslip"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "gate-a")
    monkeypatch.setattr(A, "_finance_mode", lambda: "off")
    monkeypatch.setattr(P, "_source", None)
    P._seed_cache.update(key=None, m=None)
    yield
    P._seed_cache.update(key=None, m=None)


def _user(role, modules, uid=7):
    return {"id": uid, "username": "u", "role": role, "modules": json.dumps(modules)}


def test_registry_covers_every_dsl_shape():
    assert len(CAPS) == len(CATALOG) and {c.risk for c in CAPS.values()} >= {"low", "high"}


def test_default_matrix_is_equivalent_to_todays_predicates_for_every_role_and_tick_shape():
    checked = 0
    for role, modules in itertools.product(ROLES, list(_shapes())):
        u = _user(role, modules)
        for key, cap in CAPS.items():
            assert P.can(u, key) == _legacy(dict([_node(cap)]), role, modules), (role, modules, key)
            checked += 1
    assert checked >= len(ROLES) * len(CAPS) * (len(KEYS) + 4)


def _node(cap):
    """Capability.legacy（正規化樹）→ DSL 字典（讓比對用的 legacy 副本吃同一份宣告）。"""
    def to_dsl(t):
        if t[0] == "superadmin":
            return {"superadmin": True}
        if t[0] == "role":
            return {"role": list(t[1])}
        if t[0] == "module":
            return {"module": t[1]}
        return {"any": [to_dsl(k) for k in t[1]]}
    return next(iter(to_dsl(cap.legacy).items()))


def test_seed_is_derived_only_from_role_leaves_and_has_no_personal_overrides():
    m = P.seed_from_legacy(CAPS)
    assert m.allow == {} and m.deny == {}
    assert m.role_grants["admin"] == frozenset({"zz.doc.edit", "zz.doc.submit", "zz.doc.export", "zz.doc.config"})
    assert "zz.doc.view" not in {k for g in m.role_grants.values() for k in g}, "模組葉子不進角色種子（由勾選展開）"
    assert P.seed_from_legacy(CAPS).role_grants == m.role_grants, "冪等"


def test_superadmin_always_passes_and_cannot_be_denied_or_locked_out():
    su = _user("superadmin", [], uid=1)
    P.set_matrix_source(lambda: P.Matrix(deny={1: frozenset(CAPS)}))
    assert all(P.can(su, k) for k in CAPS) and P.can(su, "zz.nope.view"), "連不存在的能力都直通（並記 log）"
    P.require(su, "zz.doc.approve")


def test_deny_wins_over_every_grant_and_allow_adds_only_for_delegable_caps():
    admin = _user("admin", ["payslip"], uid=9)
    assert P.can(admin, "zz.doc.edit") and P.can(admin, "zz.doc.view")
    P.set_matrix_source(lambda: P.Matrix(role_grants=P.seed_from_legacy(CAPS).role_grants, deny={9: frozenset({"zz.doc.edit", "zz.doc.view"})}))
    assert not P.can(admin, "zz.doc.edit") and not P.can(admin, "zz.doc.view"), "禁止優先：角色格與模組展開都擋得掉"
    assert P.can(admin, "zz.doc.submit"), "沒被禁止的不受影響"
    viewer = _user("viewer", [], uid=10)
    assert not P.can(viewer, "zz.doc.approve")
    P.set_matrix_source(lambda: P.Matrix(allow={10: frozenset({"zz.doc.approve", "zz.doc.config"})}))
    assert P.can(viewer, "zz.doc.approve"), "可委派能力：個人允許生效（『某個管理員可以有財務查看』這類）"
    assert not P.can(viewer, "zz.doc.config"), "不可委派的能力忽略個人允許"


def test_editing_the_role_grid_changes_the_outcome_as_designed():
    fin = _user("finance", [], uid=11)
    assert not P.can(fin, "zz.doc.edit")
    base = P.seed_from_legacy(CAPS)
    grants = dict(base.role_grants)
    grants["finance"] = frozenset(grants.get("finance", frozenset()) | {"zz.doc.edit"})
    P.set_matrix_source(lambda: P.Matrix(role_grants=grants))
    assert P.can(fin, "zz.doc.edit"), "『財務我勾選這項，他就能做』——只改矩陣、不改程式"
    assert not P.can(_user("sales", [], uid=12), "zz.doc.edit")


def test_unknown_capability_is_denied_and_require_says_what_is_missing():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        P.require(_user("viewer", [], uid=13), "zz.doc.approve")
    assert e.value.status_code == 403 and "zz.doc.approve" in e.value.detail
    assert not P.can(_user("admin", [], uid=14), "zz.nope.view") and not P.can(None, "zz.doc.view")


def test_explain_reports_the_source_of_each_grant():
    assert P.explain(_user("admin", [], uid=15), "zz.doc.edit") == {"allowed": True, "via": "role"}
    assert P.explain(_user("user", ["payslip"], uid=16), "zz.doc.view") == {"allowed": True, "via": "module", "module": "payslip"}
    assert P.explain(_user("viewer", [], uid=17), "zz.doc.approve")["via"] == "none"
    assert P.explain(_user("superadmin", [], uid=1), "zz.doc.approve")["via"] == "superadmin"


def test_effective_caps_equals_the_set_of_can():
    u = _user("admin", ["payslip"], uid=18)
    assert P.effective_caps(u) == frozenset(k for k in CAPS if P.can(u, k))
    assert P.effective_caps(None) == frozenset()
