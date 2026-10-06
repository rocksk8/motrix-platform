# -*- coding: utf-8 -*-
"""t44-bonus-mail：獎金分潤核准（進入待發放）⇒ 通知送審人（之前送審人從來收不到結果）。

- 信件類型 `bonus_approved` 由 M07 登記（owner=payroll），自動併入個人通知偏好。
- 主旨＝「【MOTRIX 系統通知】簽核－獎金分潤 {單號} 已核准」（識別＋結果字；t44 申請人通知統一規範），內文有單號、客戶，**沒有金額**。
- 收件人只有送審人；送審人就是簽核的人 ⇒ 不重複寄；送審（待審核）時不寄這一封；寄信失敗不影響簽核。
"""
import pytest

from helpers import email_notify, mail_types
from modules.payroll.tests.test_bonus_payout_connectors import _legal, _to_payout, people   # noqa: F401  (people 是 fixture)
from modules.payroll.tests.test_bonus_case_api_2026_09_24 import _auth, _create, _members_spec, _seed_case


@pytest.fixture
def outbox(monkeypatch):
    """攔下所有寄信：_lookup_emails 回「帳號@example.com」並記下 (帳號清單, 事件 key)；_async_send 收 (收件人, 主旨, 內文)。"""
    got = {"lookups": [], "mails": []}

    def fake_lookup(usernames, event_key=None):
        got["lookups"].append((list(usernames or []), event_key))
        return ["%s@example.com" % u for u in (usernames or [])]
    monkeypatch.setattr(email_notify, "_lookup_emails", fake_lookup)
    monkeypatch.setattr(email_notify, "_async_send", lambda to, subj, html: got["mails"].append((list(to), subj, html)) or None)
    return got


def test_type_is_registered_by_payroll_and_listed_in_prefs():
    t = mail_types.get("bonus_approved")
    assert t is not None and t.owner == "payroll" and t.category == "approval" and t.group == "none"
    from helpers import notification_prefs
    assert "bonus_approved" in notification_prefs.EVENT_KEYS


def test_requester_gets_the_approved_mail_with_outcome_in_subject(client, people, outbox):
    r = _to_payout(client, people, "MQ-BA-001")                       # bc_sa 建立＋送審，bc_sa2 核准 ⇒ 待發放
    assert r.json()["status"] == "待發放"
    approved = [(to, s, h) for (to, s, h) in outbox["mails"] if "已核准" in s]
    assert len(approved) == 1, [m[1] for m in outbox["mails"]]
    to, subj, html = approved[0]
    assert to == ["bc_sa@example.com"]
    assert subj == "【MOTRIX 系統通知】簽核－獎金分潤 MQ-BA-001 已核准"
    assert "MQ-BA-001" in html and "已核准" in html
    assert "NT$" not in html and "金額：" not in html
    assert (["bc_sa"], "bonus_approved") in outbox["lookups"]
    # 出納仍照舊收到「待發放」信（兩封各走各的類型）
    assert any(k == "bonus_payout_ready" for _u, k in outbox["lookups"])


def test_submit_does_not_send_the_approved_mail(client, people, outbox):
    _seed_case("MQ-BA-002", net=2000000)
    assert _create(client, people["bc_sa"], "MQ-BA-002", members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/MQ-BA-002/submit", headers=_auth(people["bc_sa"])).status_code == 200
    assert not [k for _u, k in outbox["lookups"] if k == "bonus_approved"]


def test_not_sent_to_the_approver_himself(monkeypatch):
    from modules.payroll import bonus_notify
    sent = []
    monkeypatch.setattr(bonus_notify, "_notice_in_app", lambda *a, **k: None)   # 不碰真資料庫（站內通知另有專題）
    orig = email_notify.send_registered
    email_notify.send_registered = lambda *a, **k: sent.append(k) or True
    try:
        assert bonus_notify.fire_approved("MQ-X", "客", "bc_sa", approver="bc_sa") is False
        assert bonus_notify.fire_approved("MQ-X", "客", "", approver="bc_sa2") is False
        assert not sent
        assert bonus_notify.fire_approved("MQ-X", "客", "bc_sa", approver="bc_sa2") is True
        assert sent and sent[0]["usernames"] == ["bc_sa"]
    finally:
        email_notify.send_registered = orig


def test_a_failing_mail_never_breaks_the_approval(client, people, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(email_notify, "send_registered", boom)
    r = _to_payout(client, people, "MQ-BA-003")                       # _to_payout 內含 200＋「待發放」斷言
    assert r.json()["status"] == "待發放"


def _bell_rows(username, type_="bonus_approved"):
    from db import get_db
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM notifications WHERE username=? AND type=?", (username, type_)).fetchall()]
    finally:
        conn.close()


def test_requester_gets_an_in_app_notice_with_quote_no_and_link(client, people, outbox):
    r = _to_payout(client, people, "MQ-BA-004")
    assert r.json()["status"] == "待發放"
    rows = _bell_rows("bc_sa")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["ref_id"] == "MQ-BA-004" and "MQ-BA-004" in row["message"] and "已核准" in row["message"]
    assert "NT$" not in row["message"] and "元" not in row["message"]
    if "link" in row:                                                  # link 欄由 t44-inapp-bell 加入；整合後必有
        assert row["link"] == "bonus.html?q=MQ-BA-004"
    assert not _bell_rows("bc_sa2")                                    # 簽核的人自己不收


def test_a_failing_in_app_notice_never_breaks_the_approval_or_the_mail(client, people, outbox, monkeypatch):
    from modules.payroll import bonus_notify
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(bonus_notify, "_notice_in_app", boom)
    r = _to_payout(client, people, "MQ-BA-005")
    assert r.json()["status"] == "待發放"
    assert any("已核准" in s for (_to, s, _h) in outbox["mails"])      # 信照寄


def test_reject_and_return_mail_the_requester_with_outcome_in_subject(client, people, outbox):
    r = _to_payout(client, people, "MQ-BA-006")                       # 待發放，送審人 bc_sa
    outbox["mails"].clear()
    rr = client.post("/api/bonus/cases/MQ-BA-006/return", json={"reason": "金額要重算"}, headers=_auth(people["bc_sa2"]))
    assert rr.status_code == 200, rr.text
    got = [(to, s, h) for (to, s, h) in outbox["mails"] if "已退回" in s]
    assert len(got) == 1, [m[1] for m in outbox["mails"]]
    to, subj, html = got[0]
    assert to == ["bc_sa@example.com"] and subj == "【MOTRIX 系統通知】簽核－獎金分潤 MQ-BA-006 已退回"
    assert "金額要重算" in html and "NT$" not in html
    rows = _bell_rows("bc_sa", "bonus_returned")
    assert len(rows) == 1 and "已退回" in rows[0]["message"] and "MQ-BA-006" in rows[0]["message"]


def test_in_app_link_url_encodes_the_quote_no():
    from modules.payroll import bonus_notify
    assert bonus_notify._page_link("MQ-202610-001") == "bonus.html?q=MQ-202610-001"
    assert bonus_notify._page_link("A B&c=d") == "bonus.html?q=A%20B%26c%3Dd"
