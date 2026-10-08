# -*- coding: utf-8 -*-
"""R2 第 2 步（docs/platform/R2-STEPS-2-4-DESIGN.md §2；使用者裁示 Q1–Q3）：
2c 舊 PUT 勾到被扣的鍵 ⇒ 400（旗標可退場）、2d 唯讀報表讀生效權限（--raw 舊口徑）、2e/8a audit_id 填值＋禁止 REPLACE 的靜態掃描、2a 預覽＝真實生效路徑。
每一題都有突變檢查（拿掉對應的程式，題目必須紅）。"""
import itertools
import json
import os
import re
import sys
from pathlib import Path

import pytest

import db
from helpers import auth as A
from helpers import duty_roles as DR

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tools"))


def _hdr(client, name, pw="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _free_keys(n):
    ks = sorted(k for k in DR.known_keys() if k not in DR.FINANCE_KEYS and k not in DR.HIGH_SENSITIVITY_KEYS)
    assert len(ks) >= n
    return ks[:n]


@pytest.fixture
def W(client, make_user):
    make_user(username="r2s2_sa", role="superadmin")
    make_user(username="r2s2_adm", role="admin", modules=["dashboard"], legacy_finance_flag=False)
    make_user(username="r2s2_eng", role="engineer", modules=["dashboard"])
    conn = db.get_db()
    ids = {n: conn.execute("SELECT id FROM users WHERE username=?", (n,)).fetchone()[0] for n in ("r2s2_sa", "r2s2_adm", "r2s2_eng")}
    sa = dict(conn.execute("SELECT * FROM users WHERE username='r2s2_sa'").fetchone())
    roles = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM duty_roles")}
    conn.close()
    return {"sa": _hdr(client, "r2s2_sa"), "ids": ids, "roles": roles, "client": client, "actor": sa}


def _raw(uid):
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT modules FROM users WHERE id=?", (uid,)).fetchone()[0])
    finally:
        conn.close()


def _subtract(W, uid, key):
    conn = db.get_db()
    try:
        DR.set_subtract(conn, W["actor"], uid, key, "")
    finally:
        conn.close()


def _put(W, uid, modules):
    return W["client"].put("/api/users/%d" % uid, json={"modules": modules}, headers=W["sa"])


def _set_flag(value):
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("users_put_reject_subtracted", json.dumps(value), "2026-10-08T00:00:00"))
        conn.commit()
    finally:
        conn.close()


# ── 2c ───────────────────────────────────────────────────────────────────────────────────────────
def test_put_with_a_subtracted_key_is_rejected_and_nothing_changes(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    uid = W["ids"]["r2s2_eng"]
    k1, k2 = _free_keys(2)
    assert _put(W, uid, ["dashboard", k1]).status_code == 200
    _subtract(W, uid, k2)
    before = _raw(uid)
    r = _put(W, uid, ["dashboard", k1, k2])
    assert r.status_code == 400 and k2 in r.text and "扣項" in r.text, r.text
    assert _raw(uid) == before, "被擋 ⇒ users.modules 位元組不變"
    conn = db.get_db()
    try:
        row = conn.execute("SELECT detail FROM audit_log WHERE action='user.put_rejected_subtract' ORDER BY id DESC").fetchone()
    finally:
        conn.close()
    assert row and k2 in json.loads(row[0])["keys"], "拒絕要留稽核（鍵、對象）"


def test_put_without_conflict_still_works_and_other_fields_pass(W):
    uid = W["ids"]["r2s2_eng"]
    k1, k2 = _free_keys(2)
    _subtract(W, uid, k2)
    assert _put(W, uid, ["dashboard", k1]).status_code == 200 and _raw(uid) == ["dashboard", k1]
    r = W["client"].put("/api/users/%d" % uid, json={"display_name": "新名字"}, headers=W["sa"])        # 不帶 modules ⇒ 不檢查
    assert r.status_code == 200


@pytest.mark.parametrize("off", [0, "0", False, "off"])
def test_flag_off_restores_the_old_behaviour(W, off):
    uid = W["ids"]["r2s2_eng"]
    k1, k2 = _free_keys(2)
    _subtract(W, uid, k2)
    _set_flag(off)
    assert _put(W, uid, ["dashboard", k1, k2]).status_code == 200, "旗標關 ⇒ 舊行為（靜默勝出）"
    assert k2 in _raw(uid)


def test_flag_default_is_on_and_users_without_subtracts_are_unaffected(W):
    uid = W["ids"]["r2s2_adm"]
    k1, k2 = _free_keys(2)
    assert _put(W, uid, ["dashboard", k1, k2]).status_code == 200


# ── 預覽＝真實生效路徑（2a）────────────────────────────────────────────────────────────────────
def test_preview_equals_the_real_effective_modules_for_every_combination(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    conn = db.get_db()
    try:
        role_ids = [W["roles"][k] for k in sorted(W["roles"])[:3]]
        free = _free_keys(3)
        uid = W["ids"]["r2s2_eng"]
        checked = 0
        for role in ("admin", "engineer", "finance", "viewer"):
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
            for raw in ([], ["dashboard"], ["dashboard", free[0]]):
                conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(raw), uid))
                for n in range(0, 4):
                    for bound in itertools.combinations(role_ids, n):
                        for subs in ([], [free[1]], [free[1], free[2]], [free[0]]):
                            conn.execute("DELETE FROM user_duty_roles WHERE user_id=?", (uid,))
                            conn.execute("DELETE FROM user_perm_subtracts WHERE user_id=?", (uid,))
                            for rid in bound:
                                conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)", (uid, rid, 1, "t", ""))
                            applied = [s for s in subs if s not in raw]                  # 真實路徑不允許「同時勾選又扣」（set_subtract 拒絕），預覽也要忽略
                            for s in applied:
                                conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)", (uid, s, 1, "t", ""))
                            real = A.effective_modules(role, json.dumps(raw), user_id=uid, conn=conn)
                            prev = DR.preview_whatif(conn, uid, raw, list(bound), subs, role=role)
                            assert prev["effective"] == real, (role, raw, bound, subs, prev, real)
                            checked += 1
        assert checked > 100
    finally:
        conn.rollback()
        conn.close()


def test_preview_endpoint_is_read_only_and_superadmin_only(W, make_user):
    uid = W["ids"]["r2s2_eng"]
    body = {"userId": uid, "modules": ["dashboard"], "roleIds": [W["roles"]["procurement"]], "subtracts": []}
    r = W["client"].post("/api/duty-roles/preview", json=body, headers=W["sa"])
    assert r.status_code == 200 and "procurement" in r.json()["effective"], r.text
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM user_duty_roles WHERE user_id=?", (uid,)).fetchone()[0] == 0, "預覽不寫任何東西"
    finally:
        conn.close()
    assert _raw(uid) == ["dashboard"]
    h = _hdr(W["client"], "r2s2_adm")
    assert W["client"].post("/api/duty-roles/preview", json=body, headers=h).status_code == 403


def test_superadmin_invariant_roles_and_subtracts_still_refused(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    sid = W["ids"]["r2s2_sa"]
    r = W["client"].post("/api/duty-roles/bindings", json={"userId": sid, "roleId": W["roles"]["procurement"]}, headers=W["sa"])
    assert r.status_code == 400, r.text
    r = W["client"].post("/api/duty-roles/subtracts", json={"userId": sid, "key": _free_keys(1)[0]}, headers=W["sa"])
    assert r.status_code == 400, r.text
    prev = DR.preview_whatif(db.get_db(), sid, ["dashboard"], [W["roles"]["procurement"]], _free_keys(1))
    assert "procurement" not in prev["effective"] or "procurement" in A.effective_modules("superadmin", ["dashboard"]), "superadmin 預覽不套角色／扣項"


# ── 8a：audit_id 填值，且每個動作只有一筆 audit_log ─────────────────────────────────────────────
def test_every_permission_change_links_to_exactly_one_audit_log_row(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    c, uid = W["client"], W["ids"]["r2s2_eng"]
    rid = W["roles"]["procurement"]
    k = _free_keys(2)[1]
    steps = [("/bindings", {"userId": uid, "roleId": rid}, "duty_roles.bind"),
             ("/bindings/remove", {"userId": uid, "roleId": rid}, "duty_roles.unbind"),
             ("/subtracts", {"userId": uid, "key": k}, "duty_roles.subtract"),
             ("/subtracts/remove", {"userId": uid, "key": k}, "duty_roles.unsubtract")]
    for path, body, _action in steps:
        assert c.post("/api/duty-roles" + path, json=body, headers=W["sa"]).status_code in (200, 201), path
    r = c.post("/api/duty-roles", json={"key": "r2s2_role", "name": "第二步測試角色", "description": "", "permissions": [k], "reason": ""}, headers=W["sa"])
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert c.put("/api/duty-roles/%d" % new_id, json={"permissions": [k, _free_keys(1)[0]]}, headers=W["sa"]).status_code == 200
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT id, kind, audit_id FROM permission_changes ORDER BY id").fetchall()
        assert rows and all(r["audit_id"] for r in rows), [dict(r) for r in rows]
        for r in rows:
            a = conn.execute("SELECT action FROM audit_log WHERE id=?", (r["audit_id"],)).fetchone()
            assert a and a[0].startswith("duty_roles."), (dict(r), a)
        # 沒有重複：每個 audit_id 只被一筆變更引用；duty_roles.* 的 audit_log 列數＝變更數
        assert len({r["audit_id"] for r in rows}) == len(rows)
        n_audit = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'duty_roles.%'").fetchone()[0]
        assert n_audit == len(rows), (n_audit, len(rows))
    finally:
        conn.close()


def test_noop_role_update_still_leaves_one_audit_row_and_no_permission_change(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    c = W["client"]
    r = c.post("/api/duty-roles", json={"key": "r2s2_noop", "name": "不變", "description": "", "permissions": [_free_keys(1)[0]], "reason": ""}, headers=W["sa"])
    rid = r.json()["id"]
    conn = db.get_db()
    before = (conn.execute("SELECT COUNT(*) FROM permission_changes").fetchone()[0], conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='duty_roles.role_update'").fetchone()[0])
    conn.close()
    assert c.put("/api/duty-roles/%d" % rid, json={"name": "不變"}, headers=W["sa"]).status_code == 200
    conn = db.get_db()
    after = (conn.execute("SELECT COUNT(*) FROM permission_changes").fetchone()[0], conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='duty_roles.role_update'").fetchone()[0])
    conn.close()
    assert after == (before[0], before[1] + 1), "與舊路由一致：沒有實質變更也留一筆 audit_log，但不寫 permission_changes"


# ── 2e：permission_changes 不得用 REPLACE 寫入（靜態掃描；含 backend/tools、tools/）──────────────────────
_REPLACE = re.compile(r"(INSERT\s+OR\s+REPLACE\s+INTO|REPLACE\s+INTO)\s+permission_changes", re.I)


def replace_violations(text: str) -> list:
    """把字串拼接也算進去：連續的字串字面值先黏起來再比對（`"INSERT OR REPLACE " "INTO permission_changes"`）。"""
    glued = re.sub(r"[\"']\s*\n?\s*[\"']", "", text)
    return _REPLACE.findall(glued)


def test_replace_scan_has_a_positive_control():
    assert replace_violations('conn.execute("INSERT OR REPLACE INTO permission_changes (ts) VALUES (?)")')
    assert replace_violations('conn.execute("REPLACE INTO permission_changes (ts) VALUES (?)")')
    assert replace_violations('conn.execute("INSERT OR REPLACE " "INTO permission_changes (ts) VALUES (?)")'), "字串拼接也要抓到"
    assert not replace_violations('conn.execute("INSERT INTO permission_changes (ts) VALUES (?)")')


def test_no_source_file_writes_permission_changes_with_replace():
    roots = [BACKEND, BACKEND.parent / "tools"]
    bad = []
    for root in roots:
        for p in root.rglob("*.py"):
            if "tests" in p.parts or ".venv" in "".join(p.parts) or "node_modules" in p.parts:
                continue
            try:
                t = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if "permission_changes" in t and replace_violations(t):
                bad.append(str(p))
    assert not bad, "permission_changes 只增不改：不得 REPLACE 寫入 ⇒ %s" % bad


# ── 2d：唯讀報表讀生效權限，--raw 舊口徑 ────────────────────────────────────────────────────────
def test_audit_tool_reads_effective_permissions_by_default_and_raw_on_request(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    import audit_account_permissions as T
    aid = W["ids"]["r2s2_adm"]
    key = _free_keys(3)[2]
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO duty_roles (key, name, description, permissions, is_system, active, version, created_at, updated_at) VALUES ('r2s2_t','工具測試','',?,0,1,1,'t','t')",
                     (json.dumps([key]),))
        rid = conn.execute("SELECT id FROM duty_roles WHERE key='r2s2_t'").fetchone()[0]
        conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)", (aid, rid, 1, "t", ""))
        conn.commit()
    finally:
        conn.close()
    eff = {r["username"]: r for r in T._audit()}["r2s2_adm"]
    raw = {r["username"]: r for r in T._audit(raw=True)}["r2s2_adm"]
    assert key in eff["modules"] and eff["basis"] == "effective"
    assert key not in raw["modules"] and raw["basis"] == "raw"


def test_finance_report_applies_duty_roles_but_not_the_finance_rule(W, client):   # client 明列（W 夾具已含；b5 預檢 A8 的靜態檢查不追夾具鏈）
    import finance_role_impact_report as T
    eid = W["ids"]["r2s2_eng"]
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO duty_roles (key, name, description, permissions, is_system, active, version, created_at, updated_at) VALUES ('r2s2_f','財務工具測試','',?,0,1,1,'t','t')",
                     (json.dumps(["cashier"]),))
        rid = conn.execute("SELECT id FROM duty_roles WHERE key='r2s2_f'").fetchone()[0]
        conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)", (eid, rid, 1, "t", ""))
        conn.commit()
        eff = T.build_report(conn)
        raw = T.build_report(conn, raw=True)
    finally:
        conn.close()
    lose_eff = {i["username"]: i for i in eff["loseAccess"]}
    lose_raw = {i["username"]: i for i in raw["loseAccess"]}
    assert "cashier" in lose_eff["r2s2_eng"]["heldFlags"] and eff["basis"] == "duty_roles_applied"
    assert "r2s2_eng" not in lose_raw and raw["basis"] == "raw"
