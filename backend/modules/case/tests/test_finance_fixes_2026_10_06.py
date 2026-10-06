# -*- coding: utf-8 -*-
"""（42 班稽核 a／b／c／e／f／g）：
(a) 財務角色對非自己負責案件的一般叫料清單只能看不能改（成員／superadmin／admin 不受影響；付款相關端點維持）
(b) 舊整包格式非成員財務的 403 訊息明說「只能改款項」
(c) 自我核可拒絕訊息指向「其他財務角色成員或最高管理者」
(e) 提醒信防重複記號寄成功才寫（SMTP 暫時失敗當天會重試）
(f) 出納退回匯款差額後，行事曆「付款待辦」重建
(g) 提醒信假日順延（T−3／T0；同一寄信日只寄一封）用 L1 `helpers.business_days` 的官方假日表
"""
from datetime import date

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的財務修正")

from modules.case.tests import test_material_guard_2026_10_02 as G  # noqa: E402
from modules.case.tests import test_payable_planned_pay_date_2026_10_05 as P  # noqa: E402
from modules.case.tests.test_payable_planned_pay_date_2026_10_05 import mails  # noqa: E402,F401  fixture


@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)


# ── (a) ─────────────────────────────────────────────────────────────────

def _patch_orders(client, h, rows):
    return client.patch("/api/quotations/%s/material-orders" % G.NO, json={"materialOrders": rows}, headers=h)


def _world_a(client, make_user, member_fin=False):
    out = {}
    for name, role in (("fx_fin", "finance"), ("fx_sa", "superadmin"), ("fx_adm", "admin")):
        u, p = make_user(username=name, role=role)
        out[name] = G._login(client, u, p)
    G._seed(assigned=[G._uid("fx_fin")] if member_fin else [])
    return out


def _edited():
    rows = G._cr()["materialOrders"]
    rows[0]["notes"] = "財務改的備註"
    return rows


def test_finance_cannot_edit_orders_on_a_case_it_does_not_own(client, make_user):
    w = _world_a(client, make_user)
    r = _patch_orders(client, w["fx_fin"], _edited())
    assert r.status_code == 403 and "只能檢視" in r.text, r.text
    assert G._cr()["materialOrders"][0]["notes"] == "", "資料沒被改"


def test_finance_can_still_view_orders_on_any_case(client, make_user):
    w = _world_a(client, make_user)
    r = client.get("/api/quotations/%s/material-orders" % G.NO, headers=w["fx_fin"])
    assert r.status_code == 200 and "L1" in r.text, r.text


def test_finance_who_owns_the_case_and_superadmin_and_admin_can_edit(client, make_user):
    w = _world_a(client, make_user, member_fin=True)
    assert _patch_orders(client, w["fx_fin"], _edited()).status_code == 200, "自己負責的案件照常可改"
    for who in ("fx_sa", "fx_adm"):
        rows = G._cr()["materialOrders"]
        rows[0]["notes"] = who
        r = _patch_orders(client, w[who], rows)
        assert r.status_code == 200, (who, r.text)
        assert G._cr()["materialOrders"][0]["notes"] == who


def test_superadmin_edits_a_case_nobody_owns(client, make_user):
    w = _world_a(client, make_user)
    assert _patch_orders(client, w["fx_sa"], _edited()).status_code == 200, "superadmin 不變式：每個功能都能用"


# ── (b) ─────────────────────────────────────────────────────────────────

def test_non_member_finance_legacy_whole_form_403_message_says_payment_only(client, make_user):
    w = _world_a(client, make_user)
    cr = G._cr()
    cr["contract"] = {"note": "非款項欄位被改"}
    r = client.patch("/api/quotations/%s/case-record" % G.NO, json={"case_record": cr}, headers=w["fx_fin"])
    assert r.status_code == 403 and "只能修改款項" in r.text and "成員（業務" not in r.text, r.text
    # 一般非成員、非財務：訊息維持「成員限定」
    u, p = make_user(username="fx_eng", role="engineer")
    r2 = client.patch("/api/quotations/%s/case-record" % G.NO, json={"case_record": cr}, headers=G._login(client, u, p))
    assert r2.status_code in (403, 404)
    if r2.status_code == 403:
        assert "成員" in r2.text and "只能修改款項" not in r2.text


# ── (c)(f) 匯款差額：自核訊息、退回後行事曆重建 ───────────────────────────

def _pay_with_diff(client, make_user, monkeypatch):
    cal = P._gcal(monkeypatch, {"payable_due": True})
    eid = P._seed_exp(planned="2031-06-10")
    h1 = P._hdr(client, make_user, "fx_cash1", "finance")
    h2 = P._hdr(client, make_user, "fx_cash2", "finance")
    sa = P._hdr(client, make_user, "fx_sa2")
    assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (P.NO, eid), headers=sa,
                        json={"plannedPayDate": "2031-06-11"}).status_code == 200
    assert len(cal.events) == 1
    r = client.post("/api/cashier/pending-payables/case/%s/pay" % eid, headers=h1,
                    json={"paidDate": "2031-06-09", "actualAmount": 1300})
    assert r.status_code == 200 and r.json().get("remitReview"), r.text
    assert cal.events == {}, "付款後待辦收回"
    return cal, eid, h1, h2


def test_self_review_refusal_names_other_finance_or_top_admin(client, make_user, monkeypatch):
    cal, eid, h1, h2 = _pay_with_diff(client, make_user, monkeypatch)
    r = client.post("/api/cashier/remit-reviews/case/%s/decision" % eid, headers=h1, json={"decision": "approve"})
    assert r.status_code == 403, r.text
    assert "其他財務角色" in r.text and "最高管理者" in r.text and "其他管理員" not in r.text, r.text


def test_payable_calendar_event_rebuilt_after_cashier_rejects(client, make_user, monkeypatch):
    cal, eid, h1, h2 = _pay_with_diff(client, make_user, monkeypatch)
    r = client.post("/api/cashier/remit-reviews/case/%s/decision" % eid, headers=h2, json={"decision": "reject", "note": "多付"})
    assert r.status_code == 200 and "payableEvent" not in r.json(), r.text
    assert len(cal.events) == 1, "退回＝回待付款 ⇒ 付款待辦重建"
    ev = str(next(iter(cal.events.values())))
    assert "1300" not in ev and "1,300" not in ev and "1200" not in ev, "事件不含金額"


def test_calendar_not_rebuilt_on_approve_or_when_no_planned_date(client, make_user, monkeypatch):
    cal, eid, h1, h2 = _pay_with_diff(client, make_user, monkeypatch)
    r = client.post("/api/cashier/remit-reviews/case/%s/decision" % eid, headers=h2, json={"decision": "approve"})
    assert r.status_code == 200 and cal.events == {}, "核可＝維持已付款 ⇒ 不重建"
    eid2 = P._seed_exp(planned="")
    h3 = P._hdr(client, make_user, "fx_cash3", "finance")
    assert client.post("/api/cashier/pending-payables/case/%s/pay" % eid2, headers=h1,
                       json={"paidDate": "2031-06-09", "actualAmount": 1300}).status_code == 200
    assert client.post("/api/cashier/remit-reviews/case/%s/decision" % eid2, headers=h3,
                       json={"decision": "reject", "note": "x"}).status_code == 200
    assert cal.events == {}, "沒有預定付款日 ⇒ 不建事件"


# ── (e) ─────────────────────────────────────────────────────────────────

@pytest.fixture
def flaky(monkeypatch):
    """可控結果的寄送：outcomes 依序給每次的結果（用完就是成功）。"""
    from helpers import email_notify as en
    log, outcomes = [], []

    class _H:
        def __init__(self, o):
            self.o = o

        def wait(self, timeout=None):
            return self.o

    def fake(to, subject, html):
        log.append(subject)
        return _H(outcomes.pop(0) if outcomes else en.SEND_SENT)

    monkeypatch.setattr(en, "_async_send", fake)
    return log, outcomes


def _guard_count():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM system_settings WHERE key LIKE 'payable_due_notif.%'").fetchone()[0]
    finally:
        conn.close()


def test_guard_written_only_after_successful_send(client, make_user, flaky):
    from helpers import email_notify as en
    log, outcomes = flaky
    P._finance(make_user, "fx_fin_a")
    P._seed_exp(planned=P.TODAY.isoformat())
    outcomes.append(en.SEND_TRANSIENT_FAIL)
    assert P._run() == 0 and len(log) == 1, "SMTP 暫時失敗 ⇒ 沒寄成"
    assert _guard_count() == 0, "失敗不寫 guard"
    assert P._run() == 1 and len(log) == 2, "同一天重跑補寄"
    assert _guard_count() == 1
    assert P._run() == 0 and len(log) == 2, "寄成功後才寫 guard ⇒ 不再重寄"


def test_skipped_send_also_retries(client, make_user, flaky):
    from helpers import email_notify as en
    log, outcomes = flaky
    P._finance(make_user, "fx_fin_b")
    P._seed_exp(planned=P.TODAY.isoformat())
    outcomes.append(en.SEND_SKIPPED)
    assert P._run() == 0
    assert P._run() == 1, "機器層級略過（SMTP 未設定）⇒ 設定好後補寄"


def test_send_registered_wait_semantics(client, make_user, monkeypatch):
    from helpers import email_notify as en
    P._finance(make_user, "fx_fin_c")

    class _H:
        def __init__(self, o):
            self.o = o

        def wait(self, timeout=None):
            return self.o

    for outcome, expect in ((en.SEND_SENT, True), (en.SEND_TRANSIENT_FAIL, False), (en.SEND_SKIPPED, False), (en.SEND_UNKNOWN, False)):
        monkeypatch.setattr(en, "_async_send", lambda to, subject, html, o=outcome: _H(o))
        assert en.send_registered("payable_due_today", title="t", rows=[("a", "b")], to_group=True, wait=True) is expect, outcome


# ── (g) 假日順延（真的官方假日表，不 monkeypatch）────────────────────────

def test_reminders_shift_back_over_a_weekday_holiday(client, make_user, mails):
    """2026-10-09（週五）是補假日：預定日 10/12（週一）⇒ T−3＝10/9 假日 ⇒ 10/8（週四）寄；預定日 10/9 本身 ⇒ 10/8 寄當天那封。"""
    P._finance(make_user, "fx_fin_g")
    P._seed_exp(planned="2026-10-12")
    assert P._run(date(2026, 10, 9)) == 0, "假日當天不寄"
    assert P._run(date(2026, 10, 8)) == 1 and P._subjects_kind(mails) == ["soon"], "T−3 落在假日 ⇒ 前一個工作日（週四）寄"
    assert P._run(date(2026, 10, 12)) == 1 and P._subjects_kind(mails) == ["soon", "today"], "T0 是工作日 ⇒ 當天寄"
    P._seed_exp(planned="2026-10-09")                                         # 預定日本身是假日
    assert P._run(date(2026, 10, 8)) == 1 and P._subjects_kind(mails)[-1] == "today", "T0 落在假日 ⇒ 前一個工作日寄"
    assert P._run(date(2026, 10, 9)) == 0


def test_long_holiday_collapses_to_one_mail_on_the_working_day_before(client, make_user, mails):
    """春節 2026-02-14～02-22：預定日 02-18，T−3＝02-15、T0＝02-18 都折到 02-13（週五）⇒ 只寄一封（當天那封）。"""
    P._finance(make_user, "fx_fin_h")
    P._seed_exp(planned="2026-02-18")
    from modules.case import payable_reminders as R
    assert R.effective_send_day(date(2026, 2, 15)) == R.effective_send_day(date(2026, 2, 18)) == date(2026, 2, 13)
    assert P._run(date(2026, 2, 13)) == 1 and P._subjects_kind(mails) == ["today"], "兩封折成一封"
    assert P._run(date(2026, 2, 13)) == 0 and P._run(date(2026, 2, 18)) == 0 and len(mails) == 1


def test_working_day_uses_holiday_table_and_uncovered_year_falls_back_to_weekends(client, make_user):
    from modules.case import payable_reminders as R
    assert R.is_working_day(date(2026, 10, 8)) and not R.is_working_day(date(2026, 10, 9))
    assert not R.is_working_day(date(2031, 6, 14)) and R.is_working_day(date(2031, 6, 13)), "假日表未涵蓋的年份：只排除週六日"
