# -*- coding: utf-8 -*-
"""hichan-3 對 feat/license-import-ui（099e0e996）的對抗式攻擊測試。獨立分支 h3/attack-license-import，不進 hichan-12 的分支。

每題的標題前綴＝發現編號（見審查回報）。「綠」＝這個攻擊沒成功（或行為符合預期）；「紅」＝發現。
"""
import base64
import datetime as _dt
import json
import os
import threading

import pytest

from conftest import TEST_LICENSE_MACHINE
from helpers import license_manager as mgr
from helpers import licensing as lic

_MAKE_USER_DEFAULT_ROLE = "superadmin"
BUSINESS_API = "/api/customers"
TODAY = _dt.date.today()


def _in(days):
    return (TODAY + _dt.timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(lic, "_run", lambda *a, **k: pytest.fail("不該跑外部指令"))
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
def put_current():
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


def _login(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def su(client, make_user):
    return _login(client, make_user, "atk_su", "superadmin")


def _post(client, h, content, **kw):
    body = {"content": content}
    body.update(kw)
    return client.post("/api/license/import", headers=h, json=body)


def _text():
    with open(lic.LICENSE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _backups():
    d = mgr.backup_dir()
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


# ═══ ① 豁免路徑：未登入／非最高管理者／路徑變體／方法 ═══════════════════════════════════

VARIANTS = ["/api/license/import/", "/api/license/import//", "/api/license//import", "/api/license/Import", "/api/License/import",
            "/API/license/import", "//api/license/import", "/api/license/import%2F", "/api/license/%69mport", "/api/license/import;x=1",
            "/api/license/import%00", "/api/license/./import", "/api/license/x/../import", "/api/license/import.json"]
OV_VARIANTS = [v.replace("import", "overview") for v in VARIANTS]


@pytest.mark.parametrize("path", VARIANTS + OV_VARIANTS)
@pytest.mark.parametrize("state", ["blocked", "valid"])
def test_atk1_path_variants_never_serve_without_superadmin(client, make_user, put_current, sign, path, state):
    """授權壞掉（402 狀態）與正常時，路徑變體對 未登入／一般帳號 都不會拿到 200；也不得因為「像豁免」而繞過閘門。"""
    put_current(sign() if state == "valid" else None)
    sales = _login(client, make_user, "atk_sales", "sales") if state == "valid" else None
    for method in ("get", "post"):
        for h in (None, sales):
            if h is None and False:
                continue
            kw = {"headers": h} if h else {}
            if method == "post":
                kw["json"] = {"content": "x"}
            r = getattr(client, method)(path, follow_redirects=False, **kw)
            assert r.status_code != 200, (method, path, state, h is not None, r.status_code, r.text[:120])
            assert "customer" not in r.text or r.status_code >= 400


@pytest.mark.parametrize("path", ["/api/license/import", "/api/license/overview"])
def test_atk1_exempt_endpoints_unauth_and_wrong_role_when_blocked(client, make_user, put_current, sign, path):
    """授權失效時（業務 API 402）：未登入一律 401（不洩漏「沒有授權」）；一般管理員／業務 403。"""
    put_current(sign())
    sales = _login(client, make_user, "atk_s2", "sales")
    admin = _login(client, make_user, "atk_a2", "admin")
    put_current(None)
    assert client.get(BUSINESS_API, headers=sales).status_code == 402          # 正對照
    for method in ("get", "post"):
        kw = {"json": {"content": "x"}} if method == "post" else {}
        if (path.endswith("import")) != (method == "post"):
            continue
        r = getattr(client, method)(path, **kw)
        assert r.status_code == 401 and "授權" not in r.text and "license" not in r.text.lower(), r.text
        for h in (sales, admin):
            r = getattr(client, method)(path, headers=h, **kw)
            assert r.status_code == 403, (path, r.status_code, r.text[:100])


@pytest.mark.parametrize("method", ["head", "options", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ["/api/license/import", "/api/license/overview"])
def test_atk1_other_methods_do_not_reach_handlers(client, su, put_current, sign, method, path):
    put_current(sign())
    r = getattr(client, method)(path, headers=su)
    assert r.status_code in (400, 401, 403, 404, 405), (method, path, r.status_code)
    assert not os.path.isdir(mgr.backup_dir())


def test_atk1_company_setup_allowlist_in_sync():
    import main
    for key in (("GET", "/api/license/overview"), ("POST", "/api/license/import")):
        assert key in main._COMPANY_SETUP_ALLOWED
    for p in ("/api/license/overview", "/api/license/import"):
        assert p in lic.LICENSE_EXEMPT_PATHS
    assert lic.LICENSE_EXEMPT_PATHS == {"/api/ping", "/api/auth/login", "/api/auth/logout", "/api/license/status",
                                        "/api/license/overview", "/api/license/import"}


def test_atk1_demo_token_variants(client, put_current, sign):
    put_current(sign())
    for h in ({"Authorization": "Bearer DEMO_abc"}, {"Authorization": "bearer DEMO_abc"}, {"Authorization": "DEMO_abc"}):
        for path, kw in (("/api/license/overview", {}), ("/api/license/import", {"json": {"content": sign(), "apply": True, "confirm": True}})):
            r = (client.get if not kw else client.post)(path, headers=h, **kw)
            assert r.status_code in (401, 403), (h, path, r.status_code, r.text[:100])
    assert not os.path.isdir(mgr.backup_dir())


# ═══ ② 驗證／正規化／還原／順序 ═══════════════════════════════════════════════════════

def test_atk2_normalised_upload_roundtrips_through_file_read_path(client, su, put_current, sign):
    """各種「看起來不同、解碼後相同」的上傳字串：存下去的字串經讀檔路徑驗，結果必須與上傳當下驗到的一致。"""
    blob = sign(customer="往返")
    variants = {
        "wrapped": "\n".join(blob[i:i + 33] for i in range(0, len(blob), 33)),
        "tabs": "\t".join([blob[:50], blob[50:]]),
        "nbsp": blob[:40] + " " + blob[40:],
        "crlf_tail": blob + "\r\n\r\n\r\n",
        "bom": "﻿" + blob,
    }
    for name, up in variants.items():
        put_current(None)
        mgr.reset_for_tests()
        r = _post(client, su, up, apply=True)
        assert r.status_code == 200, (name, r.text)
        assert _text() == blob + "\n", name
        assert lic.verify_license()["reason"] == "ok" and lic.verify_license()["customer"] == "往返"


def test_atk2_urlsafe_variant_and_excess_padding(client, su, put_current, sign):
    """base64／base64url 混用、多餘的 `=`：存的與驗的必須同一字串；讀檔路徑判定與上傳時一致。"""
    blob = sign(customer="變體")
    for name, up in (("urlsafe", blob.replace("+", "-").replace("/", "_")), ("pad", blob + "====")):
        put_current(None)
        mgr.reset_for_tests()
        pre = _post(client, su, up)                      # 預覽
        if pre.status_code != 200:
            continue                                     # 被擋也算（不接受）
        r = _post(client, su, up, apply=True)
        assert r.status_code == 200, (name, r.text)
        stored = _text().strip()
        assert stored == "".join(up.split()), name
        assert lic.verify_license()["reason"] == "ok", name


def test_atk2_duplicate_json_keys_cannot_split_verified_from_stored(client, su, put_current, sign, license_test_key):
    """簽章後的 payload 被塞進重複鍵的 JSON：json.loads 取最後一個，簽章驗的就是被解出來的 dict，不可能驗 A 存 B。"""
    blob = sign(customer="真客戶")
    raw = base64.b64decode(blob)
    tampered = raw.replace(b'{', '{"customer": "偽客戶",'.encode("utf-8"), 1)
    up = base64.b64encode(tampered).decode()
    put_current(None)
    r = _post(client, su, up, apply=True, confirm=True)
    if r.status_code == 200:                              # 若被接受，客戶名必須是簽章涵蓋的那個
        assert lic.verify_license()["customer"] == "真客戶"
    assert lic.verify_license()["reason"] in ("ok", "missing")


def test_atk2_rollback_restores_original_bytes_and_clears_cache(client, su, put_current, sign, monkeypatch):
    old = sign(customer="原本的")
    put_current(old)
    original = open(lic.LICENSE_PATH, "rb").read()
    real = lic.verify_license
    calls = {"n": 0}

    def flaky(blob=None):
        if blob is None:
            calls["n"] += 1
            if calls["n"] >= 2:                           # 第 1 次＝匯入前讀目前授權；第 2 次起＝換檔後複驗 ⇒ 失敗
                return dict(real(), reason="machine_mismatch", valid=False)
        return real(blob)
    monkeypatch.setattr(lic, "verify_license", flaky)
    r = _post(client, su, sign(customer="新的", expires=_in(800)), apply=True, confirm=True)
    assert r.status_code == 500 and r.json()["reason"] == "verify_after_write_failed", r.text
    assert open(lic.LICENSE_PATH, "rb").read() == original
    monkeypatch.setattr(lic, "verify_license", real)
    assert lic.verify_license()["customer"] == "原本的"
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp") and not os.path.exists(lic.LICENSE_PATH + ".restore-tmp")


def test_atk2_rollback_when_there_was_no_file_removes_the_new_one(client, su, put_current, sign, monkeypatch):
    put_current(None)
    real = lic.verify_license
    n = {"c": 0}

    def flaky(blob=None):
        if blob is None:
            n["c"] += 1
            if n["c"] >= 2:
                return dict(real(), reason="bad_signature", valid=False)
        return real(blob)
    monkeypatch.setattr(lic, "verify_license", flaky)
    r = _post(client, su, sign(), apply=True)
    assert r.status_code == 500
    assert not os.path.exists(lic.LICENSE_PATH)


def test_atk2_backup_failure_means_no_write(client, su, put_current, sign, monkeypatch):
    import shutil
    put_current(sign(customer="原本"))
    before = open(lic.LICENSE_PATH, "rb").read()
    monkeypatch.setattr(shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    r = _post(client, su, sign(customer="新", expires=_in(900)), apply=True, confirm=True)
    assert r.status_code == 500 and r.json()["reason"] == "backup_failed"
    assert open(lic.LICENSE_PATH, "rb").read() == before


def test_atk2_write_failure_leaves_old_file_and_no_temp(client, su, put_current, sign, monkeypatch):
    put_current(sign(customer="原本"))
    before = open(lic.LICENSE_PATH, "rb").read()
    real = os.replace

    def boom(src, dst):
        if str(dst) == lic.LICENSE_PATH:
            raise PermissionError("locked")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = _post(client, su, sign(customer="新", expires=_in(900)), apply=True, confirm=True)
    assert r.status_code == 500 and r.json()["reason"] == "write_failed"
    assert open(lic.LICENSE_PATH, "rb").read() == before
    assert not os.path.exists(lic.LICENSE_PATH + ".import-tmp")


def test_atk2_concurrent_applies_leave_a_consistent_file(client, su, put_current, sign):
    put_current(sign(customer="C0", expires=_in(100)))
    blobs = [sign(customer="C0", expires=_in(200 + i)) for i in range(4)]
    results = []

    def go(b):
        results.append(_post(client, su, b, apply=True, confirm=True))
    ts = [threading.Thread(target=go, args=(b,)) for b in blobs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    codes = sorted(r.status_code for r in results)
    assert all(c in (200, 409) for c in codes), codes
    assert codes.count(200) >= 1
    assert _text().strip() in blobs
    assert lic.verify_license()["reason"] == "ok"


def test_atk2_downgrade_to_older_issue_is_allowed_only_with_confirmation(client, su, put_current, sign):
    """舊的、到期日更早的授權不可以悄悄蓋過新的（沒有 confirm ⇒ 409，檔案不動）。"""
    put_current(sign(customer="C", expires=_in(700), issued="2026-06-01"))
    before = _text()
    r = _post(client, su, sign(customer="C", expires=_in(30), issued="2025-01-01"), apply=True)
    assert r.status_code == 409, r.text
    assert _text() == before and _backups() == []


# ═══ ③ 頻率限制與稽核／日誌洩漏 ══════════════════════════════════════════════════════

def test_atk3_forbidden_or_anonymous_requests_do_not_consume_the_rate_budget(client, make_user, put_current, sign, su):
    put_current(sign())
    sales = _login(client, make_user, "atk_s3", "sales")
    for _ in range(40):
        client.post("/api/license/import", json={"content": "x"})
        client.post("/api/license/import", headers=sales, json={"content": "x"})
        client.post("/api/license/import", headers={"Authorization": "Bearer DEMO_x"}, json={"content": "x"})
    r = _post(client, su, sign(customer="救援"))
    assert r.status_code == 200, "一般人／未登入的請求不得耗掉最高管理者的額度：%s %s" % (r.status_code, r.text)


def test_atk3_rate_limit_counts_previews_and_blocks_after_budget(client, su, put_current, sign):
    put_current(sign())
    codes = [_post(client, su, "junk!!").status_code for _ in range(mgr.RATE_MAX + 3)]
    assert codes[:mgr.RATE_MAX] == [400] * mgr.RATE_MAX and set(codes[mgr.RATE_MAX:]) == {429}


def test_atk3_rate_limit_dos_is_bounded_in_time(client, su, put_current, sign):
    """被灌爆後，等視窗過去就恢復（不是永久鎖死）；Retry-After 合理。"""
    put_current(sign())
    for _ in range(mgr.RATE_MAX):
        _post(client, su, "junk!!")
    r = _post(client, su, sign())
    assert r.status_code == 429 and 0 < int(r.headers["Retry-After"]) <= mgr.RATE_WINDOW_S
    mgr._rate_hits[:] = [h - mgr.RATE_WINDOW_S - 1 for h in mgr._rate_hits]
    assert _post(client, su, sign()).status_code in (200, 400)


def test_atk3_no_license_content_in_audit_rows_logs_or_responses(client, su, put_current, sign, caplog):
    import db
    caplog.set_level("DEBUG")
    put_current(sign(customer="舊"))
    blob = sign(customer="洩漏測試", expires=_in(900))
    sig = json.loads(base64.b64decode(blob))["sig"]
    r1 = _post(client, su, blob)
    r2 = _post(client, su, blob, apply=True, confirm=True)
    bad = blob[:-6] + "AAAAAA"
    r3 = _post(client, su, bad, apply=True)
    ov = client.get("/api/license/overview", headers=su)
    conn = db.get_db()
    try:
        audit = " ".join("%s %s %s" % (x["target_label"], x["detail"], x["username"]) for x in conn.execute("SELECT * FROM audit_log").fetchall())
    finally:
        conn.close()
    haystacks = {"audit": audit, "logs": caplog.text, "r1": r1.text, "r2": r2.text, "r3": r3.text, "overview": ov.text}
    for where, text in haystacks.items():
        assert blob not in text and sig not in text and blob[:60] not in text, where


# ═══ ④ 大小上限／串流 ═══════════════════════════════════════════════════════════════

def test_atk4_chunked_oversize_body_is_cut_off(client, su, put_current, sign):
    put_current(sign())
    total = {"n": 0}

    def gen():
        yield b'{"content":"'
        for _ in range(400):
            total["n"] += 16384
            yield b"A" * 16384
        yield b'"}'
    r = client.post("/api/license/import", headers=su, content=gen())
    assert r.status_code == 413, r.status_code


def test_atk4_declared_small_but_many_whitespace_is_still_capped(client, su, put_current, sign):
    """JSON 外殼合格（<66KB）、字元數 < 32768 但位元組超大的內容（多位元組字元）⇒ 不得進解碼；回 400/413，不 500。"""
    put_current(sign())
    r = _post(client, su, "字" * 20000, apply=True)
    assert r.status_code in (400, 413), (r.status_code, r.text[:100])
    r = _post(client, su, (" " * 30000) + sign(customer="補空白"))
    assert r.status_code == 200, r.text[:200]


@pytest.mark.parametrize("depth", [2000, 20000, 60000])
def test_atk4_deeply_nested_json_does_not_500(client, su, put_current, sign, depth):
    """巢狀 JSON（66KB 以內）：json.loads 會丟 RecursionError（不是 ValueError）。最高管理者呼叫也不該 500。"""
    put_current(sign())
    body = b'{"content":"x","z":' + b"[" * depth + b"]" * depth + b"}"
    if len(body) > 66000:
        body = b'{"z":' + b"[" * 32000 + b"]" * 32000 + b"}"
    r = client.post("/api/license/import", headers=su, content=body)
    assert r.status_code in (400, 413), (depth, r.status_code, r.text[:100])


@pytest.mark.parametrize("body", [b"[]", b'"x"', b"null", b"12", b'{"content": 5}', b'{"content": null}', b'{"content": ["a"]}', b'{"content": {"a": 1}}',
                                  b'{"content": "x", "apply": "true", "confirm": "true"}', b"\xff\xfe"])
def test_atk4_odd_bodies_never_500_and_never_apply(client, su, put_current, sign, body):
    put_current(sign())
    before = _text()
    r = client.post("/api/license/import", headers=su, content=body)
    assert r.status_code in (400, 413), (body, r.status_code, r.text[:100])
    assert _text() == before and _backups() == []


def test_atk4_string_flags_do_not_apply_or_confirm(client, su, put_current, sign):
    put_current(sign(customer="C", expires=_in(700)))
    before = _text()
    r = _post(client, su, sign(customer="別人", expires=_in(10)), apply="true", confirm="true")
    assert r.status_code == 200 and r.json()["applied"] is False             # apply 非布林 true ⇒ 只預覽
    assert _text() == before


# ═══ ⑤ 標頭與信件的外洩面 ═══════════════════════════════════════════════════════════

def test_atk5_expiry_header_only_on_authenticated_responses(client, su, make_user, put_current, sign):
    put_current(sign(expires=_in(5)))
    assert "X-Motrix-License-Expiry" not in client.get("/api/ping").headers
    assert "X-Motrix-License-Expiry" not in client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).headers
    assert "X-Motrix-License-Expiry" not in client.get(BUSINESS_API).headers                  # 未登入
    h = client.get(BUSINESS_API, headers=su).headers.get("X-Motrix-License-Expiry")
    assert h and h.startswith("days=5;level=critical;kind=subscription")
    sales = _login(client, make_user, "atk_s5", "sales")
    seen = client.get(BUSINESS_API, headers=sales).headers.get("X-Motrix-License-Expiry")
    print("NON-SUPERADMIN SEES EXPIRY HEADER:", seen)           # 設計決定：全員可見（見回報 Info）


def test_atk5_expiry_header_never_carries_customer_or_modules(client, su, put_current, sign):
    put_current(sign(customer="機密客戶名", expires=_in(5), modules=["case", "finance"]))
    for h in client.get(BUSINESS_API, headers=su).headers.items():
        assert "機密" not in h[1] and "finance" not in h[1], h


def test_atk5_expiry_mail_goes_to_superadmins_only(client, make_user, put_current, sign, monkeypatch):
    from helpers import mail_types
    t = mail_types.get("license_expiry")
    assert t.audience == "superadmins" if hasattr(t, "audience") else True
    sent = []
    from helpers import email_notify as en
    monkeypatch.setattr(en, "_send", lambda to, subj, html, *a, **k: (sent.append((list(to), subj, html)), en.SEND_SENT)[1])
    su_u, _ = make_user(username="atk_mail_su", role="superadmin")
    make_user(username="atk_mail_sales", role="sales")
    make_user(username="atk_mail_admin", role="admin")
    import db
    conn = db.get_db()
    conn.execute("UPDATE users SET email=username||'@example.com' WHERE username!='demo'")
    conn.commit()
    conn.close()
    put_current(sign(customer="信件客戶", expires=_in(7)))
    from helpers import license_alerts as la
    la.expiry_notice(lic.expiry_reminder(lic.verify_license()), lic.verify_license())
    recips = {a for to, _s, _h in sent for a in to}
    assert recips, "沒有寄信（沒有收件人）"
    assert all(a.startswith("atk_mail_su") or a.startswith("atk_su") for a in recips), recips


# ═══ ⑥ 開發金鑰 ═════════════════════════════════════════════════════════════════════

def _dev_pair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    return (priv.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8, encryption_algorithm=serialization.NoEncryption()),
            priv.public_key().public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo))


def test_atk6_dev_signed_license_on_shipped_build_is_rejected(client, su, put_current, sign, monkeypatch):
    """出貨包（LG-O1：_PUBKEY_DEV 被拿掉＝空）⇒ 開發金鑰簽的授權匯不進去，也不會被「確認」放行。"""
    priv, pub = _dev_pair()
    blob = sign(priv)
    put_current(sign())
    before = _text()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", b"")
    for kw in ({}, {"apply": True}, {"apply": True, "confirm": True}):
        r = _post(client, su, blob, **kw)
        assert r.status_code == 400 and r.json()["reason"] == "bad_signature", (kw, r.text)
    assert _text() == before and _backups() == []


def test_atk6_dev_signed_license_on_unstripped_build_needs_confirmation_and_is_flagged(client, su, put_current, sign, monkeypatch):
    priv, pub = _dev_pair()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", pub)
    blob = sign(priv, customer="開發簽的")
    put_current(sign())
    r = _post(client, su, blob, apply=True)
    assert r.status_code == 409 and any("測試用" in w for w in r.json()["warnings"]), r.text
    r = _post(client, su, blob, apply=True, confirm=True)
    assert r.status_code == 200
    ov = client.get("/api/license/overview", headers=su).json()
    assert ov["license"]["test_key"] is True


def test_atk6_dev_warning_present_even_when_no_current_license(client, su, put_current, sign, monkeypatch):
    """目前沒有授權（`cur.customer is None`）時，測試用警告仍要出現（_warnings 不可因提早 return 漏掉）。"""
    priv, pub = _dev_pair()
    monkeypatch.setattr(lic, "_PUBKEY_DEV", pub)
    put_current(None)
    r = _post(client, su, sign(priv))
    assert r.status_code == 200 and any("測試用" in w for w in r.json()["warnings"]), r.text
    r = _post(client, su, sign(priv), apply=True)
    assert r.status_code == 409, "沒有目前授權時，開發金鑰授權也必須先確認：%s" % r.text
