# -*- coding: utf-8 -*-
"""LINE 收件人過濾契約題（2026-11-12；PM 裁示 D1／D2）：角色允許清單＋個人勾選，**只縮不擴**。

釘住：
① 沒有任何設定＝行為與舊版完全相同（不查資料庫、不丟掉任何人）；
② 角色允許清單（缺省＝所有角色、`[]`＝沒有角色、壞值 fail-closed）；
③ 個人退訂（opt-out）、恢復、無變化不寫入、空清單不殘留；
④ 絕不讓不在呼叫端清單裡的人收到東西；停用帳號被濾掉；資料庫出錯 fail-closed；
⑤ `notify_users` 整合：推播對象只剩「角色∩個人∩已綁定」；
⑥ 端點：誰能改角色（只限最高管理者）、個人只能改自己、角色不被允許的類型不開放。
對外呼叫一律換掉 `line_notify._http`。
"""
import logging

import pytest

TOKEN = "tok-SECRET-0123456789"
EV = "approval_review_edit"
EV2 = "warranty_expiry"


def _uid(n):
    return "U" + ("%032x" % n)


class _Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        return 200, {}


@pytest.fixture
def env(client, monkeypatch, make_user):
    from helpers import line_notify as L
    from helpers import line_quota
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "events": {EV: True, EV2: True}})
    fake = _Fake()
    monkeypatch.setattr(L, "_http", fake)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    monkeypatch.setattr(line_quota, "after_push", lambda *a, **k: None)         # 額度檢查另有專題；這裡不排計時器
    users = {}
    for i, (name, role) in enumerate([("amy", "sales"), ("bob", "admin"), ("carol", "finance"), ("dan", "viewer")], start=1):
        make_user(username=name, role=role)
        L.link_user(name, _uid(i))
        users[name] = _uid(i)
    return L, fake, users


# ── ① 沒有設定＝舊行為 ─────────────────────────────────────────────────────

def test_no_settings_means_nobody_is_dropped_and_no_db_lookup(env, monkeypatch):
    from helpers import line_recipients as lr
    monkeypatch.setattr(lr, "_role_of", lambda names: (_ for _ in ()).throw(AssertionError("不該查資料庫")))
    assert lr.filter_usernames(EV, ["amy", "ghost", "amy", "bob"]) == ["amy", "ghost", "bob"]
    assert lr.allowed_roles(EV) is None


# ── ② 角色允許清單 ────────────────────────────────────────────────────────

def test_role_allowlist_keeps_only_allowed_roles_in_order(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales", "admin"])
    assert lr.filter_usernames(EV, ["dan", "bob", "carol", "amy"]) == ["bob", "amy"]
    assert lr.filter_usernames(EV2, ["dan", "bob", "carol", "amy"]) == ["dan", "bob", "carol", "amy"], "別的類型不受影響"


def test_empty_allowlist_means_no_role_and_none_restores_all(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, [])
    assert lr.filter_usernames(EV, ["amy", "bob"]) == []
    L.set_event_roles(EV, None)
    assert lr.allowed_roles(EV) is None and lr.filter_usernames(EV, ["amy", "bob"]) == ["amy", "bob"]


@pytest.mark.parametrize("bad", ["sales", {"sales": 1}, ["sales", "ceo"], [1], 5])
def test_set_event_roles_rejects_bad_values(env, bad):
    L, _, _ = env
    with pytest.raises(ValueError):
        L.set_event_roles(EV, bad)


def test_set_event_roles_rejects_unwired_event_and_is_idempotent_without_write(env, monkeypatch):
    L, _, _ = env
    with pytest.raises(ValueError):
        L.set_event_roles("bonus_submitted", ["sales"])      # 獎金類永遠排除（2026-11-13）
    L.set_event_roles(EV, ["sales"])
    writes = []
    real = L._set_setting
    monkeypatch.setattr(L, "_set_setting", lambda k, v: (writes.append(k), real(k, v))[1])
    L.set_event_roles(EV, ["sales"])           # 沒變
    L.set_event_roles(EV2, None)               # 本來就沒限制
    assert writes == [], "沒有變化就不寫（硬碟寫入越少越好）"


@pytest.mark.parametrize("corrupt", ["sales", {"x": 1}, ["sales", "ceo"], 7])
def test_corrupt_allowlist_fails_closed_with_warning(env, caplog, corrupt):
    from helpers import line_recipients as lr
    from helpers.settings import _get_setting, _set_setting
    c = _get_setting("line_notify", {})
    c["event_roles"] = {EV: corrupt}
    _set_setting("line_notify", c)
    with caplog.at_level(logging.WARNING):
        assert lr.filter_usernames(EV, ["amy", "bob"]) == []
    assert "event_roles" in caplog.text


def test_event_roles_view_lists_only_wired_events(env):
    L, _, _ = env
    L.set_event_roles(EV, ["admin"])
    v = L.event_roles_view()          # 2026-11-13：接線單位＝信件登記表（約 110 項），不再只有三項
    assert v[EV] == ["admin"] and v[EV2] is None and v["auth_lockout"] is None
    assert not [k for k in v if k.startswith(("bonus_", "payslip_"))] and "system_test_mail" not in v


# ── ③ 個人勾選 ────────────────────────────────────────────────────────────

def test_personal_mute_and_restore(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    lr.set_muted("amy", EV, True)
    assert lr.is_muted("amy", EV) and not lr.is_muted("amy", EV2) and not lr.is_muted("bob", EV)
    assert lr.filter_usernames(EV, ["amy", "bob"]) == ["bob"]
    assert lr.filter_usernames(EV2, ["amy", "bob"]) == ["amy", "bob"], "只退訂了一個類型"
    lr.set_muted("amy", EV, False)
    assert lr.filter_usernames(EV, ["amy", "bob"]) == ["amy", "bob"]


def test_restore_leaves_no_empty_entry_and_unchanged_does_not_write(env, monkeypatch):
    from helpers import line_recipients as lr
    from helpers.settings import _get_setting
    lr.set_muted("amy", EV, True)
    lr.set_muted("amy", EV, False)
    assert "amy" not in (_get_setting(lr.PREFS_KEY, {}) or {})
    writes = []
    real = lr._set_setting
    monkeypatch.setattr(lr, "_set_setting", lambda k, v: (writes.append(k), real(k, v))[1])
    lr.set_muted("amy", EV, False)             # 本來就沒退訂
    assert writes == []


def test_set_muted_rejects_unwired_event_non_bool_and_disallowed_role(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    with pytest.raises(ValueError):
        lr.set_muted("amy", "bonus_submitted", True)
    with pytest.raises(ValueError):
        lr.set_muted("amy", EV, "yes")
    L.set_event_roles(EV, ["admin"])
    with pytest.raises(ValueError):
        lr.set_muted("amy", EV, True, role="sales")
    lr.set_muted("bob", EV, True, role="admin")


def test_corrupt_prefs_value_is_treated_as_nothing_muted(env):
    from helpers import line_recipients as lr
    from helpers.settings import _set_setting
    _set_setting(lr.PREFS_KEY, ["not", "a", "dict"])
    assert lr.filter_usernames(EV, ["amy", "bob"]) == ["amy", "bob"]
    _set_setting(lr.PREFS_KEY, {"amy": "oops", "bob": [EV, 3, None]})
    assert lr.muted_events("amy") == set() and lr.muted_events("bob") == {EV}


# ── ④ 只縮不擴、停用帳號、資料庫出錯 ───────────────────────────────────────

def test_never_adds_people_who_were_not_given(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales", "admin", "finance", "viewer"])          # 所有人的角色都被允許
    assert lr.filter_usernames(EV, ["amy"]) == ["amy"]
    assert lr.filter_usernames(EV, []) == [] and lr.filter_usernames(EV, None) == []


def test_inactive_and_missing_accounts_are_dropped_when_roles_are_restricted(env):
    L, _, _ = env
    import db
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales", "admin"])
    c = db.get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE username='amy'")
        c.commit()
    finally:
        c.close()
    assert lr.filter_usernames(EV, ["amy", "bob", "ghost"]) == ["bob"]


def test_database_error_fails_closed_and_never_raises(env, monkeypatch, caplog):
    L, _, _ = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales"])
    monkeypatch.setattr(lr, "_role_of", lambda names: (_ for _ in ()).throw(RuntimeError("db gone")))
    with caplog.at_level(logging.WARNING):
        assert lr.filter_usernames(EV, ["amy"]) == []
    assert "RuntimeError" in caplog.text and "db gone" not in caplog.text, "只記例外型別"


def test_large_lists_are_chunked(env, monkeypatch):
    L, _, _ = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales"])
    monkeypatch.setattr(lr, "_CHUNK", 2)
    assert lr.filter_usernames(EV, ["dan", "amy", "carol", "bob", "ghost"]) == ["amy"]


# ── prefs_view ────────────────────────────────────────────────────────────

def test_prefs_view_lists_only_company_enabled_and_role_allowed(env):
    L, _, _ = env
    from helpers import line_recipients as lr
    names = lambda role: [e["key"] for e in lr.prefs_view("amy", role)]          # noqa: E731
    assert names("sales") == [EV, EV2]
    L.set_event_roles(EV, ["admin"])
    assert names("sales") == [EV2] and names("admin") == [EV, EV2]
    L.set_event(EV2, False)
    assert names("admin") == [EV]
    lr.set_muted("amy", EV, True)
    e = lr.prefs_view("amy", "admin")[0]
    assert e == {"key": EV, "name": e["name"], "enabled": False, "group": "報價單與簽核", "kind": "mail"}


# ── ⑤ notify_users 整合 ───────────────────────────────────────────────────

def _targets(fake):
    out = []
    for m, path, payload in fake.calls:
        if path.endswith("/push"):
            out.append(payload["to"])
        elif path.endswith("/multicast"):
            out.extend(payload["to"])
    return out


def test_notify_users_pushes_only_role_and_personal_filtered_linked_users(env):
    L, fake, uid = env
    from helpers import line_recipients as lr
    L.set_event_roles(EV, ["sales", "admin", "finance"])
    lr.set_muted("carol", EV, True)
    th = L.notify_users(EV, ["amy", "bob", "carol", "dan"], "標題", [("單號", "MQ-1")])
    assert th is not None
    th.join(5)
    assert sorted(_targets(fake)) == sorted([uid["amy"], uid["bob"]]), "dan 角色不允許、carol 自己退訂"


def test_notify_users_does_nothing_when_filter_leaves_nobody(env):
    L, fake, _ = env
    L.set_event_roles(EV, [])
    assert L.notify_users(EV, ["amy", "bob"], "t") is None
    assert fake.calls == []


def test_notify_users_without_restrictions_behaves_as_before(env):
    L, fake, uid = env
    th = L.notify_users(EV, ["amy", "bob", "ghost"], "t")
    th.join(5)
    assert sorted(_targets(fake)) == sorted([uid["amy"], uid["bob"]])


# ── ⑥ 端點 ────────────────────────────────────────────────────────────────

def _hdr(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_roles_endpoint_superadmin_only_and_validates(client, env, make_user):
    sa = _hdr(client, make_user, "sa1", "superadmin")
    ad = _hdr(client, make_user, "ad1", "admin")
    url = "/api/settings/line-notify/events/%s/roles" % EV
    assert client.put(url, json={"roles": ["sales"]}, headers=ad).status_code == 403
    assert client.put(url, json={"roles": ["sales", "ceo"]}, headers=sa).status_code == 400
    assert client.put(url, json={}, headers=sa).status_code == 400
    assert client.put("/api/settings/line-notify/events/bonus_submitted/roles", json={"roles": []}, headers=sa).status_code == 404
    assert client.put(url, json={"roles": ["sales", "admin"]}, headers=sa).status_code == 200
    g = client.get("/api/settings/line-notify", headers=sa).json()
    ev = {e["key"]: e for e in g["events"]}
    assert ev[EV]["roles"] == ["sales", "admin"] and ev[EV2]["roles"] is None
    assert "sales" in g["role_choices"] and "superadmin" in g["role_choices"]
    assert client.put(url, json={"roles": None}, headers=sa).status_code == 200
    assert {e["key"]: e for e in client.get("/api/settings/line-notify", headers=sa).json()["events"]}[EV]["roles"] is None


def test_roles_change_survives_main_settings_save(client, env, make_user):
    """PUT 主設定（讀改寫整份 line_notify）不可把 event_roles 蓋掉。"""
    sa = _hdr(client, make_user, "sa2", "superadmin")
    assert client.put("/api/settings/line-notify/events/%s/roles" % EV, json={"roles": ["admin"]}, headers=sa).status_code == 200
    assert client.put("/api/settings/line-notify", json={"include_links": False}, headers=sa).status_code == 200
    from helpers import line_recipients as lr
    assert lr.allowed_roles(EV) == ["admin"]


def test_prefs_endpoints_are_self_service_and_respect_roles(client, env, make_user):
    L, _, _ = env
    amy = _hdr(client, make_user, "amy2", "sales")
    L.link_user("amy2", _uid(99))
    g = client.get("/api/line/prefs", headers=amy).json()
    assert g["linked"] is True and [e["key"] for e in g["events"]] == [EV, EV2] and all(e["enabled"] for e in g["events"])
    assert client.put("/api/line/prefs/%s" % EV, json={"enabled": False}, headers=amy).status_code == 200
    assert {e["key"]: e["enabled"] for e in client.get("/api/line/prefs", headers=amy).json()["events"]} == {EV: False, EV2: True}
    assert client.put("/api/line/prefs/%s" % EV, json={"enabled": "no"}, headers=amy).status_code == 400
    assert client.put("/api/line/prefs/bonus_submitted", json={"enabled": False}, headers=amy).status_code == 404
    L.set_event_roles(EV2, ["admin"])
    assert client.put("/api/line/prefs/%s" % EV2, json={"enabled": False}, headers=amy).status_code == 403, "角色不被允許的類型不開放"
    assert [e["key"] for e in client.get("/api/line/prefs", headers=amy).json()["events"]] == [EV]
    assert client.get("/api/line/prefs").status_code in (401, 403)
    from helpers import line_recipients as lr
    assert lr.muted_events("amy2") == {EV}, "只動到自己"


def test_prefs_unlinked_user_still_lists_but_reports_unlinked(client, env, make_user):
    amy = _hdr(client, make_user, "amy3", "sales")
    g = client.get("/api/line/prefs", headers=amy).json()
    assert g["linked"] is False and g["events"]
