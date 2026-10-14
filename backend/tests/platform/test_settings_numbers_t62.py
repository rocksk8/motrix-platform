# -*- coding: utf-8 -*-
"""census #7／#8：設定中心的數字——保固預警天數、保固郵件兩階段、確認檔到期提醒、密碼最短長度（只准加嚴）、登入有效天數（只准縮短）。

- 預設＝今天寫死的數字（沒改設定時行為逐位元相同）
- 預警類：讀不到設定／型別不對／超出範圍 ⇒ 夾回範圍或預設
- **安全類兩項是嚴格讀取**（04 審查）：讀不到 ⇒ 不退回預設（8／30＝放寬）。密碼規則讀不到 ⇒ PolicyUnreadable，設定／更改密碼回 503；
  登入天數讀不到 ⇒ 最後一次讀到的值，沒有就 7 天
- 密碼最短長度只套用在『設定／更改密碼』；登入時的弱密碼判斷維持常數 8（調高門檻不會把既有使用者鎖在門外）
- 放寬方向走既有的『放寬→待確認期間→第二位核准』：密碼最短長度往下調＝放寬；登入有效天數往上調＝放寬；其餘預警天數往下調＝放寬
"""
import pytest

from helpers import alert_settings as AS


def _patch(monkeypatch, vals):
    import helpers.settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: vals.get((g, f), AS.DEFAULTS.get(f)))


def _strict(monkeypatch, vals):
    """嚴格讀取路徑（安全類）：假的資料庫連線＋假的 strict_value。vals 值是 Exception 實例 ⇒ 丟出。"""
    monkeypatch.setattr("db.get_db", lambda: type("C", (), {"close": lambda self: None})())

    def sv(conn, g, f):
        v = vals.get((g, f), AS.DEFAULTS[f])
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr("helpers.settings_strict.strict_value", sv)


def test_defaults_are_todays_hard_coded_numbers(monkeypatch):
    from helpers.auth import MIN_PASSWORD_LEN
    from helpers.company_setup import SIGNED_EXPIRY_WARN_DAYS
    assert AS.DEFAULTS["password_min_len"] == MIN_PASSWORD_LEN == 8
    assert AS.DEFAULTS["cert_warn_days"] == SIGNED_EXPIRY_WARN_DAYS == 30
    assert (AS.DEFAULTS["warranty_mail_urgent_days"], AS.DEFAULTS["warranty_mail_early_days"]) == (7, 30)
    assert AS.DEFAULTS["warranty_report_days"] == 90 and AS.DEFAULTS["login_days"] == 30
    _patch(monkeypatch, {})
    u, e = AS.warranty_mail_days()
    assert (u, e) == (7, 30) and f"緊急預警：{u}天內到期" == "緊急預警：7天內到期" and f"{e}天到期預警" == "30天到期預警", "郵件標題逐字等於今天"
    _strict(monkeypatch, {})
    assert AS.min_password_len() == 8 and AS.login_days() == 30


def test_registry_declares_the_groups_with_limits_loosen_directions_and_impact_scope():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    g = SR.groups()
    f = {x["key"]: x for x in g["account_security"]["fields"]}
    assert (f["password_min_len"]["default"], f["password_min_len"]["min"], f["password_min_len"]["loosen"]) == (8, 8, "down"), "下限 8；往下調＝放寬"
    assert (f["login_days"]["default"], f["login_days"]["max"], f["login_days"]["loosen"]) == (30, 30, "up"), "上限 30；往上調＝放寬"
    assert f["password_min_len"]["riskText"] and f["login_days"]["riskText"]
    for k in ("password_min_len", "login_days"):
        sc = f[k]["impactScope"]
        assert sc and sc["effective"] == "pending" and sc["reversible"] is True, "高風險欄位要宣告影響範圍（放寬欄位 ⇒ pending）"
    a = {x["key"]: x for x in g["alerts"]["fields"]}
    assert {k: (v["default"], v["loosen"]) for k, v in a.items()} == {"warranty_report_days": (90, "down"), "warranty_mail_early_days": (30, "down"),
                                                                     "warranty_mail_urgent_days": (7, "down"), "cert_warn_days": (30, "down")}


def test_alert_numbers_fail_to_defaults_and_clamp(monkeypatch):
    import helpers.settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: (_ for _ in ()).throw(RuntimeError("unreadable")))
    assert (AS.warranty_report_days(), AS.cert_warn_days(), AS.warranty_mail_days()) == (90, 30, (7, 30))
    _patch(monkeypatch, {("alerts", "warranty_report_days"): 5, ("alerts", "cert_warn_days"): 1000})
    assert AS.warranty_report_days() == 30 and AS.cert_warn_days() == 90, "超出範圍 ⇒ 夾回"
    _patch(monkeypatch, {("alerts", "warranty_mail_urgent_days"): 30, ("alerts", "warranty_mail_early_days"): 10})
    u, e = AS.warranty_mail_days()
    assert e == 10 and u == 9 and u < e, "緊急天數一定小於提前天數"
    _patch(monkeypatch, {("alerts", "warranty_mail_urgent_days"): 3, ("alerts", "warranty_mail_early_days"): 45})
    assert AS.warranty_mail_days() == (3, 45)


def test_password_policy_is_read_strictly_and_never_falls_to_the_loosest(monkeypatch):
    _strict(monkeypatch, {("account_security", "password_min_len"): 12})
    assert AS.min_password_len() == 12, "往嚴的方向可以調"
    for bad in (RuntimeError("database is locked"), 3, 9999, "12", True, None, 7.5):
        _strict(monkeypatch, {("account_security", "password_min_len"): bad})
        with pytest.raises(AS.PolicyUnreadable):
            AS.min_password_len()                                                    # 讀不到／不合法 ⇒ 不是 8（放寬），而是讓呼叫端拒絕


def test_login_days_falls_back_to_the_last_known_good_value_else_seven(monkeypatch):
    monkeypatch.setattr(AS, "_last_login_days", None)
    _strict(monkeypatch, {("account_security", "login_days"): RuntimeError("database is locked")})
    assert AS.login_days() == AS.LOGIN_DAYS_FALLBACK == 7, "從沒讀到過 ⇒ 保守的 7 天，不是 30"
    _strict(monkeypatch, {("account_security", "login_days"): 10})
    assert AS.login_days() == 10
    _strict(monkeypatch, {("account_security", "login_days"): RuntimeError("database is locked")})
    assert AS.login_days() == 10, "之後讀不到 ⇒ 最後一次讀到的值"
    for bad in (0, 31, 365, "30", True, None):
        _strict(monkeypatch, {("account_security", "login_days"): bad})
        assert AS.login_days() == 10, bad                                           # 超出上限 30／不合法 ⇒ 不採用，維持最後讀到的值


def test_login_time_weak_password_check_keeps_the_constant_so_raising_the_policy_never_locks_anyone_out(monkeypatch):
    from helpers.auth import MIN_PASSWORD_LEN, is_weak_password
    _strict(monkeypatch, {("account_security", "password_min_len"): 20})
    assert is_weak_password("Xy7!pQ2r") is False, "8 碼的既有密碼登入時不算弱（即使設定調到 20）"
    assert is_weak_password("Xy7!pQ2") is True and MIN_PASSWORD_LEN == 8
    _strict(monkeypatch, {("account_security", "password_min_len"): RuntimeError("locked")})
    assert is_weak_password("Xy7!pQ2r") is False, "設定讀不到也不影響登入"


def test_setters_use_the_policy_and_answer_503_when_it_cannot_be_read(monkeypatch):
    from fastapi import HTTPException
    from routers import auth as RA
    _strict(monkeypatch, {("account_security", "password_min_len"): 12})
    assert RA._min_pw() == 12
    _strict(monkeypatch, {("account_security", "password_min_len"): RuntimeError("database is locked")})
    with pytest.raises(HTTPException) as ei:
        RA._min_pw()
    assert ei.value.status_code == 503 and "密碼規則暫時讀不到" in ei.value.detail


def test_login_session_length_follows_the_setting_and_never_exceeds_thirty_days(client, make_user, monkeypatch):
    import db
    from datetime import datetime
    u, pw = make_user(username="num_u1", role="viewer")[:2]
    real_get_db = db.get_db         # `_strict()` 會把 db.get_db 換成假連線（只給嚴格讀取用）；這題自己查 sessions 表要用真的

    def login_expires():
        r = client.post("/api/auth/login", json={"username": u, "password": pw})
        assert r.status_code == 200, r.text
        c = real_get_db()
        try:
            row = c.execute("SELECT expires_at FROM sessions WHERE username=? ORDER BY created_at DESC LIMIT 1", (u,)).fetchone()
        finally:
            c.close()
        return (datetime.fromisoformat(row[0]) - datetime.now()).total_seconds() / 86400

    assert 29.9 < login_expires() <= 30.0, "預設＝今天的 30 天"
    monkeypatch.setattr(AS, "_last_login_days", None)
    _strict(monkeypatch, {("account_security", "login_days"): 7})
    assert 6.9 < login_expires() <= 7.0
    _strict(monkeypatch, {("account_security", "login_days"): 365})
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
    ha = (b / "helpers" / "auth.py").read_text(encoding="utf-8")
    assert "len(password) < MIN_PASSWORD_LEN" in ha and "alert_settings" not in ha.split("def is_weak_password")[1].split("def ")[0]
