# -*- coding: utf-8 -*-
"""T85 匯入精靈——員工匯入端點 `POST /api/users/import-rows`（只有最高管理者；只新增；臨時密碼只出現一次）。"""
import json
import logging

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _super(client, make_user, name="imp_super"):
    return _login(client, *make_user(username=name, role="superadmin"))


def _row(no, username, display="某人", role="", **kw):
    d = {"row": no, "username": username, "displayName": display, "role": role}
    d.update(kw)
    return d


def _plan(client, h, rows, **kw):
    r = client.post("/api/users/import-rows", json=dict({"rows": rows, "dryRun": True}, **kw), headers=h)
    return r


def _commit(client, h, rows, plan_hash=None):
    if plan_hash is None:
        plan_hash = _plan(client, h, rows).json()["planHash"]
    return client.post("/api/users/import-rows", json={"rows": rows, "dryRun": False, "planHash": plan_hash}, headers=h)


def _users():
    import db
    c = db.get_db()
    try:
        return {r["username"]: dict(r) for r in c.execute("SELECT * FROM users").fetchall()}
    finally:
        c.close()


@pytest.mark.parametrize("role", ["admin", "sales", "viewer"])
def test_only_superadmin_can_use_it(client, make_user, role):
    h = _login(client, *make_user(username="imp_" + role, role=role))
    assert _plan(client, h, [_row(2, "x1")]).status_code == 403
    assert client.post("/api/users/import-rows", json={"rows": [_row(2, "x1")], "dryRun": False, "planHash": "x"}, headers=h).status_code == 403
    assert "x1" not in _users()


@pytest.mark.parametrize("dry", [None, True, "false", 0, "False", 1])
def test_only_a_real_false_writes_and_preview_has_no_passwords(client, make_user, dry):
    h = _super(client, make_user)
    body = {"rows": [_row(2, "newbie")]}
    if dry is not None:
        body["dryRun"] = dry
    r = client.post("/api/users/import-rows", json=body, headers=h)
    assert r.status_code == 200 and r.json()["created"] == 1 and "credentials" not in r.json()
    assert "password" not in r.text.lower().replace("planhash", "")
    assert "newbie" not in _users()


def test_commit_needs_the_plan_hash_and_a_stale_plan_is_409(client, make_user):
    h = _super(client, make_user)
    rows = [_row(2, "a1")]
    assert client.post("/api/users/import-rows", json={"rows": rows, "dryRun": False}, headers=h).status_code == 400
    ph = _plan(client, h, rows).json()["planHash"]
    make_user(username="a1", role="viewer")                       # 預覽之後有人先建了同名帳號
    r = _commit(client, h, rows, ph)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_changed"
    r2 = _commit(client, h, [_row(2, "a2")], ph)                    # 換了列的內容 ⇒ 雜湊不符
    assert r2.status_code == 409 and "a2" not in _users()


def test_creates_accounts_must_change_password_empty_modules_and_one_time_passwords(client, make_user):
    h = _super(client, make_user)
    rows = [_row(2, "emp_sales", "業務甲", "業務", email="a@example.com", phone="0912"),
            _row(3, "emp_eng", "工程乙", "工程師"),
            _row(4, "emp_view", "檢視丙", ""),
            _row(5, "emp_view2", "檢視丁", "viewer")]
    r = _commit(client, h, rows)
    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == "no-store"
    body = r.json()
    assert body["created"] == 4 and len(body["credentials"]) == 4
    users = _users()
    assert users["emp_sales"]["role"] == "sales" and users["emp_eng"]["role"] == "engineer" and users["emp_view"]["role"] == "viewer"
    assert users["emp_sales"]["email"] == "a@example.com" and users["emp_sales"]["phone"] == "0912"
    for c in body["credentials"]:
        u = users[c["username"]]
        assert u["must_change_password"] == 1 and u["active"] == 1 and json.loads(u["modules"]) == []
        assert len(c["password"]) >= 14
        assert _login(client, c["username"], c["password"])             # 臨時密碼真的能登入
    assert len({c["password"] for c in body["credentials"]}) == 4


def test_high_privilege_roles_are_listed_as_manual_and_not_created(client, make_user):
    h = _super(client, make_user)
    rows = [_row(2, "boss1", "老闆", "管理員"), _row(3, "fin1", "財務", "finance"), _row(4, "root1", "根", "最高管理者"), _row(5, "ok1", "好", "業務")]
    r = _commit(client, h, rows)
    assert r.status_code == 200
    body = r.json()
    assert [m["username"] for m in body["manual"]] == ["boss1", "fin1", "root1"]
    assert all("此角色需手動建立" in m["reason"] for m in body["manual"])
    assert body["created"] == 1 and [c["username"] for c in body["credentials"]] == ["ok1"]
    users = _users()
    assert "boss1" not in users and "fin1" not in users and "root1" not in users and "ok1" in users


def test_unknown_role_blank_name_and_in_file_duplicates_are_errors(client, make_user):
    h = _super(client, make_user)
    rows = [_row(2, "e1", "甲", "老大"), _row(3, "e2", ""), _row(4, "dup", "乙"), _row(5, "DUP", "丙"), _row(6, "", "丁"), _row(7, "has space", "戊")]
    body = _plan(client, h, rows).json()
    assert body["failed"] == 5 and body["created"] == 1
    assert any("不認得的角色" in e for e in body["errors"])
    assert any("出現多次" in e for e in body["errors"])
    r = _commit(client, h, rows, body["planHash"])
    assert [c["username"] for c in r.json()["credentials"]] == ["dup"]
    assert set(_users()) >= {"dup"} and not ({"e1", "e2", "DUP", "has space"} & set(_users()))


def test_existing_accounts_are_skipped_even_when_only_case_or_width_differs(client, make_user):
    h = _super(client, make_user)
    make_user(username="Alice", role="sales")
    all_before = _users()
    before = all_before["Alice"]
    for variant in ("Alice", "alice", "ＡＬＩＣＥ"):
        body = _plan(client, h, [_row(2, variant, "新名字", "viewer")]).json()
        assert [s["username"] for s in body["skipped"]] == [variant.replace("ＡＬＩＣＥ", "ALICE")] and body["created"] == 0, variant
    r = _commit(client, h, [_row(2, "Alice", "新名字", "viewer"), _row(3, "bob", "鮑伯")])
    assert r.json()["created"] == 1
    after = _users()
    assert after["Alice"] == before, "既有帳號完全不動"
    assert set(after) - set(all_before) == {"bob"}


def test_password_column_is_ignored_with_a_warning_and_never_stored_or_logged(client, make_user, caplog):
    caplog.set_level(logging.DEBUG)
    h = _super(client, make_user)
    rows = [_row(2, "pw1", "密碼甲", "業務", hadPassword=True, password="Secret#Pass123")]
    body = _plan(client, h, rows).json()
    assert any("密碼欄不會使用" in w["message"] for w in body["warnings"])
    r = _commit(client, h, rows)
    cred = r.json()["credentials"][0]
    assert cred["password"] != "Secret#Pass123"
    import db
    c = db.get_db()
    try:
        dump = json.dumps([dict(x) for x in c.execute("SELECT * FROM audit_log").fetchall()], ensure_ascii=False, default=str)
        hashes = [x["password_hash"] for x in c.execute("SELECT password_hash FROM users").fetchall()]
    finally:
        c.close()
    assert cred["password"] not in dump, "稽核裡沒有臨時密碼"
    assert "Secret#Pass123" not in dump and cred["password"] not in caplog.text
    assert all(cred["password"] not in x for x in hashes)
    assert "user.import" in dump and "user.create" in dump and "pw1" in dump


def test_department_and_email_warnings_and_department_match(client, make_user):
    import db
    c = db.get_db()
    c.execute("INSERT INTO divisions (name, created_at) VALUES ('營業處', '2026-01-01')")
    did = c.execute("SELECT id FROM divisions").fetchone()["id"]
    c.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?, '業務一部', '2026-01-01')", (did,))
    c.commit()
    dep = c.execute("SELECT id FROM departments WHERE name='業務一部'").fetchone()["id"]
    c.close()
    h = _super(client, make_user)
    rows = [_row(2, "d1", "甲", "業務", department="業務一部"), _row(3, "d2", "乙", "業務", department="不存在部", email="not-an-email")]
    body = _plan(client, h, rows).json()
    msgs = [w["message"] for w in body["warnings"]]
    assert any("不存在部" in m for m in msgs) and any("Email" in m for m in msgs)
    _commit(client, h, rows, body["planHash"])
    users = _users()
    assert users["d1"]["department_id"] == dep and users["d2"]["department_id"] is None


def test_row_cap_and_empty_rows(client, make_user):
    h = _super(client, make_user)
    assert _plan(client, h, []).status_code == 400
    assert _plan(client, h, [_row(i + 2, "u%d" % i) for i in range(301)]).status_code == 400
    assert _plan(client, h, [_row(i + 2, "u%d" % i) for i in range(300)]).status_code == 200


def test_failure_in_the_middle_leaves_nothing_behind(client, make_user, monkeypatch):
    import routers.auth as A
    h = _super(client, make_user)
    rows = [_row(2, "ok_a"), _row(3, "ok_b"), _row(4, "ok_c")]
    ph = _plan(client, h, rows).json()["planHash"]
    real = A._insert_new_user
    n = {"i": 0}

    def boom(*a, **k):
        n["i"] += 1
        if n["i"] == 3:
            raise RuntimeError("Secret#Leak123")
        return real(*a, **k)
    monkeypatch.setattr(A, "_insert_new_user", boom)
    r = _commit(client, h, rows, ph)
    assert r.status_code == 500 and r.json()["detail"]["code"] == "import_failed" and "Secret#Leak123" not in r.text
    assert not ({"ok_a", "ok_b", "ok_c"} & set(_users()))


def test_create_user_endpoint_still_works_after_sharing_the_insert(client, make_user):
    h = _super(client, make_user)
    r = client.post("/api/users", json={"username": "plain1", "password": "Str0ng#Passw0rd", "display_name": "一般", "role": "sales"}, headers=h)
    assert r.status_code == 201 and r.json()["mustChangePassword"] is True
    assert _users()["plain1"]["must_change_password"] == 1
    assert client.post("/api/users", json={"username": "plain1", "password": "Str0ng#Passw0rd"}, headers=h).status_code == 409
