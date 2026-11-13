# -*- coding: utf-8 -*-
"""授權匯入（T83）：授權頁的檢視／匯入端點、到期提醒、402 說明頁連結。

這份檔案守的是 helpers/license_manager.py 的 [不變式]（① 驗章不重寫 ② 只換驗過 ok 的、換後複驗失敗就還原 ③ 先備份、原子寫入
④ 驗的與存的是同一個字串 ⑤ 大小上限 ⑥ 頻率限制 ⑦ 有差異要確認 ⑧ 一次只有一個匯入 ⑨ 白話）與路由層的權限（最高管理者、非示範帳號）。

每題都走**真的簽章路徑**（真的 `sign_license`／`verify_license`，只換公鑰、機器指紋與授權檔路徑，見 conftest `license_test_key`）；
**每題都把 `LICENSE_PATH` 換到自己的暫存目錄**——conftest 的 session 金鑰檔是所有測試共用的，匯入會真的覆蓋檔案。
"""
import base64
import datetime as _dt
import json
import os

import pytest

from conftest import TEST_LICENSE_MACHINE
from helpers import license_manager as mgr
from helpers import licensing as lic

_MAKE_USER_DEFAULT_ROLE = "superadmin"
BUSINESS_API = "/api/customers"


def _in(days):
    return (_dt.date.today() + _dt.timedelta(days=days)).isoformat()


# ── 固件 ─────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """授權檔指到暫存目錄、重置頻率限制、封死外部指令（本檔不碰硬體）。"""
    def _boom(*a, **kw):
        pytest.fail("授權匯入測試不該跑外部指令：%r" % (a,))
    monkeypatch.setattr(lic, "_run", _boom)
    d = tmp_path / "lic"
    d.mkdir()
    monkeypatch.setattr(lic, "LICENSE_PATH", str(d / "license.key"))
    lic._LICENSE_FILE_CACHE = None
    lic._EMERGENCY_CACHE = None
    mgr.reset_for_tests()
    yield
    mgr.reset_for_tests()
    lic._LICENSE_FILE_CACHE = None


@pytest.fixture()
def sign(license_test_key):
    def _sign(priv_pem=None, **overrides):
        payload = {"customer": "測試用公司", "tax_id": "00000000", "machine": TEST_LICENSE_MACHINE, "modules": ["*"],
                   "issued": "2026-01-01", "expires": _in(365), "kind": lic.LICENSE_KIND_SUBSCRIPTION}
        payload.update(overrides)
        return lic.sign_license(payload, priv_pem or license_test_key["priv_pem"])
    return _sign


@pytest.fixture()
def put_current(sign):
    """把一段文字當成目前的 license.key（None＝沒有）。"""
    def _put(blob):
        path = lic.LICENSE_PATH
        if blob is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(blob + "\n")
            st = os.stat(path)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        lic._LICENSE_FILE_CACHE = None
        return path
    return _put


@pytest.fixture()
def hdr(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _post(client, hdr, content, **kw):
    body = {"content": content}
    body.update(kw)
    return client.post("/api/license/import", headers=hdr, json=body)


def _current_text():
    with open(lic.LICENSE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _backups():
    d = mgr.backup_dir()
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _other_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())


def _audit_rows(*actions):
    import db
    conn = db.get_db()
    try:
        ph = ",".join("?" * len(actions))
        return [dict(r) for r in conn.execute(
            "SELECT action, detail, username FROM audit_log WHERE action IN (%s) ORDER BY id" % ph, actions).fetchall()]
    finally:
        conn.close()


# ── 權限 ─────────────────────────────────────────────────────────────────────

def test_endpoints_require_login(client):
    assert client.get("/api/license/overview").status_code == 401
    assert client.post("/api/license/import", json={"content": "x"}).status_code == 401


@pytest.mark.parametrize("role", ["admin", "sales", "engineer", "viewer"])
def test_only_superadmin_may_view_or_import(client, make_user, put_current, sign, role):
    put_current(sign())
    username, password = make_user(username="u_" + role, role=role)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/api/license/overview", headers=h).status_code == 403
    before = _current_text()
    assert _post(client, h, sign(customer="別人想換的")).status_code == 403
    assert _current_text() == before and _backups() == []


def test_demo_account_cannot_touch_the_license(client, put_current, sign):
    """示範帳號 role＝superadmin、操作的是隔離庫，但授權檔是整台機器共用的 ⇒ 一律擋。"""
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = 'demo'", (_hash_pw("60575481"),))
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"username": "demo", "password": "60575481"})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert h["Authorization"].startswith("Bearer DEMO_")
    put_current(sign())
    before = _current_text()
    assert client.get("/api/license/overview", headers=h).status_code == 403
    r = _post(client, h, sign(customer="示範帳號想換"), apply=True, confirm=True)
    assert r.status_code == 403
    assert _current_text() == before and _backups() == []


# ── 授權壞掉時也要能用（豁免）→ 匯入新授權 → 系統恢復 ──────────────────────────────

def test_rescue_flow_from_missing_license(client, hdr, put_current, sign):
    """核心情境：這台機器沒有授權，業務 API 全 402；最高管理者在授權頁匯入後，同一個 session 立刻恢復（不需要重啟）。"""
    put_current(sign())
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200      # 登入要在有授權時
    put_current(None)
    assert client.get(BUSINESS_API, headers=hdr).status_code == 402      # 正對照：擋的是授權
    ov = client.get("/api/license/overview", headers=hdr)
    assert ov.status_code == 200, ov.text
    assert ov.json()["state"] == "missing" and ov.json()["level"] == "bad"
    r = _post(client, hdr, sign(customer="新客戶股份有限公司"), apply=True)
    assert r.status_code == 200 and r.json()["applied"] is True, r.text
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    ov = client.get("/api/license/overview", headers=hdr).json()
    assert ov["state"] == "ok" and ov["license"]["customer"] == "新客戶股份有限公司" and ov["level"] == "ok"
    assert _backups() == []                                                # 原本沒有檔，沒東西可備份


@pytest.mark.parametrize("why", ["expired", "machine_mismatch", "bad_signature"])
def test_rescue_flow_from_each_blocked_state(client, hdr, put_current, sign, why):
    put_current(sign())
    tok = hdr
    if why == "expired":
        put_current(sign(expires=_in(-3)))
    elif why == "machine_mismatch":
        put_current(sign(machine="ffffffffffffffff"))
    else:
        put_current(sign(_other_key()))
    assert client.get(BUSINESS_API, headers=tok).status_code == 402
    ov = client.get("/api/license/overview", headers=tok).json()
    assert ov["level"] == "bad" and ov["headline"]
    r = _post(client, tok, sign(customer="修好了"), apply=True, confirm=True)
    assert r.status_code == 200 and r.json()["applied"] is True, r.text
    assert client.get(BUSINESS_API, headers=tok).status_code == 200
    assert len(_backups()) == 1                                            # 舊的壞檔也備份了（要能還原）


# ── 預覽與匯入 ───────────────────────────────────────────────────────────────

def test_preview_writes_nothing(client, hdr, put_current, sign):
    put_current(sign())
    before = _current_text()
    r = _post(client, hdr, sign(customer="預覽用"))
    assert r.status_code == 200 and r.json()["reason"] == "preview" and r.json()["applied"] is False, r.text
    assert r.json()["license"]["customer"] == "預覽用"
    assert _current_text() == before and _backups() == []
    assert _audit_rows("license.import") == []


def test_apply_backs_up_old_file_and_replaces_atomically(client, hdr, put_current, sign):
    old = sign(customer="舊客戶")
    put_current(old)
    new = sign(customer="舊客戶", expires=_in(700))
    r = _post(client, hdr, new, apply=True)
    assert r.status_code == 200 and r.json()["applied"] is True, r.text
    assert r.json()["backup"] and r.json()["backup"] in _backups()
    assert _current_text().strip() == new
    with open(os.path.join(mgr.backup_dir(), r.json()["backup"]), "r", encoding="utf-8") as fh:
        assert fh.read().strip() == old                                    # 備份＝換掉之前的內容
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp")
    assert lic.verify_license()["expires"] == _in(700)                     # 快取已更新，馬上讀得到新到期日


def test_backups_are_pruned_to_the_newest_n(client, hdr, put_current, sign, monkeypatch):
    monkeypatch.setattr(mgr, "BACKUP_KEEP", 3)
    put_current(sign(customer="C0", expires=_in(100)))
    for i in range(1, 7):
        r = _post(client, hdr, sign(customer="C0", expires=_in(100 + i)), apply=True, confirm=True)
        assert r.status_code == 200, r.text
        mgr.reset_for_tests()
    assert len(_backups()) == 3


def test_upload_is_normalised_and_what_is_stored_is_what_was_verified(client, hdr, put_current, sign):
    """BOM、折行、前後空白都收；存下去的是單行、只含 base64 字元的那一串。"""
    put_current(None)
    blob = sign(customer="折行")
    wrapped = "﻿  " + "\r\n".join(blob[i:i + 40] for i in range(0, len(blob), 40)) + "  \r\n\r\n"
    r = _post(client, hdr, wrapped, apply=True)
    assert r.status_code == 200, r.text
    assert _current_text() == blob + "\n"
    assert lic.verify_license()["reason"] == "ok"


@pytest.mark.parametrize("junk", ["本文夾雜中文" , "abc def!!!", "{\"customer\": \"x\"}", "AAAA\x00BBBB"])
def test_non_base64_characters_are_rejected_not_silently_dropped(client, hdr, put_current, sign, junk):
    """`base64.b64decode` 預設會悄悄丟掉非字母表字元；若不先擋，「驗過的」與「存下去的」可能不是同一份。"""
    put_current(sign())
    before = _current_text()
    blob = sign(customer="夾雜")
    r = _post(client, hdr, blob[:20] + junk + blob[20:], apply=True)
    assert r.status_code == 400 and r.json()["reason"] == "malformed", r.text
    assert _current_text() == before and _backups() == []


# ── 拒絕（每一種都白話、都不動檔案、都有稽核）────────────────────────────────────

REJECTS = {
    "bad_signature":    (lambda sign: sign(_other_key()), 400, "沒有通過驗證"),
    "machine_mismatch": (lambda sign: sign(machine="0123456789abcdef"), 400, "給另一台電腦"),
    "expired":          (lambda sign: sign(expires=_in(-1)), 400, "已經過期"),
    "malformed":        (lambda sign: base64.b64encode(b'{"hello":"world"}').decode(), 400, "不是有效的授權檔"),
    "empty":            (lambda sign: "  \n ", 400, "沒有收到授權內容"),
}


@pytest.mark.parametrize("reason", sorted(REJECTS))
def test_rejects_with_plain_reason_and_leaves_everything_alone(client, hdr, put_current, sign, reason):
    put_current(sign())
    before = _current_text()
    make, status, phrase = REJECTS[reason]
    for apply in (False, True):
        mgr.reset_for_tests()
        r = _post(client, hdr, make(sign), apply=apply, confirm=True)
        assert r.status_code == status, r.text
        j = r.json()
        assert j["ok"] is False and j["reason"] == reason and phrase in j["message"] and j["detail"] == j["message"], j
    assert _current_text() == before and _backups() == []
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp")
    rows = _audit_rows("license.import_rejected")
    assert len(rows) == 2 and all(json.loads(x["detail"])["reason"] == reason for x in rows)
    assert not _audit_rows("license.import")


def test_expired_perpetual_license_is_also_rejected(client, hdr, put_current, sign):
    """永久授權「已過維護期」閘門雖不擋，但匯入的目的是讓系統能用 ⇒ 只收 reason=ok 的。"""
    put_current(sign())
    r = _post(client, hdr, sign(kind=lic.LICENSE_KIND_PERPETUAL, expires=_in(-30)), apply=True)
    assert r.status_code == 400 and r.json()["reason"] == "expired"


def test_machine_mismatch_names_the_customer_only_after_signature_is_verified(client, hdr, put_current, sign):
    put_current(sign())
    r = _post(client, hdr, sign(machine="0123456789abcdef", customer="別台的客戶"))
    assert r.json()["license"]["customer"] == "別台的客戶"                 # 簽章驗過，欄位才可信
    r = _post(client, hdr, sign(_other_key(), customer="偽造的客戶"))
    assert r.json().get("license") is None                                  # 簽章沒過：不回任何欄位
    assert "偽造的客戶" not in r.text


def test_machine_unreadable_is_not_reported_as_wrong_machine(client, hdr, put_current, sign, monkeypatch):
    put_current(sign())
    blob = sign(customer="讀不到指紋")
    def _cannot():
        raise RuntimeError("no hardware")
    monkeypatch.setattr(lic, "machine_fingerprint", _cannot)
    import routers.licensing as rl
    monkeypatch.setattr(rl, "_FP_FAIL_UNTIL", 0.0)
    r = _post(client, hdr, blob, apply=True)
    assert r.status_code == 400 and r.json()["reason"] == "machine_unreadable", r.text


def test_same_license_as_current_is_a_noop(client, hdr, put_current, sign):
    blob = sign()
    put_current(blob)
    r = _post(client, hdr, blob, apply=True)
    assert r.status_code == 400 and r.json()["reason"] == "same_as_current"
    assert _backups() == []


# ── 大小上限／本文格式 ───────────────────────────────────────────────────────

def test_oversized_upload_is_refused_without_parsing(client, hdr, put_current, sign):
    put_current(sign())
    before = _current_text()
    big = "A" * (mgr.MAX_UPLOAD_BYTES + 1)
    r = _post(client, hdr, big, apply=True)
    assert r.status_code == 413 and r.json()["reason"] == "too_big", r.text
    # 連 JSON 外殼都超過上限的本文：在路由層讀到上限就停（413），不進解析
    r = client.post("/api/license/import", headers=hdr, content=b'{"content":"' + b"A" * (mgr.MAX_UPLOAD_BYTES * 3) + b'"}')
    assert r.status_code == 413 and r.json()["reason"] == "too_big"
    assert _current_text() == before and _backups() == []


def test_oversized_without_content_length_is_still_capped(client, hdr, put_current, sign):
    """chunked（沒有 Content-Length）也要在讀到上限時停。"""
    put_current(sign())
    def _gen():
        for _ in range(40):
            yield b"A" * 4096
    r = client.post("/api/license/import", headers=hdr, content=_gen())
    assert r.status_code == 413, r.text


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"content": 123}', b'{"apply": true}', b""])
def test_bad_body_shapes_are_400(client, hdr, put_current, sign, body):
    put_current(sign())
    r = client.post("/api/license/import", headers={**hdr, "Content-Type": "application/json"}, content=body)
    assert r.status_code == 400 and r.json()["reason"] == "malformed", r.text


@pytest.mark.parametrize("depth", [200, 20000, 33000])
def test_deeply_nested_json_is_a_plain_400_not_a_500(client, hdr, put_current, sign, depth):
    """L1：`{"content": [[[[…` 幾萬層。以前 `json.loads` 丟 RecursionError（不是 ValueError）⇒ 500；現在是白話的 400，而且服務照常。"""
    put_current(sign())
    body = b'{"content":' + b"[" * depth + b"]" * depth + b"}"
    assert len(body) < mgr.MAX_UPLOAD_BYTES * 2 + 1024                        # 在大小上限之內（不是 413 擋掉的）
    r = client.post("/api/license/import", headers={**hdr, "Content-Type": "application/json"}, content=body)
    assert r.status_code == 400 and r.json()["reason"] == "malformed", r.text
    assert "不是有效的授權檔" in r.json()["message"]
    assert _post(client, hdr, sign(customer="之後照常")).status_code == 200


def test_the_recursion_error_net_holds_even_if_the_bracket_cap_is_removed(client, hdr, put_current, sign, monkeypatch):
    """括號數上限是第一道、`except RecursionError` 是最後一道：兩道各自獨立有效。"""
    from routers import licensing as router
    monkeypatch.setattr(router, "_MAX_JSON_BRACKETS", 10 ** 9)
    put_current(sign())
    body = b'{"content":' + b"[" * 33000 + b"]" * 33000 + b"}"
    r = client.post("/api/license/import", headers={**hdr, "Content-Type": "application/json"}, content=body)
    assert r.status_code == 400 and r.json()["reason"] == "malformed", r.text


# ── 有差異要確認 ─────────────────────────────────────────────────────────────

def test_changes_need_confirmation_before_apply(client, hdr, put_current, sign):
    put_current(sign(customer="甲公司", expires=_in(400)))
    before = _current_text()
    new = sign(customer="乙公司", expires=_in(100))
    pv = _post(client, hdr, new).json()
    assert pv["reason"] == "preview" and len(pv["warnings"]) == 2         # 客戶不同＋到期日較早
    assert any("客戶名稱" in w for w in pv["warnings"]) and any("還早" in w for w in pv["warnings"])
    r = _post(client, hdr, new, apply=True)
    assert r.status_code == 409 and r.json()["reason"] == "needs_confirm" and r.json()["applied"] is False, r.text
    assert _current_text() == before and _backups() == []                   # 沒確認，什麼都沒動
    assert not _audit_rows("license.import", "license.import_rejected")      # 要求確認不是失敗，不寫稽核
    r = _post(client, hdr, new, apply=True, confirm=True)
    assert r.status_code == 200 and r.json()["applied"] is True
    assert len(_backups()) == 1


def test_confirm_must_be_literal_true(client, hdr, put_current, sign):
    put_current(sign(customer="甲公司"))
    new = sign(customer="乙公司")
    for bad in ("true", 1, "yes", None):
        r = _post(client, hdr, new, apply=True, confirm=bad)
        assert r.status_code == 409, (bad, r.text)


def test_dev_signed_license_is_flagged_as_test_license(client, hdr, put_current, sign, license_test_key, monkeypatch):
    """開發金鑰簽的授權：閘門照舊收（既有行為，不削弱也不放寬），但匯入要明講「測試用」並要確認。"""
    monkeypatch.setattr(lic, "_PUBKEY_DEV", license_test_key["pub_pem"])
    monkeypatch.setattr(lic, "_PUBKEY_PROD", b"")
    lic._LICENSE_FILE_CACHE = None
    put_current(None)
    blob = sign(customer="測試客戶")
    pv = _post(client, hdr, blob).json()
    assert pv["license"]["test_key"] is True and any("測試用" in w for w in pv["warnings"])
    assert _post(client, hdr, blob, apply=True).status_code == 409
    assert _post(client, hdr, blob, apply=True, confirm=True).status_code == 200


def test_dev_signed_license_is_refused_outright_when_a_prod_key_is_installed(client, hdr, put_current, sign, license_test_key, monkeypatch):
    """正式公鑰已內建（`_PUBKEY_PROD` 非空）的機器：開發金鑰簽的授權一律不收——預覽就拒、`confirm` 也換不進去、不備份不寫檔。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    prod_pub = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(lic, "_PUBKEY_DEV", license_test_key["pub_pem"])
    monkeypatch.setattr(lic, "_PUBKEY_PROD", prod_pub)
    lic._LICENSE_FILE_CACHE = None
    old = sign(customer="舊的")
    put_current(old)
    before = _current_text()
    blob = sign(customer="開發金鑰簽的")
    pv = _post(client, hdr, blob)
    assert pv.status_code == 400 and pv.json()["reason"] == "dev_license_not_allowed", pv.text
    assert "測試用" in pv.json()["message"] and "簽章" not in pv.json()["message"]
    r = _post(client, hdr, blob, apply=True, confirm=True)
    assert r.status_code == 400 and r.json()["reason"] == "dev_license_not_allowed", r.text
    assert _current_text() == before and _backups() == []


def test_losing_modules_is_warned_with_names(client, hdr, put_current, sign, monkeypatch):
    from core import registry
    snap = registry.snapshot()
    registry._reset()                  # 只留本題登記的模組（真實登錄表有幾十個）
    try:
        registry.set_state("alpha_mod", "loaded", manifest={"name": "甲模組", "license_key": "alpha_mod"})
        registry.set_state("beta_mod", "unlicensed", reason="未授權", manifest={"name": "乙模組", "license_key": "beta_mod"})
        put_current(sign(modules=["*"]))
        pv = _post(client, hdr, sign(modules=["beta_mod"])).json()
        assert pv["modules_after_restart"] == {"gain": ["乙模組"], "lose": ["甲模組"]}
        assert any("甲模組" in w and "停用" in w for w in pv["warnings"])
        assert _post(client, hdr, sign(modules=["beta_mod"]), apply=True).status_code == 409
        r = _post(client, hdr, sign(modules=["beta_mod"]), apply=True, confirm=True)
        assert r.status_code == 200 and r.json()["restart_needed"] is True
        assert "重新啟動" in r.json()["message"]
    finally:
        registry.restore(snap)


# ── 失敗時的保護：寫入失敗、換後複驗失敗、備份失敗 ──────────────────────────────────

def test_write_failure_leaves_old_license_untouched(client, hdr, put_current, sign, monkeypatch):
    old = sign(customer="舊的")
    put_current(old)
    real_replace = os.replace
    def _deny(src, dst):
        raise PermissionError("locked")
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(mgr.time, "sleep", lambda s: None)
    r = _post(client, hdr, sign(customer="舊的", expires=_in(900)), apply=True)
    monkeypatch.setattr(os, "replace", real_replace)
    assert r.status_code == 500 and r.json()["reason"] == "write_failed", r.text
    assert _current_text().strip() == old
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp")


def test_verify_after_write_failure_restores_the_old_license(client, hdr, put_current, sign, monkeypatch):
    old = sign(customer="舊的")
    put_current(old)
    real = mgr._atomic_write
    def _corrupting(path, text):
        real(path, text[:-10])           # 模擬磁碟寫壞：存下去的和驗過的不一樣
    monkeypatch.setattr(mgr, "_atomic_write", _corrupting)
    r = _post(client, hdr, sign(customer="舊的", expires=_in(900)), apply=True)
    assert r.status_code == 500 and r.json()["reason"] == "verify_after_write_failed", r.text
    monkeypatch.setattr(mgr, "_atomic_write", real)
    assert _current_text().strip() == old                                    # 還原成原本的
    assert lic.verify_license()["reason"] == "ok"
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_verify_after_write_failure_with_no_prior_license_removes_the_new_file(client, hdr, put_current, sign, monkeypatch):
    put_current(None)
    real = mgr._atomic_write
    monkeypatch.setattr(mgr, "_atomic_write", lambda path, text: real(path, text[:-10]))
    r = _post(client, hdr, sign(), apply=True)
    assert r.status_code == 500 and r.json()["reason"] == "verify_after_write_failed"
    assert not os.path.exists(lic.LICENSE_PATH)


@pytest.mark.parametrize("had_old", [True, False])
def test_any_exception_after_the_swap_restores_the_old_state(client, hdr, put_current, sign, monkeypatch, had_old):
    """L2：新檔已經換上去之後，複驗**丟例外**（不是回「不通過」）也要還原；不可以留下「換了一半、沒複驗」的檔案。"""
    old = sign(customer="舊的")
    put_current(old if had_old else None)
    new = sign(customer="新的", expires=_in(900))
    real = lic.verify_license

    def _flaky(blob=None):
        if blob is None:
            try:
                with open(lic.LICENSE_PATH, "r", encoding="utf-8") as fh:
                    if new in fh.read():                                         # 只在「檔案已經是新的」時丟：就是換後複驗那一次
                        raise RuntimeError("boom")
            except OSError:
                pass
        return real(blob)
    monkeypatch.setattr(lic, "verify_license", _flaky)
    r = _post(client, hdr, new, apply=True, confirm=True)
    monkeypatch.setattr(lic, "verify_license", real)
    assert r.status_code == 500 and r.json()["reason"] == "verify_after_write_failed", r.text
    if had_old:
        assert _current_text().strip() == old
    else:
        assert not os.path.exists(lic.LICENSE_PATH)
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp") and not os.path.exists(lic.LICENSE_PATH + ".restore-tmp")
    if had_old:
        assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_backup_failure_means_no_replacement(client, hdr, put_current, sign, monkeypatch):
    old = sign(customer="舊的")
    put_current(old)
    def _nope(path):
        raise OSError("disk full")
    monkeypatch.setattr(mgr, "_backup_current", _nope)
    r = _post(client, hdr, sign(customer="舊的", expires=_in(900)), apply=True)
    assert r.status_code == 500 and r.json()["reason"] == "backup_failed", r.text
    assert _current_text().strip() == old


def test_concurrent_import_is_refused_as_busy(client, hdr, put_current, sign):
    put_current(sign())
    assert mgr._IMPORT_LOCK.acquire(blocking=False)
    try:
        r = _post(client, hdr, sign(customer="搶著換", expires=_in(900)), apply=True, confirm=True)
    finally:
        mgr._IMPORT_LOCK.release()
    assert r.status_code == 409 and r.json()["reason"] == "busy", r.text


# ── 頻率限制（每個帳號＋寬鬆的全域；預覽半點、正式匯入 1 點）──────────────────────────

def _login_another_superadmin(client, make_user, name):
    username, password = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_rate_limit_counts_every_apply_and_audits_only_the_first_block(client, hdr, put_current, sign):
    put_current(sign())
    codes = [_post(client, hdr, "AAAA", apply=True).status_code for _ in range(mgr.RATE_MAX)]
    assert set(codes) == {400}
    r = _post(client, hdr, sign())                                           # 第 RATE_MAX+1 次：連有效授權也擋
    assert r.status_code == 429 and r.json()["reason"] == "rate_limited" and int(r.headers["Retry-After"]) > 0, r.text
    assert r.json()["retryAfter"] == int(r.headers["Retry-After"])
    for _ in range(3):
        assert _post(client, hdr, sign()).status_code == 429
    limited = [x for x in _audit_rows("license.import_rejected") if json.loads(x["detail"]).get("reason") == "rate_limited"]
    assert len(limited) == 1                                                  # 被灌時不連稽核表一起灌爆


def test_previews_cost_half_as_much_as_imports(client, hdr, put_current, sign):
    put_current(sign())
    n = int(mgr.RATE_MAX / mgr.PREVIEW_WEIGHT)
    assert {_post(client, hdr, "AAAA").status_code for _ in range(n)} == {400}      # 預覽可以比正式匯入多一倍
    assert _post(client, hdr, "AAAA").status_code == 429


def test_one_accounts_flood_does_not_lock_out_the_other_superadmins(client, make_user, hdr, put_current, sign):
    """被盜的一個 session 灌到被限流之後，其他最高管理者照常能預覽、匯入（L4）。"""
    put_current(None)
    for _ in range(mgr.RATE_MAX):
        _post(client, hdr, "AAAA", apply=True)
    assert _post(client, hdr, "AAAA").status_code == 429                      # 第一個帳號被鎖
    other = _login_another_superadmin(client, make_user, "su_second")
    assert _post(client, other, "AAAA").status_code == 400                    # 第二個帳號不受影響（格式不對，但沒被限流）
    r = _post(client, other, sign(customer="第二位管理者匯入"), apply=True)
    assert r.status_code == 200 and r.json()["applied"] is True, r.text


def test_rate_window_slides_per_account():
    t = 1000.0
    for i in range(mgr.RATE_MAX):
        assert mgr.rate_allow("a", now=t + i)[0] is True
    ok, retry, first = mgr.rate_allow("a", now=t + 20)
    assert (ok, first) == (False, True) and 1 <= retry <= mgr.RATE_WINDOW_S
    assert mgr.rate_allow("a", now=t + 21)[2] is False                         # 同一視窗第二次被擋：不再是「第一次」
    assert mgr.rate_allow("b", now=t + 21)[0] is True                          # 別的帳號不受影響
    assert mgr.rate_allow("a", now=t + mgr.RATE_WINDOW_S + 1)[0] is True       # 視窗過了就恢復


def test_weights_add_up_and_a_blocked_try_records_nothing():
    t = 5000.0
    assert mgr.rate_allow("w", mgr.PREVIEW_WEIGHT, now=t)[0] and mgr.rate_allow("w", mgr.PREVIEW_WEIGHT, now=t)[0]
    for _ in range(mgr.RATE_MAX - 1):
        assert mgr.rate_allow("w", 1.0, now=t)[0] is True                      # 1 + 9 ＝ 10 點用完
    assert mgr.rate_allow("w", mgr.PREVIEW_WEIGHT, now=t)[0] is False
    assert mgr.rate_allow("x", now=t)[0] is True                               # 被擋的嘗試沒有佔掉全域的點數


def test_global_cap_is_looser_but_still_there():
    assert mgr.RATE_GLOBAL_MAX > mgr.RATE_MAX * 2                              # 比單一帳號寬鬆，不然就退化成全域限流
    t = 9000.0
    for i in range(mgr.RATE_GLOBAL_MAX):
        assert mgr.rate_allow("acct%d" % i, now=t)[0] is True
    ok, _retry, first = mgr.rate_allow("one-more", now=t)
    assert (ok, first) == (False, True)                                        # 很多帳號一起灌：全域擋住
    assert mgr.rate_allow("acct0", now=t)[2] is False


# ── 稽核 ─────────────────────────────────────────────────────────────────────

def test_success_is_audited_without_license_content(client, hdr, put_current, sign):
    put_current(sign(customer="舊客戶"))
    new = sign(customer="舊客戶", expires=_in(800))
    assert _post(client, hdr, new, apply=True).status_code == 200
    rows = _audit_rows("license.import")
    assert len(rows) == 1
    d = json.loads(rows[0]["detail"])
    assert d["customer"] == "舊客戶" and d["expires"] == _in(800) and d["backup"] and d["apply"] is True
    assert len(d["file_id"]) == 12
    assert new not in rows[0]["detail"] and new[:30] not in rows[0]["detail"]   # 稽核不存授權內容
    assert rows[0]["username"]                                                  # 記得是誰


# ── 白話：授權頁資料不出現簽章／雜湊字樣 ─────────────────────────────────────────

BANNED = ("簽章", "指紋", "hash", "Hash", "sha256", "base64", "bad_signature", "machine_mismatch", "fingerprint", "Ed25519", "payload")


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in ("machine_code", "state", "level", "kind", "reason", "bucket"):   # 機器代碼是給供應商的值；其餘是給程式判斷的代碼
                yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


@pytest.mark.parametrize("state", ["ok", "soon", "expired", "perpetual_ended", "machine_mismatch", "missing", "bad_signature", "malformed"])
def test_overview_is_plain_language_in_every_state(client, hdr, put_current, sign, state):
    if state == "ok":
        put_current(sign())
    elif state == "soon":
        put_current(sign(expires=_in(10)))
    elif state == "expired":
        put_current(sign(expires=_in(-2)))
    elif state == "perpetual_ended":
        put_current(sign(kind=lic.LICENSE_KIND_PERPETUAL, expires=_in(-2)))
    elif state == "machine_mismatch":
        put_current(sign(machine="0123456789abcdef"))
    elif state == "missing":
        put_current(None)
    elif state == "bad_signature":
        put_current(sign(_other_key()))
    else:
        put_current("AAAA")
    r = client.get("/api/license/overview", headers=hdr)
    assert r.status_code == 200, r.text
    d = r.json()
    for s in _strings(d):
        for w in BANNED:
            assert w not in s, (state, w, s)
    assert d["headline"] and d["level"] in ("ok", "notice", "warning", "critical", "bad", "info")
    assert d["machine_text"]


def test_overview_shows_customer_expiry_modules_and_machine_binding(client, hdr, put_current, sign):
    from core import registry
    snap = registry.snapshot()
    registry._reset()                  # 只留本題登記的模組（真實登錄表有幾十個）
    try:
        registry.set_state("alpha_mod", "loaded", manifest={"name": "甲模組", "license_key": "alpha_mod"})
        put_current(sign(customer="顯示用公司", expires=_in(200), modules=["alpha_mod", "gone_mod"]))
        d = client.get("/api/license/overview", headers=hdr).json()
    finally:
        registry.restore(snap)
    L = d["license"]
    assert L["customer"] == "顯示用公司" and L["expires"] == _in(200) and L["days_left"] == 200 and "200" in L["days_text"]
    assert L["modules"] == {"all": False, "names": ["甲模組"], "unknown": 1, "invalid": False}
    assert d["machine_text"] == "已綁定這台電腦" and d["machine_code"] == TEST_LICENSE_MACHINE
    assert d["max_upload_bytes"] == mgr.MAX_UPLOAD_BYTES


def test_overview_lists_recent_imports(client, hdr, put_current, sign):
    put_current(sign())
    _post(client, hdr, sign(machine="0123456789abcdef"), apply=True)
    _post(client, hdr, sign(customer="測試用公司", expires=_in(900)), apply=True, confirm=True)
    rec = client.get("/api/license/overview", headers=hdr).json()["recent"]
    assert len(rec) == 2 and "成功" in rec[0]["what"] and "另一台電腦" in rec[1]["what"]
    assert all(r["who"] and r["at"] for r in rec)


# ── 到期提醒 ─────────────────────────────────────────────────────────────────

def _status(days, kind=lic.LICENSE_KIND_SUBSCRIPTION, reason="ok"):
    return {"valid": reason == "ok", "reason": reason, "days_left": days, "kind": kind, "expires": _in(days), "env": "prod"}


@pytest.mark.parametrize("days,level,bucket", [(31, None, None), (30, "notice", 30), (15, "notice", 30), (14, "warning", 14),
                                               (8, "warning", 14), (7, "critical", 7), (0, "critical", 7)])
def test_expiry_reminder_thresholds(days, level, bucket):
    r = lic.expiry_reminder(_status(days))
    if level is None:
        assert r is None
    else:
        assert (r["level"], r["bucket"], r["days"]) == (level, bucket, days)


def test_expiry_reminder_only_for_usable_licenses():
    assert lic.expiry_reminder(_status(5, reason="machine_mismatch")) is None
    assert lic.expiry_reminder(_status(-2, reason="expired")) is None                      # 年費過期＝閘門 402，說明頁處理
    ended = lic.expiry_reminder(_status(-2, kind=lic.LICENSE_KIND_PERPETUAL, reason="expired"))
    assert ended["level"] == "ended" and ended["bucket"] == "ended"
    assert lic.expiry_reminder(None) is None and lic.expiry_reminder({"days_left": "x"}) is None
    assert lic.expiry_reminder({"reason": "ok", "days_left": True, "kind": "subscription"}) is None
    assert lic.expiry_banner(_status(20)) == "days=20;level=notice;kind=subscription"
    assert lic.expiry_banner(_status(10)) == "days=10;level=warning;kind=subscription"
    assert lic.expiry_banner(_status(100)) is None


def test_expiry_header_on_authed_responses(client, hdr, put_current, sign):
    put_current(sign(expires=_in(100)))
    assert client.get(BUSINESS_API, headers=hdr).headers[lic.EXPIRY_HEADER] == "none"
    put_current(sign(expires=_in(20)))
    assert client.get(BUSINESS_API, headers=hdr).headers[lic.EXPIRY_HEADER] == "days=20;level=notice;kind=subscription"
    put_current(sign(expires=_in(5)))
    assert client.get(BUSINESS_API, headers=hdr).headers[lic.EXPIRY_HEADER] == "days=5;level=critical;kind=subscription"
    put_current(sign(kind=lic.LICENSE_KIND_PERPETUAL, expires=_in(-4)))
    assert client.get(BUSINESS_API, headers=hdr).headers[lic.EXPIRY_HEADER] == "days=-4;level=ended;kind=perpetual"
    # 未登入／公開端點：沒有標頭（不洩漏授權狀態，也不讓前端橫幅閃掉）
    assert lic.EXPIRY_HEADER not in client.get("/api/ping").headers


@pytest.mark.parametrize("role", ["admin", "sales", "engineer", "viewer"])
def test_expiry_header_is_for_superadmin_only(client, make_user, hdr, put_current, sign, role):
    """L5：剩幾天到期是商務資訊——其他角色的回應根本不帶這個標頭（橫幅也就不會出現）。"""
    put_current(sign(expires=_in(5)))
    assert client.get(BUSINESS_API, headers=hdr).headers[lic.EXPIRY_HEADER].startswith("days=5;")
    username, password = make_user(username="hdr_" + role, role=role)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    resp = client.get(BUSINESS_API, headers=h)
    assert resp.status_code in (200, 403), resp.status_code
    assert lic.EXPIRY_HEADER not in resp.headers
    assert "days=" not in "".join("%s: %s" % kv for kv in resp.headers.items()).lower()


def test_banner_script_and_402_page_show_expiry_details_to_superadmin_only():
    js = _read("frontend/static/notif.js")
    i = js.index("function _licenseExpiryBanner")
    body = js[i:js.index("function _isApi", i)]
    assert "role !== 'superadmin'" in body and "請通知最高管理者" not in body        # 其他角色：不顯示、也沒有「通知最高管理者」的替代文案
    html = _page("license-required.html")
    assert "if (!isSuper) return" in html and "請聯絡您的系統管理員" in html          # 其他角色的說明頁：只有「請聯絡系統管理員」，沒有狀態代碼／機器代碼／到期日


def test_expiry_header_is_independent_of_the_existing_banner_header(client, hdr, put_current, sign):
    put_current(sign(expires=_in(5)))
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.headers[lic.LICENSE_HEADER] == "none" and r.headers[lic.EXPIRY_HEADER].startswith("days=5;")


# ── 每日通知（30／14／7 各一次）──────────────────────────────────────────────────

@pytest.fixture()
def notices(monkeypatch, client):
    from helpers import license_alerts as la
    got = []
    monkeypatch.setattr(la, "expiry_notice", lambda rem, st: got.append(dict(rem)) or True)
    import helpers.system_checks as sc
    real_thread = sc.threading.Thread

    class _Sync:
        def __init__(self, target=None, args=(), **kw):
            self._t, self._a = target, args
        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(sc.threading, "Thread", _Sync)
    from helpers import _set_setting
    _set_setting("license_expiry_notified", "")
    yield got


def test_daily_check_notifies_once_per_threshold(notices, put_current, sign):
    import helpers.system_checks as sc
    put_current(sign(expires=_in(100)))
    sc._check_license_expiry()
    assert notices == []                                                       # 還很遠
    put_current(sign(expires=_in(29)))
    sc._check_license_expiry(); sc._check_license_expiry()
    assert [n["bucket"] for n in notices] == [30]                              # 同一檔位只一次
    put_current(sign(expires=_in(14)))
    sc._check_license_expiry(); sc._check_license_expiry()
    put_current(sign(expires=_in(6)))
    sc._check_license_expiry(); sc._check_license_expiry()
    assert [n["bucket"] for n in notices] == [30, 14, 7]
    put_current(sign(expires=_in(400)))                                          # 續約 ⇒ 旗標清掉
    sc._check_license_expiry()
    put_current(sign(expires=_in(20)))                                           # 下一年又快到期 ⇒ 重新通知
    sc._check_license_expiry()
    assert [n["bucket"] for n in notices] == [30, 14, 7, 30]


def test_daily_check_retries_tomorrow_when_the_send_did_not_go_out(monkeypatch, notices, put_current, sign):
    import helpers.system_checks as sc
    from helpers import license_alerts as la
    put_current(sign(expires=_in(20)))
    monkeypatch.setattr(la, "expiry_notice", lambda rem, st: False)              # 沒寄成（例如沒有收件人）
    sc._check_license_expiry()
    monkeypatch.setattr(la, "expiry_notice", lambda rem, st: notices.append(dict(rem)) or True)
    sc._check_license_expiry()
    assert [n["bucket"] for n in notices] == [30]


def test_daily_check_does_nothing_when_gate_is_off(notices, put_current, sign, monkeypatch):
    import helpers.system_checks as sc
    put_current(sign(expires=_in(3)))
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    called = []
    monkeypatch.setattr(lic, "verify_license", lambda *a, **k: called.append(1))
    sc._check_license_expiry()
    assert notices == [] and called == []


def test_expiry_mail_type_is_registered_for_superadmins_and_locked():
    from helpers import mail_types, notify_matrix
    mt = mail_types.get("license_expiry")
    assert mt is not None and mt.group == "superadmins"
    assert "license_expiry" in notify_matrix.MAIL_OFF_LOCKED


def test_expiry_line_event_is_wired_critical_and_default_off(client):
    """信件類型、LINE 事件、接線三處要一起在：少了 LINE_EVENTS 條目，管理者在 LINE 設定頁永遠勾不到這一類。
    LINE 預設全關慣例：沒勾選之前不發。"""
    from helpers import line_catalog, line_notify as L, mail_types
    assert mail_types.get("license_expiry") is not None
    assert "license_expiry" in L.LINE_EVENTS and "license_expiry" in L.WIRED_EVENTS
    spec = L.LINE_EVENTS["license_expiry"]
    assert spec["priority"] == "critical" and spec["digest"] is False and spec["line_group"] == "inherit"
    assert L.events_view().get("license_expiry") is False
    assert L.event_enabled("license_expiry") is False
    assert line_catalog.group_of("license_expiry") == "系統告警"


# ── 前端：402 說明頁連結、授權頁、橫幅 ───────────────────────────────────────────

def _page(name):
    from core import source_tree
    return source_tree.page_file(name).read_text(encoding="utf-8")


def _read(rel):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "..", rel), "r", encoding="utf-8") as fh:
        return fh.read()


def test_402_page_links_to_license_page_for_superadmin_only():
    html = _page("license-required.html")
    assert 'id="lr-import"' in html and 'href="license-settings.html"' in html and "前往授權頁匯入" in html
    i = html.index('id="lr-import"')
    assert "hidden" in html[i:i + 120]                                          # 預設隱藏
    assert "sess.role === 'superadmin'" in html                                 # 只有最高管理者才顯示


def test_license_page_is_registered_and_not_redirected_away_by_402():
    pages = json.loads(_read("backend/core/l1_pages.json"))
    assert "license-settings.html" in pages
    menu = json.loads(_read("backend/core/menu_l1.json"))
    items = [m for m in (menu["items"] if isinstance(menu, dict) else menu) if m.get("href") == "license-settings.html"]
    assert len(items) == 1 and items[0]["perm"] == "superadmin"
    assert "here402 !== 'license-settings.html'" in _read("frontend/static/notif.js")   # 402 時不被導離這一頁（否則救不回來）
    import re
    page = re.sub(r"<!--.*?-->", "", _page("license-settings.html"), flags=re.S)   # 註解可以講它刻意沒做的事
    assert "innerHTML" not in page                                              # 伺服器回的文字一律 textContent
    for forbidden in ("/api/customers", "sidebar", "auth-guard", "Alpine", "x-data"):
        assert forbidden not in page, forbidden                                  # 只碰豁免端點，不載入會打業務 API 的東西
    assert page.count("/api/license/") == 2 and "/api/license/overview" in page and "/api/license/import" in page


# ── 不削弱 T80：沒有私鑰、沒有繞過 ─────────────────────────────────────────────

def test_import_code_has_no_signing_no_private_keys_and_no_download():
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in ("helpers/license_manager.py", "routers/licensing.py"):
        with open(os.path.join(here, "..", rel), "r", encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for needle in ("sign_license", "issue_license", "PRIVATE KEY", "private_key", "_license_private_key", "FileResponse",
                       "_PUBKEY_DEV =", "_PUBKEY_PROD =", "LICENSE_GATE_ENABLED ="):
            assert needle not in code, (rel, needle)
    # 驗章只有一條路：license_manager 呼叫 licensing.verify_license，沒有自己的 Ed25519／base64 驗證
    import ast
    with open(os.path.join(here, "..", "helpers/license_manager.py"), "r", encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not ({"base64", "binascii", "cryptography"} & imported), imported      # 沒有自己的驗章／編解碼
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "verify_license" in calls                                               # 驗章只走 licensing.verify_license


def test_an_emergency_pass_is_not_an_importable_license(client, hdr, put_current, sign, license_test_key):
    """通行證（purpose=emergency_pass）缺授權金鑰必要欄位 ⇒ 不是授權：匯入端不可以把它當授權換上去。"""
    put_current(sign())
    before = _current_text()
    token = lic.sign_license({"purpose": lic.EMERGENCY_PURPOSE, "tax_id": "00000000", "machine": TEST_LICENSE_MACHINE,
                              "issued": _dt.date.today().isoformat(), "expires": _in(5), "reason": "試試看"}, license_test_key["priv_pem"])
    r = _post(client, hdr, token, apply=True, confirm=True)
    assert r.status_code == 400 and r.json()["reason"] == "malformed", r.text
    assert _current_text() == before and _backups() == []


def test_backups_and_temp_files_are_never_tracked():
    ignore = _read(".gitignore")
    assert "backend/license_backups/" in ignore and "backend/license.key.*-tmp" in ignore


# ── 套用／回滾腳本不可以碰授權的備份與暫存（L3）─────────────────────────────────────

def _ps_statements(name):
    """腳本的 robocopy 敘述（接續行 ` 併回同一行）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "tools", name), "r", encoding="utf-8-sig") as fh:
        text = fh.read().replace("`" + chr(13) + chr(10), " ").replace("`" + chr(10), " ")
    return [l.strip() for l in text.splitlines() if "robocopy" in l and not l.lstrip().startswith("#")]


@pytest.mark.parametrize("name,expected", [("apply_update.ps1", 7), ("rollback_update.ps1", 3)])
def test_apply_and_rollback_never_touch_license_backups_or_import_tmp_files(name, expected):
    """授權匯入會在授權檔旁邊留 `license_backups/`（每次換檔前的舊檔）與 `license.key.import-tmp`／`.restore-tmp`（換檔瞬間的暫存）。
    它們跟 `license.key` 一樣是這台機器的東西，不在部署包、也不在快照裡：任何一份 robocopy 的排除清單沒列它們，
    還原快照時就會被當成「快照沒有的檔」清掉（或寫回舊版），備份就沒了。"""
    stmts = [l for l in _ps_statements(name) if "/XF" in l and "license.key" in l]
    assert len(stmts) == expected, "量法壞了或有人新增／刪掉一份排除清單（要同步檢查）：%d vs %d" % (len(stmts), expected)
    import re
    for l in stmts:
        xd, xf = l.split("/XF", 1)
        assert re.search(r"(?<![\w.])license_backups(?![\w.])", xd), ("/XD 沒有 license_backups", l[:140])
        for tmp in ("license.key.import-tmp", "license.key.restore-tmp"):
            assert tmp in xf.split(), (tmp, l[:140])


def test_the_excluded_tmp_names_are_the_ones_license_manager_really_writes():
    """排除清單列的暫存檔名要和程式真正用的同一個——改名時這題會叫（不然排除清單悄悄失效）。"""
    src = _read("backend/helpers/license_manager.py")
    assert 'path + ".import-tmp"' in src and 'path + ".restore-tmp"' in src
    assert mgr.BACKUP_DIR_NAME == "license_backups"


def test_verify_package_refuses_license_backups_and_import_tmp_files():
    """出貨包不可以帶著授權備份資料夾或換檔暫存檔（`*.key` 已擋備份檔本身；暫存檔 `license.key.import-tmp` 副檔名不是 .key，要另外擋）。"""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_vp_license_probe", os.path.join(here, "..", "tools", "verify_package.py"))
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    bad = {code: fn for code, _why, fn in vp.BAD}
    assert bad["license-backups"]("backend/license_backups/license_x.txt", "license_x.txt")
    assert bad["license-backups"]("backend\\license_backups\\a.txt", "a.txt")
    assert not bad["license-backups"]("backend/helpers/license_manager.py", "license_manager.py")
    for name in ("license.key.import-tmp", "license.key.restore-tmp"):
        assert bad["license-tmp"]("backend/" + name, name)
    assert not bad["license-tmp"]("backend/helpers/licensing.py", "licensing.py")


# ── GET /api/license/status：完整狀態只給最高管理者（PM 裁示，T83 L5 追加）────────────────

_SLIM_KEYS = {"valid", "reason", "gate", "blocked", "emergency", "modules_unlicensed_count"}


def _login(client, make_user, name, role):
    username, password = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_status_is_complete_for_superadmin_exactly_as_before(client, hdr, put_current, sign):
    put_current(sign(customer="某某股份有限公司", expires=_in(20)))
    s = client.get("/api/license/status", headers=hdr).json()
    assert s["customer"] == "某某股份有限公司" and s["expires"] == _in(20) and s["days_left"] == 20
    for k in ("valid", "reason", "modules", "env", "machine", "emergency", "gate", "blocked", "modules_unlicensed"):
        assert k in s, k
    assert "modules_unlicensed_count" not in s


@pytest.mark.parametrize("role", ["admin", "sales", "engineer", "viewer"])
def test_status_is_slim_for_every_other_role(client, make_user, put_current, sign, role):
    put_current(sign(customer="某某股份有限公司", expires=_in(20)))
    h = _login(client, make_user, "st_" + role, role)
    r = client.get("/api/license/status", headers=h)
    assert r.status_code == 200 and set(r.json()) == _SLIM_KEYS, r.text
    s = r.json()
    assert s["valid"] is True and s["reason"] == "ok" and s["blocked"] is False and s["gate"] is True and s["emergency"] is None
    for leak in ("某某股份有限公司", _in(20), TEST_LICENSE_MACHINE):
        assert leak not in r.text, leak
    for k in ("days_left", "expires", "customer", "machine", "modules", "env"):      # 以鍵名判斷（modules 是 modules_unlicensed_count 的子字串）
        assert k not in s, k


@pytest.mark.parametrize("state", ["missing", "expired", "machine_mismatch", "bad_signature"])
def test_slim_status_still_tells_the_front_end_to_block(client, make_user, put_current, sign, state):
    """精簡版仍然夠前端判斷「擋不擋」：blocked／reason 與完整版一致。"""
    blobs = {"missing": None, "expired": lambda: sign(expires=_in(-3)), "machine_mismatch": lambda: sign(machine="0123456789abcdef"),
             "bad_signature": lambda: sign(_other_key())}
    b = blobs[state]
    put_current(b() if callable(b) else None)
    h = _login(client, make_user, "slim_" + state, "admin")
    s = client.get("/api/license/status", headers=h).json()
    assert s["reason"] == state and s["valid"] is False and s["blocked"] is True and set(s) == _SLIM_KEYS


def test_demo_account_gets_the_slim_status(client, put_current, sign):
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = 'demo'", (_hash_pw("60575481"),))
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"username": "demo", "password": "60575481"})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    put_current(sign(customer="正式客戶不給示範看", expires=_in(20)))
    resp = client.get("/api/license/status", headers=h)
    assert resp.status_code == 200 and set(resp.json()) == _SLIM_KEYS and "正式客戶不給示範看" not in resp.text


def test_402_page_works_with_the_slim_status_for_non_superadmin():
    html = _page("license-required.html")
    assert "modules_unlicensed_count" in html                                   # 精簡版只帶件數
    assert "s.blocked === false || s.gate === false || (s.emergency && s.emergency.active)" in html   # 判斷用的欄位精簡版都有


# ── L6：還原也失敗時，不可以對使用者說「已自動還原」 ────────────────────────────────────

def _force_after_swap_failure(monkeypatch, deny_restore):
    import shutil
    real = lic.verify_license
    n = {"c": 0}

    def flaky(blob=None):
        if blob is None:
            n["c"] += 1
            if n["c"] >= 2:                                       # 第 1 次＝匯入前讀目前授權；第 2 次＝換檔後複驗
                return dict(real(), reason="machine_mismatch", valid=False)
        return real(blob)
    monkeypatch.setattr(lic, "verify_license", flaky)
    if deny_restore:
        real_copy, real_remove = shutil.copyfile, os.remove

        def deny_copy(src, dst, *a, **k):
            if str(dst).endswith(".restore-tmp"):
                raise OSError("denied")
            return real_copy(src, dst, *a, **k)

        def deny_rm(path, *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(lic.LICENSE_PATH):
                raise OSError("denied")
            return real_remove(path, *a, **k)
        monkeypatch.setattr(shutil, "copyfile", deny_copy)
        monkeypatch.setattr(os, "remove", deny_rm)


@pytest.mark.parametrize("had_old", [True, False])
def test_l6_restore_failure_is_reported_honestly(client, hdr, put_current, sign, monkeypatch, caplog, had_old):
    if had_old:
        put_current(sign(customer="原本"))
    _force_after_swap_failure(monkeypatch, deny_restore=True)
    with caplog.at_level("ERROR"):
        r = client.post("/api/license/import", headers=hdr, json={"content": sign(customer="新的", expires=_in(900)), "apply": True, "confirm": True})
    j = r.json()
    assert r.status_code == 500 and j["reason"] == "restore_failed", r.text
    assert "已自動還原" not in j["message"] and "無法自動還原舊授權" in j["message"] and "聯絡供應商" in j["message"]
    assert any("還原舊授權失敗" in m for m in caplog.messages)
    import db
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT detail FROM audit_log WHERE action = 'license.import_restore_failed'").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1 and "新的" not in rows[0]["detail"]                 # 有這一筆稽核，且不含授權內容


def test_l6_restore_success_still_says_restored(client, hdr, put_current, sign, monkeypatch):
    put_current(sign(customer="原本"))
    _force_after_swap_failure(monkeypatch, deny_restore=False)
    r = client.post("/api/license/import", headers=hdr, json={"content": sign(customer="新的", expires=_in(900)), "apply": True, "confirm": True})
    assert r.status_code == 500 and r.json()["reason"] == "verify_after_write_failed" and "已自動還原" in r.json()["message"]


def test_l6_restore_helper_returns_a_bool():
    import inspect
    from helpers import license_manager as M
    src = inspect.getsource(M._restore)
    assert "return ok" in src and "restore_failed" in inspect.getsource(M._after_swap_failed)
    assert "license.import_restore_failed" in open(M.__file__.replace("helpers", "routers").replace("license_manager", "licensing"), encoding="utf-8").read()
