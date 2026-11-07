# -*- coding: utf-8 -*-
"""T78 R2：「誰是財務收件人」各處的判斷要彼此一致（只加測試，不動邏輯）。

目前同一個答案（在職的 `finance` 角色＋`superadmin`）寫在好幾個地方，各自判斷：
  A `helpers.auth.finance_usernames`（帳號清單）
  B `helpers.email_notify.finance_recipient_emails`（信箱清單）
  C `helpers.payable_due_core.notify_finance`（站內通知，自己查 users）
  D `helpers.notify_actions._people`（通知動作的 `group: finance`，自己查 users）
  E `routers/mail_settings.receivable`（收件設定頁「這位使用者可能收到嗎」的 finance 群組）
  F `helpers.auth.has_finance_access`（權限判斷；旗標 `finance_via_effective` 打開後改看生效權限）
哪天其中一處改了（例如旗標 `on` 之後權限那邊多了／少了人，或有人只改了信箱那一支），這裡會紅，提醒另外幾處要一起改，而不是悄悄分裂。
轉換：全部換成帳號集合再比（B 的信箱 ↔ 帳號靠 users.email 對應，種子帳號的信箱彼此不同）。"""
import json
from types import SimpleNamespace

import pytest

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")
FINANCE = {"superadmin", "finance"}


@pytest.fixture()
def seeded(client):
    """每個角色各一個在職、一個停用的帳號，全部有互不相同的信箱；回 `{username: (role, active, email)}`。"""
    import db
    rows = {}
    c = db.get_db()
    try:
        for role in ROLES:
            for active in (1, 0):
                u = "fx_%s_%d" % (role, active)
                em = u + "@example.invalid"
                c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password, email) "
                          "VALUES (?,?,?,?,?,?,?,0,?)", (u, "x", u, role, "[]", active, "2026-01-01T00:00:00", em))
                rows[u] = (role, active, em)
        for r in c.execute("SELECT id FROM users WHERE COALESCE(email,'')=''").fetchall():       # 安裝時內建的帳號（demo 等）沒有信箱：補上，免得「沒有信箱」的合理差異混進一般比對
            c.execute("UPDATE users SET email=? WHERE id=?", ("builtin%d@example.invalid" % r["id"], r["id"]))
        c.commit()
    finally:
        c.close()
    return rows


def _set_mode(mode):
    import db
    from helpers import auth
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO system_settings (key, value_json) VALUES (?, ?)", (auth.FINANCE_FLAG_KEY, json.dumps(mode)))
        c.commit()
    finally:
        c.close()
    auth.reset_finance_mode_cache()


def _all_users():
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT id, username, role, active, email FROM users").fetchall()]
    finally:
        c.close()


def _each_view(monkeypatch):
    """六處判斷各自算出的帳號集合。"""
    import db
    import helpers
    from helpers import auth, email_notify as en, notify_actions as na, payable_due_core as pdc
    from routers import mail_settings as ms
    users = _all_users()
    by_email = {u["email"]: u["username"] for u in users if u["email"]}
    assert len(by_email) == len([u for u in users if u["email"]]), "前提：信箱不重複，才能由信箱對回帳號"

    a = set(auth.finance_usernames())
    b = {by_email[e] for e in en.finance_recipient_emails("payable_due_soon")}

    notified = []
    monkeypatch.setattr(helpers, "_notify", lambda username, *a_, **k: notified.append(username))
    pdc.notify_finance("soon", "src", "k1", "ident", "2026-01-01")
    c_ = set(notified)

    conn = db.get_db()
    try:
        d = set(na._people(conn, {}, {}, {"kind": "group", "value": "finance"}))
    finally:
        conn.close()

    probe = SimpleNamespace(key="x_finance_probe", group="finance", event="", name="probe")
    e = {u["username"] for u in users if u["active"] and ms.receivable(probe, {}, u["username"], u["role"])}

    f = {u["username"] for u in users if u["active"] and auth.has_finance_access({"id": u["id"], "role": u["role"], "modules": "[]"})}
    return {"A finance_usernames": a, "B finance_recipient_emails": b, "C payable notify_finance": c_,
            "D notify_actions group:finance": d, "E mail_settings.receivable": e, "F has_finance_access": f}


@pytest.mark.parametrize("mode", ["off", "shadow", "on"])
def test_every_finance_audience_helper_agrees(client, seeded, monkeypatch, mode):
    """六處的結果必須完全相同；旗標 `finance_via_effective` 在 off／shadow／on 下都一樣（沒有職責角色綁定時，生效權限＝角色）。"""
    _set_mode(mode)
    try:
        views = _each_view(monkeypatch)
    finally:
        _set_mode("off")
    ref = views["A finance_usernames"]
    assert ref, "前提：至少有財務收件人"
    for name, got in views.items():
        assert got == ref, "%s 與 finance_usernames 不一致（旗標 %s）：多了 %s／少了 %s" % (name, mode, sorted(got - ref), sorted(ref - got))


def test_reference_set_is_exactly_active_finance_and_superadmin(client, seeded):
    """基準本身：在職的 finance／superadmin；一般角色與停用帳號都不在內（防止兩邊一起壞掉時測試仍綠）。"""
    from helpers import auth
    got = set(auth.finance_usernames())
    want = {u for u, (role, active, _em) in seeded.items() if active and role in FINANCE}
    assert want <= got
    assert not {u for u, (role, active, _em) in seeded.items() if (role not in FINANCE or not active)} & got


def test_account_without_email_is_the_only_allowed_difference(client, seeded, monkeypatch):
    """沒有信箱的財務帳號：帳號清單、站內通知、通知動作都有，只有『信箱清單』少了——這是唯一合理的差異，且只差這一人。"""
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE users SET email='' WHERE username='fx_finance_1'")
        c.commit()
    finally:
        c.close()
    views = _each_view(monkeypatch)
    ref = views["A finance_usernames"]
    assert "fx_finance_1" in ref
    assert views["B finance_recipient_emails"] == ref - {"fx_finance_1"}
    for name, got in views.items():
        if not name.startswith("B "):
            assert got == ref, name


def test_probe_catches_a_split(client, seeded, monkeypatch):
    """正對照：故意讓信箱那一支多算 `admin`，比對必須抓到（證明上面的斷言不是空的）。"""
    from helpers import email_notify as en
    real = en._users_emails
    monkeypatch.setattr(en, "finance_recipient_emails",
                        lambda event_key=None: real("role IN ('finance','superadmin','admin')", (), event_key))
    views = _each_view(monkeypatch)
    assert views["B finance_recipient_emails"] != views["A finance_usernames"]
    assert any(u.startswith("fx_admin_") for u in views["B finance_recipient_emails"])
