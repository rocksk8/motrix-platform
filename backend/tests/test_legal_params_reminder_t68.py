# -*- coding: utf-8 -*-
"""T68 Y：法規參數跨年提醒的起算日是設定（預設 10/1），不再寫死 12 月；起算日以外的法規檢查不變。"""
from datetime import date

import pytest

from helpers import legal_params as lp
from helpers import settings_groups  # noqa: F401  登錄群組
from helpers import settings_registry as SR

V = lp.DEFAULT_TAX_RULE_VERSIONS


def _v2027():
    import copy
    v = copy.deepcopy(V[-1])
    v["version"], v["effectiveFrom"] = "2027", "2027-01-01"
    return v


def test_setting_defaults_and_bounds_are_registered():
    f = {x["key"]: x for x in SR.groups()["legal_params_reminder"]["fields"]}
    assert (f["start_month"]["default"], f["start_month"]["min"], f["start_month"]["max"]) == (10, 1, 12)
    assert (f["start_day"]["default"], f["start_day"]["min"], f["start_day"]["max"]) == (1, 1, 28)
    assert lp._reminder_start() == (10, 1) == lp._REMINDER_FALLBACK


@pytest.mark.parametrize("today,start,missing", [
    (date(2026, 9, 30), (10, 1), False),
    (date(2026, 10, 1), (10, 1), True),
    (date(2026, 11, 15), (10, 1), True),
    (date(2026, 11, 30), (12, 1), False),          # 等值：舊行為（12 月起）可由設定還原
    (date(2026, 12, 1), (12, 1), True),
    (date(2026, 3, 15), (3, 15), True),
    (date(2026, 3, 14), (3, 15), False),
])
def test_reminder_starts_on_the_configured_date(today, start, missing, monkeypatch):
    monkeypatch.setattr(lp, "_reminder_start", lambda conn=None: start)
    st = lp.year_status(V, today)
    assert st["nextYearMissing"] is missing
    assert any("2027 年的法規參數" in w for w in st["warnings"]) is missing


def test_default_start_is_read_from_the_setting_when_not_given():
    assert lp.year_status(V, date(2026, 10, 1))["nextYearMissing"] is True
    assert lp.year_status(V, date(2026, 9, 30))["nextYearMissing"] is False


def test_once_next_year_has_a_version_the_reminder_stops_whatever_the_start(monkeypatch):
    for start in ((1, 1), (10, 1), (12, 1)):
        monkeypatch.setattr(lp, "_reminder_start", lambda conn=None, s=start: s)
        assert lp.year_status(V + [_v2027()], date(2026, 12, 20))["nextYearMissing"] is False


def test_warning_wording_follows_the_start_and_legal_parts_stay_fixed(monkeypatch):
    def at(today, start):
        monkeypatch.setattr(lp, "_reminder_start", lambda conn=None: start)
        return lp.year_status(V, today)
    w10 = [w for w in at(date(2026, 10, 5), (10, 1))["warnings"] if "2027" in w][0]
    assert w10.startswith("已進入 10 月，2027 年的法規參數（最低工資、扣繳起扣標準、補充保費門檻）還沒有設定")
    w12 = [w for w in at(date(2026, 12, 5), (12, 1))["warnings"] if "2027" in w][0]
    assert w12.startswith("已進入 12 月，2027 年的法規參數"), "起算日 12/1 時文字與原本逐字相同"
    wd = [w for w in at(date(2026, 11, 20), (11, 15))["warnings"] if "2027" in w][0]
    assert wd.startswith("已過 11 月 15 日，2027 年的法規參數")
    st = at(date(2026, 10, 5), (10, 1))
    assert st["nextYear"] == 2027                                        # 下一年度＝今年＋1（法規決定，不可設定）


def test_unreadable_setting_falls_back_and_bad_values_are_ignored(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("設定層壞了")
    monkeypatch.setattr(SR, "get", boom)
    assert lp._reminder_start() == (10, 1)
    monkeypatch.setattr(SR, "get", lambda g, f, **k: 13 if f == "start_month" else 1)
    assert lp._reminder_start() == (10, 1), "月份超出 1–12 ⇒ 後備"
    monkeypatch.setattr(SR, "get", lambda g, f, **k: 3 if f == "start_month" else 15)
    assert lp._reminder_start() == (3, 15)


# ── r2：真實設定 → 行為（不 monkeypatch 讀設定那層）、跨年邊界 ──────────────────
@pytest.fixture()
def real_conn(client):
    from db import get_db
    c = get_db()
    SR.invalidate()
    yield c
    c.close()
    SR.invalidate()


def test_published_setting_really_changes_year_status(real_conn):
    """真實路徑（不 monkeypatch 讀設定那層）：往後延＝放寬 ⇒ 待生效，確認期間後才改變 year_status；提前＝立即生效。"""
    from datetime import datetime, timedelta
    from helpers import config_ledger as L
    c = real_conn
    assert lp.year_status(V, date(2026, 10, 5))["nextYearMissing"] is True
    out = SR.publish("legal_params_reminder", {"start_month": 12, "start_day": 1}, reason="測試", user="admin", conn=c)
    c.commit()
    SR.invalidate()
    assert out["pending"], "往後延（10/1 → 12/1）是放寬方向 ⇒ 待生效"
    assert lp._reminder_start() == (10, 1) and lp.year_status(V, date(2026, 10, 5))["nextYearMissing"] is True, "確認期間內仍是舊值"
    rows = L.pending(c, "setting:legal_params_reminder")
    assert {r["field"] for r in rows} == {"start_month"}, "只有月份往後延；日 1→1 沒變"
    for r in rows:                                                    # 第二位最高管理者核准（申請人不能核准自己的）
        L.approve(c, r["id"], "approver_b", "測試核准")
    later = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
    assert SR.materialize_due(c, now=later) >= 1
    c.commit()
    SR.invalidate()
    assert lp._reminder_start() == (12, 1)
    assert lp.year_status(V, date(2026, 10, 5))["nextYearMissing"] is False, "起算日改成 12/1 ⇒ 10 月不再提醒（與舊行為相同）"
    assert lp.year_status(V, date(2026, 12, 1))["nextYearMissing"] is True
    out = SR.publish("legal_params_reminder", {"start_month": 11, "start_day": 15}, reason="測試", user="admin", conn=c)
    c.commit()
    SR.invalidate()
    assert lp._reminder_start() == (11, 1) and out["pending"], "月 12→11 提前 ⇒ 立即生效；日 1→15 往後延 ⇒ 待生效（逐欄判斷）"
    SR.publish("legal_params_reminder", {"start_month": 9}, reason="測試", user="admin", conn=c)    # 提前：立即生效
    c.commit()
    SR.invalidate()
    assert lp._reminder_start()[0] == 9
    assert lp.year_status(V, date(2026, 9, 1))["nextYearMissing"] is True


def test_setting_is_flagged_as_a_loosening_with_risk_text():
    f = {x["key"]: x for x in SR.groups()["legal_params_reminder"]["fields"]}
    for k in ("start_month", "start_day"):
        assert f[k]["loosen"] == "up" and f[k]["impactScope"]["effective"] == "pending", k
        assert f[k]["riskText"] if "riskText" in f[k] else f[k].get("risk_text")


@pytest.mark.parametrize("today,missing", [
    (date(2026, 12, 31), True),          # 提醒一直到年底
    (date(2027, 1, 1), False),           # 跨年：今年＝2027，下一年 2028 要到 10/1 才提醒
    (date(2027, 9, 30), False),
    (date(2027, 10, 1), True),
])
def test_year_rollover_boundary(today, missing):
    st = lp.year_status(V, today)
    assert st["nextYearMissing"] is missing
    assert st["nextYear"] == today.year + 1
