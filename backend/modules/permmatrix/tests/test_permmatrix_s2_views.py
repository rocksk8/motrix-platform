# -*- coding: utf-8 -*-
"""權限矩陣 PM-S2：唯讀檢視端點（matrix／users／effective／pending／versions／delegations）與頁面接線。規格 SPEC PMX16。"""
import json
from pathlib import Path

import pytest

import db
from core import capabilities as C
from helpers import auth as A
from helpers import perm as P
from modules.permmatrix import service as S

ROOT = Path(__file__).resolve().parents[4]


def _d(key, label, legacy, **kw):
    return dict(key=key, label=label, desc=label + "（測試用的一句話說明）", impact="勾選後可以" + label + "（測試用的影響說明）", legacy=legacy, **kw)


DECLS = [
    _d("zz.doc.view", "檢視測試單", {"role": ["admin", "sales"]}),
    _d("zz.doc.pay", "付款測試單", {"role": ["admin"]}),
]
CAPS, PROBLEMS = C.collect({"zz": {"capabilities": DECLS}}, valid_roles=A.VALID_ROLES)
URLS = ["/api/permmatrix/matrix", "/api/permmatrix/users", "/api/permmatrix/pending", "/api/permmatrix/versions", "/api/permmatrix/delegations"]


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def declared(client, monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "s2-test")
    monkeypatch.setattr(P, "_source", None)
    monkeypatch.setattr(P, "_provider", lambda: S.load_matrix)
    monkeypatch.setattr(P, "_last_good", {"m": None})
    monkeypatch.setattr(P, "_degraded", {"on": False})
    P.invalidate()
    yield
    P.invalidate()


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="pm_s2_su", role="superadmin")
    return _login(client, u, p)


@pytest.mark.parametrize("url", URLS + ["/api/permmatrix/users/1/effective"])
def test_every_view_requires_superadmin(client, make_user, url):
    assert client.get(url).status_code in (401, 403)
    u, p = make_user(username="pm_s2_admin", role="admin")
    assert client.get(url, headers=_login(client, u, p)).status_code == 403


def test_matrix_lists_declared_caps_with_seed_and_flags(client, su, declared):
    d = client.get("/api/permmatrix/matrix", headers=su).json()
    assert "superadmin" not in [r["role"] for r in d["roles"]]
    rows = {c["key"]: c for c in d["caps"]}
    assert set(rows) == {"zz.doc.view", "zz.doc.pay"}
    assert rows["zz.doc.view"]["cells"]["sales"] == {"granted": True, "seeded": True, "changed": False}
    assert rows["zz.doc.pay"]["cells"]["sales"]["granted"] is False
    assert rows["zz.doc.pay"]["risk"] == "high" or rows["zz.doc.pay"]["action"] == "pay"
    assert {a["action"] for a in d["actions"]} == set(C.ACTIONS)


def test_matrix_marks_cells_changed_from_seed(client, su, declared):
    conn = db.get_db()
    try:
        S.set_role_cap(conn, {"id": 1, "username": "pm_s2_su", "role": "superadmin"}, "sales", "zz.doc.view", False, "測試取消勾選")
    finally:
        conn.close()
    cell = {c["key"]: c for c in client.get("/api/permmatrix/matrix", headers=su).json()["caps"]}["zz.doc.view"]["cells"]["sales"]
    assert cell == {"granted": False, "seeded": True, "changed": True}


def test_matrix_without_declarations_is_empty_not_error(client, su, monkeypatch):
    monkeypatch.setattr(C, "all_caps", lambda: {})
    d = client.get("/api/permmatrix/matrix", headers=su).json()
    assert d["caps"] == [] and d["roles"]


def test_views_are_read_only(client, su, declared):
    conn = db.get_db()
    try:
        before = [conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("perm_role_caps", "perm_user_overrides", "perm_versions", "audit_log")]
    finally:
        conn.close()
    for url in URLS:
        assert client.get(url, headers=su).status_code == 200
    conn = db.get_db()
    try:
        assert before == [conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("perm_role_caps", "perm_user_overrides", "perm_versions", "audit_log")]
    finally:
        conn.close()


def test_effective_explains_each_cap_in_plain_chinese(client, su, make_user, declared):
    make_user(username="pm_s2_sales", role="sales")
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='pm_s2_sales'").fetchone()["id"]
    finally:
        conn.close()
    d = client.get("/api/permmatrix/users/%d/effective" % uid, headers=su).json()
    by = {c["key"]: c for c in d["caps"]}
    assert by["zz.doc.view"]["allowed"] is True and by["zz.doc.pay"]["allowed"] is False
    for c in d["caps"]:
        assert any("一" <= ch <= "鿿" for ch in c["why"]) and "zz.doc" not in c["why"]
    assert client.get("/api/permmatrix/users/999999/effective", headers=su).status_code == 404


def test_users_view_excludes_superadmin_and_lists_overrides(client, su, make_user, declared):
    make_user(username="pm_s2_eng", role="engineer")
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='pm_s2_eng'").fetchone()["id"]
        S.set_user_override(conn, {"id": 1, "username": "pm_s2_su", "role": "superadmin"}, uid, "zz.doc.view", "deny", "測試個人禁止")
    finally:
        conn.close()
    users = client.get("/api/permmatrix/users", headers=su).json()["users"]
    assert all(u["roleLabel"] != "超級管理員" for u in users)
    me = [u for u in users if u["id"] == uid][0]
    assert me["overrides"][0]["effect"] == "deny" and me["overrides"][0]["label"] == "檢視測試單"


def test_page_wired_into_module_and_hub():
    mod = json.loads((ROOT / "backend/modules/permmatrix/module.json").read_text(encoding="utf-8"))
    assert [p["path"] for p in mod["pages"]] == ["permission-matrix.html"]
    assert "menu" not in mod["pages"][0]                       # 只走系統中心卡片，不新增選單
    hub = json.loads((ROOT / "backend/core/system_hub_l1.json").read_text(encoding="utf-8"))
    card = [c for c in (hub if isinstance(hub, list) else hub.get("cards", hub.get("items", []))) if c.get("id") == "permission-matrix"][0]
    assert card["perm"] == "superadmin" and not card.get("planned")
    assert (ROOT / "frontend/pages" / card["href"]).exists()
