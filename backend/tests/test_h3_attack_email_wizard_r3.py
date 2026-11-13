# -*- coding: utf-8 -*-
"""寄信精靈第三輪（3aa9e09eb：證明只存 HMAC、備份總括遮蔽）——hichan-3，2026-11-13。

綠燈：密碼不在任何資料庫列／備份匯出／回應；「我收到了」必須重送『與測試時完全相同』的候選設定；過期／失敗重測／用過的證明都不能再啟用；
      同帳號並發 test-me 不超過上限；舊 PUT／舊寄測試信的限制。
xfail(strict)＝新發現：
  K HMAC 金鑰存在 `email_setup_hmac_secret`，備份匯出會把它遮成「[已遮蔽]」；用備份重建／手動還原該設定後，
    金鑰不是 hex ⇒ `bytes.fromhex` 丟 ValueError ⇒ 精靈測試、啟用都 500（要自己刪掉金鑰才恢復）。
"""
import json
import threading

import pytest


def _h(client, make_user, name, role="superadmin", email="me@example.com"):
    su, sp = make_user(username=name, role=role)
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET email=? WHERE username=?", (email, name))
    c.commit()
    c.close()
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": sp}).json()["token"]}


GOOD = {"provider": "gmail", "smtp_user": "co@gmail.com", "smtp_password": "abcd efgh ijkl mnop", "base_url": "https://erp.example.com"}
PW = "abcdefghijklmnop"


def _S():
    import importlib
    return importlib.import_module("routers.system")


def _cfg():
    return _S()._get_setting("email_notify", {}) or {}


@pytest.fixture()
def fake_smtp(monkeypatch):
    from helpers import email_notify as EN
    box = {"logins": [], "opens": []}

    class _C:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): box["logins"].append((u, p))
        def sendmail(self, *a, **k): pass

    def opener(host, port, timeout=15):
        box["opens"].append((host, port))
        return _C()
    monkeypatch.setattr(EN, "_smtp_open", opener)
    monkeypatch.setattr(EN, "_smtp_send_blocked", lambda subject: False)
    return box


def _all_settings_rows():
    import db
    c = db.get_db()
    try:
        return [(r[0], r[1]) for r in c.execute("SELECT key, value_json FROM system_settings").fetchall()]
    finally:
        c.close()


def _export_rows():
    import archive
    import db
    c = db.get_db()
    try:
        return [(d["key"], d["value_json"]) for d in (archive._general_row("系統設定", dict(r)) for r in c.execute(archive._daily_backup_tables()["系統設定"]).fetchall())]
    finally:
        c.close()


def _ok(client, h, body=None):
    return client.post("/api/settings/email-notify/wizard/test-me", json=body or GOOD, headers=h)


def _act(client, h, body=None):
    return client.post("/api/settings/email-notify/wizard/activate", json=body if body is not None else GOOD, headers=h)


# ── 綠燈：密碼不落地（證明、備份、回應） ───────────────────────────────────────
def test_after_test_me_the_password_is_nowhere_in_the_database_nor_the_backup_export(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_pw")
    assert _ok(client, h).status_code == 200
    for k, v in _all_settings_rows():
        assert PW not in (v or "") and "abcd efgh" not in (v or ""), "資料庫設定列 %s 含密碼" % k
    for k, v in _export_rows():
        assert PW not in (v or ""), "備份匯出列 %s 含密碼" % k
    proof = _S()._get_setting(_S()._EMAIL_WIZARD_PROOF, {})
    assert proof and set(proof) >= {"fp", "fp_full", "base_fp", "at"} and "cfg" not in proof and "smtp_password" not in proof


def test_after_activate_backup_export_still_has_no_password_and_hmac_key_is_masked(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_pw2")
    assert _ok(client, h).status_code == 200
    r = _act(client, h)
    assert r.status_code == 200, r.text
    assert _cfg()["smtp_password"] == PW and _cfg()["enabled"] is True                   # 正式設定仍是明文（既有設計，備份擋掉）
    rows = dict(_export_rows())
    assert PW not in json.dumps(rows, ensure_ascii=False)
    key_row = rows.get("email_setup_hmac_secret")
    assert key_row is not None and "[已遮蔽]" in key_row
    live_key = _S()._get_setting(_S()._WIZARD_HMAC_KEY, "")
    assert live_key and live_key not in json.dumps(rows, ensure_ascii=False)
    assert live_key not in client.get("/api/settings/email-notify", headers=h).text


# ── 綠燈：「我收到了」必須重送與測試時完全相同的設定 ───────────────────────────
@pytest.mark.parametrize("change", [
    {"smtp_password": "zzzz zzzz zzzz zzzz"},
    {"smtp_user": "other@gmail.com"},
    {"base_url": "https://evil.example.com"},
    {"from_name": "偽造的名稱"},
    {"provider": "other", "smtp_host": "evil.example.com", "smtp_port": 587},
])
def test_activate_with_any_different_field_is_refused_and_nothing_is_written(client, make_user, fake_smtp, change):
    h = _h(client, make_user, "atk_r3_diff_%d" % abs(hash(json.dumps(change, sort_keys=True))))
    before = dict(_cfg())
    assert _ok(client, h).status_code == 200
    r = _act(client, h, {**GOOD, **change})
    assert r.status_code in (400, 422), r.text
    assert _cfg() == before and not _cfg().get("enabled")


def test_activate_without_a_body_or_with_empty_body_is_refused(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_nobody")
    assert _ok(client, h).status_code == 200
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400
    assert client.post("/api/settings/email-notify/wizard/activate", json={}, headers=h).status_code in (400, 422)
    assert not _cfg().get("enabled")


def test_proof_is_single_use_and_a_failed_retest_voids_it(client, make_user, fake_smtp, monkeypatch):
    h = _h(client, make_user, "atk_r3_once")
    assert _ok(client, h).status_code == 200
    assert _act(client, h).status_code == 200
    assert _act(client, h).status_code == 400                                              # 用過即廢
    h2 = _h(client, make_user, "atk_r3_once2")
    assert _ok(client, h2, {**GOOD, "smtp_user": "second@gmail.com"}).status_code == 200
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "_smtp_open", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert _ok(client, h2, {**GOOD, "smtp_user": "third@gmail.com"}).status_code == 502
    assert _act(client, h2, {**GOOD, "smtp_user": "second@gmail.com"}).status_code == 400   # 重測失敗 ⇒ 先前的證明作廢


def test_activate_is_refused_when_live_config_changed_after_the_test(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_live")
    assert _ok(client, h).status_code == 200
    S = _S()
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, **_cfg(), "smtp_user": "x@y.com", "smtp_password": "other"})
    assert _act(client, h).status_code == 400
    assert _cfg()["smtp_user"] == "x@y.com"


def test_non_superadmin_cannot_activate_even_with_the_right_body(client, make_user, fake_smtp):
    hs = _h(client, make_user, "atk_r3_su")
    assert _ok(client, hs).status_code == 200
    ha = _h(client, make_user, "atk_r3_adm", role="admin")
    assert _act(client, ha).status_code == 403
    assert not _cfg().get("enabled")


# ── 綠燈：頻率限制在並發下也成立；舊端點 ────────────────────────────────────────
def test_parallel_test_me_from_one_account_never_exceeds_the_limit(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_par")
    codes = []

    def go():
        codes.append(client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code)
    ts = [threading.Thread(target=go) for _ in range(14)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert codes.count(200) <= 5, codes
    assert len(fake_smtp["opens"]) <= 5


def test_old_put_cannot_move_to_an_arbitrary_port_even_from_an_unusual_legacy_port(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r3_port")
    S = _S()
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, "smtp_host": "legacy.example.com", "smtp_port": 2526, "smtp_user": "a@b.com", "smtp_password": "p"})
    assert client.put("/api/settings/email-notify", json={"from_name": "ok"}, headers=h).status_code == 200      # 沒改埠 ⇒ 舊設定仍可存
    for port in (22, 3306, 6379, 2527):
        r = client.put("/api/settings/email-notify", json={"smtp_port": port}, headers=h)
        assert r.status_code == 422, port
    assert _cfg()["smtp_port"] == 2526


# ── 複驗新發現 ───────────────────────────────────────────────────────────────
def test_unusable_hmac_key_is_regenerated_not_a_500(client, make_user, fake_smtp):
    S = _S()
    for i, bad in enumerate(("[已遮蔽]", "zz" * 32, "ab", 123, None, ["x"], "AB" * 32 + "00")):
        h = _h(client, make_user, "atk_r3_k%d" % i)                   # 每個壞值用自己的帳號（頻率限制是每帳號 5 次）
        S._set_setting(S._WIZARD_HMAC_KEY, bad)                      # 備份匯出裡看到的值（還原後的樣子）與各種壞形狀
        assert _ok(client, h).status_code == 200, bad
        assert _act(client, h).status_code == 200, bad
        key = S._get_setting(S._WIZARD_HMAC_KEY, "")
        assert isinstance(key, str) and len(key) == 64 and bytes.fromhex(key), bad


# ── 新發現 L ────────────────────────────────────────────────────────────────
def test_numeric_string_secrets_are_masked_in_the_backup_export(client):
    import archive
    row = {"key": "some_integration", "updated_at": "x",
           "value_json": json.dumps({"api_token": "123456789012", "login_password": "12345678", "pin_secret": "0000", "enabled": True, "password_min_len": 8}, ensure_ascii=False)}
    out = json.loads(archive._general_row("系統設定", dict(row))["value_json"])
    assert out["enabled"] is True and out["password_min_len"] == 8                       # 規則設定保留（修正想要的）
    leaked = [k for k in ("api_token", "login_password", "pin_secret") if out[k] != "[已遮蔽]"]
    assert not leaked, "純數字字串的祕密沒被遮蔽：%s" % leaked
