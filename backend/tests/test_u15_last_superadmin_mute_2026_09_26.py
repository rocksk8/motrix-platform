# -*- coding: utf-8 -*-
"""U15（使用者 2026-09-26 表單）：系統技術類信件，超級管理員可以退訂，但不可以是最後一位收得到的超管。
斷言打在伺服器（API 狀態碼＋DB 的 notification_muted），不打在畫面文字。"""
import json

import pytest


def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _exec(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _system_key():
    from helpers import mail_types as mt
    ks = sorted(t.key for t in mt.all_types()
                if t.category == "system" and not t.event and t.key not in mt.MANAGED_ELSEWHERE)
    assert ks, "前提：至少有一種系統技術類信件"
    return ks[0]


def _business_key():
    from helpers import mail_types as mt
    ks = sorted(t.key for t in mt.all_types() if t.category != "system")
    assert ks
    return ks[0]


def _id(username):
    return _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def _muted(username):
    return json.loads(_q("SELECT notification_muted FROM users WHERE username=?", (username,))[0]["notification_muted"] or "[]")


@pytest.fixture
def two_superadmins(make_user):
    boss = make_user(username="u15_boss", role="superadmin")
    a = make_user(username="u15_a", role="superadmin")
    b = make_user(username="u15_b", role="superadmin")
    for u in ("u15_boss", "u15_a", "u15_b"):
        _exec("UPDATE users SET email=?, active=1, notification_muted='[]' WHERE username=?", (u + "@example.test", u))
    key = _system_key()
    # 其他既有的超管（種子資料）先退訂這一類，讓「剩幾位」只取決於本題的三位
    others = [r["username"] for r in _q("SELECT username FROM users WHERE role='superadmin'")
              if r["username"] not in ("u15_boss", "u15_a", "u15_b")]
    for u in others:
        _exec("UPDATE users SET notification_muted=? WHERE username=?", (json.dumps([key]), u))
    return boss, key


def test_the_last_receiving_superadmin_cannot_unsubscribe(client, two_superadmins):
    boss, key = two_superadmins
    h = _h(client, boss)
    assert client.put("/api/users/%d" % _id("u15_boss"), json={"notification_muted": [key]}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_a"), json={"notification_muted": [key]}, headers=h).status_code == 200
    r = client.put("/api/users/%d" % _id("u15_b"), json={"notification_muted": [key]}, headers=h)
    assert r.status_code == 400 and "最後一位" in r.json()["detail"], r.text
    assert key not in _muted("u15_b"), "被擋下就不可以寫進 DB"


def test_positive_controls(client, two_superadmins):
    """正對照：還有別人收得到 ⇒ 可以退訂；業務類不受限；別人重新訂閱後就可以退訂。"""
    boss, key = two_superadmins
    h = _h(client, boss)
    biz = _business_key()
    assert client.put("/api/users/%d" % _id("u15_boss"), json={"notification_muted": [key]}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_a"), json={"notification_muted": [key, biz]}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_b"), json={"notification_muted": [biz]}, headers=h).status_code == 200
    assert _muted("u15_b") == [biz]
    assert client.put("/api/users/%d" % _id("u15_a"), json={"notification_muted": []}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_b"), json={"notification_muted": [key]}, headers=h).status_code == 200
    assert _muted("u15_b") == [key]


def test_a_superadmin_without_email_does_not_count(client, two_superadmins):
    """寄信端只寄給有 Email 的人 ⇒ 沒 Email 的超管不算「收得到」：剩下的人是最後一位時照樣擋。"""
    boss, key = two_superadmins
    h = _h(client, boss)
    _exec("UPDATE users SET email='' WHERE username='u15_a'")
    assert client.put("/api/users/%d" % _id("u15_boss"), json={"notification_muted": [key]}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_b"), json={"notification_muted": [key]}, headers=h).status_code == 400



def _make_last(client, boss, key):
    """boss、a 退訂 ⇒ b 是最後一位收得到的超管。"""
    h = _h(client, boss)
    assert client.put("/api/users/%d" % _id("u15_boss"), json={"notification_muted": [key]}, headers=h).status_code == 200
    assert client.put("/api/users/%d" % _id("u15_a"), json={"notification_muted": [key]}, headers=h).status_code == 200
    return h


@pytest.mark.parametrize("change", [{"email": ""}, {"role": "admin"}])
def test_the_last_receiving_superadmin_cannot_lose_email_or_role_either(client, two_superadmins, change):
    """D 稽核 M-1：同一支端點清空 Email、改成非超管，一樣會讓最後一位消失 ⇒ 擋，DB 不變。"""
    boss, key = two_superadmins
    h = _make_last(client, boss, key)
    r = client.put("/api/users/%d" % _id("u15_b"), json=change, headers=h)
    assert r.status_code == 400 and "沒有任何超級管理員" in r.json()["detail"], r.text
    row = _q("SELECT email, role FROM users WHERE username='u15_b'")[0]
    assert row == {"email": "u15_b@example.test", "role": "superadmin"}, row


def test_business_types_are_never_blocked_even_for_the_last_one(client, two_superadmins):
    """D 稽核 S-2：業務類處在「只剩一位」時照樣可以退訂（原本的正對照從沒處在這個狀態 ⇒ 突變「業務類也擋」存活）。"""
    from helpers import mail_types as mt
    boss, _key = two_superadmins
    h = _h(client, boss)
    biz = sorted(t.key for t in mt.all_types() if t.category != "system" and not t.event)[0]
    for u in ("u15_boss", "u15_a"):
        assert client.put("/api/users/%d" % _id(u), json={"notification_muted": [biz]}, headers=h).status_code == 200
    r = client.put("/api/users/%d" % _id("u15_b"), json={"notification_muted": [biz]}, headers=h)
    assert r.status_code == 200, r.text
    assert _muted("u15_b") == [biz]


def test_custom_override_for_a_system_type_must_reach_someone(client, two_superadmins):
    """D 稽核 S-1：系統類型存成 custom 覆寫，名單上沒有人收得到 ⇒ 拒絕；有人收得到 ⇒ 放行（正對照）。"""
    boss, key = two_superadmins
    h = _h(client, boss)
    _exec("UPDATE users SET email='' WHERE username='u15_a'")
    r = client.put("/api/mail-types/%s/recipients" % key, json={"mode": "custom", "users": ["u15_a"]}, headers=h)
    assert r.status_code == 400 and "系統技術類" in r.json()["detail"], r.text
    r = client.put("/api/mail-types/%s/recipients" % key, json={"mode": "custom", "users": ["u15_b"]}, headers=h)
    assert r.status_code == 200, r.text
    assert client.put("/api/mail-types/%s/recipients" % key, json={"mode": "default"}, headers=h).status_code == 200
