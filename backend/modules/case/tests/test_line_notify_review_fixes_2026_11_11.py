# -*- coding: utf-8 -*-
"""T79 LINE 通知 K 審修正（hichan-13）：
S1：要寫「已通知」記號的呼叫端（wait=True，例如保固到期每日檢查）重試時，LINE 不可每次重試都再推一次。
L2：superadmin_only 覆寫＋共用信箱，被覆寫丟掉的事件收件人不可多收 LINE；custom 覆寫是加人、不丟人。
"""
import pytest

from modules.case.tests.test_content_fp_s1_2026_11_06 import NO
from modules.case.tests.test_line_review_edit_2026_11_11 import _uid, line  # noqa: F401  (fixture)
from modules.case.tests.test_review_edit_chain_reset_2026_11_11 import _set_email
from tests._requires import requires_module

pytestmark = requires_module("case", "打 M01 的報價單與案件通知")


class _Handle:
    def __init__(self, outcome):
        self.outcome = outcome

    def wait(self, timeout=None):
        return self.outcome


def _owner(make_user):
    from helpers import line_notify as L
    make_user(username="wr_owner", role="sales")
    _set_email("wr_owner", "wr_owner@example.test")
    L.link_user("wr_owner", _uid(77))
    return _uid(77)


def _targets_of(line):
    out = []
    for c in line.calls:
        t = c["payload"]["to"]
        out += [t] if isinstance(t, str) else list(t)
    return out


@pytest.mark.parametrize("outcome,expect_push", [("skipped", 0), ("transient_fail", 0), ("sent", 1), ("unknown", 1), ("permanent_fail", 1)])
def test_warranty_line_follows_the_mark_writing_outcomes(client, make_user, line, monkeypatch, outcome, expect_push):
    """與「可以寫已通知記號」同一組結果才發 LINE：暫時失敗／機器層級略過 ⇒ 明天會重試，今天不推；其餘（寄出、不確定、永久失敗）⇒ 記號會寫，推一次。"""
    from helpers import email_notify as EN
    from helpers import line_notify as L
    uid = _owner(make_user)
    L.set_event("warranty_expiry", True)
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: _Handle(outcome))
    ok = EN._send_warranty_expiry("冷氣主機", "甲客戶", NO, 5, "2026-11-16", owner_username="wr_owner")
    assert ok is (outcome in ("sent", "unknown", "permanent_fail"))
    line.wait(expect_push, timeout=2.0)
    assert _targets_of(line).count(uid) == expect_push, (outcome, line.calls)


def test_warranty_retry_days_push_line_exactly_once(client, make_user, line, monkeypatch):
    """SMTP 沒設好連續 3 天（skipped／transient）⇒ 0 則 LINE；第 4 天寄出 ⇒ 1 則。不會同一台設備天天推。"""
    from helpers import email_notify as EN
    from helpers import line_notify as L
    uid = _owner(make_user)
    L.set_event("warranty_expiry", True)
    seq = iter(["skipped", "transient_fail", "skipped", "sent"])
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: _Handle(next(seq)))
    results = [EN._send_warranty_expiry("冷氣主機", "甲客戶", NO, 5, "2026-11-16", owner_username="wr_owner") for _ in range(4)]
    assert results == [False, False, False, True]
    line.wait(1, timeout=2.0)
    assert len(line.calls) == 1 and _targets_of(line).count(uid) == 1


def test_superadmin_only_override_with_shared_mailbox_does_not_leak_line_to_the_dropped_requester(client, make_user, line):
    import db
    from helpers import line_notify as L
    from helpers import mail_types as mt
    from helpers.settings import _set_setting
    from modules.case import review_edit_notify as RN
    make_user(username="sale_a", role="sales")
    make_user(username="boss_b", role="superadmin")
    c = db.get_db()
    c.execute("UPDATE users SET email=NULL WHERE role='superadmin' AND username!='boss_b'")
    c.commit()
    c.close()
    _set_email("sale_a", "shared@example.test")
    _set_email("boss_b", "shared@example.test")
    L.link_user("sale_a", _uid(1))
    L.link_user("boss_b", _uid(2))
    _set_setting(mt.OVERRIDES_KEY, {"approval_review_edit": {"mode": "superadmin_only", "users": [], "roles": []}})
    assert RN.fire_edited(NO, customer="甲", editor="e", requester="sale_a", fields=["數量"]) is True
    line.wait(1)
    assert line.targets() == [_uid(2)], "覆寫成僅超級管理員：送審人被丟掉，即使跟超管共用信箱也不收 LINE"


def test_custom_override_adds_people_without_dropping_the_requester(client, make_user, line):
    import db
    from helpers import line_notify as L
    from helpers import mail_types as mt
    from helpers.settings import _set_setting
    from modules.case import review_edit_notify as RN
    make_user(username="sale_a", role="sales")
    make_user(username="extra_c", role="engineer")
    c = db.get_db()
    c.execute("UPDATE users SET email=NULL WHERE role='superadmin'")
    c.commit()
    c.close()
    _set_email("sale_a", "a@example.test")
    _set_email("extra_c", "c@example.test")
    L.link_user("sale_a", _uid(1))
    L.link_user("extra_c", _uid(3))
    _set_setting(mt.OVERRIDES_KEY, {"approval_review_edit": {"mode": "custom", "users": ["extra_c"], "roles": []}})
    assert RN.fire_edited(NO, customer="甲", editor="e", requester="sale_a", fields=["數量"]) is True
    line.wait(1)
    assert line.targets() == sorted([_uid(1), _uid(3)])
