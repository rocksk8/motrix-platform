"""`PUT /api/users/{id}` 的高敏感權限檢查點（安全票 fix/user-perm-sensitive-gate，2026-11-13）。

漏洞：以前只有職責角色（`/api/duty-roles`）授予高敏感鍵（`HIGH_SENSITIVITY_KEYS`）要原因、寫 `permission_changes`；
`PUT /api/users/{id}` 的個人勾選可以直接授予／取消同一批鍵，不需原因、不寫 `permission_changes`，稽核只有一般的 `user.update`。

現在：高敏感規則抽成 `helpers.duty_roles.gate_reason`（職責角色各動作與 PUT 共用，之後批次／範本套用也走它）。
  - 授予或取消高敏感鍵 ⇒ 原因必填（≥4 個不同字）；不合格 400，什麼都不寫；
  - 成功 ⇒ `permission_changes`（kind=user_modules）＋同交易 `audit_log`（user.perm_change）；
  - 沒動到高敏感鍵（含「整串送回、高敏感鍵沒變」）⇒ 行為與以前完全相同；
  - 改完仍是最高管理者 ⇒ 他的 modules 不影響生效權限，不算授予。
"""
import json
from pathlib import Path

import pytest

from helpers import duty_roles as dr

BACKEND = Path(__file__).resolve().parent.parent


def _login(client, username, password="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _row(uid):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT role, modules FROM users WHERE id=?", (uid,)).fetchone()
        return r["role"], json.loads(r["modules"] or "[]")
    finally:
        conn.close()


def _changes(uid):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM permission_changes WHERE target_type='user' AND target_id=? ORDER BY id", (uid,)).fetchall()]
    finally:
        conn.close()


def _audit(action, uid):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE action=? AND target_id=? ORDER BY id", (action, str(uid))).fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    make_user("root", role="superadmin", modules=[])
    make_user("staff", role="sales", modules=["dashboard", "sales"])
    return {"h": _login(client, "root"), "uid": _uid("staff")}


# ── 1. 單元：共用檢查點 ───────────────────────────────────────────────
def test_unit_gate_reason_rules():
    assert dr.gate_reason(["sales"], "") == (False, "")                       # 沒動高敏感鍵：原因不用寫
    assert dr.gate_reason([], "隨便") == (False, "隨便")
    assert dr.gate_reason(["cashier"], "接手出納業務") == (True, "接手出納業務")
    for bad in ("", "   ", "接手", "aaaa", "好好好好", "。。。。。。"):         # 缺、太短、重複同一字、純標點
        with pytest.raises(dr.DutyError) as e:
            dr.gate_reason(["payslip"], bad)
        assert e.value.status == 400
    with pytest.raises(dr.DutyError):
        dr.gate_reason(["settings"], "字" * 201)


def test_unit_every_high_sensitivity_key_is_gated_and_the_list_is_unchanged():
    assert dr.HIGH_SENSITIVITY_KEYS == ("financial_view", "finance", "cashier", "settings", "audit_log", "module_versions", "payslip")   # 使用者裁示，不動
    for k in dr.HIGH_SENSITIVITY_KEYS:
        with pytest.raises(dr.DutyError):
            dr.user_modules_gate([], [k], "")
        with pytest.raises(dr.DutyError):
            dr.user_modules_gate([k], [], "")                                  # 取消也要


def test_unit_user_modules_gate_compares_the_diff_only():
    assert dr.user_modules_gate(["cashier", "sales"], ["cashier", "sales", "quotation"], "") == (False, "")     # 高敏感鍵沒變
    assert dr.user_modules_gate(["cashier"], ["cashier"], "") == (False, "")
    assert dr.user_modules_gate([], ["cashier"], "", inert=True) == (False, "")                                # 惰性（仍是超管）


def test_unit_duty_roles_use_the_shared_gate():
    """職責角色各動作不再自帶一份規則：`_require_reason_if_sensitive` 只在 `gate_reason` 裡被呼叫。"""
    src = (BACKEND / "helpers" / "duty_roles.py").read_text(encoding="utf-8")
    assert src.count("_require_reason_if_sensitive(") == 2, "定義一處＋gate_reason 內呼叫一處"
    assert src.count("gate_reason(") >= 7, "create_role／update_role／bind／unbind／set_subtract／unset_subtract＋user_modules_gate"


# ── 2. PUT /api/users/{id} ───────────────────────────────────────────
def test_grant_high_key_without_reason_is_400_and_writes_nothing(client, world):
    uid, h = world["uid"], world["h"]
    before = _row(uid)
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard", "sales", "cashier"]}, headers=h)
    assert r.status_code == 400, r.text
    assert "原因" in r.json()["detail"]
    assert _row(uid) == before, "400 就是什麼都沒寫"
    assert _changes(uid) == [] and _audit("user.update", uid) == [] and _audit("user.perm_change", uid) == []


@pytest.mark.parametrize("bad", ["", "   ", "接手", "aaaa", "。。。。。。"])
def test_reason_too_short_or_trivial_is_400(client, world, bad):
    uid, h = world["uid"], world["h"]
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard", "sales", "payslip"], "reason": bad}, headers=h)
    assert r.status_code == 400, r.text
    assert _row(uid)[1] == ["dashboard", "sales"] and _changes(uid) == []


def test_reason_over_200_chars_is_400(client, world):
    r = client.put("/api/users/%d" % world["uid"], json={"modules": ["settings"], "reason": "字" * 201}, headers=world["h"])
    assert r.status_code == 400


def test_grant_with_reason_succeeds_and_writes_permission_changes_and_audit(client, world):
    uid, h = world["uid"], world["h"]
    r = client.put("/api/users/%d" % uid, json={"display_name": "業務甲", "modules": ["dashboard", "sales", "settings", "audit_log"],
                                                 "reason": "接手系統管理業務"}, headers=h)
    assert r.status_code == 200, r.text
    assert _row(uid)[1] == ["dashboard", "sales", "settings", "audit_log"]
    ch = _changes(uid)
    assert len(ch) == 1
    c = ch[0]
    assert (c["kind"], c["high_sensitivity"], c["reason"]) == ("user_modules", 1, "接手系統管理業務")
    assert c["actor_username"] == "root" and c["target_label"] == "業務甲"
    assert json.loads(c["added"]) == ["audit_log", "settings"] and json.loads(c["removed"]) == []
    assert json.loads(c["before_json"]) == {"modules": ["dashboard", "sales"]}
    assert json.loads(c["after_json"])["modules"] == ["audit_log", "dashboard", "sales", "settings"]
    a = _audit("user.perm_change", uid)
    assert len(a) == 1 and c["audit_id"] == a[0]["id"], "permission_changes.audit_id 指向同交易的 audit_log"
    assert len(_audit("user.update", uid)) == 1, "原本的 user.update 稽核照舊"


def test_revoke_high_key_needs_a_reason_too(client, make_user):
    make_user("root", role="superadmin", modules=[])
    make_user("clerk", role="sales", modules=["dashboard", "payslip"])
    h, uid = _login(client, "root"), _uid("clerk")
    assert client.put("/api/users/%d" % uid, json={"modules": ["dashboard"]}, headers=h).status_code == 400
    assert _row(uid)[1] == ["dashboard", "payslip"]
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard"], "reason": "轉調離開薪資業務"}, headers=h)
    assert r.status_code == 200, r.text
    c = _changes(uid)
    assert len(c) == 1 and json.loads(c[0]["removed"]) == ["payslip"] and json.loads(c[0]["added"]) == []


def test_non_sensitive_change_behaves_as_before(client, world):
    uid, h = world["uid"], world["h"]
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard", "sales", "quotation"]}, headers=h)     # 沒帶 reason、沒動高敏感鍵
    assert r.status_code == 200, r.text
    assert _row(uid)[1] == ["dashboard", "sales", "quotation"]
    assert _changes(uid) == [] and _audit("user.perm_change", uid) == []
    assert len(_audit("user.update", uid)) == 1
    # 帶了原因也不會被當成高敏感變更記錄
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard"], "reason": "整理勾選項目"}, headers=h)
    assert r.status_code == 200 and _changes(uid) == []
    # 不帶 modules（只改其他欄位）完全不經檢查點
    assert client.put("/api/users/%d" % uid, json={"phone": "0912"}, headers=h).status_code == 200


def test_resending_an_unchanged_high_key_needs_no_reason(client, make_user):
    """畫面每次存檔都整串送回 modules：沒動到的高敏感鍵不該要求原因（否則改個電話也被擋）。"""
    make_user("root", role="superadmin", modules=[])
    make_user("fin2", role="sales", modules=["dashboard", "settings"])
    h, uid = _login(client, "root"), _uid("fin2")
    r = client.put("/api/users/%d" % uid, json={"display_name": "乙", "modules": ["dashboard", "settings", "quotation"]}, headers=h)
    assert r.status_code == 200, r.text
    assert _changes(uid) == []


def test_superadmin_target_staying_superadmin_is_inert(client, make_user):
    """最高管理者的 modules 不影響生效權限（全功能）⇒ 不算授予，不要求原因、不寫變更列；行為與以前相同。"""
    make_user("root", role="superadmin", modules=[])
    make_user("root2", role="superadmin", modules=[])
    h, uid = _login(client, "root"), _uid("root2")
    r = client.put("/api/users/%d" % uid, json={"modules": ["settings"]}, headers=h)
    assert r.status_code == 200, r.text
    assert _changes(uid) == []


def test_demoting_a_superadmin_with_stored_high_keys_needs_a_reason(client, make_user):
    """降級那一刻，存著的高敏感鍵才開始生效 ⇒ 同一個請求把 role 改成非超管且 modules 含高敏感鍵 ⇒ 要原因。"""
    make_user("root", role="superadmin", modules=[])
    make_user("root2", role="superadmin", modules=[])
    h, uid = _login(client, "root"), _uid("root2")
    r = client.put("/api/users/%d" % uid, json={"role": "sales", "modules": ["settings"]}, headers=h)
    assert r.status_code == 400, r.text
    assert _row(uid)[0] == "superadmin"
    r = client.put("/api/users/%d" % uid, json={"role": "sales", "modules": ["settings"], "reason": "改任一般業務並保留設定權"}, headers=h)
    assert r.status_code == 200, r.text
    assert len(_changes(uid)) == 1


def test_non_superadmin_still_cannot_call_put(client, make_user):
    make_user("adm", role="admin")
    make_user("tgt", role="sales", modules=[])
    h = _login(client, "adm")
    assert client.put("/api/users/%d" % _uid("tgt"), json={"modules": ["cashier"], "reason": "我想要這個權限"}, headers=h).status_code in (401, 403)
    assert _row(_uid("tgt"))[1] == []


# ── 3. 職責角色同一條規則（行為不變）──────────────────────────────────
def test_duty_roles_path_still_requires_the_reason(client, world):
    h = world["h"]
    r = client.post("/api/duty-roles", json={"key": "gate_t_role", "name": "閘門測試", "description": "", "permissions": ["cashier"], "reason": ""}, headers=h)
    assert r.status_code == 400 and "原因" in r.json()["detail"]
    r = client.post("/api/duty-roles", json={"key": "gate_t_role", "name": "閘門測試", "description": "", "permissions": ["cashier"], "reason": "新增出納職責"}, headers=h)
    assert r.status_code == 201, r.text


# ── 4. POST /api/users（建立帳號時帶 modules）同一條規則 ───────────────────
def _create(client, h, username, modules, **extra):
    body = {"username": username, "password": "Zx9-strong-Pass!", "display_name": "新人" + username, "role": "sales", "modules": modules}
    body.update(extra)
    return client.post("/api/users", json=body, headers=h)


def test_create_with_high_key_without_reason_is_400_and_creates_nothing(client, world):
    h = world["h"]
    r = _create(client, h, "newbie", ["dashboard", "cashier"])
    assert r.status_code == 400 and "原因" in r.json()["detail"], r.text
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE username='newbie'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM permission_changes").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("bad", ["", "接手", "aaaa", "。。。。"])
def test_create_reason_too_short_or_trivial_is_400(client, world, bad):
    assert _create(client, world["h"], "newbie2", ["payslip"], reason=bad).status_code == 400
    assert _create(client, world["h"], "newbie2", ["payslip"], reason="字" * 201).status_code == 400


def test_create_with_reason_writes_permission_changes_and_audit(client, world):
    h = world["h"]
    r = _create(client, h, "newbie3", ["dashboard", "settings", "payslip"], reason="新進人事兼系統管理")
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    ch = _changes(uid)
    assert len(ch) == 1
    c = ch[0]
    assert (c["kind"], c["high_sensitivity"], c["reason"], c["actor_username"]) == ("user_modules", 1, "新進人事兼系統管理", "root")
    assert json.loads(c["added"]) == ["dashboard", "payslip", "settings"] and json.loads(c["removed"]) == []
    assert json.loads(c["before_json"]) == {"modules": []}
    a = _audit("user.perm_change", uid)
    assert len(a) == 1 and c["audit_id"] == a[0]["id"]
    assert len(_audit("user.create", "newbie3")) == 1, "原有的 user.create 稽核照舊"


def test_create_without_high_keys_is_unchanged(client, world):
    h = world["h"]
    r = _create(client, h, "newbie4", ["dashboard", "quotation"])            # 沒帶 reason 也沒關係
    assert r.status_code in (200, 201), r.text
    assert _changes(r.json()["id"]) == []
    r = _create(client, h, "newbie5", [])
    assert r.status_code in (200, 201) and _changes(r.json()["id"]) == []
    r = _create(client, h, "newbie6", ["dashboard"], reason="多餘的原因也不記")
    assert r.status_code in (200, 201) and _changes(r.json()["id"]) == []


def test_create_a_superadmin_is_inert(client, world):
    r = _create(client, world["h"], "root3", ["settings"], role="superadmin")
    assert r.status_code in (200, 201), r.text
    assert _changes(r.json()["id"]) == []


def test_duplicate_username_with_reason_leaves_no_change_row(client, world):
    h = world["h"]
    assert _create(client, h, "dupe", ["cashier"], reason="第一次建立帳號").status_code in (200, 201)
    n = len(_changes(_uid("dupe")))
    assert _create(client, h, "dupe", ["cashier"], reason="第二次重複建立").status_code == 409
    assert len(_changes(_uid("dupe"))) == n == 1
