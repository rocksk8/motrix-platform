# -*- coding: utf-8 -*-
"""S6（設定改版，2026-11-13）：我的帳號 → 通知分頁 →「我要收的 Email 通知」。
本人自己 GET／PUT `/api/mail-types/mine`（只改自己的 users.notification_muted，opt-out 清單）。
斷言打在伺服器（狀態碼＋DB＋稽核），不打畫面文字。"""
import json

import pytest

_MAKE_USER_DEFAULT_ROLE = "superadmin"

_SELF_ACTION = "user.notification_prefs.self"


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


def _muted(username):
    return json.loads(_q("SELECT notification_muted FROM users WHERE username=?", (username,))[0]["notification_muted"] or "[]")


def _audits(username=None):
    rows = _q("SELECT * FROM audit_log WHERE action=? ORDER BY id", (_SELF_ACTION,))
    return [r for r in rows if username is None or r["target_id"] == username]


def _get(client, h):
    r = client.get("/api/mail-types/mine", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, h, body):
    return client.put("/api/mail-types/mine", json=body, headers=h)


def _pick(items, low_risk):
    ks = [i["key"] for i in items if i["lowRisk"] is low_risk]
    assert ks, "前提：這位使用者至少收得到一種%s通知" % ("業務類" if low_risk else "簽核／系統技術類")
    return ks[0]


@pytest.fixture
def me(make_user):
    u = make_user(username="s6_me", role="superadmin")
    _exec("UPDATE users SET email=?, active=1, notification_muted='[]' WHERE username=?", ("s6_me@example.test", "s6_me"))
    return u


def test_requires_login(client):
    assert client.get("/api/mail-types/mine").status_code == 401
    assert client.put("/api/mail-types/mine", json={"changes": {"x": False}}).status_code == 401


def test_get_lists_what_reaches_me_with_everything_on_by_default(client, me):
    d = _get(client, _h(client, me))
    assert d["hasEmail"] is True and d["version"]
    assert d["items"] and all(i["receive"] is True for i in d["items"])
    assert {i["category"] for i in d["items"]} >= {"business"}
    # 業務類標 lowRisk、其餘不是；每列都帶分類名稱供畫面分組
    assert all(i["lowRisk"] == (i["category"] == "business") for i in d["items"])
    assert all(i["categoryLabel"] for i in d["items"])


def test_has_email_false_is_reported(client, make_user):
    u = make_user(username="s6_noemail", role="superadmin")
    _exec("UPDATE users SET email='' WHERE username=?", ("s6_noemail",))
    assert _get(client, _h(client, u))["hasEmail"] is False


def test_turning_a_low_risk_type_off_and_on_round_trips_and_is_audited(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    r = _put(client, h, {"changes": {key: False}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"][0]["key"] == key and r.json()["risky"] == []
    assert _muted("s6_me") == [key]
    assert [i for i in _get(client, h)["items"] if i["key"] == key][0]["receive"] is False
    a = _audits("s6_me")
    assert len(a) == 1 and json.loads(a[0]["detail"])["keys_off"] == [key] and json.loads(a[0]["detail"])["by"] == "self"
    r = _put(client, h, {"changes": {key: True}})
    assert r.status_code == 200 and _muted("s6_me") == []
    assert len(_audits("s6_me")) == 2


def test_a_no_op_writes_nothing_and_leaves_no_audit(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    v0 = _get(client, h)["version"]
    r = _put(client, h, {"changes": {key: True}})                      # 本來就收 ⇒ 沒有實質變動
    assert r.status_code == 200 and r.json()["changed"] == [] and r.json()["unchanged"] == [key]
    assert r.json()["version"] == v0 and _muted("s6_me") == [] and _audits("s6_me") == []


def test_turning_off_an_approval_or_system_type_needs_confirm_on_the_server(client, me, make_user):
    # 另有一位收得到的超管，這題才只驗「confirm 閘」，不會先撞 U15「最後一位」
    make_user(username="s6_peer", role="superadmin")
    _exec("UPDATE users SET email=?, active=1, notification_muted='[]' WHERE username=?", ("s6_peer@example.test", "s6_peer"))
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], False)
    r = _put(client, h, {"changes": {key: False}})
    assert r.status_code == 409 and "confirm" in r.json()["detail"], r.text
    assert _muted("s6_me") == [] and _audits("s6_me") == [], "沒帶 confirm 不可以寫入"
    # preview：不寫入、列出高影響名稱
    p = _put(client, h, {"changes": {key: False}, "preview": True})
    assert p.status_code == 200 and p.json()["preview"] is True and len(p.json()["risky"]) == 1
    assert _muted("s6_me") == [] and _audits("s6_me") == []
    r = _put(client, h, {"changes": {key: False}, "confirm": True})
    assert r.status_code == 200, r.text
    assert _muted("s6_me") == [key] and len(_audits("s6_me")) == 1


def test_turning_a_risky_type_back_on_never_needs_confirm(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], False)
    _exec("UPDATE users SET notification_muted=? WHERE username=?", (json.dumps([key]), "s6_me"))
    r = _put(client, h, {"changes": {key: True}})
    assert r.status_code == 200 and _muted("s6_me") == [], r.text


def test_expect_version_conflict_is_409(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    v0 = _get(client, h)["version"]
    _exec("UPDATE users SET notification_muted=? WHERE username=?", (json.dumps([key]), "s6_me"))     # 管理員代為設定了
    r = _put(client, h, {"changes": {key: True}, "expect": v0})
    assert r.status_code == 409, r.text
    assert _muted("s6_me") == [key]


@pytest.mark.parametrize("body", [
    {},                                                                 # 沒有 changes
    {"changes": {}},                                                    # 空的
    {"changes": []},                                                    # 型別不對
    {"changes": {"no_such_mail_type": False}},                          # 不認得的類型
])
def test_bad_requests_are_400(client, me, body):
    r = _put(client, _h(client, me), body)
    assert r.status_code == 400, r.text
    assert _muted("s6_me") == []


def test_values_must_be_booleans(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    for v in ("false", 0, None, "off"):
        assert _put(client, h, {"changes": {key: v}}).status_code == 400
    assert _muted("s6_me") == []


def test_muted_keys_that_are_not_listed_are_preserved(client, me):
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    _exec("UPDATE users SET notification_muted=? WHERE username=?", (json.dumps(["legacy_gone_type", key]), "s6_me"))
    assert _put(client, h, {"changes": {key: True}}).status_code == 200
    assert _muted("s6_me") == ["legacy_gone_type"], "清單裡我看不到的舊項目不能被這頁悄悄洗掉"


def test_it_only_ever_touches_my_own_row(client, me, make_user):
    make_user(username="s6_other", role="superadmin")
    _exec("UPDATE users SET email=?, notification_muted='[]' WHERE username=?", ("s6_other@example.test", "s6_other"))
    h = _h(client, me)
    key = _pick(_get(client, h)["items"], True)
    assert _put(client, h, {"changes": {key: False}, "username": "s6_other", "user_id": 1}).status_code == 200
    assert _muted("s6_me") == [key] and _muted("s6_other") == []


def test_the_last_receiving_superadmin_cannot_drop_a_system_type_here_either(client, make_user):
    from helpers import mail_types as mt
    keys = sorted(t.key for t in mt.all_types() if t.category == "system" and not t.event and t.key not in mt.MANAGED_ELSEWHERE)
    assert keys, "前提：至少有一種系統技術類信件"
    key = keys[0]
    solo = make_user(username="s6_solo", role="superadmin")
    _exec("UPDATE users SET email=?, active=1, notification_muted='[]' WHERE username=?", ("s6_solo@example.test", "s6_solo"))
    for r in _q("SELECT username FROM users WHERE role='superadmin' AND username<>'s6_solo'"):
        _exec("UPDATE users SET notification_muted=? WHERE username=?", (json.dumps([key]), r["username"]))
    h = _h(client, solo)
    r = _put(client, h, {"changes": {key: False}, "confirm": True})
    assert r.status_code == 400 and "最後一位" in r.json()["detail"], r.text
    assert _muted("s6_solo") == [] and _audits("s6_solo") == []


def test_the_admin_proxy_endpoint_is_unchanged(client, me, make_user):
    make_user(username="s6_victim", role="sales")
    _exec("UPDATE users SET email=? WHERE username=?", ("s6_victim@example.test", "s6_victim"))
    vid = _q("SELECT id FROM users WHERE username='s6_victim'")[0]["id"]
    from helpers import mail_types as mt
    key = sorted(t.key for t in mt.all_types() if t.category == "business")[0]
    r = client.put("/api/users/%d" % vid, json={"notification_muted": [key]}, headers=_h(client, me))
    assert r.status_code == 200, r.text
    assert _muted("s6_victim") == [key]
