# -*- coding: utf-8 -*-
"""T79 LINE Login 綁定流程（電腦發起、手機授權）：helpers/line_login.py＋ /api/line/* 路由＋設定欄位。

對外呼叫一律換掉：`line_login._post_form`（換 code／驗 id_token）與 `line_notify._http`（綁定完成的確認訊息）；不連 LINE。
"""
import json
import logging
import urllib.parse

import pytest

TOKEN = "tok-line-login-0123456789"
CID = "1234567890"
SECRET = "0123456789abcdef0123456789abcdef"
BASE = "https://line.example.com"
UID = "U" + "c" * 32
UID2 = "U" + "d" * 32
CB = BASE + "/api/line/callback"


class _FakeForm:
    """假的 LINE OAuth 端點。"""

    def __init__(self):
        self.calls = []
        self.token_status, self.verify_status = 200, 200
        self.id_token = "hdr.payload.sig"
        self.sub, self.aud, self.nonce, self.nonce_resp = UID, None, "", None

    def __call__(self, path, fields):
        self.calls.append((path, dict(fields)))
        if path.endswith("/token"):
            return self.token_status, ({"id_token": self.id_token} if self.token_status == 200 and self.id_token else {})
        return self.verify_status, {"aud": self.aud or fields["client_id"],
                                    "nonce": self.nonce if self.nonce_resp is None else self.nonce_resp, "sub": self.sub}


class _FakeLine:
    def __init__(self):
        self.calls, self.status = [], 200

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, token, payload))
        return self.status, {}


@pytest.fixture
def env(client, monkeypatch):
    from helpers import line_login, line_notify
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "public_base_url": BASE,
                                 "login_channel_id": CID, "login_channel_secret": SECRET, "events": {}})
    form, line = _FakeForm(), _FakeLine()
    monkeypatch.setattr(line_login, "_post_form", form)
    monkeypatch.setattr(line_notify, "_http", line)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    monkeypatch.setattr(line_login, "START_INTERVAL", 0)         # 一般題可以連續發起；節流有自己的題
    line_login.reset_for_tests()
    form.line = line
    yield form
    line_login.reset_for_tests()


def _login(client, make_user, name, role="sales"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _begin(client, hdr, form):
    r = client.post("/api/line/binding/start", headers=hdr)
    assert r.status_code == 200, r.text
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.json()["authorizeUrl"]).query)
    form.nonce = q["nonce"][0]
    return q["state"][0], r.json()


def _cb(client, **params):
    return client.get("/api/line/callback", params=params)


def _binding(client, hdr):
    r = client.get("/api/line/binding", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


# ── 公開路徑本身 ──────────────────────────────────────────────────────────

def test_callback_is_public_and_the_page_is_fixed_without_erp_data(client, env):
    import main
    assert "/api/line/callback" in main._PUBLIC_API_PATHS
    r = _cb(client, state="x" * 40, code="abc")                       # 沒有 Authorization
    assert r.status_code == 400 and "無效" in r.text
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["content-type"].startswith("text/html")
    assert env.calls == [], "state 不存在時不可去打 LINE"


def test_callback_without_any_params_is_a_safe_400(client, env):
    assert _cb(client).status_code == 400


# ── 正常流程 ──────────────────────────────────────────────────────────────

def test_full_flow_links_the_initiator_only_and_returns_no_erp_data(client, make_user, env):
    import db
    hdr = _login(client, make_user, "bind_amy")
    assert _binding(client, hdr) == {"linked": False, "linkedAt": "", "confirmed": None, "available": True}
    state, res = _begin(client, hdr, env)
    assert res["qrCodePng"].startswith("data:image/png;base64,") and res["expiresIn"] == 600
    u = urllib.parse.urlparse(res["authorizeUrl"])
    q = urllib.parse.parse_qs(u.query)
    assert u.netloc == "access.line.me" and q["client_id"] == [CID] and q["redirect_uri"] == [CB]
    assert q["response_type"] == ["code"] and q["scope"] == ["openid"] and q["state"] == [state]

    r = _cb(client, code="the-code-123", state=state)                  # 手機的瀏覽器：沒有 session
    assert r.status_code == 200 and "綁定完成" in r.text
    assert "bind_amy" not in r.text and UID not in r.text
    tok = [c for c in env.calls if c[0].endswith("/token")][0][1]
    assert tok == {"grant_type": "authorization_code", "code": "the-code-123", "redirect_uri": CB,
                   "client_id": CID, "client_secret": SECRET}
    v = _binding(client, hdr)
    assert v["linked"] and v["confirmed"] is True and v["linkedAt"]
    assert UID not in json.dumps(v), "userId 不回到瀏覽器"
    # 確認訊息：只推給剛綁定的人，內容沒有 ERP 資料
    pushes = [c for c in env.line.calls if c[1].endswith("/push") or c[1].endswith("/multicast")]
    assert len(pushes) == 1 and UID in json.dumps(pushes[0][3])
    # 稽核：發起人是行為人，只記結果
    conn = db.get_db()
    try:
        row = conn.execute("SELECT username, detail FROM audit_log WHERE action='line.binding.callback'").fetchone()
    finally:
        conn.close()
    assert row["username"] == "bind_amy" and json.loads(row["detail"]) == {"result": "linked"}
    from helpers import line_notify
    assert line_notify.ids_for(["bind_amy"]) == [UID]


def test_state_is_single_use(client, make_user, env):
    hdr = _login(client, make_user, "bind_su")
    state, _ = _begin(client, hdr, env)
    assert _cb(client, code="c1", state=state).status_code == 200
    n = len(env.calls)
    r = _cb(client, code="c2", state=state)
    assert r.status_code == 400 and "無效" in r.text and len(env.calls) == n, "第二次不可再去換 code"


def test_binding_follows_the_initiator_session_not_the_phone(client, make_user, env):
    """發起人在手機授權完成前登出 ⇒ 不綁（綁定要綁發起人的登入 session）。"""
    import db
    hdr = _login(client, make_user, "bind_out")
    state, _ = _begin(client, hdr, env)
    conn = db.get_db()
    conn.execute("DELETE FROM sessions WHERE username='bind_out'")
    conn.commit()
    conn.close()
    r = _cb(client, code="c", state=state)
    assert r.status_code == 400 and "登出" in r.text and env.calls == []
    from helpers import line_notify
    assert not line_notify.is_linked("bind_out")


def test_inactive_user_is_not_linked(client, make_user, env):
    import db
    hdr = _login(client, make_user, "bind_off")
    state, _ = _begin(client, hdr, env)
    conn = db.get_db()
    conn.execute("UPDATE users SET active=0 WHERE username='bind_off'")
    conn.commit()
    conn.close()
    assert _cb(client, code="c", state=state).status_code == 400
    from helpers import line_notify
    assert not line_notify.is_linked("bind_off") and env.calls == []


def test_user_cancel_burns_the_state(client, make_user, env):
    hdr = _login(client, make_user, "bind_no")
    state, _ = _begin(client, hdr, env)
    r = _cb(client, state=state, error="access_denied")
    assert r.status_code == 400 and "取消" in r.text and env.calls == []
    assert "無效" in _cb(client, code="c", state=state).text


def test_expired_state(client, make_user, env, monkeypatch):
    from helpers import line_login
    hdr = _login(client, make_user, "bind_exp")
    state, _ = _begin(client, hdr, env)
    t0 = line_login._now()
    monkeypatch.setattr(line_login, "_now", lambda: t0 + line_login.STATE_TTL + 1)
    r = _cb(client, code="c", state=state)
    assert r.status_code == 400 and "逾時" in r.text and env.calls == []


@pytest.mark.parametrize("what", ["token_400", "no_id_token", "verify_400", "nonce_mismatch", "aud_mismatch", "bad_sub"])
def test_line_side_failures_never_link_and_burn_the_state(client, make_user, env, what):
    from helpers import line_notify
    hdr = _login(client, make_user, "bind_f_" + what[:6])
    state, _ = _begin(client, hdr, env)
    if what == "token_400":
        env.token_status = 400
    elif what == "no_id_token":
        env.id_token = ""
    elif what == "verify_400":
        env.verify_status = 400
    elif what == "nonce_mismatch":
        env.nonce_resp = "someone-elses-nonce"
    elif what == "aud_mismatch":
        env.aud = "9999999999"
    elif what == "bad_sub":
        env.sub = "not-a-line-id"
    r = _cb(client, code="c", state=state)
    assert r.status_code == 400 and "失敗" in r.text
    assert not line_notify.is_linked("bind_f_" + what[:6]) and env.line.calls == []
    assert "無效" in _cb(client, code="c", state=state).text


def test_a_line_account_already_bound_to_someone_else_is_refused(client, make_user, env):
    from helpers import line_notify
    other = _login(client, make_user, "bind_first")
    s1, _ = _begin(client, other, env)
    assert _cb(client, code="c", state=s1).status_code == 200
    hdr = _login(client, make_user, "bind_second")
    s2, _ = _begin(client, hdr, env)
    r = _cb(client, code="c", state=s2)                               # 同一個 LINE 帳號
    assert r.status_code == 400 and "失敗" in r.text
    assert line_notify.ids_for(["bind_first"]) == [UID] and not line_notify.is_linked("bind_second")


def test_confirmation_outcomes_are_recorded(client, make_user, env):
    from helpers import line_notify
    from helpers.settings import _set_setting, _get_setting
    hdr = _login(client, make_user, "bind_conf")
    env.line.status = 400                      # LINE 回永久失敗（例：Login 與 Messaging 不同 Provider ⇒ userId 對不上）
    s, _ = _begin(client, hdr, env)
    assert _cb(client, code="c", state=s).status_code == 200
    assert _binding(client, hdr)["confirmed"] is False
    cfg = _get_setting("line_notify")
    _set_setting("line_notify", {**cfg, "enabled": False})              # LINE 通知沒啟用 ⇒ 沒驗
    s, _ = _begin(client, hdr, env)
    assert _cb(client, code="c", state=s).status_code == 200
    assert _binding(client, hdr)["confirmed"] is None and line_notify.is_linked("bind_conf")


# ── 發起端 ────────────────────────────────────────────────────────────────

def test_start_needs_login_and_complete_configuration(client, make_user, env):
    from helpers.settings import _set_setting, _get_setting
    assert client.post("/api/line/binding/start").status_code == 401
    assert client.get("/api/line/binding").status_code == 401
    hdr = _login(client, make_user, "bind_cfg")
    cfg = _get_setting("line_notify")
    _set_setting("line_notify", {**cfg, "login_channel_secret": ""})
    assert client.post("/api/line/binding/start", headers=hdr).status_code == 400
    assert _binding(client, hdr)["available"] is False
    _set_setting("line_notify", {**cfg, "public_base_url": ""})
    assert client.post("/api/line/binding/start", headers=hdr).status_code == 400
    assert _binding(client, hdr)["available"] is False


def test_pending_caps(client, make_user, env, monkeypatch):
    from helpers import line_login
    hdr = _login(client, make_user, "bind_cap")
    states = [_begin(client, hdr, env)[0] for _ in range(line_login.MAX_PENDING_PER_USER + 1)]
    assert line_login.pending_count() == line_login.MAX_PENDING_PER_USER
    assert "無效" in _cb(client, code="c", state=states[0]).text, "最舊的被擠掉"
    monkeypatch.setattr(line_login, "MAX_PENDING_TOTAL", line_login.pending_count())
    with pytest.raises(ValueError):
        line_login.start("someone_else", "tok")


def test_garbage_requests_never_count_against_the_rate_limit(client, make_user, env, monkeypatch):
    """K 審 N1：垃圾 state 不花對外成本、不計入限流——攻擊者不能把所有人擋在外面。"""
    from helpers import line_login, line_notify
    monkeypatch.setattr(line_login, "CALLBACK_RATE_LIMIT", 3)
    hdr = _login(client, make_user, "bind_rl")
    state, _ = _begin(client, hdr, env)
    assert [_cb(client, code="c", state="g" * 40).status_code for _ in range(100)] == [400] * 100
    assert _cb(client, code="c", state=state).status_code == 200 and line_notify.is_linked("bind_rl")


def test_rate_limit_applies_to_valid_states_and_burns_the_state(client, make_user, env, monkeypatch):
    """限流只算「要去打 LINE」的請求；被擋的那一筆 state 也已銷毀（進 access log 的 code／state 不是活的）。"""
    from helpers import line_login
    monkeypatch.setattr(line_login, "CALLBACK_RATE_LIMIT", 2)
    hdr = _login(client, make_user, "bind_rl2")
    codes, last = [], None
    for _ in range(3):                                 # 每筆都要用自己的 nonce，所以發起一筆就回調一筆
        last, _r = _begin(client, hdr, env)
        codes.append(_cb(client, code="c", state=last).status_code)
    assert codes == [200, 200, 429]
    n = len(env.calls)
    assert _cb(client, code="c", state=last).status_code == 400 and len(env.calls) == n, "被限流的 state 已經死了"


def test_start_is_throttled_per_user(client, make_user, env, monkeypatch):
    """K 審 N3：同一個人兩次發起至少間隔 START_INTERVAL 秒。"""
    from helpers import line_login
    monkeypatch.setattr(line_login, "START_INTERVAL", 3)
    t0 = line_login._now()
    now = [t0]
    monkeypatch.setattr(line_login, "_now", lambda: now[0])
    hdr = _login(client, make_user, "bind_thr")
    assert client.post("/api/line/binding/start", headers=hdr).status_code == 200
    assert client.post("/api/line/binding/start", headers=hdr).status_code == 400
    other = _login(client, make_user, "bind_thr2")
    assert client.post("/api/line/binding/start", headers=other).status_code == 200, "別人不受影響"
    now[0] = t0 + 3.5
    assert client.post("/api/line/binding/start", headers=hdr).status_code == 200


def test_no_code_state_secret_or_id_token_in_logs(client, make_user, env, caplog):
    hdr = _login(client, make_user, "bind_log")
    with caplog.at_level(logging.DEBUG):
        state, _ = _begin(client, hdr, env)
        _cb(client, code="the-secret-code-777", state=state)
        env.token_status = 400
        s2, _ = _begin(client, hdr, env)
        _cb(client, code="another-code-888", state=s2)
    # 只看伺服器端（helpers／routers）的 log；httpx 是測試用戶端自己印的請求網址，不是我們的 log
    ours = " | ".join(r.getMessage() for r in caplog.records if r.name.split(".")[0] in ("helpers", "routers", "main", "db"))
    for frag in (state, s2, "the-secret-code-777", "another-code-888", SECRET, env.id_token, TOKEN):
        assert frag not in ours


# ── 解除綁定 ──────────────────────────────────────────────────────────────

def test_unlink_own_and_superadmin_unlinks_others(client, make_user, env):
    from helpers import line_notify
    amy = _login(client, make_user, "bind_u1")
    sa = _login(client, make_user, "bind_sa", "superadmin")
    line_notify.link_user("bind_u1", UID)
    line_notify.link_user("bind_sa", UID2)
    assert client.delete("/api/line/binding/bind_sa", headers=amy).status_code == 403
    assert line_notify.is_linked("bind_sa")
    assert client.delete("/api/line/binding", headers=amy).json() == {"ok": True, "unlinked": True}
    assert not line_notify.is_linked("bind_u1")
    assert client.delete("/api/line/binding", headers=amy).json()["unlinked"] is False
    assert client.delete("/api/line/binding/bind_sa", headers=sa).json() == {"ok": True, "unlinked": True}


def test_deleting_a_user_drops_the_binding(client, make_user, env):
    import db
    from helpers import line_notify
    sa = _login(client, make_user, "bind_sa2", "superadmin")
    make_user(username="bind_gone", role="sales")
    line_notify.link_user("bind_gone", UID)
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='bind_gone'").fetchone()["id"]
    conn.close()
    r = client.delete("/api/users/%d" % uid, headers=sa)
    assert r.status_code == 200, r.text
    assert not line_notify.is_linked("bind_gone")


# ── 設定欄位：LINE Login channel ──────────────────────────────────────────

def _put(client, sa, **body):
    return client.put("/api/settings/line-notify", headers=sa, json=body)


@pytest.mark.parametrize("field,bad", [("login_channel_id", "12ab"), ("login_channel_id", "1" * 30), ("login_channel_secret", "short"),
                                       ("login_channel_secret", "z" * 32), ("login_channel_secret", SECRET[:16] + "\n" + SECRET[17:])])
def test_put_rejects_bad_login_credentials_and_keeps_the_old(client, make_user, env, field, bad):
    from helpers.settings import _get_setting
    sa = _login(client, make_user, "bind_cfg_sa", "superadmin")
    r = _put(client, sa, **{field: bad})
    assert r.status_code == 400 and SECRET not in r.text
    assert _get_setting("line_notify")[field] == (CID if field == "login_channel_id" else SECRET)


def test_secret_is_masked_kept_audited_without_value_and_removed_from_export(client, make_user, env):
    import db
    from helpers.settings import _get_setting
    from tests.test_system_audit_2026_09_14 import _json_backup_queries
    sa = _login(client, make_user, "bind_cfg_sa2", "superadmin")
    g = client.get("/api/settings/line-notify", headers=sa).json()
    assert g["login_channel_id"] == CID and g["login_channel_secret"] not in ("", SECRET) and SECRET not in json.dumps(g)
    assert g["callback_url"] == CB
    assert _put(client, sa, login_channel_secret=g["login_channel_secret"]).status_code == 200     # 遮罩值＝保留
    assert _get_setting("line_notify")["login_channel_secret"] == SECRET
    new = "f" * 32
    assert _put(client, sa, login_channel_secret=new).status_code == 200
    assert _get_setting("line_notify")["login_channel_secret"] == new
    conn = db.get_db()
    try:
        audits = " ".join(r["detail"] for r in conn.execute("SELECT detail FROM audit_log WHERE action='settings.line_notify.update'"))
        rows = {r[0]: r[1] for r in conn.execute(_json_backup_queries()["系統設定"]).fetchall()}
    finally:
        conn.close()
    assert SECRET not in audits and new not in audits and '"loginSecretChanged": true' in audits
    exported = json.loads(rows["line_notify"])
    assert "login_channel_secret" not in exported and exported["login_channel_id"] == CID and new not in rows["line_notify"]
    assert _put(client, sa, login_channel_secret="").status_code == 200                            # 空字串＝清除
    assert _get_setting("line_notify")["login_channel_secret"] == ""


def test_dev_marker_blocks_push_but_not_the_read_only_token_check(client, make_user, env, monkeypatch):
    """K 審結論（hichan-13）：開發機標記擋推播；verify／quota 是唯讀、刻意不擋（部署前要能先驗 token）。這題把它釘住，免得有人「順手補」。"""
    from helpers import line_notify as L
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (False, "測試：開發機標記"))
    env.line.status = 200
    assert L.push([UID], "hi") == L.SEND_SKIPPED and env.line.calls == []
    assert L.verify_token()["ok"] is True and L.quota()["ok"] is True
    assert {c[1] for c in env.line.calls} >= {"/v2/bot/info", "/v2/bot/message/quota"}
