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


@pytest.mark.parametrize("outcome,expect_push", [("skipped", 1), ("transient_fail", 1), ("sent", 1), ("unknown", 1), ("permanent_fail", 1)])
def test_warranty_line_is_independent_of_the_mail_outcome(client, make_user, line, monkeypatch, outcome, expect_push):
    """2026-11-12（LINE 獨立通道）：不論信件結果如何，LINE 都推一次（信件暫時失敗／略過時呼叫端隔天重試，由 `line_key` 的「已推播」記號擋住不重推，見下一題）；
    呼叫端能不能寫記號（`ok`）仍只看信件結果。"""
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
    """SMTP 沒設好連續 3 天（skipped／transient）、第 4 天寄出：LINE 第 1 天就推（獨立通道），之後每天重試都被「已推播」記號擋住 ⇒ 全程只有 1 則，不會同一台設備天天推。"""
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
