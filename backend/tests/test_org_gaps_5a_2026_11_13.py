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


# ── 審查修正（hichan-10 審查 → 5a 修正 commit）：M1～M4、L5～L7 ─────────────────────────────

def _set_flag(mode):
    from helpers import auth
    _sql("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,'2026-11-13') "
         "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (auth.FINANCE_FLAG_KEY, json.dumps(mode)))
    auth.reset_finance_mode_cache()


@pytest.fixture
def flag_reset():
    from helpers import auth
    yield
    auth.reset_finance_mode_cache()


def _reference(conn):
    """逐人呼叫 finance_duty_person 的舊算法（參考答案）：有沒有任何在職的人持有財務職務。"""
    from helpers.auth import finance_duty_person
    return any(finance_duty_person({"id": r["id"], "username": r["username"], "role": r["role"], "modules": r["modules"]})
               for r in conn.execute("SELECT id, username, role, modules FROM users WHERE active=1").fetchall())


def _bind_finance_duty_role(username, key="og_fin_duty"):
    rid = _sql("INSERT INTO duty_roles (key, name, description, permissions, is_system, active, version, created_at, updated_at) "
               "VALUES (?,?,?,?,0,1,1,'2026-11-13','2026-11-13')", (key, key, "", json.dumps(["finance"])))
    _sql("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)",
         (_uid(username), rid, 1, "2026-11-13", ""))
    return rid


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_finance_holder_exists_matches_finance_duty_person_in_every_mode(client, make_user, flag_reset, mode):
    """一致性：一次查詢的版本與逐人呼叫 finance_duty_person 在 off／shadow／on 下答案相同（含職責角色授權、個人扣項、停用、最高管理者）。"""
    from db import get_db
    _set_flag(mode)

    def same(expect_on=None):
        conn = get_db()
        try:
            got, ref = OG.finance_holder_exists(conn), _reference(conn)
        finally:
            conn.close()
        from helpers import auth
        auth.reset_finance_mode_cache()
        assert got == ref, (mode, got, ref)
        return got

    make_user(username="og_p_root", role="superadmin")
    make_user(username="og_p_sales", role="sales")
    assert same() is False                                              # 最高管理者與一般同仁都不算
    fin, _ = make_user(username="og_p_fin", role="finance")
    assert same() is True                                               # 財務角色
    _sql("UPDATE users SET active=0 WHERE username=?", (fin,))
    assert same() is False                                              # 停用的不算
    _sql("UPDATE users SET active=1 WHERE username=?", (fin,))
    _sql("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
         (_uid(fin), "finance", 1, "2026-11-13", ""))
    same()                                                              # 財務角色被扣掉財務鍵：on 為 False、其他模式為 True（兩邊必須一致）
    _sql("DELETE FROM user_perm_subtracts")
    _sql("UPDATE users SET active=0 WHERE username=?", (fin,))
    _bind_finance_duty_role("og_p_sales")
    same()                                                              # 業務＋職責角色給 finance 鍵：on 為 True、其他模式為 False


def test_finance_check_is_read_only_and_writes_no_audit_in_shadow_mode(client, make_user, su, flag_reset):
    """shadow 模式下 GET /api/org/gaps 不可寫稽核（舊算法逐人呼叫 finance_duty_person 會在 old≠new 時開背景執行緒寫稽核）。"""
    from db import get_db
    from helpers import auth
    make_user(username="og_sh_sales", role="sales")
    u, _ = make_user(username="og_sh_sales2", role="sales")
    _bind_finance_duty_role(u)                                          # old(角色)=False、new(生效權限)=True ⇒ 舊算法會報差異
    _set_flag("shadow")

    def audits():
        conn = get_db()
        try:
            return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()

    before = audits()
    for _ in range(3):
        assert client.get("/api/org/gaps", headers=su).status_code == 200
    auth._join_shadow_threads()
    assert audits() == before
    assert auth._fin_threads == []


def test_300_users_without_finance_is_fast_in_every_mode(client, make_user, flag_reset):
    import time
    from db import get_db
    conn = get_db()
    for i in range(300):
        conn.execute("INSERT INTO users (username, display_name, password_hash, role, active, created_at, department_id) VALUES (?,?,?,?,1,'2026-01-01',NULL)",
                     ("og_bulk%d" % i, "B%d" % i, "x", "sales"))
    conn.commit()
    conn.close()
    for mode in ("off", "shadow", "on"):
        _set_flag(mode)
        t = time.perf_counter()
        res = OG.check()
        dt = time.perf_counter() - t
        assert OG.GAP_NO_FINANCE in _by_key(res), mode
        assert dt < 0.5, (mode, dt)          # 目標 < 100 ms；測試機負載高時放寬到 0.5 s（舊算法 on 模式 300 人約 2 s）


def test_fresh_install_shows_no_gaps(client, flag_reset):
    """全新安裝（只有最高管理者）：三項都不提醒（審查 M3；原本會對「展示帳號」報沒部門、對沒人財務報缺口）。"""
    from db import get_db
    conn = get_db()
    try:
        assert OG.check(conn) == {"ok": True, "count": 0, "gaps": []}
    finally:
        conn.close()


def test_superadmin_is_not_a_no_department_gap_but_staff_still_are(client, make_user, su):
    make_user(username="og_staff", role="sales")
    g = _by_key(client.get("/api/org/gaps", headers=su).json())
    names = [i["name"] for i in g[OG.GAP_NO_DEPARTMENT]["items"]]
    assert "og_staff" in names and "og_root" not in names and "og_root" not in " ".join(names)
    assert "最高管理者若要送審，仍然需要歸屬部門" in g[OG.GAP_NO_DEPARTMENT]["detail"]
    assert "送審會被擋下" in g[OG.GAP_NO_DEPARTMENT]["detail"] or "送審時會被擋下" in g[OG.GAP_NO_DEPARTMENT]["detail"]
    assert "改送給最高管理者" not in g[OG.GAP_NO_DEPARTMENT]["detail"]    # 2026-09-15 起不再往最高管理者遞補


def test_non_admin_error_body_has_no_names(client, make_user):
    u, p = make_user(username="og_na", role="sales")
    make_user(username="og_secret_person", role="sales")
    r = client.get("/api/org/gaps", headers=_login(client, u, p))
    assert r.status_code == 403 and "og_secret_person" not in r.text


def test_banner_script_skips_non_admin_and_ignores_stale_responses():
    """前端靜態檢查：非管理者不發請求（沒存角色的舊登入照發）；連續重查只認最後一次回應；人名只走 textContent；刪除使用者後也重查。"""
    from pathlib import Path
    from core import source_tree
    js = (Path(__file__).resolve().parent.parent.parent / "frontend" / "static" / "org-gaps.js").read_text(encoding="utf-8")
    assert "canSee()" in js and "'superadmin'" in js and "'admin'" in js
    assert "data-org-gaps-seq" in js
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js     # 不可有任何 HTML 注入入口
    users = source_tree.page_file("users.html").read_text(encoding="utf-8")
    delete_body = users[users.index("async deleteUser"):users.index("async loadUsers")]
    assert "MotrixOrgGaps.refresh()" in delete_body


def test_gap_item_shape_is_stable(client, make_user, su):
    """回應形狀釘在這裡（response_keys_baseline 只錄「全新安裝＝沒有缺口」那一種形狀）：前端與開始使用清單都依賴它。"""
    make_user(username="og_shape", role="sales")
    res = client.get("/api/org/gaps", headers=su).json()
    assert set(res) == {"ok", "count", "gaps"} and res["ok"] is False
    for g in res["gaps"]:
        assert {"key", "severity", "title", "detail", "count", "items", "fix"} <= set(g)
        assert set(g["fix"]) == {"label", "href"} and g["key"] in OG.GAP_KEYS
        for i in g["items"]:
            assert {"id", "name"} <= set(i) and set(i) <= {"id", "name", "note"}
