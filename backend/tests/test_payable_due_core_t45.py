# -*- coding: utf-8 -*-
"""第 45 班 S5：L1 共用提醒庫 `helpers.payable_due_core` 的純函式——不需要任何 L2 模組（模組缺席時照常要過；PLAYBOOK §G5 #7）。"""
from datetime import date, timedelta


def _wd(d):
    return d.weekday() < 5


def test_overdue_is_first_working_day_after_planned():
    from helpers import payable_due_core as C
    tue = date(2031, 6, 10)
    assert C.due_kind(tue.isoformat(), tue + timedelta(days=1), _wd)[0] == "overdue"
    assert C.due_kind(tue.isoformat(), tue + timedelta(days=2), _wd)[0] == "", "只一封，不週提"
    fri = date(2031, 6, 13)
    assert C.due_kind(fri.isoformat(), date(2031, 6, 14), _wd)[0] == ""                      # 週六不是工作日
    assert C.due_kind(fri.isoformat(), date(2031, 6, 16), _wd) == ("overdue", [("overdue", date(2031, 6, 16))])   # 週一
    assert C.due_kind(tue.isoformat(), tue, _wd)[0] == "today" and C.due_kind("2031-06-12", date(2031, 6, 9), _wd)[0] == "soon"


def test_candidates_include_the_dates_whose_overdue_day_is_today():
    from helpers import payable_due_core as C
    mon = date(2031, 6, 16)
    c = C.candidate_planned_dates(mon, _wd)
    assert {"2031-06-13", "2031-06-14", "2031-06-15"} <= set(c), "週五／六／日到期 ⇒ 週一逾期"
    assert "2031-06-12" not in c
    assert C.candidate_planned_dates(date(2031, 6, 14), _wd) == []                           # 週末不寄
    for d in (date(2031, 6, 11), mon):                                                       # 與 due_kind 一致：候選以外的日期今天不可能有信
        for k in range(-20, 20):
            p = (d + timedelta(days=k)).isoformat()
            if C.due_kind(p, d, _wd)[0]:
                assert p in C.candidate_planned_dates(d, _wd), (d, p)


def test_sync_event_is_off_for_payslips_and_on_for_the_three_sources(monkeypatch):
    from helpers import payable_due_core as C
    import helpers
    calls = []
    monkeypatch.setattr(helpers, "push_event_upsert_for_module", lambda *a: calls.append(("up",) + a))
    monkeypatch.setattr(helpers, "push_event_delete_for_module", lambda *a: calls.append(("del",) + a))
    assert C.sync_event("payroll_payslip", "PS-1", ("t", "d", "2031-06-10")) is False and C.sync_event("payroll_payslip", "PS-1") is False
    assert calls == [], "勞報單不進行事曆：一律零呼叫"
    for src in ("case", "subcontract_voucher", "case_material"):
        assert C.sync_event(src, "K") is True and C.sync_event(src, "K", ("t", "d", "2031-06-10")) is True
    assert [c[0] for c in calls] == ["del", "up"] * 3
    assert {c[-1] for c in calls} == {"case:K", "subcontract_voucher:K", "case_material:K"}


