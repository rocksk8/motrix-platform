# -*- coding: utf-8 -*-
"""census #7／#8：設定中心的數字——保固預警天數、保固郵件兩階段、確認檔到期提醒、密碼最短長度（只准加嚴）、登入有效天數（只准縮短）。

- 預設＝今天寫死的數字（沒改設定時行為逐位元相同）
- 讀不到設定／型別不對／超出範圍 ⇒ 夾回範圍或預設；安全類的底線（密碼 8 碼、登入 30 天）寫死在程式裡，設定值再怎麼設都突破不了
- 放寬方向走既有的『放寬→待核准→確認期間』：密碼最短長度往下調＝放寬；登入有效天數往上調＝放寬；其餘預警天數往下調＝放寬
"""
import pytest

from helpers import alert_settings as AS


def _patch(monkeypatch, vals):
    import helpers.settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: vals.get((g, f), AS.DEFAULTS.get(f)))


def test_defaults_are_todays_hard_coded_numbers():
    from helpers.auth import MIN_PASSWORD_LEN
    from helpers.company_setup import SIGNED_EXPIRY_WARN_DAYS
    assert AS.DEFAULTS["password_min_len"] == MIN_PASSWORD_LEN == 8
    assert AS.DEFAULTS["cert_warn_days"] == SIGNED_EXPIRY_WARN_DAYS == 30
    assert (AS.DEFAULTS["warranty_mail_urgent_days"], AS.DEFAULTS["warranty_mail_early_days"]) == (7, 30)
    assert AS.DEFAULTS["warranty_report_days"] == 90 and AS.DEFAULTS["login_days"] == 30
    u, e = AS.warranty_mail_days()
    assert (u, e) == (7, 30) and f"緊急預警：{u}天內到期" == "緊急預警：7天內到期" and f"{e}天到期預警" == "30天到期預警", "郵件標題逐字等於今天"


def test_registry_declares_the_groups_with_limits_and_loosen_directions():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    g = SR.groups()
    f = {x["key"]: x for x in g["account_security"]["fields"]}
    assert (f["password_min_len"]["default"], f["password_min_len"]["min"], f["password_min_len"]["loosen"]) == (8, 8, "down"), "下限 8；往下調＝放寬"
    assert (f["login_days"]["default"], f["login_days"]["max"], f["login_days"]["loosen"]) == (30, 30, "up"), "上限 30；往上調＝放寬"
    assert f["password_min_len"]["riskText"] and f["login_days"]["riskText"]
    a = {x["key"]: x for x in g["alerts"]["fields"]}
    assert {k: (v["default"], v["loosen"]) for k, v in a.items()} == {"warranty_report_days": (90, "down"), "warranty_mail_early_days": (30, "down"),
                                                                     "warranty_mail_urgent_days": (7, "down"), "cert_warn_days": (30, "down")}


def test_fail_closed_to_defaults_and_hard_floors_cannot_be_broken(monkeypatch):
    import helpers.settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: (_ for _ in ()).throw(RuntimeError("unreadable")))
    assert (AS.min_password_len(), AS.login_days(), AS.warranty_report_days(), AS.cert_warn_days()) == (8, 30, 90, 30)
    _patch(monkeypatch, {("account_security", "password_min_len"): 3, ("account_security", "login_days"): 365})
    assert AS.min_password_len() == 8, "密碼最短長度不能低於 8（程式底線）"
    assert AS.login_days() == 30, "登入有效天數不能超過 30（程式上限）"
    _patch(monkeypatch, {("account_security", "password_min_len"): 12, ("account_security", "login_days"): 7})
    assert AS.min_password_len() == 12 and AS.login_days() == 7, "往嚴的方向可以調"
    _patch(monkeypatch, {("account_security", "password_min_len"): "12", ("account_security", "login_days"): True})
    assert AS.min_password_len() == 8 and AS.login_days() == 30, "型別不對 ⇒ 預設"
    _patch(monkeypatch, {("account_security", "password_min_len"): 9999})
    assert AS.min_password_len() == 64


def test_mail_urgent_days_is_always_below_the_early_days(monkeypatch):
    _patch(monkeypatch, {("alerts", "warranty_mail_urgent_days"): 30, ("alerts", "warranty_mail_early_days"): 10})
    u, e = AS.warranty_mail_days()
    assert e == 10 and u == 9 and u < e
    _patch(monkeypatch, {("alerts", "warranty_mail_urgent_days"): 3, ("alerts", "warranty_mail_early_days"): 45})
    assert AS.warranty_mail_days() == (3, 45)
    _patch(monkeypatch, {("alerts", "warranty_report_days"): 5, ("alerts", "cert_warn_days"): 1000})
    assert AS.warranty_report_days() == 30 and AS.cert_warn_days() == 90, "超出範圍 ⇒ 夾回"


def test_is_weak_password_uses_the_setting_but_never_below_eight(monkeypatch):
    from helpers.auth import is_weak_password
    _patch(monkeypatch, {})
    assert is_weak_password("Xy7!pQ2r") is False, "8 碼（預設門檻）夠長"
    assert is_weak_password("Xy7!pQ2") is True, "7 碼永遠太短"
    _patch(monkeypatch, {("account_security", "password_min_len"): 12})
    assert is_weak_password("Xy7!pQ2rT9z") is True, "11 碼 < 12"
    assert is_weak_password("Xy7!pQ2rT9zK") is False
    _patch(monkeypatch, {("account_security", "password_min_len"): 3})
    assert is_weak_password("Xy7!pQ2") is True, "設定想放寬到 3 碼也沒用：底線 8"


def test_login_session_length_follows_the_setting_and_never_exceeds_thirty_days(client, make_user, monkeypatch):
    import db
    from datetime import datetime
    u, pw = make_user(username="num_u1", role="viewer")[:2]

    def login_expires():
        r = client.post("/api/auth/login", json={"username": u, "password": pw})
        assert r.status_code == 200, r.text
        c = db.get_db()
        try:
            row = c.execute("SELECT expires_at FROM sessions WHERE username=? ORDER BY created_at DESC LIMIT 1", (u,)).fetchone()
        finally:
            c.close()
        return (datetime.fromisoformat(row[0]) - datetime.now()).total_seconds() / 86400

    _patch(monkeypatch, {})
    assert 29.9 < login_expires() <= 30.0, "預設＝今天的 30 天"
    _patch(monkeypatch, {("account_security", "login_days"): 7})
    assert 6.9 < login_expires() <= 7.0
    _patch(monkeypatch, {("account_security", "login_days"): 365})
    assert login_expires() <= 30.0, "設再大也不超過 30 天"


def test_sources_use_the_helpers_instead_of_the_old_literals():
    from pathlib import Path
    b = Path(__file__).resolve().parents[2]
    rep = (b / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
    assert "dl <= _WARR_DAYS" in rep and "dl <= 90" not in rep and "_warranty_days()" in rep
    dl = (b / "modules" / "case" / "case_deadlines.py").read_text(encoding="utf-8")
    assert "days_left > _early" in dl and "days_left > 30" not in dl and "warranty_mail_days()" in dl
    em = (b / "helpers" / "email_notify.py").read_text(encoding="utf-8")
    assert "warranty_mail_days()" in em and '"緊急預警：7天內到期"' not in em
    cs = (b / "helpers" / "company_setup.py").read_text(encoding="utf-8")
    assert "<= cert_warn_days()" in cs and "<= SIGNED_EXPIRY_WARN_DAYS" not in cs
    au = (b / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "< MIN_PASSWORD_LEN" not in au and "timedelta(days=login_days())" in au and au.count("_min_pw()") >= 8
