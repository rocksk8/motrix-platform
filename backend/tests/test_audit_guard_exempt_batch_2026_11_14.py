# -*- coding: utf-8 -*-
"""稽核守門 EXEMPT 的實證（T84，h9）：四支批次端點的稽核不在端點函式裡直接呼叫 `_audit`，而是在引擎／helper 的同一個交易裡寫；
守門（test_write_endpoints_are_audited）是語法檢查看不到，所以 EXEMPT 只在「呼叫一次 → audit_log 真的多一筆」被證明時才成立。

  POST /api/settings-center/batch            → helpers.settings_registry.publish → config_ledger.record（同交易寫 audit_log）
  POST /api/users/permissions/batch          → helpers.user_perm_batch.apply → duty_roles.record_user_modules_change → _record → _write_audit（`user.perm_change`）
  POST /api/users/permissions/batch/undo     → helpers.user_perm_batch.undo → 同上
  POST /api/users/permissions/batch/preview  → helpers.user_perm_batch.preview：唯讀，呼叫前後 audit_log／permission_changes 列數不變（正對照：套用那題有 +1）
"""
import json


def _login(client, username, password="Test-Pass-123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _max_audit_id():
    return _rows("SELECT COALESCE(MAX(id),0) AS m FROM audit_log")[0]["m"]


def _new_audits(since_id):
    return _rows("SELECT id, username, action, target_type, target_id FROM audit_log WHERE id>? ORDER BY id", (since_id,))


def _count(table):
    return _rows("SELECT COUNT(*) AS n FROM %s" % table)[0]["n"]


def _uid(username):
    return _rows("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def test_settings_center_batch_writes_an_audit_row_for_the_group_it_changed(client, make_user):
    make_user("aud_root", role="superadmin", modules=[])
    h = _login(client, "aud_root")
    from helpers import settings_registry as SR
    cur = int(SR.get("uploads", "max_file_mb"))
    new = cur - 1 if cur > 1 else cur + 1                      # 1～200：往旁邊挪一格（縮小＝立即生效）
    before = _max_audit_id()
    r = client.post("/api/settings-center/batch", json={"groups": {"uploads": {"values": {"max_file_mb": new}}}, "reason": "稽核守門實證"}, headers=h)
    assert r.status_code == 200, r.text
    rows = _new_audits(before)
    assert rows, "批次儲存成功卻沒有任何稽核列"
    mine = [x for x in rows if x["action"].startswith("settings.uploads") or x["target_id"] == "uploads"]
    assert len(mine) == 1 and mine[0]["username"] == "aud_root", rows


def _grant(client, h, uid):
    return client.post("/api/users/permissions/batch", json={"userIds": [uid], "grant": ["customer"]}, headers=h)


def test_permission_batch_apply_and_undo_each_write_a_user_perm_change_audit_row(client, make_user):
    make_user("aud_root2", role="superadmin", modules=[])
    make_user("aud_bob", role="sales", modules=["dashboard", "work_log"])
    h, bob = _login(client, "aud_root2"), _uid("aud_bob")
    b0 = _max_audit_id()
    ap = _grant(client, h, bob)
    assert ap.status_code == 200, ap.text
    rows = _new_audits(b0)
    assert [(x["action"], x["target_id"], x["username"]) for x in rows] == [("user.perm_change", str(bob), "aud_root2")], rows
    changes = [p for p in ap.json()["people"] if p["status"] == "change"]
    assert changes, ap.text
    b1 = _max_audit_id()
    un = client.post("/api/users/permissions/batch/undo", json={"changes": changes}, headers=h)
    assert un.status_code == 200, un.text
    rows2 = _new_audits(b1)
    assert [(x["action"], x["target_id"], x["username"]) for x in rows2] == [("user.perm_change", str(bob), "aud_root2")], rows2


def test_permission_batch_preview_writes_nothing(client, make_user):
    """EXEMPT 的反面：預覽不寫稽核也不寫權限變更；同一份請求正式套用時才有一列（上一題）。"""
    make_user("aud_root3", role="superadmin", modules=[])
    make_user("aud_cat", role="engineer", modules=["dashboard"])
    h, cat = _login(client, "aud_root3"), _uid("aud_cat")
    a0, p0 = _count("audit_log"), _count("permission_changes")
    mods0 = _rows("SELECT modules FROM users WHERE id=?", (cat,))[0]["modules"]
    r = client.post("/api/users/permissions/batch/preview", json={"userIds": [cat], "grant": ["customer"]}, headers=h)
    assert r.status_code == 200, r.text
    assert any(p["status"] == "change" for p in r.json()["people"]), "預覽要真的算出會變動，才證明『算了卻沒寫』"
    assert (_count("audit_log"), _count("permission_changes")) == (a0, p0)
    assert _rows("SELECT modules FROM users WHERE id=?", (cat,))[0]["modules"] == mods0
    assert json.loads(mods0 or "[]") == ["dashboard"]
