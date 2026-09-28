# -*- coding: utf-8 -*-
"""本公司資料設定閘門 段③：輸出端第二道、請款單匯款欄位、排程月報、demo 示範公司、側欄、重新確認、失敗快取、到期提醒
（COMPANY-SETUP-GATE §4.1、§4.2、§4.3、§5、§6.5；D CG5-M1／CG5-S1／CG5-S2）。

用真的判定（company_gate marker）。統編由檢查碼演算法產生，不寫真實公司資料。
"""
import json
from datetime import datetime, timedelta

import pytest

from helpers import company_setup as cs
from tests.test_company_setup_core_2026_09_28 import make_ubn

pytestmark = pytest.mark.company_gate

UBN = make_ubn("3456780")
PROFILE = {"name": "測試丙股份有限公司", "tax_id": UBN, "contact_info": "Tel: 02-2222-3333"}


@pytest.fixture(autouse=True)
def _fresh_gate_cache():
    cs.reset_cache()
    yield
    cs.reset_cache()


def _login(client, make_user, name, role):
    u, pw = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def boss(client, make_user):
    return _login(client, make_user, "og_boss", "superadmin")


@pytest.fixture()
def clerk(client, make_user):
    return _login(client, make_user, "og_clerk", "admin")


def _confirm(client, h, **over):
    return client.put("/api/settings/company-profile", json=dict(PROFILE, confirmIdentity=True, **over), headers=h)


def _boom(monkeypatch):
    calls = []

    def boom(conn, root=None, now=None, demo=False):
        calls.append(1)
        raise RuntimeError("boom")
    monkeypatch.setattr(cs, "status", boom)
    cs.reset_cache()
    return calls


@pytest.fixture()
def no_mail(monkeypatch):
    sent = []
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_group_emails", lambda key: ["a@example.invalid"])
    monkeypatch.setattr(en, "_send_raising", lambda to, subj, body: sent.append(subj) or "sent")
    return sent


# ── 第二道（CG5-M1）：判定失敗時中介層放行，但含本公司資料的輸出 428 undetermined ──────────

def test_undetermined_passes_general_api_but_refuses_output(client, boss, clerk, monkeypatch, no_mail):
    assert _confirm(client, boss).status_code == 200
    ok = client.get("/api/legal-params/privacy-notice", params={"purpose": "contractor"}, headers=clerk)
    assert ok.status_code == 200 and ok.json()["company"] == PROFILE["name"]          # 正對照：已設定照常
    _boom(monkeypatch)
    assert client.get("/api/customers", headers=clerk).status_code == 200            # 第一道放行（Q7＝C）
    for url, params in (("/api/legal-params/privacy-notice", {"purpose": "contractor"}),
                        ("/api/reports/financial/excel", {"period": "2026-08"})):
        r = client.get(url, params=params, headers=clerk)
        assert r.status_code == 428, (url, r.status_code, r.text[:200])
        d = r.json()
        assert d["code"] == cs.CODE_UNDETERMINED and d["detail"] == cs.MSG_UNDETERMINED, d


def test_output_helpers_refuse_when_unconfigured_or_undetermined(client, monkeypatch):
    import pdf_gen
    from helpers import company_identity as ci
    from modules.accounting import voucher_pdf
    for fn in (ci.company_name, lambda: ci.company_heading("x"), ci.contact_line, ci.footer_line,
               lambda: pdf_gen._identity_head({}), lambda: pdf_gen._identity_foot({}),
               lambda: pdf_gen._identity_foot_short({}), voucher_pdf._company_name,
               lambda: pdf_gen._payslip_view({})):
        with pytest.raises(cs.CompanySetupRequired) as e:
            fn()
        assert e.value.code == cs.CODE_REQUIRED and e.value.status_code == 428
    _boom(monkeypatch)
    with pytest.raises(cs.CompanySetupRequired) as e:
        ci.company_name()
    assert e.value.code == cs.CODE_UNDETERMINED


def test_grace_lets_output_through(client, monkeypatch):
    from helpers import company_identity as ci
    monkeypatch.setattr(cs, "status", lambda conn, root=None, now=None, demo=False: {
        "configured": False, "reason": cs.NO_RECORD, "grace": {"active": True, "until": "2099-01-01T00:00:00"}})
    cs.reset_cache()
    assert ci.company_name() == ""


def test_payment_request_needs_bank_fields(client, boss):
    import pdf_gen
    assert _confirm(client, boss).status_code == 200
    with pytest.raises(cs.CompanySetupRequired) as e:
        pdf_gen._require_payment_bank({})
    assert e.value.code == "company_bank_required" and set(e.value.missing) == {"銀行名稱", "戶名", "帳號"}
    r = client.put("/api/settings/company-profile", headers=boss, json=dict(
        PROFILE, bank_name="測試銀行", bank_account_name="測試丙股份有限公司", bank_account_number="0001234567"))
    assert r.status_code == 200, r.text                                              # 匯款欄位不是必要欄位 ⇒ 不必重新確認
    pdf_gen._require_payment_bank({})                                                # 補齊 ⇒ 放行


def test_both_payment_request_generators_check_bank_fields_first():
    """下載與簽核後存檔兩條產生路徑都在組 HTML 之前驗匯款欄位（AST：呼叫順序）。"""
    import ast
    import inspect
    import pdf_gen
    for fn in (pdf_gen.generate_payment_request_pdf_bytes, pdf_gen._generate_payment_request_pdf):
        calls = [n.func.id for n in ast.walk(ast.parse(inspect.getsource(fn)))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert "_require_payment_bank" in calls, fn.__name__
        assert calls.index("_require_payment_bank") < calls.index("_build_payment_request_html"), fn.__name__


# ── 排程月報（非 HTTP）───────────────────────────────────────────────────────────

def test_monthly_report_is_skipped_and_alerted_without_advancing(client, monkeypatch, no_mail):
    from modules.analytics.api import reports
    from helpers.settings import _get_setting, _set_setting
    _set_setting("monthly_report_last_sent", "2020-01")
    sent = []
    monkeypatch.setattr(reports, "_send_monthly_report_for", lambda p: sent.append(p))
    reports._catchup_monthly_reports()                                               # 未設定
    assert sent == [] and _get_setting("monthly_report_last_sent") == "2020-01"
    assert len(no_mail) == 1
    reports._catchup_monthly_reports()                                               # 同一天不再寄告警
    assert len(no_mail) == 1


def test_monthly_report_direct_call_does_not_send_either(client, monkeypatch, no_mail):
    import helpers.email_notify as en
    from modules.analytics.api import reports
    mails = []
    monkeypatch.setattr(en, "notify_monthly_report", lambda *a: mails.append(a))
    reports._send_monthly_report_for("2026-08")
    assert mails == []


# ── demo（Q3）─────────────────────────────────────────────────────────────────────

def test_demo_gets_a_fictional_company_and_watermark(client, make_user, boss):
    import db
    import pdf_gen
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:                                                                             # 種子已有 demo 帳號 ⇒ 換成已知密碼
        n = conn.execute("UPDATE users SET password_hash=?, must_change_password=0, active=1 WHERE username='demo'",
                         (_hash_pw("Demo-Pass-123"),)).rowcount
        if not n:
            conn.close()
            make_user(username="demo", password="Demo-Pass-123", role="admin")
        else:
            conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    u = client.post("/api/auth/login", json={"username": "demo", "password": "Demo-Pass-123"})
    assert u.status_code == 200, u.text
    h = {"Authorization": "Bearer " + u.json()["token"]}
    assert client.get("/api/customers", headers=h).status_code == 200               # demo 不被擋（示範公司已確認）
    st = client.get("/api/settings/company-setup/status", headers=h).json()
    assert st["configured"] is True and st["via"] == "demo_seed"
    # 正式庫沒有被寫入任何確認紀錄；正式帳號仍被擋
    conn = db.get_db()
    try:
        assert cs._get(conn, cs.CONFIRMATION_SETTING) is None
        # 反向控制：demo 的確認紀錄帶進正式庫 ⇒ install_mismatch（DEMO_INSTALL 只有 demo 判定認得）
        cs.seed_demo(conn)
        assert cs.status(conn)["reason"] == cs.INSTALL_MISMATCH
        conn.rollback()
    finally:
        conn.close()
    assert client.get("/api/customers", headers=boss).status_code == 428
    db.set_demo_mode(True)
    try:
        cs.reset_cache()
        head = pdf_gen._identity_head({"company_name": cs.DEMO_PROFILE["name"]})
        assert cs.DEMO_WATERMARK in head and "data-demo-watermark" in head
    finally:
        db.set_demo_mode(False)
        cs.reset_cache()


def test_demo_fictional_identity_is_marked_and_valid():
    assert cs.DEMO_WATERMARK in cs.DEMO_PROFILE["name"]
    assert cs.required_problems(cs.DEMO_PROFILE) == []
    assert not cs.is_developer_identity(cs.DEMO_PROFILE)


def test_real_watermark_is_absent_outside_demo(client, boss):
    import pdf_gen
    assert _confirm(client, boss).status_code == 200
    assert "data-demo-watermark" not in pdf_gen._identity_head({})


# ── 側欄與設定頁提示 ─────────────────────────────────────────────────────────────────

def test_menu_shows_only_the_settings_entry_while_unconfigured(client, boss, clerk):
    m = client.get("/api/platform/menu", headers=boss).json()
    assert m["companySetup"]["blocked"] is True and m["companySetup"]["configured"] is False
    hrefs = [it["href"] for g in m["layout"]["groups"] for it in g["items"]]
    assert hrefs == ["company-profile-settings.html"], hrefs
    assert client.get("/api/platform/menu", headers=clerk).json()["layout"]["groups"] == []
    assert _confirm(client, boss).status_code == 200
    m = client.get("/api/platform/menu", headers=boss).json()
    assert m["companySetup"] == {"configured": True, "grace": False, "canFix": True, "blocked": False}
    assert len([1 for g in m["layout"]["groups"] for _ in g["items"]]) > 5          # 正對照：設定後完整


def test_single_superadmin_count_is_reported_to_superadmins_only(client, boss, clerk):
    st = client.get("/api/settings/company-setup/status", headers=boss).json()
    assert st["superadminCount"] >= 1
    assert "superadminCount" not in client.get("/api/settings/company-setup/status", headers=clerk).json()


def test_changing_required_fields_needs_save_and_confirm(client, boss, clerk):
    """D CG5-S1：已確認後一般存檔改必要欄位 ⇒ 409、不存（其他人不會被突然擋住）；帶 confirmIdentity ⇒ 存並確認。"""
    assert _confirm(client, boss).status_code == 200
    before = client.get("/api/settings/company-profile", headers=boss).json()
    r = client.put("/api/settings/company-profile", headers=boss, json=dict(PROFILE, name="測試丙二股份有限公司"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "company_setup_reconfirm"
    assert client.get("/api/settings/company-profile", headers=boss).json() == before
    assert client.get("/api/customers", headers=clerk).status_code == 200
    assert client.put("/api/settings/company-profile", headers=boss,
                      json=dict(PROFILE, google_maps_api_key="AIzaTESTKEY0000000000000000000000000000")).status_code == 200
    r = _confirm(client, boss, name="測試丙二股份有限公司")
    assert r.status_code == 200 and r.json()["confirmed"] is True
    assert client.get("/api/customers", headers=clerk).status_code == 200


def test_unconfirmed_install_saves_freely(client, boss):
    """反向控制：本來就未確認 ⇒ 一般存檔照常（不 409）。"""
    assert client.put("/api/settings/company-profile", headers=boss, json=PROFILE).status_code == 200
    assert client.put("/api/settings/company-profile", headers=boss,
                      json=dict(PROFILE, name="測試丙三股份有限公司")).status_code == 200


# ── 判定失敗的短時快取（CG5-S2）─────────────────────────────────────────────────────

def test_failure_is_cached_briefly_and_alerts_once(client, monkeypatch, no_mail):
    import db
    calls = _boom(monkeypatch)
    conn = db.get_db()
    try:
        for _ in range(5):
            assert cs.gate(conn)[0] == cs.GATE_UNDETERMINED
    finally:
        conn.close()
    assert len(calls) == 1 and len(no_mail) == 1
    cs._GATE_ERROR_UNTIL[False] = datetime.now() - timedelta(seconds=1)              # 過期 ⇒ 重算
    conn = db.get_db()
    try:
        assert cs.gate(conn)[0] == cs.GATE_UNDETERMINED
    finally:
        conn.close()
    assert len(calls) == 2 and len(no_mail) == 1                                     # 告警仍是每日一次


def test_alert_in_process_throttle_holds_when_the_db_is_unreadable(no_mail):
    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("db gone")
    assert cs.alert(Broken(), "status_error", "x") is True
    assert cs.alert(Broken(), "status_error", "x") is False
    assert len(no_mail) == 1


# ── 到期提醒（§4.3、§6.5）────────────────────────────────────────────────────────────

@pytest.fixture()
def gate_files():
    """本 worker 的放行檔／簽章檔（FILES_OVERRIDE）：題目寫了就要刪，否則同 worker 的下一題會看到放行中。"""
    import os
    yield cs._files()
    for p in cs._files()[1:]:
        if os.path.exists(p):
            os.remove(p)


def _alert_codes(conn):
    return [json.loads(r[0])["code"] for r in conn.execute(
        "SELECT detail FROM audit_log WHERE action='company_setup.alert'")]


def test_grace_expiring_soon_alerts(client, no_mail, gate_files):
    import db
    root = None
    cs.ensure_install_id(root)
    now = datetime.now()
    with open(cs._files(root)[2], "w", encoding="utf-8") as f:
        json.dump({"created": now.isoformat(), "until": (now + timedelta(hours=2)).isoformat(), "reason": "測試",
                   "install": cs.install_hash(root)}, f)
    conn = db.get_db()
    try:
        assert cs.gate(conn)[0] == cs.GATE_GRACE                                     # 經 gate（中介層同一條路）觸發
        cs.reset_cache()
        cs.gate(conn)
        assert _alert_codes(conn).count("grace_expiring") == 1
    finally:
        conn.close()


def test_signed_file_expiring_soon_alerts(client, monkeypatch, no_mail, gate_files):
    import db
    from tests.test_company_setup_core_2026_09_28 import UBN_A
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(cs, "DEVELOPER_IDENTITY_FP", frozenset({cs.identity_fp("tax", UBN_A)}))
    monkeypatch.setattr(cs, "PUBKEYS", (pub,))
    cs.ensure_install_id(None)
    today = datetime.now().date()

    def write(days_left):
        text = cs.sign_confirmation({"identity_fp": cs.identity_fp("tax", UBN_A), "install": cs.install_hash(None),
                                     "issued": (today - timedelta(days=1)).isoformat(),
                                     "expires": (today + timedelta(days=days_left)).isoformat()}, priv)
        with open(cs._files(None)[1], "w", encoding="utf-8") as f:
            f.write(text)

    conn = db.get_db()
    try:
        cs._set(conn, "company_profile", {"name": "測試甲股份有限公司", "tax_id": UBN_A, "phone": "02-0000-0000"})
        write(200)
        cs.observe_expiry(conn)                                                      # 反向控制：還早 ⇒ 不告警
        assert "signed_file_expiring" not in _alert_codes(conn)
        write(10)
        cs.observe_expiry(conn)
        assert _alert_codes(conn).count("signed_file_expiring") == 1
    finally:
        conn.close()
