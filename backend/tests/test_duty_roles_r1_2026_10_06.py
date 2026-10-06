# -*- coding: utf-8 -*-
"""職責角色化 R1（DUTY-ROLES-DESIGN §2、§7；使用者裁示 Q1–Q12、N1–N4）：演算法、原因規則、扣項、紀錄、授權。
零行為變更的證明在 `test_duty_roles_equivalence_2026_10_06.py`（上線關卡）。"""
import json
import sqlite3

import pytest

import db
from helpers import auth as A
from helpers import duty_roles as DR


def _hdr(client, name, pw="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def W(client, make_user):
    make_user(username="dr_sa", role="superadmin")
    make_user(username="dr_adm", role="admin", modules=["dashboard"], legacy_finance_flag=False)
    make_user(username="dr_eng", role="engineer", modules=["dashboard"])
    conn = db.get_db()
    ids = {n: conn.execute("SELECT id FROM users WHERE username=?", (n,)).fetchone()[0] for n in ("dr_sa", "dr_adm", "dr_eng")}
    roles = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM duty_roles")}
    conn.close()
    return {"sa": _hdr(client, "dr_sa"), "adm": _hdr(client, "dr_adm"), "eng": _hdr(client, "dr_eng"), "ids": ids, "roles": roles, "client": client}


def _post(W, path, body, who="sa"):
    return W["client"].post("/api/duty-roles" + path, json=body, headers=W[who])


def _eff(uid):
    conn = db.get_db()
    try:
        u = conn.execute("SELECT role, modules FROM users WHERE id=?", (uid,)).fetchone()
        return A.effective_modules(u["role"], u["modules"], user_id=uid, conn=conn)
    finally:
        conn.close()


def _changes(**kw):
    conn = db.get_db()
    try:
        return DR.list_changes(conn, **kw)
    finally:
        conn.close()


def _require_user_modules(W, who):
    return json.loads(A._require_user(W[who]["Authorization"])["modules"])


# ── 算法 ────────────────────────────────────────────────────────────────

def test_bind_adds_role_keys_everywhere_the_seam_is_used(W):
    uid = W["ids"]["dr_eng"]
    assert "procurement" not in _eff(uid)
    r = _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]})
    assert r.status_code == 201, r.text
    assert "procurement" in _eff(uid) and "dashboard" in _eff(uid)
    assert "procurement" in _require_user_modules(W, "eng"), "_require_user 的 modules 也要含角色授予的鍵"
    assert A.user_has_module(A._require_user(W["eng"]["Authorization"]), "procurement") is True
    me = W["client"].get("/api/auth/me", headers=W["eng"]).json()["modules"]
    assert "procurement" in me
    # 原有勾選不受影響
    assert "dashboard" in me


def test_unbind_removes_role_keys(W):
    uid = W["ids"]["dr_eng"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201
    assert _post(W, "/bindings/remove", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 200
    assert "procurement" not in _eff(uid)


def test_subtract_wins_over_role_even_when_role_later_grants_again(W):
    uid, c = W["ids"]["dr_eng"], W["client"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201
    assert _post(W, "/subtracts", {"userId": uid, "key": "inventory"}).status_code == 201
    eff = _eff(uid)
    assert "procurement" in eff and "inventory" not in eff, "角色給了 inventory，但被個人扣除"
    # 角色定義後來又（再）授予同一個鍵 ⇒ 扣項仍贏
    r = c.put("/api/duty-roles/%d" % W["roles"]["procurement"], headers=W["sa"],
              json={"permissions": ["dashboard", "procurement", "inventory", "equipment", "map"]})
    assert r.status_code == 200, r.text
    assert "map" in _eff(uid) and "inventory" not in _eff(uid)
    assert "inventory" not in _require_user_modules(W, "eng")


def test_subtract_conflicts_with_personal_checkbox_and_idle_subtract_is_harmless(W):
    uid = W["ids"]["dr_eng"]
    r = _post(W, "/subtracts", {"userId": uid, "key": "dashboard"})                    # 個人勾選裡有 dashboard
    assert r.status_code == 400 and "個人勾選" in r.text
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201
    assert _post(W, "/subtracts", {"userId": uid, "key": "inventory"}).status_code == 201
    r = W["client"].put("/api/duty-roles/%d" % W["roles"]["procurement"], headers=W["sa"], json={"permissions": ["dashboard", "procurement"]})
    assert r.status_code == 200
    assert "inventory" not in _eff(uid) and "procurement" in _eff(uid), "閒置扣項不影響生效"


def test_inactive_role_does_not_count(W):
    uid = W["ids"]["dr_eng"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201
    assert W["client"].put("/api/duty-roles/%d" % W["roles"]["procurement"], headers=W["sa"], json={"active": False}).status_code == 200
    assert "procurement" not in _eff(uid)
    r = _post(W, "/bindings", {"userId": W["ids"]["dr_adm"], "roleId": W["roles"]["procurement"]})
    assert r.status_code == 400, "已停用的角色不能再綁"


def test_two_roles_union(W):
    uid = W["ids"]["dr_eng"]
    for k in ("procurement", "sales"):
        assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"][k]}).status_code == 201
    eff = set(_eff(uid))
    assert {"procurement", "inventory", "quotation", "customer", "map"} <= eff


# ── superadmin 不變式 ───────────────────────────────────────────────────

def test_superadmin_cannot_be_bound_or_subtracted_and_hard_inserted_rows_do_not_reduce_it(W):
    sa = W["ids"]["dr_sa"]
    assert _post(W, "/subtracts", {"userId": sa, "key": "quotation"}).status_code == 400
    assert _post(W, "/bindings", {"userId": sa, "roleId": W["roles"]["viewer"]}).status_code == 400
    before = _eff(sa)
    raw_before = A._require_user(W["sa"]["Authorization"])["modules"]
    conn = db.get_db()                                              # 繞過服務層，硬塞資料
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_at) VALUES (?,?,?)", (sa, "quotation", "x"))
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_at) VALUES (?,?,?)", (sa, "dashboard", "x"))
    conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_at) VALUES (?,?,?)", (sa, W["roles"]["viewer"], "x"))
    conn.commit()
    conn.close()
    assert _eff(sa) == before, "任何角色／扣項資料都不可能降低 superadmin"
    assert A._require_user(W["sa"]["Authorization"])["modules"] == raw_before
    assert A.has_finance_access(A._require_user(W["sa"]["Authorization"])) is True


def test_finance_trio_subtract_is_refused_and_binding_finance_role_does_not_grant_finance_access(W):
    uid = W["ids"]["dr_adm"]
    for k in ("cashier", "finance", "financial_view"):
        r = _post(W, "/subtracts", {"userId": uid, "key": k, "reason": "測試原因"})
        assert r.status_code == 400 and "財務三鍵" in r.text, k
    r = _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["finance"], "reason": "測試綁定財務角色"})
    assert r.status_code == 201, r.text
    u = A._require_user(W["adm"]["Authorization"])
    assert A.has_finance_access(u) is False and A.has_cashier_access(u) is False, "第42班：財務權只由基礎類別 finance／superadmin 決定"
    assert A.user_has_module(u, "cashier") is False
    assert not ({"cashier", "finance", "financial_view"} & set(_eff(uid))), "effective 清單仍套財務規則"
    assert "reports" in _eff(uid), "非財務鍵照常授予"


# ── 原因規則（Q4 b）──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", list(DR.HIGH_SENSITIVITY_KEYS))
def test_every_high_sensitivity_key_requires_a_reason_on_role_create(W, key):
    body = {"key": "t_" + key, "name": "測試" + key, "permissions": [key]}
    r = _post(W, "/", body) if False else W["client"].post("/api/duty-roles", json=body, headers=W["sa"])
    assert r.status_code == 400 and "原因" in r.text, key
    r = W["client"].post("/api/duty-roles", json=dict(body, reason="  ab "), headers=W["sa"])
    assert r.status_code == 400, "去空白後 <4 字仍算缺"
    r = W["client"].post("/api/duty-roles", json=dict(body, reason="需要這個職務"), headers=W["sa"])
    assert r.status_code == 201, r.text
    ch = _changes(target_type="role")[0]
    assert ch["highSensitivity"] is True and key in ch["added"] and ch["reason"] == "需要這個職務"


def test_non_sensitive_changes_need_no_reason_and_flag_is_server_computed(W):
    c = W["client"]
    r = c.post("/api/duty-roles", json={"key": "plain", "name": "一般", "permissions": ["dashboard", "equipment"], "highSensitivity": True}, headers=W["sa"])
    assert r.status_code == 201, r.text
    ch = _changes(target_type="role")[0]
    assert ch["highSensitivity"] is False and ch["reason"] == "", "前端傳的旗標被忽略"
    uid = W["ids"]["dr_eng"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201       # 一般角色綁定：免原因
    assert _post(W, "/subtracts", {"userId": uid, "key": "inventory"}).status_code == 201                         # 一般鍵扣項：免原因
    assert r.status_code == 201


def test_sensitive_bind_and_subtract_and_role_edit_need_reason(W):
    uid = W["ids"]["dr_eng"]
    # 角色含高敏感鍵：綁定要原因
    c = W["client"]
    assert c.post("/api/duty-roles", json={"key": "pay", "name": "薪資", "permissions": ["payslip"], "reason": "建立薪資角色"}, headers=W["sa"]).status_code == 201
    rid = [r for r in DR.list_roles(db.get_db()) if r["key"] == "pay"][0]["id"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": rid}).status_code == 400
    assert _post(W, "/bindings", {"userId": uid, "roleId": rid, "reason": "兼任薪資"}).status_code == 201
    assert _post(W, "/bindings/remove", {"userId": uid, "roleId": rid}).status_code == 400, "解除含高敏感鍵的角色也要原因"
    assert _post(W, "/bindings/remove", {"userId": uid, "roleId": rid, "reason": "不再兼任"}).status_code == 200
    # 扣高敏感鍵（settings）要原因
    assert _post(W, "/bindings", {"userId": W["ids"]["dr_adm"], "roleId": W["roles"]["sysadmin"], "reason": "系統管理"}).status_code == 201
    assert _post(W, "/subtracts", {"userId": W["ids"]["dr_adm"], "key": "settings"}).status_code == 400
    assert _post(W, "/subtracts", {"userId": W["ids"]["dr_adm"], "key": "settings", "reason": "暫不給設定"}).status_code == 201
    assert _post(W, "/subtracts/remove", {"userId": W["ids"]["dr_adm"], "key": "settings"}).status_code == 400
    # 角色加／減高敏感鍵要原因；加一般鍵不用
    r = c.put("/api/duty-roles/%d" % rid, headers=W["sa"], json={"permissions": ["payslip", "audit_log"]})
    assert r.status_code == 400
    r = c.put("/api/duty-roles/%d" % rid, headers=W["sa"], json={"permissions": ["payslip", "equipment"]})
    assert r.status_code == 200, r.text


def test_reason_too_long_is_refused(W):
    r = W["client"].post("/api/duty-roles", json={"key": "x1", "name": "x", "permissions": ["settings"], "reason": "長" * 201}, headers=W["sa"])
    assert r.status_code == 400


# ── 紀錄 ────────────────────────────────────────────────────────────────

def test_each_action_writes_one_change_with_effective_diff(W):
    uid = W["ids"]["dr_eng"]
    _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]})
    _post(W, "/subtracts", {"userId": uid, "key": "inventory"})
    _post(W, "/subtracts/remove", {"userId": uid, "key": "inventory"})
    _post(W, "/bindings/remove", {"userId": uid, "roleId": W["roles"]["procurement"]})
    rows = list(reversed(_changes(target_type="user", target_id=uid)))
    assert [r["kind"] for r in rows] == ["bind", "subtract", "unsubtract", "unbind"]
    assert {"procurement", "inventory", "equipment", "work_log", "daily_task"} == set(rows[0]["added"]) and rows[0]["removed"] == []
    assert rows[1]["removed"] == ["inventory"] and rows[1]["added"] == []
    assert rows[2]["added"] == ["inventory"]
    assert {"procurement", "inventory", "equipment", "work_log", "daily_task"} == set(rows[3]["removed"]) and rows[3]["added"] == []
    assert all(r["actor"] for r in rows)


def test_permission_changes_is_append_only_at_the_database_layer(W):
    _post(W, "/bindings", {"userId": W["ids"]["dr_eng"], "roleId": W["roles"]["procurement"]})
    conn = db.get_db()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="只增不改"):
            conn.execute("UPDATE permission_changes SET reason='竄改'")
        with pytest.raises(sqlite3.DatabaseError, match="只增不刪"):
            conn.execute("DELETE FROM permission_changes")
    finally:
        conn.close()


def test_no_update_or_delete_route_for_changes_and_roles():
    from routers import duty_roles as router_mod
    seen = [(r.path, sorted(r.methods)) for r in router_mod.router.routes if getattr(r, "path", "").startswith("/api/duty-roles")]
    assert seen, "路由沒登記"
    for path, methods in seen:
        if path.endswith("/changes"):
            assert methods == ["GET"], (path, methods)
        assert "DELETE" not in methods, (path, methods)


def test_demo_reset_can_clear_the_append_only_table_and_keeps_the_trigger():
    import inspect
    src = inspect.getsource(db.reset_demo_db)
    assert "permission_changes_no_update" in src and "permission_changes_no_delete" in src
    assert {"duty_roles", "user_duty_roles", "user_perm_subtracts", "permission_changes"} <= db.DEMO_CLEARED_TABLES


# ── 授權與護欄 ──────────────────────────────────────────────────────────

def test_only_superadmin_can_use_the_api(W):
    c = W["client"]
    for who in ("adm", "eng"):
        h = W[who]
        assert c.get("/api/duty-roles", headers=h).status_code == 403
        assert c.get("/api/duty-roles/users", headers=h).status_code == 403
        assert c.get("/api/duty-roles/changes", headers=h).status_code == 403
        assert c.post("/api/duty-roles", json={"key": "k", "name": "n", "permissions": []}, headers=h).status_code == 403
        assert c.put("/api/duty-roles/1", json={"name": "n"}, headers=h).status_code == 403
        for p in ("/bindings", "/bindings/remove", "/subtracts", "/subtracts/remove"):
            assert c.post("/api/duty-roles" + p, json={"userId": 1, "roleId": 1, "key": "x"}, headers=h).status_code == 403, p
    assert c.get("/api/duty-roles").status_code == 401
    data = c.get("/api/duty-roles", headers=W["sa"]).json()
    assert len(data["roles"]) >= 8 and set(data["highSensitiveKeys"]) == set(DR.HIGH_SENSITIVITY_KEYS)
    users = c.get("/api/duty-roles/users", headers=W["sa"]).json()["users"]
    assert {"dr_sa", "dr_adm", "dr_eng"} <= {u["username"] for u in users}


def test_non_superadmin_actor_cannot_change_self_or_grant_keys_they_lack(W):
    conn = db.get_db()
    try:
        actor = {"id": W["ids"]["dr_adm"], "username": "dr_adm", "display_name": "", "role": "admin", "modules": json.dumps(["dashboard"])}
        with pytest.raises(DR.DutyError) as e:
            DR.bind_role(conn, actor, W["ids"]["dr_adm"], W["roles"]["procurement"])
        assert e.value.status == 403
        with pytest.raises(DR.DutyError) as e2:
            DR.bind_role(conn, actor, W["ids"]["dr_eng"], W["roles"]["procurement"])
        assert e2.value.status == 403 and "沒有這些權限" in str(e2.value), "Q6 a：不能授予自己沒有的鍵"
    finally:
        conn.close()


def test_unknown_keys_and_missing_targets_are_rejected(W):
    c = W["client"]
    assert c.post("/api/duty-roles", json={"key": "bad", "name": "壞", "permissions": ["no_such_key"]}, headers=W["sa"]).status_code == 400
    assert _post(W, "/bindings", {"userId": 99999, "roleId": W["roles"]["viewer"]}).status_code == 404
    assert _post(W, "/bindings", {"userId": W["ids"]["dr_eng"], "roleId": 99999}).status_code == 404
    assert _post(W, "/subtracts", {"userId": W["ids"]["dr_eng"], "key": "no_such_key"}).status_code == 400
    assert _post(W, "/bindings", {"userId": "x", "roleId": 1}).status_code == 400


def test_menu_entry_is_superadmin_only():
    from core import menu as core_menu
    items = [i for i in core_menu.load_l1() if i.get("href") == "duty-roles.html"] if isinstance(core_menu.load_l1(), list) else []
    if not items:
        items = [i for i in core_menu.load_l1().get("items", []) if i.get("href") == "duty-roles.html"]
    assert items and items[0]["perm"] == "superadmin"


def test_high_sensitivity_list_is_the_ruled_one_without_reports():
    assert set(DR.HIGH_SENSITIVITY_KEYS) == {"financial_view", "finance", "cashier", "settings", "audit_log", "module_versions", "payslip"}
    assert "reports" not in DR.HIGH_SENSITIVITY_KEYS


def test_page_exists_calls_only_real_endpoints_and_states_the_partial_effect_warning():
    import re
    from routers import duty_roles as router_mod
    from core import source_tree
    page = source_tree.page_file("duty-roles.html").read_text(encoding="utf-8")
    real = {r.path for r in router_mod.router.routes}
    called = set(re.findall(r"'(/api/duty-roles[^']*)'", page))
    assert called, "頁面沒有呼叫任何職責角色 API"
    for c in called:
        base = re.sub(r"/\d+$", "", c).rstrip("/")
        assert any(base == r or base == re.sub(r"/\{[^}]+\}$", "", r) for r in real), "頁面呼叫不存在的端點：" + c
    assert "部分生效" in page and "財務三鍵" in page and "至少 4 個不同的字" in page
    assert "超級管理員本身不受角色或扣項影響" in page


# ── 稽核補強（hichan-cf）：(a) 逐字相同要抓得到重新序列化 (b) 登入回應路徑 (c) 原因不得敷衍 ──────────────

ODD_RAW = ['["dashboard","case_manage"]', '[ "dashboard" ,   "case_manage" ]', '["case_manage", "dashboard"]', "[]", '[\n  "dashboard"\n]']


@pytest.mark.parametrize("raw", ODD_RAW)
def test_require_user_returns_the_stored_modules_string_byte_for_byte_even_for_odd_spacing(client, make_user, raw):
    """重新序列化（json.dumps）會改掉空白 ⇒ 沒有綁定／扣項的人必須原字串回傳。"""
    make_user(username="odd_u", role="admin", modules=["dashboard"], legacy_finance_flag=False)
    conn = db.get_db()
    conn.execute("UPDATE users SET modules=? WHERE username='odd_u'", (raw,))
    conn.commit()
    conn.close()
    tok = _hdr(client, "odd_u")["Authorization"]
    assert A._require_user(tok)["modules"] == raw


def test_login_and_me_and_issue_session_responses_include_role_keys_for_a_bound_user(W):
    uid, c = W["ids"]["dr_eng"], W["client"]
    assert _post(W, "/bindings", {"userId": uid, "roleId": W["roles"]["procurement"]}).status_code == 201
    r = c.post("/api/auth/login", json={"username": "dr_eng", "password": "Test-Pass-123"})
    assert r.status_code == 200 and "procurement" in r.json()["modules"], "登入回應的 modules 要含角色授予的鍵"
    assert "procurement" in c.get("/api/auth/me", headers={"Authorization": "Bearer " + r.json()["token"]}).json()["modules"]
    from routers import auth as auth_router
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id, username, display_name, role, modules, COALESCE(must_change_password,0) AS must_change_password,"
                           " COALESCE(totp_enabled,0) AS totp_enabled FROM users WHERE id=?", (uid,)).fetchone()
        out = auth_router._issue_session(conn, row, False)          # TOTP／通行金鑰／QR 登入共用的出口
    finally:
        conn.close()
    assert "procurement" in out["modules"]


@pytest.mark.parametrize("bad", ["。。。。", "....", "aaaa", "好好好好", "1111", "abc", "a b a b", "，，，，，，", "!!!???"])
def test_trivial_reasons_are_refused_for_sensitive_changes(W, bad):
    r = W["client"].post("/api/duty-roles", json={"key": "triv", "name": "敷衍", "permissions": ["settings"], "reason": bad}, headers=W["sa"])
    assert r.status_code == 400 and "原因" in r.text, bad


@pytest.mark.parametrize("ok", ["abcd", "兼任薪資", "需要這個職務", "Q4 audit", "老闆口頭同意"])
def test_reasonable_reasons_are_accepted(W, ok):
    r = W["client"].post("/api/duty-roles", json={"key": "okr", "name": "正常", "permissions": ["settings"], "reason": ok}, headers=W["sa"])
    assert r.status_code == 201, (ok, r.text)


def test_self_change_guard_unit_level(W):
    """路由層只有 superadmin 能進，這道護欄平常走不到 ⇒ 直接打服務層驗（未來放寬管理者時才會生效）。"""
    conn = db.get_db()
    try:
        me = {"id": W["ids"]["dr_adm"], "username": "dr_adm", "display_name": "", "role": "admin", "modules": json.dumps(["dashboard", "procurement"])}
        for fn, args in ((DR.bind_role, (me["id"], W["roles"]["viewer"])), (DR.set_subtract, (me["id"], "inventory"))):
            with pytest.raises(DR.DutyError) as e:
                fn(conn, me, *args)
            assert e.value.status == 403 and "自己" in str(e.value)
    finally:
        conn.close()
