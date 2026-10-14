# -*- coding: utf-8 -*-
"""F3b：預定付款日提醒的『提前天數』跟著設定中心『出納』的自訂天數（旗標 custom_due_soon 關＝3 天＝今天的行為）。純函式題。
- soon_days()：旗標關／值不合法／讀不到 ⇒ 3；旗標開且 1～60 ⇒ 該值
- due_kind／candidate_planned_dates：預設（含 days=None 與旗標關）對『每個預定日 × 每個今天（前後各 12 天）』逐格等於舊算式（含週末、國定假日、連假）；
  自訂天數 N 時等於『把舊算式的 3 換成 N』；突變正對照：N=5 的結果一定和預設不同
- label：預設逐字『預定付款日將到（3 天後）』；信件文字（兩個模組）用 soon_days()
- 原始碼：核心裡不再有直接用 SOON_DAYS 做日期運算的地方（只剩預設常數）"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from helpers import payable_due_core as C

ROOT = Path(__file__).resolve().parents[1]
HOL = {date(2026, 10, 10), date(2026, 10, 12), date(2026, 12, 25), date(2027, 1, 1), date(2027, 2, 8), date(2027, 2, 9), date(2027, 2, 10)}


def wd(d):
    return d.weekday() < 5 and d not in HOL


def legacy_due_kind(planned, today, is_wd, soon=3):
    p = date.fromisoformat(planned)
    e_soon, e_today = C.effective_send_day(p - timedelta(days=soon), is_wd), C.effective_send_day(p, is_wd)
    e_over = C.next_working_day(p + timedelta(days=1), is_wd)
    if e_soon == e_today and e_today == today:
        return "today", [("soon", e_soon), ("today", e_today)]
    if e_today == today and e_soon != e_today:
        return "today", [("today", e_today)]
    if e_soon == today and e_soon != e_today:
        return "soon", [("soon", e_soon)]
    if e_over == today:
        return "overdue", [("overdue", e_over)]
    return "", []


def legacy_candidates(today, is_wd, soon=3):
    if not is_wd(today):
        return []
    span = [today]
    d = today + timedelta(days=1)
    while not is_wd(d) and len(span) < 14:
        span.append(d)
        d += timedelta(days=1)
    out = {(x + timedelta(days=k)).isoformat() for x in span for k in (0, soon)}
    d = today - timedelta(days=1)
    for _ in range(14):
        out.add(d.isoformat())
        if is_wd(d):
            break
        d -= timedelta(days=1)
    return sorted(out)


def _fake(monkeypatch, values):
    from helpers import settings_registry as SR

    def get(group, field, conn=None, **kw):
        if group != "finance_cashier":
            raise KeyError(group)
        return values[field]
    monkeypatch.setattr(SR, "get", get)


def test_soon_days_semantics(monkeypatch):
    _fake(monkeypatch, {"custom_due_soon": 0, "due_soon_planned_days": 9})
    assert C.soon_days() == 3
    _fake(monkeypatch, {"custom_due_soon": 1, "due_soon_planned_days": 5})
    assert C.soon_days() == 5
    for bad in (0, 61, -2, "x", None):
        _fake(monkeypatch, {"custom_due_soon": 1, "due_soon_planned_days": bad})
        assert C.soon_days() == 3, bad
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert C.soon_days() == 3


def test_default_dates_are_exactly_todays_for_every_weekend_and_holiday_case(monkeypatch):
    _fake(monkeypatch, {"custom_due_soon": 0, "due_soon_planned_days": 3})
    n = 0
    for k in range(0, 420):
        p = date(2026, 10, 1) + timedelta(days=k)
        for off in range(-12, 12):
            t = p + timedelta(days=off)
            want = legacy_due_kind(p.isoformat(), t, wd)
            assert C.due_kind(p.isoformat(), t, wd) == want and C.due_kind(p.isoformat(), t, wd, 3) == want, (p, t)
            n += 1
        assert C.candidate_planned_dates(p, wd) == legacy_candidates(p, wd) == C.candidate_planned_dates(p, wd, 3), p
    assert n > 9000


@pytest.mark.parametrize("days", [1, 2, 5, 7, 14])
def test_custom_days_equal_the_old_formula_with_the_number_swapped(days):
    differs = 0
    for k in range(0, 200):
        p = date(2026, 10, 1) + timedelta(days=k)
        for off in range(-16, 16):
            t = p + timedelta(days=off)
            assert C.due_kind(p.isoformat(), t, wd, days) == legacy_due_kind(p.isoformat(), t, wd, days)
            differs += C.due_kind(p.isoformat(), t, wd, days) != legacy_due_kind(p.isoformat(), t, wd, 3)
        assert C.candidate_planned_dates(p, wd, days) == legacy_candidates(p, wd, days)
    if days != 3:
        assert differs > 0                                   # 突變正對照：不同天數真的會改變寄信日


def test_run_scan_uses_one_number_for_the_whole_scan(monkeypatch):
    _fake(monkeypatch, {"custom_due_soon": 1, "due_soon_planned_days": 5})
    sent = []
    today = date(2026, 11, 2)                                # 週一
    planned = (today + timedelta(days=5)).isoformat()        # 預定日 − 5 天 ＝ 今天 ⇒ soon
    monkeypatch.setattr(C, "notify_finance", lambda *a, **k: 1)
    monkeypatch.setattr(C, "_get_setting", lambda k, d=None: None)
    monkeypatch.setattr(C, "_set_setting", lambda k, v: None)
    monkeypatch.setattr(C, "prune_guards", lambda t: None)

    def send(kind, rows, link, ident, out):
        sent.append(kind)
        out["outcome"] = C._en.SEND_SENT
        return True
    n = C.run_scan([{"guard_id": "t", "planned": planned, "ident": "X1", "rows": [], "source": "t", "key": "k"}], today, is_wd=wd, send=send, link="x")
    assert n == 1 and sent == ["soon"]


def test_label_and_mail_text():
    assert C.label("soon") == "預定付款日將到（3 天後）" == C._LABEL["soon"]
    assert C.label("soon", 5) == "預定付款日將到（5 天後）" and C.label("today") == "預定付款日當天" and C.label("overdue") == "預定付款日已逾期"
    for rel in ("modules/case/payable_reminders.py", "modules/subcontract/payable_due.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert '"%d 天後到期" % _core.soon_days()' in src and "還有 %d 天" in src and 'badge_text="3 天後到期"' not in src, rel
    assert "預定付款日將到（3 天前）" in (ROOT / "modules/case/payable_reminders.py").read_text(encoding="utf-8")     # 信件類型的清單標題不變


def test_core_no_longer_does_date_math_with_the_constant():
    src = (ROOT / "helpers/payable_due_core.py").read_text(encoding="utf-8")
    assert "timedelta(days=SOON_DAYS)" not in src and "(0, SOON_DAYS)" not in src
    assert "timedelta(days=days)" in src and "(0, days)" in src
