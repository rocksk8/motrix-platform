# -*- coding: utf-8 -*-
"""職責角色「權限矩陣」批次（T86；`helpers/duty_role_matrix.py`、`POST /api/duty-roles/matrix/{preview,apply,undo}`）。

守的規則：
  - 預覽唯讀、算出每個角色實際多／少什麼與影響幾位成員；套用一定要帶預覽的 `planHash`（沒帶 400、過期 409）；
  - 原因規則與其他職責角色動作同一個檢查點：高敏感鍵授予或取消都要原因（≥4 個不同字）、寫 `permission_changes`＋同交易 `audit_log`、版本 +1；
  - 沒有實質變更的角色不寫；不認得的鍵 400；同鍵同時授予與取消 400；非最高管理者 403；
  - 整批同一個交易（中途例外 ⇒ 全部不寫）；
  - 復原這一批＝逐角色 compare-and-set（被其他人改過的角色只拒絕那一個）；成員的實際權限跟著角色走。
"""
import json

import pytest

import db
from helpers import auth as A
from helpers import duty_roles as dr

PREVIEW, APPLY, UNDO = "/api/duty-roles/matrix/preview", "/api/duty-roles/matrix/apply", "/api/duty-roles/matrix/undo"


def _login(client, username, password="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def W(client, make_user):
    make_user(username="dm_sa", role="superadmin")
    make_user(username="dm_adm", role="admin", modules=["dashboard"], legacy_finance_flag=False)
    make_user(username="dm_eng", role="engineer", modules=["dashboard"])
    sa = _login(client, "dm_sa")
    ids = {}
    for key, perms in (("dm_a", ["dashboard"]), ("dm_b", ["dashboard", "quotation"])):
        r = client.post("/api/duty-roles", json={"key": key, "name": "矩陣測試" + key[-1].upper(), "description": "", "permissions": perms, "reason": ""}, headers=sa)
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='dm_eng'").fetchone()[0]
    finally:
        conn.close()
    assert client.post("/api/duty-roles/bindings", json={"userId": uid, "roleId": ids["dm_a"], "reason": ""}, headers=sa).status_code == 201
    return {"c": client, "sa": sa, "adm": _login(client, "dm_adm"), "eng": _login(client, "dm_eng"), "ids": ids, "uid": uid}


def _perms(rid):
    conn = db.get_db()
    try:
        r = conn.execute("SELECT permissions, version FROM duty_roles WHERE id=?", (rid,)).fetchone()
        return json.loads(r["permissions"]), r["version"]
    finally:
        conn.close()


def _count(table, where="1=1", args=()):
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM %s WHERE %s" % (table, where), args).fetchone()[0]
    finally:
        conn.close()


def _chg(rid, grant=(), revoke=()):
    return {"roleId": rid, "grant": list(grant), "revoke": list(revoke)}


def _plan(W, changes, who="sa"):
    r = W["c"].post(PREVIEW, json={"changes": changes}, headers=W[who])
    assert r.status_code == 200, r.text
    return r.json()


def _apply(W, changes, plan, reason="", who="sa"):
    return W["c"].post(APPLY, json={"changes": changes, "planHash": plan["planHash"], "reason": reason}, headers=W[who])


# ── 預覽 ───────────────────────────────────────────────────────────────

def test_preview_is_read_only_and_reports_members_and_cells(W):
    a = W["ids"]["dm_a"]
    before = (_perms(a), _count("permission_changes"), _count("audit_log"))
    p = _plan(W, [_chg(a, grant=["quotation"], revoke=["dashboard"])])
    assert p["summary"]["changed"] == 1 and p["summary"]["cellsAdded"] == 1 and p["summary"]["cellsRemoved"] == 1
    role = p["roles"][0]
    assert role["status"] == "change" and role["adds"] == ["quotation"] and role["removes"] == ["dashboard"] and role["members"] == 1
    assert p["summary"]["membersAffected"] == 1 and p["needsReason"] is False and p["planHash"]
    assert (_perms(a), _count("permission_changes"), _count("audit_log")) == before


def test_preview_flags_high_sensitive_and_finance_notes(W):
    a = W["ids"]["dm_a"]
    p = _plan(W, [_chg(a, grant=["settings", "finance"])])
    assert p["needsReason"] is True and p["gatedKeys"] == ["finance", "settings"]
    assert p["roles"][0]["financeNote"] == ["finance"] and p["roles"][0]["notes"], "財務三鍵可放進角色，但要提醒持有者不會因此取得財務能力"


def test_preview_skips_missing_role_and_marks_nochange(W):
    a = W["ids"]["dm_a"]
    p = _plan(W, [_chg(a, grant=["dashboard"]), _chg(987654, grant=["quotation"])])
    by = {r["roleId"]: r for r in p["roles"]}
    assert by[a]["status"] == "nochange" and by[987654]["status"] == "skipped" and by[987654]["note"]
    assert p["summary"]["changed"] == 0 and p["summary"]["skipped"] == 1


@pytest.mark.parametrize("body", [
    {}, {"changes": []}, {"changes": "x"}, {"changes": [1]}, {"changes": [{"roleId": True, "grant": ["quotation"]}]},
    {"changes": [{"roleId": "1_0", "grant": []}]}, {"changes": [{"roleId": 1.5, "grant": []}]}, {"changes": [{"roleId": 2 ** 40, "grant": []}]},
    {"changes": [{"roleId": 1, "grant": "quotation"}]}, {"changes": [{"roleId": 1, "grant": [1]}]},
    {"changes": [{"roleId": 1, "grant": ["quotation"], "revoke": ["quotation"]}]},
    {"changes": [{"roleId": 1, "grant": []}, {"roleId": 1, "grant": []}]},
    {"changes": [{"roleId": 1, "grant": []}], "reason": 5}, {"changes": [{"roleId": 1, "grant": []}], "planHash": 7},
])
def test_malformed_requests_are_400_not_500(W, body):
    for path in (PREVIEW, APPLY):
        assert W["c"].post(path, json=body, headers=W["sa"]).status_code in (400, 422), (path, body)


@pytest.mark.parametrize("body", [
    {}, {"changes": []}, {"changes": "x"}, {"changes": [1]}, {"changes": [{"roleId": True}]}, {"changes": [{"roleId": 1, "adds": "x"}]},
    {"changes": [{"roleId": 1, "removes": [3]}]}, {"changes": [{"roleId": 1}], "reason": 5},
])
def test_malformed_undo_requests_are_400_not_500(W, body):
    assert W["c"].post(UNDO, json=body, headers=W["sa"]).status_code in (400, 422), body


def test_unknown_key_to_grant_is_400(W):
    r = W["c"].post(PREVIEW, json={"changes": [_chg(W["ids"]["dm_a"], grant=["no_such_key"])]}, headers=W["sa"])
    assert r.status_code == 400 and "no_such_key" in r.text


def test_only_superadmin(W):
    body = {"changes": [_chg(W["ids"]["dm_a"], grant=["quotation"])]}
    for who in ("adm", "eng"):
        for path in (PREVIEW, APPLY, UNDO):
            assert W["c"].post(path, json=body, headers=W[who]).status_code == 403, (who, path)
    assert W["c"].post(PREVIEW, json=body).status_code in (401, 403)


# ── 套用 ───────────────────────────────────────────────────────────────

def test_apply_requires_plan_hash_and_rejects_stale_hash(W):
    a = W["ids"]["dm_a"]
    ch = [_chg(a, grant=["quotation"])]
    assert W["c"].post(APPLY, json={"changes": ch}, headers=W["sa"]).status_code == 400
    p = _plan(W, ch)
    # 預覽之後有人改了這個角色 ⇒ 版本變了 ⇒ 409，且什麼都沒寫
    assert W["c"].put("/api/duty-roles/%d" % a, json={"permissions": ["dashboard", "quotation", "file_center"], "reason": ""}, headers=W["sa"]).status_code == 200
    snap = (_perms(a), _count("permission_changes"))
    assert _apply(W, ch, p).status_code == 409
    assert (_perms(a), _count("permission_changes")) == snap


def test_apply_ordinary_change_writes_role_record_and_audit_and_members_follow(W):
    a, b = W["ids"]["dm_a"], W["ids"]["dm_b"]
    ch = [_chg(a, grant=["quotation"]), _chg(b, revoke=["quotation"])]
    p = _plan(W, ch)
    n_rec, n_aud = _count("permission_changes"), _count("audit_log", "action='duty_roles.role_update'")
    r = _apply(W, ch, p)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] and sorted(out["applied"]) == sorted([a, b])
    assert "quotation" in _perms(a)[0] and "quotation" not in _perms(b)[0]
    assert _perms(a)[1] == 2 and _perms(b)[1] == 2, "版本 +1"
    assert _count("permission_changes") == n_rec + 2 and _count("audit_log", "action='duty_roles.role_update'") == n_aud + 2
    conn = db.get_db()
    try:
        u = conn.execute("SELECT role, modules FROM users WHERE id=?", (W["uid"],)).fetchone()
        assert "quotation" in A.effective_modules(u["role"], u["modules"], user_id=W["uid"], conn=conn), "綁定這個角色的成員實際權限跟著多了"
    finally:
        conn.close()


def test_nochange_roles_are_not_written(W):
    a = W["ids"]["dm_a"]
    ch = [_chg(a, grant=["dashboard"])]
    p = _plan(W, ch)
    n = _count("permission_changes")
    r = _apply(W, ch, p)
    assert r.status_code == 200 and r.json()["applied"] == [] and _count("permission_changes") == n and _perms(a)[1] == 1


def test_high_sensitive_grant_needs_a_reason(W):
    a = W["ids"]["dm_a"]
    ch = [_chg(a, grant=["settings"])]
    p = _plan(W, ch)
    assert p["needsReason"] is True
    snap = _perms(a)
    for bad in ("", "ab", "aaaa", "。。。。"):
        assert _apply(W, ch, p, reason=bad).status_code == 400, bad
    assert _perms(a) == snap
    r = _apply(W, ch, p, reason="核定新增系統設定權限")
    assert r.status_code == 200 and "settings" in _perms(a)[0]
    conn = db.get_db()
    try:
        row = conn.execute("SELECT high_sensitivity, reason FROM permission_changes WHERE target_type='role' AND target_id=? ORDER BY id DESC LIMIT 1", (a,)).fetchone()
    finally:
        conn.close()
    assert row["high_sensitivity"] == 1 and "核定" in row["reason"]


def test_high_sensitive_revoke_also_needs_a_reason(W):
    a = W["ids"]["dm_a"]
    assert W["c"].put("/api/duty-roles/%d" % a, json={"permissions": ["dashboard", "settings"], "reason": "先給再收回來測試"}, headers=W["sa"]).status_code == 200
    ch = [_chg(a, revoke=["settings"])]
    p = _plan(W, ch)
    assert p["needsReason"] is True and _apply(W, ch, p).status_code == 400
    assert _apply(W, ch, p, reason="收回系統設定權限").status_code == 200 and "settings" not in _perms(a)[0]


def test_whole_batch_is_one_transaction(W, monkeypatch):
    a, b = W["ids"]["dm_a"], W["ids"]["dm_b"]
    ch = [_chg(a, grant=["file_center"]), _chg(b, grant=["file_center"])]
    p = _plan(W, ch)
    real = dr.update_role
    calls = []

    def flaky(conn, actor, role_id, **kw):
        calls.append(role_id)
        if len(calls) == 2:
            raise dr.DutyError("模擬第二個角色寫入失敗")
        return real(conn, actor, role_id, **kw)

    monkeypatch.setattr(dr, "update_role", flaky)
    snap = (_perms(a), _perms(b), _count("permission_changes"), _count("audit_log"))
    assert _apply(W, ch, p).status_code == 400
    assert (_perms(a), _perms(b), _count("permission_changes"), _count("audit_log")) == snap, "第一個角色也不能留下"


def test_legacy_unlisted_key_is_reported_not_fatal(W):
    a, b = W["ids"]["dm_a"], W["ids"]["dm_b"]
    conn = db.get_db()
    try:
        conn.execute("UPDATE duty_roles SET permissions=? WHERE id=?", (json.dumps(["dashboard", "retired_key_x"]), a))
        conn.commit()
    finally:
        conn.close()
    p = _plan(W, [_chg(a, grant=["quotation"]), _chg(b, grant=["file_center"])])
    by = {r["roleId"]: r for r in p["roles"]}
    assert by[a]["status"] == "skipped" and "retired_key_x" in by[a]["note"] and by[b]["status"] == "change"
    p2 = _plan(W, [_chg(a, revoke=["retired_key_x"])])
    assert p2["roles"][0]["status"] == "change", "取消已下架的舊鍵是允許的"


# ── 復原這一批 ─────────────────────────────────────────────────────────

def _undo_body(out, reason=""):
    return {"changes": [{"roleId": r["roleId"], "adds": r["adds"], "removes": r["removes"]} for r in out["roles"] if r["status"] == "change"], "reason": reason}


def test_undo_restores_the_batch(W):
    a, b = W["ids"]["dm_a"], W["ids"]["dm_b"]
    start = (_perms(a)[0], _perms(b)[0])
    ch = [_chg(a, grant=["file_center"]), _chg(b, revoke=["quotation"])]
    out = _apply(W, ch, _plan(W, ch)).json()
    r = W["c"].post(UNDO, json=_undo_body(out), headers=W["sa"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert sorted(j["applied"]) == sorted([a, b]) and j["conflicts"] == []
    assert (sorted(_perms(a)[0]), sorted(_perms(b)[0])) == (sorted(start[0]), sorted(start[1]))


def test_undo_is_per_role_compare_and_set(W):
    a, b = W["ids"]["dm_a"], W["ids"]["dm_b"]
    ch = [_chg(a, grant=["file_center"]), _chg(b, grant=["file_center"])]
    out = _apply(W, ch, _plan(W, ch)).json()
    # 其他人把 a 角色的 file_center 又拿掉了 ⇒ 只有 a 被拒絕，b 照復原
    assert W["c"].put("/api/duty-roles/%d" % a, json={"permissions": ["dashboard"], "reason": ""}, headers=W["sa"]).status_code == 200
    j = W["c"].post(UNDO, json=_undo_body(out), headers=W["sa"]).json()
    assert j["applied"] == [b] and [c["roleId"] for c in j["conflicts"]] == [a] and j["conflicts"][0]["reason"]
    assert "file_center" not in _perms(b)[0]


def test_undo_of_everything_conflicting_changes_nothing(W):
    a = W["ids"]["dm_a"]
    ch = [_chg(a, grant=["file_center"])]
    out = _apply(W, ch, _plan(W, ch)).json()
    assert W["c"].put("/api/duty-roles/%d" % a, json={"permissions": ["dashboard"], "reason": ""}, headers=W["sa"]).status_code == 200
    n = _count("permission_changes")
    j = W["c"].post(UNDO, json=_undo_body(out), headers=W["sa"]).json()
    assert j["applied"] == [] and len(j["conflicts"]) == 1 and _count("permission_changes") == n


def test_undo_of_a_high_sensitive_grant_needs_a_reason(W):
    a = W["ids"]["dm_a"]
    ch = [_chg(a, grant=["settings"])]
    out = _apply(W, ch, _plan(W, ch), reason="核定新增系統設定權限").json()
    assert W["c"].post(UNDO, json=_undo_body(out), headers=W["sa"]).status_code == 400 and "settings" in _perms(a)[0]
    assert W["c"].post(UNDO, json=_undo_body(out, "取消剛才的授予"), headers=W["sa"]).status_code == 200 and "settings" not in _perms(a)[0]


def test_matrix_writes_go_through_update_role_only():
    """守門：矩陣不自帶第二份寫入／原因規則——檔案裡沒有直接寫 duty_roles／permission_changes 的 SQL。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "helpers" / "duty_role_matrix.py").read_text(encoding="utf-8")
    for bad in ("UPDATE duty_roles", "INSERT INTO permission_changes", "INSERT INTO audit_log", "gate_reason(" + "[]"):
        assert bad not in src
    assert "dr.update_role(" in src and "dr.gate_reason(" in src
