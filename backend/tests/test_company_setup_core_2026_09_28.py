# -*- coding: utf-8 -*-
"""本公司資料設定閘門：判定核心（COMPANY-SETUP-GATE §3、§4.3、§6.1；D 稽核 CG-M1／CG2-M1／CG2-S4）。

用暫存 sqlite 庫＋暫存安裝根目錄（不經 app）。**不寫任何真實公司的統編或名稱**：統編由檢查碼演算法產生；
開發者指紋以「換掉 DEVELOPER_IDENTITY_FP」測，另有一題以 core.upgrade 既有的字面值（執行時讀）驗常數正確。
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.company_gate   # 用真的判定（conftest 預設把一般題目視為已設定）

from helpers import company_setup as cs

WEIGHTS = (1, 2, 1, 2, 1, 2, 4, 1)


def make_ubn(prefix7: str) -> str:
    """給 7 碼，補第 8 碼使檢查碼成立（加權和可被 5 整除）。"""
    for last in "0123456789":
        s = prefix7 + last
        if cs.ubn_valid(s):
            return s
    raise AssertionError("no valid check digit for %s" % prefix7)


UBN_A = make_ubn("1234560")
UBN_B = make_ubn("6543210")


def _db(tmp_path, profile=None):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, user_id INTEGER,"
                 " username TEXT, display_name TEXT, action TEXT NOT NULL, target_type TEXT, target_id TEXT,"
                 " target_label TEXT, detail TEXT)")
    if profile is not None:
        cs._set(conn, "company_profile", profile)
    conn.commit()
    return conn


def _root(tmp_path, name="root"):
    r = tmp_path / name
    (r / "backend").mkdir(parents=True)
    return str(r)


GOOD = {"name": "測試甲股份有限公司", "tax_id": UBN_A, "phone": "02-0000-0000"}


@pytest.fixture()
def no_mail(monkeypatch):
    sent = []
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_group_emails", lambda key: ["a@example.invalid"])
    monkeypatch.setattr(en, "_send_raising", lambda to, subj, body: sent.append(subj) or "sent")
    return sent


# ── 欄位 ──────────────────────────────────────────────────────────────────────

def test_ubn_checksum():
    assert cs.ubn_valid(UBN_A) and cs.ubn_valid(UBN_B)
    bad = UBN_A[:-1] + str((int(UBN_A[-1]) + 1) % 10)
    assert not cs.ubn_valid(bad)
    for s in ("", "1234567", "123456789", "abcdefgh", None):
        assert not cs.ubn_valid(s)
    # 第 7 碼為 7 的例外：加權和＋1 可被 5 整除也算（財政部規則）
    found = [p for p in (f"{i:06d}7" for i in range(0, 400)) if any(
        cs.ubn_valid(p + d) for d in "0123456789")]
    assert found, "第 7 碼為 7 的樣本要找得到"


@pytest.mark.parametrize("profile,missing", [
    (GOOD, []),
    ({**GOOD, "name": ""}, ["公司名稱"]),
    ({**GOOD, "tax_id": "12345678"}, ["統一編號（8 碼且通過檢查碼）"]),
    ({**GOOD, "phone": ""}, ["電話或 email（至少一項）"]),
    ({**GOOD, "phone": "", "email": "x@example.invalid"}, []),
    ({"companyName": "別名公司", "taxId": UBN_B, "contact_info": "Tel: 02-1111-2222"}, []),   # 別名與聯絡方式後備
])
def test_required_fields(profile, missing):
    assert cs.required_problems(profile) == missing


# ── 開發者指紋 ────────────────────────────────────────────────────────────────

def test_developer_fingerprint_constants_match_the_frozen_literals():
    """常數要真的等於開發者資料的雜湊（執行時讀 core.upgrade 既有的字面值，題目本身不寫字面值）。"""
    from core.upgrade import V9_COMPANY_DEFAULTS as V
    assert cs.identity_fp("tax", V["tax_id"]) in cs.DEVELOPER_IDENTITY_FP
    assert cs.identity_fp("name", V["company_name"]) in cs.DEVELOPER_IDENTITY_FP
    assert cs.is_developer_identity({"name": V["company_name"], "tax_id": "", "phone": ""})
    assert not cs.is_developer_identity(GOOD)


def test_delivery_pubkey_matches_the_delivery_tool():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("delivery", Path(__file__).resolve().parents[1] / "tools" / "delivery.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    assert cs.DELIVERY_PUBKEY_PEM == d.DELIVERY_PUBKEY_PEM


# ── 判定矩陣 ──────────────────────────────────────────────────────────────────

def test_filled_fields_without_a_decision_are_not_configured(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    st = cs.status(conn, root)
    assert st["configured"] is False and st["reason"] == cs.NO_RECORD


def test_confirm_then_configured_and_changes_invalidate(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    rec = cs.confirm(conn, "boss", root)
    assert rec["via"] == "settings_page" and rec["install"] == cs.install_hash(root)
    assert cs.status(conn, root)["configured"] is True
    cs._set(conn, "company_profile", {**GOOD, "phone": "02-9999-9999"})          # 直接寫庫改必要欄位
    assert cs.status(conn, root)["reason"] == cs.FIELDS_CHANGED
    cs._set(conn, "company_profile", {**GOOD, "google_maps_api_key": "k"})       # 非必要欄位 ⇒ 不影響
    assert cs.status(conn, root)["configured"] is True


def test_copied_database_on_another_install_is_not_configured(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path, "a")
    cs.confirm(conn, "boss", root)
    other = _root(tmp_path, "b")
    assert cs.status(conn, other)["reason"] == cs.INSTALL_MISMATCH               # 識別檔不在
    cs.ensure_install_id(other)
    assert cs.status(conn, other)["reason"] == cs.INSTALL_MISMATCH               # 識別不同


def test_confirm_refuses_invalid_fields(tmp_path):
    conn, root = _db(tmp_path, {**GOOD, "tax_id": "1"}), _root(tmp_path)
    with pytest.raises(cs.ConfirmRefused, match="統一編號"):
        cs.confirm(conn, "boss", root)
    assert cs._get(conn, cs.CONFIRMATION_SETTING) is None


# ── 開發者身分＋簽章確認檔 ─────────────────────────────────────────────────────

@pytest.fixture()
def devco(monkeypatch):
    """把 UBN_A 當成「開發者」，並換一把測試金鑰。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(cs, "DEVELOPER_IDENTITY_FP", frozenset({cs.identity_fp("tax", UBN_A)}))
    monkeypatch.setattr(cs, "PUBKEYS", (pub,))
    return priv


def _write_sig(root, priv, install=None, tax=UBN_A, issued=None, expires=None, raw=None):
    today = datetime.now().date()
    payload = {"identity_fp": cs.identity_fp("tax", tax), "install": install or cs.install_hash(root),
               "issued": (issued or today - timedelta(days=1)).isoformat(),
               "expires": (expires or today + timedelta(days=365)).isoformat()}
    text = raw if raw is not None else cs.sign_confirmation(payload, priv)
    with open(cs._files(root)[1], "w", encoding="utf-8") as f:
        f.write(text)


def test_developer_identity_needs_a_signed_file(tmp_path, devco):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    with pytest.raises(cs.ConfirmRefused, match="開發者"):
        cs.confirm(conn, "boss", root)
    cs.ensure_install_id(root)
    _write_sig(root, devco)
    cs.confirm(conn, "boss", root)
    assert cs.status(conn, root)["configured"] is True
    os.remove(cs._files(root)[1])
    assert cs.status(conn, root)["reason"] == cs.DEVELOPER_UNSIGNED                # 反向控制：拿掉簽章檔


@pytest.mark.parametrize("case", ["other_install", "other_identity", "expired", "no_prefix", "tampered"])
def test_signed_file_rejections(tmp_path, devco, case):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    if case == "other_install":
        _write_sig(root, devco, install="0" * 64)
        want = "mismatch"
    elif case == "other_identity":
        _write_sig(root, devco, tax=UBN_B)
        want = "mismatch"
    elif case == "expired":
        _write_sig(root, devco, issued=datetime.now().date() - timedelta(days=10),
                   expires=datetime.now().date() - timedelta(days=1))
        want = "expired"
    elif case == "no_prefix":
        # 同一把金鑰簽「沒有用途前綴」的內容（例：交付包那種）⇒ 不可以被當成確認檔（CG-S3）
        from cryptography.hazmat.primitives import serialization
        import base64
        key = serialization.load_pem_private_key(devco, password=None)
        body = {"purpose": cs.PURPOSE, "identity_fp": cs.identity_fp("tax", UBN_A), "install": cs.install_hash(root),
                "issued": "2000-01-01", "expires": "2999-01-01"}
        sig = key.sign(cs._canonical(body))
        _write_sig(root, devco, raw=json.dumps(dict(body, sig=base64.b64encode(sig).decode())))
        want = "invalid"
    else:
        _write_sig(root, devco)
        doc = json.loads(open(cs._files(root)[1], encoding="utf-8").read())
        doc["expires"] = "2999-12-31"
        _write_sig(root, devco, raw=json.dumps(doc))
        want = "invalid"
    assert cs.signed_file_state(GOOD, root) == want


# ── backfill（每庫一次、不丟例外） ─────────────────────────────────────────────

def test_backfill_existing_install_once(tmp_path):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    assert cs.backfill_once(conn, root) == "backfilled"
    assert cs.status(conn, root)["via"] == "upgrade_backfill"
    assert cs.backfill_once(conn, root) == "already_done"


def test_backfill_empty_profile_never_confirms_later(tmp_path):
    """全新安裝：第一次啟動欄位是空的 ⇒ 記「做過」⇒ 之後管理員填了欄位也不會被自動確認（要按確認）。"""
    conn, root = _db(tmp_path, {}), _root(tmp_path)
    assert cs.backfill_once(conn, root) == "skipped_fields"
    cs._set(conn, "company_profile", GOOD)
    assert cs.backfill_once(conn, root) == "already_done"
    assert cs.status(conn, root)["reason"] == cs.NO_RECORD


def test_backfill_developer_identity(tmp_path, devco):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    assert cs.backfill_once(conn, root) == "waiting_signature"                    # 沒有簽章檔 ⇒ 不補
    (tmp_path / "x").mkdir()
    conn2, root2 = _db(tmp_path / "x", GOOD), _root(tmp_path, "r2")                # 另一個安裝：有簽章檔
    cs.ensure_install_id(root2)
    _write_sig(root2, devco)
    assert cs.backfill_once(conn2, root2) == "backfilled"


def test_backfill_retries_after_the_signed_file_arrives(tmp_path, devco):
    """CGI-M1（D 以 devco 五步重現）：開發者資料、簽章檔未到 ⇒ 先用暫時放行升級 ⇒ 之後簽章檔到位 ⇒ 下次啟動要補上確認。"""
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    assert cs.backfill_once(conn, root) == "waiting_signature"                    # ① 第一次啟動：等簽章
    now = datetime.now()
    with open(cs._files(root)[2], "w", encoding="utf-8") as f:                    # ② 暫時放行撐著
        json.dump({"created": now.isoformat(), "until": (now + timedelta(hours=72)).isoformat(),
                   "reason": "等簽章", "install": cs.install_hash(root)}, f)
    assert cs.status(conn, root)["grace"]["active"]
    assert cs.backfill_once(conn, root) == "waiting_signature"                    # ③ 再啟動一次：仍等
    _write_sig(root, devco)                                                        # ④ 簽章檔到位
    assert cs.backfill_once(conn, root) == "backfilled"                           # ⑤ 下次啟動補上
    st = cs.status(conn, root)
    assert st["configured"] is True and st["via"] == "upgrade_backfill"
    assert cs.backfill_once(conn, root) == "already_done"


def test_copied_developer_db_with_fields_changed_is_not_auto_confirmed(tmp_path, devco):
    """CGI2-M1：開發者資料、無簽章檔（複製庫）⇒ waiting；有人把名稱與統編改成別家、沒按確認 ⇒ 重啟也不自動確認。"""
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    assert cs.backfill_once(conn, root) == "waiting_signature"
    cs._set(conn, "company_profile", {**GOOD, "name": "別家股份有限公司", "tax_id": UBN_B})
    assert cs.backfill_once(conn, root) == "skipped_identity_changed"
    assert cs.status(conn, root)["reason"] == cs.NO_RECORD
    assert cs.backfill_once(conn, root) == "already_done"                         # 之後也不會再補
    assert cs._get(conn, cs.BACKFILL_WAITING_SETTING) is None
    # 反向控制：非開發者、從沒等過簽章的既有安裝 ⇒ 照常補
    (tmp_path / "y").mkdir()
    conn2, root2 = _db(tmp_path / "y", {**GOOD, "tax_id": UBN_B}), _root(tmp_path, "r3")
    assert cs.backfill_once(conn2, root2) == "backfilled"


def test_backfill_never_raises(tmp_path, monkeypatch, caplog):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    monkeypatch.setattr(cs, "required_problems", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cs.backfill_once(conn, root) == "error"
    assert cs._get(conn, cs.CONFIRMATION_SETTING) is None and "backfill 失敗" in caplog.text


# ── 安裝識別檔重建（CG2-M1） ──────────────────────────────────────────────────

def test_install_id_recreated_with_a_record_is_an_error_and_alert(tmp_path, caplog, no_mail):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    assert cs.startup_install_check(conn, root) == "created"                      # 新裝：WARN、不告警
    assert no_mail == []
    cs.confirm(conn, "boss", root)
    assert cs.startup_install_check(conn, root) == "present"
    os.remove(cs._files(root)[0])
    assert cs.startup_install_check(conn, root) == "recreated_with_record"
    assert "安裝識別檔遺失" in caplog.text and len(no_mail) == 1
    assert cs.status(conn, root)["reason"] == cs.INSTALL_MISMATCH


# ── 暫時放行（伺服器保證期限，CG2-S4） ────────────────────────────────────────

def _grace(root, created, until, install=None, reason="測試"):
    with open(cs._files(root)[2], "w", encoding="utf-8") as f:
        json.dump({"created": created.isoformat(), "until": until.isoformat(), "reason": reason,
                   "install": install or cs.install_hash(root)}, f)


def test_grace_basic_and_does_not_confirm(tmp_path, no_mail):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    now = datetime.now()
    _grace(root, now, now + timedelta(hours=10))
    st = cs.status(conn, root, now)
    assert st["configured"] is False and st["grace"]["active"] and cs.allows(st)
    assert cs._get(conn, cs.CONFIRMATION_SETTING) is None
    cs.observe(conn, root, now)
    assert len(no_mail) == 1
    audit = conn.execute("SELECT action FROM audit_log").fetchall()
    assert ("company_setup.grace_seen",) in audit
    cs.observe(conn, root, now)                                                    # 同一份不重記
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='company_setup.grace_seen'").fetchone()[0] == 1


def test_grace_is_capped_by_server_first_seen(tmp_path, no_mail):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    t0 = datetime(2026, 9, 28, 12, 0, 0)
    _grace(root, t0, t0 + timedelta(days=30))                                      # 手改成 30 天
    cs.observe(conn, root, t0)
    assert cs.status(conn, root, t0 + timedelta(hours=71))["grace"]["active"]
    assert cs.status(conn, root, t0 + timedelta(hours=73))["grace"] is None       # 72h 到期
    # 改 created 讓它看起來是新的：內容不同 ⇒ 新的一份 ⇒ 新 first_seen＋新稽核
    t1 = t0 + timedelta(hours=73)
    _grace(root, t1, t1 + timedelta(days=30))
    cs.observe(conn, root, t1)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='company_setup.grace_seen'").fetchone()[0] == 2
    assert cs.status(conn, root, t1 + timedelta(hours=1))["grace"]["active"]


@pytest.mark.parametrize("case", ["future", "install", "garbage"])
def test_grace_invalid(tmp_path, case):
    conn, root = _db(tmp_path, GOOD), _root(tmp_path)
    cs.ensure_install_id(root)
    now = datetime.now()
    if case == "future":
        _grace(root, now + timedelta(hours=1), now + timedelta(hours=5))
    elif case == "install":
        _grace(root, now, now + timedelta(hours=5), install="0" * 64)
    else:
        open(cs._files(root)[2], "w").write("{not json")
    assert cs.status(conn, root, now)["grace"] is None


def test_alert_is_once_per_day(tmp_path, no_mail):
    conn = _db(tmp_path, GOOD)
    assert cs.alert(conn, "x", "測試告警") is True
    assert cs.alert(conn, "x", "測試告警") is False
    assert cs.alert(conn, "y", "另一件事") is True
    assert len(no_mail) == 2


# ── 安裝設定檔登記（CG2-M1） ──────────────────────────────────────────────────

def test_three_files_are_install_config_and_never_packaged():
    from core import paths as P
    from core import upgrade as U
    rels = [U._rel(p) for p in (P.INSTALL_IDENTITY_FILE, P.COMPANY_CONFIRMATION_FILE, P.COMPANY_SETUP_GRACE_FILE)]
    for rel in rels:
        assert rel in U.CONFIG_FILES
        assert U.classify(rel) == "config", rel
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("vp", Path(__file__).resolve().parents[1] / "tools" / "verify_package.py")
    vp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vp)
    rule = [r for r in vp.BAD if r[0] == "company-setup"][0]
    for rel in rels:
        assert rule[2](rel, os.path.basename(rel))
    assert not rule[2]("backend/helpers/company_setup.py", "company_setup.py")    # 反向控制：程式檔不擋
    gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    for rel in rels:
        assert rel in gi
