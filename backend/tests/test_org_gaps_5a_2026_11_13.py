"""批次 5a：組織設定缺口檢查（2026-11-13）。只讀；三種缺口；只有管理者以上看得到；三個頁面都掛了橫幅。"""
import json

import pytest

from helpers import org_gaps as OG


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _sql(sql, args=()):
    from db import get_db
    conn = get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _uid(username):
    from db import get_db
    conn = get_db()
    r = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return r["id"]


def _dept(name, manager_id=None):
    div = _sql("INSERT INTO divisions (name, created_at) VALUES (?, '2026-01-01')", (name + "-處",)) if _has_cols("divisions", "created_at") else None
    if div is None:
        div = _sql("INSERT INTO divisions (name) VALUES (?)", (name + "-處",))
    return _sql("INSERT INTO departments (division_id, name, manager_user_id, created_at) VALUES (?,?,?, '2026-01-01')", (div, name, manager_id))


def _has_cols(table, col):
    from db import get_db
    conn = get_db()
    try:
        return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _by_key(res):
    return {g["key"]: g for g in res["gaps"]}


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="og_root", role="superadmin")
    return _login(client, u, p)


def test_user_without_department_is_a_gap_and_fixing_it_clears_it(client, make_user, su):
    u, _ = make_user(username="og_nodept", role="sales")
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    assert OG.GAP_NO_DEPARTMENT in g
    assert u in [i["name"] for i in g[OG.GAP_NO_DEPARTMENT]["items"]] and g[OG.GAP_NO_DEPARTMENT]["fix"]["href"] == "users.html"
    d = _dept("og-業務")
    _sql("UPDATE users SET department_id=? WHERE username=?", (d, u))
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    assert u not in [i["name"] for i in g.get(OG.GAP_NO_DEPARTMENT, {}).get("items", [])]


def test_inactive_users_do_not_count_as_no_department(client, make_user, su):
    u, _ = make_user(username="og_inactive", role="sales")
    _sql("UPDATE users SET active=0 WHERE username=?", (u,))
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    assert u not in [i["name"] for i in g.get(OG.GAP_NO_DEPARTMENT, {}).get("items", [])]


def test_department_without_manager_is_a_gap_only_when_it_has_active_members(client, make_user, su):
    u, _ = make_user(username="og_member", role="sales")
    empty = _dept("og-空部門")                       # 沒有成員、沒有主管 ⇒ 不算缺口
    d = _dept("og-工程")                              # 有成員、沒有主管 ⇒ 缺口
    _sql("UPDATE users SET department_id=? WHERE username=?", (d, u))
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    names = [i["name"] for i in g[OG.GAP_NO_MANAGER]["items"]]
    assert "og-工程" in names and "og-空部門" not in names
    assert g[OG.GAP_NO_MANAGER]["fix"]["href"] == "org-structure.html"
    # 指定在職主管 ⇒ 缺口消失；主管被停用 ⇒ 又回來，且註明「主管已停用」
    mgr, _ = make_user(username="og_mgr", role="admin")
    _sql("UPDATE departments SET manager_user_id=? WHERE id=?", (_uid(mgr), d))
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    assert "og-工程" not in [i["name"] for i in g.get(OG.GAP_NO_MANAGER, {}).get("items", [])]
    _sql("UPDATE users SET active=0 WHERE username=?", (mgr,))
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    item = next(i for i in g[OG.GAP_NO_MANAGER]["items"] if i["name"] == "og-工程")
    assert item["note"] == "主管已停用"
    assert empty                                     # 只是確認空部門確實建立過


def test_no_finance_holder_is_a_gap_until_someone_has_the_finance_role(client, make_user, su):
    make_user(username="og_sales2", role="sales")
    assert OG.GAP_NO_FINANCE in _by_key(client.get("/api/org/gaps", headers=su).json())           # 最高管理者不算
    make_user(username="og_fin", role="finance")
    assert OG.GAP_NO_FINANCE not in _by_key(client.get("/api/org/gaps", headers=su).json())


def test_only_managers_can_see_it(client, make_user):
    ua, pa = make_user(username="og_adm", role="admin")
    us, ps = make_user(username="og_s", role="sales")
    uv, pv = make_user(username="og_v", role="viewer")
    assert client.get("/api/org/gaps", headers=_login(client, ua, pa)).status_code == 200
    for u, p in ((us, ps), (uv, pv)):
        assert client.get("/api/org/gaps", headers=_login(client, u, p)).status_code == 403
    assert client.get("/api/org/gaps").status_code == 401


def test_check_is_read_only(client, make_user, su):
    from db import get_db
    make_user(username="og_ro", role="sales")

    def snap():
        conn = get_db()
        try:
            return [tuple(r) for r in conn.execute("SELECT id, username, department_id, active FROM users ORDER BY id").fetchall()], \
                   [tuple(r) for r in conn.execute("SELECT id, name, manager_user_id FROM departments ORDER BY id").fetchall()]
        finally:
            conn.close()

    before = snap()
    client.get("/api/org/gaps", headers=su)
    client.get("/api/org/gaps", headers=su)
    assert snap() == before


def test_a_failing_check_does_not_break_the_others(monkeypatch):
    def boom(conn):
        raise RuntimeError("x")
    monkeypatch.setattr(OG, "_no_manager", boom)
    res = OG.check()                      # 不丟例外
    assert isinstance(res["gaps"], list) and OG.GAP_NO_MANAGER not in [g["key"] for g in res["gaps"]]


def test_texts_are_plain_language():
    """缺口文字不含程式字眼（簡易檢查；完整禁用詞清單在 hichan-7 的 ux_audit_config.json，落地後另接）。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "helpers" / "org_gaps.py").read_text(encoding="utf-8")
    for bad in ("NULL", "department_id", "manager_user_id", "API", "JSON", "role=", "superadmin"):
        # 只檢查會顯示給使用者的字串：title／detail／label
        for line in src.splitlines():
            if any(k in line for k in ('"title"', '"detail"', '"label"')):
                assert bad not in line, (bad, line)


def test_three_pages_mount_the_banner():
    from core import source_tree
    for page in ("approval-settings.html", "users.html", "system-hub.html"):
        src = source_tree.page_file(page).read_text(encoding="utf-8")
        assert 'data-org-gaps' in src and "org-gaps.js" in src, page
    users = source_tree.page_file("users.html").read_text(encoding="utf-8")
    assert "MotrixOrgGaps.refresh()" in users                       # 新增／停用之後重新檢查
