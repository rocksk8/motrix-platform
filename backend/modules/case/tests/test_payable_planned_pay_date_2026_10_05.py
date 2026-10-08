# -*- coding: utf-8 -*-
"""預定付款日（2026-10-05，case v7）：欄位／API、IP-100 欄位、行事曆「付款待辦」、提醒信（3 天前＋當天）。
Google 用假行事曆（tests/_fake_gcal.py）；寄信用攔截的 `_async_send`（不連外）。"""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = requires_module("case", "預定付款日在 M01 案件額外支出")

NO = "MQ-PLANPAY-001"


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur
    finally:
        conn.close()


def _row(exp_id):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
    finally:
        conn.close()


def _seed_case():
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "預付客", "預付專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))


def _seed_exp(planned="", status="已核准", paid="", kind="", amount=1200):
    _seed_case()
    cur = _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
             " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date, kind, planned_pay_date)"
             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (NO, "材料", "線材", 1, "", amount, amount, "2031-05-01", "[]", "pp_eng", "工程師甲", "材料行", "2031-05-01",
              "2031-05-01", status, paid, kind, planned))
    return cur.lastrowid


def _hdr(client, make_user, name, role="superadmin", modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _gcal(monkeypatch, events):
    from modules.case import payable_calendar
    from modules.case.api import case_extra_expenses as ce
    from modules.arap.api import cashier
    cal = _fake_gcal.install(monkeypatch)
    for m in (payable_calendar, cashier):
        _fake_gcal.sync_spawn(monkeypatch, m)
    _fake_gcal.set_events(events=events)
    return cal


# ── migration ────────────────────────────────────────────────────────────

def test_migration_adds_column_idempotently_and_reports_missing_table():
    from modules.case.migrations import __path__ as _p  # noqa: F401
    import importlib
    m = importlib.import_module("modules.case.migrations.0007_planned_pay_date")
    c = sqlite3.connect(":memory:")
    assert "不存在" in m.up(c)                                              # 表不在 ⇒ 回原因（未完成），不丟例外
    c.execute("CREATE TABLE case_extra_expenses (id INTEGER PRIMARY KEY, description TEXT)")
    c.execute("INSERT INTO case_extra_expenses (description) VALUES ('舊列')")
    assert m.up(c) is None and m.up(c) is None                              # 冪等
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(case_extra_expenses)")}
    assert "planned_pay_date" in cols
    assert c.execute("SELECT planned_pay_date FROM case_extra_expenses").fetchone()[0] == ""   # 舊列維持空，不補值
    c.execute("INSERT INTO case_extra_expenses (description) VALUES ('新列不帶欄位')")        # 舊程式 INSERT 不帶它也成立（回滾程式碼安全）


def test_migration_is_registered_in_module_spec():
    import modules.case as case_pkg
    spec = getattr(case_pkg, "SPEC", None) or getattr(case_pkg, "spec", None)
    versions = [v for v, _fn in (spec.migrations if spec is not None else [])] if spec is not None else None
    if versions is not None:
        assert versions[-1] == 7


# ── API：建立／編輯／補登 ────────────────────────────────────────────────────

def _create(client, h, **over):
    body = {"category": "材料", "description": "線材", "unitCost": 1200, "qty": 1, "expenseDate": "2031-05-01"}
    body.update(over)
    return client.post("/api/quotations/%s/extra-expenses" % NO, headers=h, json=body)


def test_create_edit_clear_planned_pay_date(client, make_user):
    _seed_case()
    h = _hdr(client, make_user, "pp_sa")
    r = _create(client, h, plannedPayDate="2031-06-10")
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert _row(eid)["planned_pay_date"] == "2031-06-10"
    lst = client.get("/api/quotations/%s/extra-expenses" % NO, headers=h).json()
    items = lst["items"] if isinstance(lst, dict) else lst
    assert [i["plannedPayDate"] for i in items if i["id"] == eid] == ["2031-06-10"]
    body = {"category": "材料", "description": "線材", "unitCost": 1300, "qty": 1, "expenseDate": "2031-05-01"}
    assert client.patch("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h, json=body).status_code == 200
    assert _row(eid)["planned_pay_date"] == "2031-06-10", "編輯沒送 plannedPayDate ⇒ 保留原值（舊前端不會把它洗掉）"
    assert client.patch("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h,
                        json=dict(body, plannedPayDate="2031-06-20")).status_code == 200
    assert _row(eid)["planned_pay_date"] == "2031-06-20"
    assert client.patch("/api/quotations/%s/extra-expenses/%s" % (NO, eid), headers=h, json=dict(body, plannedPayDate="")).status_code == 200
    assert _row(eid)["planned_pay_date"] == ""


@pytest.mark.parametrize("bad", ["2031/06/10", "2031-02-30", "下週", "2031-6-1"])
def test_bad_planned_date_is_rejected(client, make_user, bad):
    _seed_case()
    h = _hdr(client, make_user, "pp_sa")
    assert _create(client, h, plannedPayDate=bad).status_code == 400


def test_no_planned_date_is_fine(client, make_user):
    _seed_case()
    h = _hdr(client, make_user, "pp_sa")
    r = _create(client, h)
    assert r.status_code == 201 and _row(r.json()["id"])["planned_pay_date"] == ""


def test_dates_endpoint_sets_planned_after_approval_but_not_after_paid(client, make_user):
    eid = _seed_exp()
    h = _hdr(client, make_user, "pp_sa")
    url = "/api/quotations/%s/extra-expenses/%s/dates" % (NO, eid)
    assert client.patch(url, headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    assert _row(eid)["planned_pay_date"] == "2031-06-10"
    assert client.patch(url, headers=h, json={"plannedPayDate": "亂寫"}).status_code == 400
    _x("UPDATE case_extra_expenses SET paid_date='2031-06-09' WHERE id=?", (eid,))
    r = client.patch(url, headers=h, json={"plannedPayDate": "2031-06-30"})
    assert r.status_code == 409 and "歷史" in r.json()["detail"]
    assert _row(eid)["planned_pay_date"] == "2031-06-10", "付款後預定日保留當歷史"


def test_ip100_pending_item_carries_planned_date(client, make_user):
    eid = _seed_exp(planned="2031-06-10")
    h = _hdr(client, make_user, "pp_cash", "user", ["cashier"])
    r = client.get("/api/cashier/pending-payables", headers=h)
    assert r.status_code == 200, r.text
    it = [i for i in r.json()["items"] if i["key"] == str(eid)][0]
    assert it["plannedPayDate"] == "2031-06-10"


# ── 行事曆「付款待辦」 ──────────────────────────────────────────────────────

def test_calendar_off_by_default(client, make_user, monkeypatch):
    cal = _gcal(monkeypatch, None)
    eid = _seed_exp()
    h = _hdr(client, make_user, "pp_sa")
    assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, eid), headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    assert cal.calls == []


def test_calendar_follows_state_move_clear_pay_and_void(client, make_user, monkeypatch):
    cal = _gcal(monkeypatch, {"payable_due": True})
    eid = _seed_exp()
    h = _hdr(client, make_user, "pp_sa")
    url = "/api/quotations/%s/extra-expenses/%s/dates" % (NO, eid)
    assert client.patch(url, headers=h, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    (ev,) = cal.events.values()
    assert ev["summary"].startswith("付款待辦 — ") and "線材" in ev["summary"]
    assert not any(x in ev["summary"] + ev["description"] for x in ("1,200", "1200", "NT$", "金額")), "事件不含任何金額"
    assert ev["start"] == {"date": "2031-06-10"} and "預定付款日：2031-06-10" in ev["description"]
    assert ev["extendedProperties"]["private"]["motrixMergeKey"] == "payable_due#case:%s" % eid
    assert client.patch(url, headers=h, json={"plannedPayDate": "2031-06-25"}).status_code == 200      # 改期 ⇒ 同一筆移動
    assert len(cal.events) == 1 and list(cal.events.values())[0]["start"] == {"date": "2031-06-25"}
    assert client.patch(url, headers=h, json={"plannedPayDate": ""}).status_code == 200                # 清空 ⇒ 刪
    assert cal.events == {}
    assert client.patch(url, headers=h, json={"plannedPayDate": "2031-07-01"}).status_code == 200
    assert len(cal.events) == 1
    r = client.post("/api/quotations/%s/extra-expenses/%s/void" % (NO, eid), headers=h, json={"reason": "重複請款"})   # 作廢 ⇒ 刪
    assert r.status_code == 200, r.text
    assert cal.events == {}


def test_calendar_deleted_when_cashier_pays(client, make_user, monkeypatch):
    cal = _gcal(monkeypatch, {"payable_due": True})
    eid = _seed_exp(planned="2031-06-10")
    sa = _hdr(client, make_user, "pp_sa")
    assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, eid), headers=sa, json={"plannedPayDate": "2031-06-11"}).status_code == 200
    assert len(cal.events) == 1
    cash = _hdr(client, make_user, "pp_cash", "user", ["cashier"])
    r = client.post("/api/cashier/pending-payables/case/%s/pay" % eid, headers=cash, json={"paidDate": "2031-06-09"})
    assert r.status_code == 200, r.text
    assert cal.events == {}, "出納付款 ⇒ 收回付款待辦（用 IP-100 的 來源:key 識別）"


def test_calendar_not_for_unapproved_unplanned_or_non_payable(client, make_user, monkeypatch):
    cal = _gcal(monkeypatch, {"payable_due": True})
    from modules.case import payable_calendar as PC
    sa = _hdr(client, make_user, "pp_sa")
    draft = _seed_exp(status="草稿")
    req = _seed_exp(kind="purchase_req")
    plain = _seed_exp()                                                  # 已核准但沒填預定日
    for eid in (draft, req):
        assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, eid), headers=sa, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, plain), headers=sa, json={"plannedPayDate": ""}).status_code == 200
    assert cal.events == {}, "草稿、請購單（不進出納）、沒預定日的都不該有待辦"
    assert PC.eligible(_row(draft)) is False and PC.eligible(_row(req)) is False and PC.eligible(_row(plain)) is False
    assert client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, plain), headers=sa, json={"plannedPayDate": "2031-06-10"}).status_code == 200
    assert len(cal.events) == 1, "對照：已核准的一般請款填了預定日就有待辦"


def test_calendar_created_when_final_approval_lands(client, make_user, monkeypatch):
    """送審（草稿不建）⇒ 部門主管核准（最終核准）⇒ 有預定日就建「付款待辦」。"""
    cal = _gcal(monkeypatch, {"payable_due": True})
    _seed_case()
    hq = _hdr(client, make_user, "pp_req", "admin")
    hm = _hdr(client, make_user, "pp_mgr", "admin")
    _x("INSERT OR IGNORE INTO divisions (id, name, sort_order, created_at) VALUES (1, '營運處', 0, '2026-01-01T00:00:00')")
    _x("INSERT OR IGNORE INTO departments (id, division_id, name, sort_order, created_at) VALUES (1, 1, '工程部', 0, '2026-01-01T00:00:00')")
    _x("UPDATE departments SET manager_user_id=(SELECT id FROM users WHERE username='pp_mgr') WHERE id=1")
    _x("UPDATE users SET department_id=1 WHERE username='pp_req'")
    r = _create(client, hq, plannedPayDate="2031-06-10")
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert cal.events == {}, "草稿不建"
    r = client.post("/api/quotations/%s/extra-expenses/%s/submit" % (NO, eid), headers=hq)
    assert r.status_code == 200, r.text
    assert cal.events == {} or r.json().get("status") == "已核准"
    if r.json().get("status") != "已核准":
        assert cal.events == {}, "送審中不建"
        for _ in range(5):
            ra = client.post("/api/quotations/%s/extra-expenses/%s/approve" % (NO, eid), headers=hm, json={})
            if ra.status_code != 200 or ra.json().get("status") == "已核准":
                break
        assert _row(eid)["status"] == "已核准", ra.text
    assert len(cal.events) == 1 and list(cal.events.values())[0]["start"] == {"date": "2031-06-10"}


# ── 提醒信 ─────────────────────────────────────────────────────────────────

TODAY = date(2031, 6, 10)


def _set_mail(username, email, muted=()):
    _x("UPDATE users SET email=?, notification_muted=?, active=1 WHERE username=?", (email, json.dumps(list(muted)), username))


@pytest.fixture
def mails(monkeypatch):
    from helpers import email_notify as en
    sent = []
    class _Sent:                                              # 寄送把手：本次起提醒信等結果才寫 guard（`send_registered(wait=True)`）
        outcome = en.SEND_SENT

        def wait(self, timeout=None):
            return self.outcome

    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: sent.append((sorted(to), subject, html)) or _Sent())
    return sent


def _finance(make_user, name, role="superadmin", muted=(), email=None):
    make_user(username=name, role=role)
    _set_mail(name, email or "%s@example.com" % name, muted)


def _run(today=TODAY):
    from modules.case import payable_reminders as R
    return R.run(today)


def test_fires_three_days_before_and_on_the_day_and_is_idempotent(client, make_user, mails):
    _finance(make_user, "fin_a")
    soon = _seed_exp(planned=(TODAY + timedelta(days=3)).isoformat())
    today_item = _seed_exp(planned=TODAY.isoformat())
    assert _run() == 2
    subjects = " | ".join(m[1] for m in mails)
    assert len(mails) == 2 and "預定付款日將到" in subjects + "".join(m[2] for m in mails) and "預定付款日當天" in "".join(m[2] for m in mails)
    assert _run() == 0 and len(mails) == 2, "同一天重跑／重啟補跑不重寄（guard key）"
    assert soon != today_item


def test_not_on_other_days_and_no_date_and_paid_voided_unapproved_are_skipped(client, make_user, mails):
    _finance(make_user, "fin_a")
    _seed_exp(planned=(TODAY + timedelta(days=2)).isoformat())          # 2 天前不發（只有 3 天前與當天）
    _seed_exp(planned=(TODAY + timedelta(days=4)).isoformat())
    _seed_exp(planned=(TODAY - timedelta(days=5)).isoformat())          # 已過很久不補（逾期只在「預定日後第 1 個工作日」寄一封，第 45 班 Q2）發
    _seed_exp(planned="")                                               # 沒填 ⇒ 不提醒
    _seed_exp(planned=TODAY.isoformat(), paid="2031-06-09")             # 已付款
    _seed_exp(planned=TODAY.isoformat(), status="已作廢")
    _seed_exp(planned=TODAY.isoformat(), status="待審核")
    _seed_exp(planned=TODAY.isoformat(), kind="purchase_req")           # 請購單不進出納
    assert _run() == 0 and mails == []


def _subjects_kind(mails):
    return ["today" if "今日到期" in m[2] else ("overdue" if "已逾期" in m[2] else "soon") for m in mails]


def test_calendar_assumptions():
    assert TODAY.weekday() == 1                                            # 2031-06-10 週二
    assert date(2031, 6, 13).weekday() == 4 and date(2031, 6, 14).weekday() == 5 and date(2031, 6, 15).weekday() == 6


def test_due_on_saturday_or_sunday_sends_the_friday_before(client, make_user, mails):
    _finance(make_user, "fin_a")
    fri, sat, sun = date(2031, 6, 13), date(2031, 6, 14), date(2031, 6, 15)
    _seed_exp(planned=sat.isoformat())
    _seed_exp(planned=sun.isoformat())
    assert _run(sat) == 0 and _run(sun) == 0 and mails == [], "週末當天不寄（已提前）"
    assert _run(fri) == 2 and _subjects_kind(mails) == ["today", "today"], "週六、週日到期 ⇒ 週五寄「今日到期」"
    assert _run(fri) == 0, "同一天重跑不重寄"


def test_three_days_before_landing_on_weekend_moves_to_previous_friday(client, make_user, mails):
    _finance(make_user, "fin_a")
    due = date(2031, 6, 17)                                                # 週二；−3 天＝週六 6/14
    _seed_exp(planned=due.isoformat())
    assert (due - timedelta(days=3)).weekday() == 5
    assert _run(date(2031, 6, 14)) == 0 and _run(date(2031, 6, 15)) == 0
    assert _run(date(2031, 6, 13)) == 1 and _subjects_kind(mails) == ["soon"]
    assert _run(due) == 1 and _subjects_kind(mails) == ["soon", "today"], "當天仍照常再寄一封"


def test_sunday_minus_three_is_thursday_and_saturday_minus_three_is_wednesday(client, make_user, mails):
    _finance(make_user, "fin_a")
    _seed_exp(planned=date(2031, 6, 15).isoformat())                       # 週日 ⇒ −3＝週四
    assert _run(date(2031, 6, 12)) == 1 and _subjects_kind(mails) == ["soon"]
    _seed_exp(planned=date(2031, 6, 14).isoformat())                       # 週六 ⇒ −3＝週三
    assert _run(date(2031, 6, 11)) == 1 and _subjects_kind(mails)[-1] == "soon"


def test_collapse_to_one_mail_when_both_land_on_the_same_send_day(client, make_user, monkeypatch, mails):
    """名義日折到同一個寄信日 ⇒ 只寄一封（當天那封）；用注入的假日驗（目前工作日只排除週末，週末情形不會折疊）。"""
    from modules.case import payable_reminders as R
    _finance(make_user, "fin_a")
    holiday = date(2031, 6, 16)                                            # 週一假日：週五是上一個工作日
    monkeypatch.setattr(R, "is_working_day", lambda d: d.weekday() < 5 and d != holiday)
    _seed_exp(planned=holiday.isoformat())                                 # T0 → 6/13（週五）；T−3 = 6/13（週五）
    fri = date(2031, 6, 13)
    assert R.due_kind(holiday.isoformat(), fri)[0] == "today"
    assert _run(fri) == 1 and _subjects_kind(mails) == ["today"], "兩封折成一封"
    assert _run(fri) == 0 and len(mails) == 1
    assert _run(holiday) == 0, "假日當天不寄"
    assert _run(date(2031, 6, 17)) == 1 and _subjects_kind(mails) == ["today", "overdue"], "預定日後第 1 個工作日＝逾期那一封（第 45 班 Q2）"
    assert _run(date(2031, 6, 17)) == 0 and _run(date(2031, 6, 18)) == 0, "逾期只一封，不週提、不再補寄當天／3 天前"


def test_holiday_seam_is_one_function(client, make_user, monkeypatch, mails):
    """接上假日表只改 is_working_day：週二是假日 ⇒ 週二到期改在週一寄。"""
    from modules.case import payable_reminders as R
    _finance(make_user, "fin_a")
    off = date(2031, 6, 10)
    monkeypatch.setattr(R, "is_working_day", lambda d: d.weekday() < 5 and d != off)
    _seed_exp(planned=off.isoformat())
    assert _run(off) == 0
    assert _run(date(2031, 6, 9)) == 1


def test_effective_send_day_and_due_kind_pure_functions():
    from modules.case import payable_reminders as R
    assert R.effective_send_day(date(2031, 6, 14)) == date(2031, 6, 13)
    assert R.effective_send_day(date(2031, 6, 15)) == date(2031, 6, 13)
    assert R.effective_send_day(date(2031, 6, 12)) == date(2031, 6, 12)
    assert R.due_kind("2031-06-14", date(2031, 6, 13)) == ("today", [("today", date(2031, 6, 13))])
    assert R.due_kind("2031-06-14", date(2031, 6, 11)) == ("soon", [("soon", date(2031, 6, 11))])
    assert R.due_kind("2031-06-14", date(2031, 6, 14))[0] == "" and R.due_kind("2031-06-14", date(2031, 6, 12))[0] == ""
    assert R._candidate_planned_dates(date(2031, 6, 14)) == [] and R._candidate_planned_dates(date(2031, 6, 15)) == []


def test_changed_date_refires_for_the_new_date(client, make_user, mails):
    _finance(make_user, "fin_a")
    eid = _seed_exp(planned=TODAY.isoformat())
    assert _run() == 1
    later = TODAY + timedelta(days=6)                                  # 週一
    _x("UPDATE case_extra_expenses SET planned_pay_date=? WHERE id=?", (later.isoformat(), eid))
    assert _run(later) == 1 and len(mails) == 2


def test_recipients_are_finance_roles_not_others_and_opt_out_is_respected(client, make_user, mails):
    _finance(make_user, "fin_a")
    _finance(make_user, "fin_muted", muted=["payable_due_today"])
    make_user(username="plain_admin", role="admin", modules=["cashier"], legacy_finance_flag=False)   # 持有惰性的出納勾選但不是財務角色 ⇒ 不收（權限路線 A）
    _set_mail("plain_admin", "plain@example.com")
    make_user(username="plain_sales", role="sales")
    _set_mail("plain_sales", "sales@example.com")
    _seed_exp(planned=TODAY.isoformat())
    assert _run() == 1
    (to, _subject, html) = mails[0]
    assert to == ["fin_a@example.com"], "只有財務角色、且沒退訂這一類的人收到"
    assert "1,200" not in html and "NT$" not in html, "信內不放金額"


def test_audience_is_the_finance_mail_group_only_no_extra_usernames(client, make_user, monkeypatch, mails):
    """合併後語意：收件人＝財務郵件群組（`finance_recipient_emails`），寄信不另帶 usernames（沒有雙重聯集）。"""
    from helpers import email_notify as en
    _finance(make_user, "fin_a")
    make_user(username="other_user", role="viewer")
    _set_mail("other_user", "other@example.com")
    seen = []
    real = en.finance_recipient_emails
    monkeypatch.setattr(en, "finance_recipient_emails", lambda event_key=None: seen.append(event_key) or ["other@example.com"])
    _seed_exp(planned=TODAY.isoformat())
    assert _run() == 1
    assert seen == ["payable_due_today"] and mails[0][0] == ["other@example.com"], "只用群組那一條，不再把 finance_usernames 併進來"
    assert real("payable_due_today") == ["fin_a@example.com"] or "fin_a@example.com" in real("payable_due_today")


def test_superadmin_only_override_is_respected(client, make_user, mails):
    """收件設定頁把這類信改成「僅超級管理員」⇒ 財務角色不收、只有超級管理員收（與其他財務信一致）。"""
    from helpers import _set_setting
    _finance(make_user, "fin_a", role="finance")
    _finance(make_user, "sa_only", role="superadmin")
    _set_setting("mail_recipient_overrides", {"payable_due_today": {"mode": "superadmin_only", "users": [], "roles": []}})
    try:
        _seed_exp(planned=TODAY.isoformat())
        assert _run() == 1
        assert "fin_a@example.com" not in mails[0][0] and "sa_only@example.com" in mails[0][0]
    finally:
        _set_setting("mail_recipient_overrides", {})                  # 共用資料庫：不留覆寫給別題


def test_no_recipients_means_no_guard_so_it_retries_later(client, make_user, monkeypatch, mails):
    from helpers import email_notify as en
    holder = []
    monkeypatch.setattr(en, "finance_recipient_emails", lambda event_key=None: list(holder))
    _seed_exp(planned=TODAY.isoformat())
    assert _run() == 0 and mails == []
    holder.append("late@example.com")
    assert _run() == 1, "有收件人之後同一天補發（先前沒寫 guard）"


def test_stale_guard_keys_are_pruned(client, make_user, mails):
    from helpers import _get_setting, _set_setting
    _set_setting("payable_due_notif.1.today.2031-05-01", "2031-05-01")
    _set_setting("payable_due_notif.2.today.2031-06-12", "2031-06-10")
    _run()
    assert not _get_setting("payable_due_notif.1.today.2031-05-01")
    assert _get_setting("payable_due_notif.2.today.2031-06-12")


def test_mail_types_registered_with_owner_case():
    from helpers import mail_types as mt
    from modules.case import payable_reminders  # noqa: F401
    for k in ("payable_due_soon", "payable_due_today"):
        t = mt._REGISTRY[k]
        assert t.owner == "case" and t.category == "business"


def test_reminder_mail_types_are_in_the_finance_group():
    """合併後財務群組一定存在：payable_due_* 登記在 finance 群組（收件設定頁覆寫與其他財務信一致）。"""
    from helpers import mail_types as mt
    from modules.case import payable_reminders  # noqa: F401
    for k in ("payable_due_soon", "payable_due_today"):
        assert mt._REGISTRY[k].group == "finance" and mt._REGISTRY[k].owner == "case"
