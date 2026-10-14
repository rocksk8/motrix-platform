# -*- coding: utf-8 -*-
"""F5a「已結案未精算」等待天數（finance_reports.settle_overdue_days）與 F4a 應收逾期寬限（finance_cashier.receivable_grace_days）。
兩者預設 0 ＝今天的行為（旗標＝數值 0）。純函式／原始碼題；需要資料庫的題寫好未跑。
- 設定讀取：0～上限的整數；布林、小數、超出範圍、讀不到 ⇒ 0
- _settle_waited：最後更新日距今超過 N 天才 True；日期讀不出來 ⇒ True（不隱藏）
- 逾期判定：寬限 0 時 `expected < today`（逐日等於舊算式）；寬限 g 時 `expected < today - g`
- 原始碼：兩處都經 finance_params；舊的直接比較式已換掉"""
from datetime import date, timedelta
from pathlib import Path

import pytest

from helpers import finance_params as F

ROOT = Path(__file__).resolve().parents[1]


def _fake(monkeypatch, group, values):
    from helpers import settings_registry as SR

    def get(g, f, conn=None, **kw):
        if g != group:
            raise KeyError(g)
        return values[f]
    monkeypatch.setattr(SR, "get", get)


@pytest.mark.parametrize("val,want", [(0, 0), (14, 14), (365, 365), (366, 0), (-1, 0), (2.5, 0), (True, 0), ("7", 0), (None, 0), (14.0, 14)])
def test_settle_overdue_days_reading(monkeypatch, val, want):
    _fake(monkeypatch, "finance_reports", {"settle_overdue_days": val})
    assert F.settle_overdue_days() == want


@pytest.mark.parametrize("val,want", [(0, 0), (3, 3), (90, 90), (91, 0), (-1, 0), (1.5, 0), (False, 0), (None, 0)])
def test_receivable_grace_days_reading(monkeypatch, val, want):
    _fake(monkeypatch, "finance_cashier", {"receivable_grace_days": val})
    assert F.receivable_grace_days() == want


def test_reading_failure_is_zero_days(monkeypatch):
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert F.settle_overdue_days() == 0 and F.receivable_grace_days() == 0


def test_settle_waited():
    from modules.analytics.api import reports as R
    today = date.today()
    d = lambda n: (today - timedelta(days=n)).isoformat() + "T10:00:00"
    assert R._settle_waited(d(15), 14) is True and R._settle_waited(d(14), 14) is False and R._settle_waited(d(0), 14) is False
    for bad in (None, "", "abc", "2026-13-40"):
        assert R._settle_waited(bad, 14) is True                         # 讀不出來 ⇒ 列出，不隱藏


def test_overdue_arithmetic_with_zero_grace_equals_the_old_expression():
    today = date(2026, 10, 14)
    for k in range(-40, 40):
        expected = (today + timedelta(days=k)).isoformat()
        old = expected < today.isoformat()
        new = expected < (today - timedelta(days=0)).isoformat()
        assert old == new
    exp = (today - timedelta(days=2)).isoformat()                          # 2 天前到期
    assert exp < (today - timedelta(days=0)).isoformat() and not (exp < (today - timedelta(days=3)).isoformat())


def test_sources_use_the_helpers():
    cash = (ROOT / "modules/arap/api/cashier.py").read_text(encoding="utf-8")
    assert "_overdue_before = (today - timedelta(days=_finance_params.receivable_grace_days())).isoformat()" in cash
    assert "expected < _overdue_before" in cash and "expected < today.isoformat()" not in cash
    rep = (ROOT / "modules/analytics/api/reports.py").read_text(encoding="utf-8")
    assert "_finance_params.settle_overdue_days()" in rep and "if _so_days > 0:" in rep and "def _settle_waited" in rep


def test_settings_are_registered_with_zero_defaults():
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    assert SR.get("finance_reports", "settle_overdue_days") == 0 and SR.get("finance_cashier", "receivable_grace_days") == 0
    f = SR._GROUPS["finance_reports"]["fields"]["settle_overdue_days"]
    g = SR._GROUPS["finance_cashier"]["fields"]["receivable_grace_days"]
    assert (f.min, f.max, g.min, g.max) == (0, 365, 0, 90)
    # D-K1（使用者裁示 2026-10-14）：寬限天數調大＝逾期標示更晚＝放寬，要第二位最高管理者核准與確認期間；風險等級 money
    assert (g.risk, g.loosen) == ("money", "up") and g.impact_scope and g.impact_scope["effective"] == "pending" and g.risk_text


# ── 需要資料庫（寫好未跑）─────────────────────────────────────────────────────
def _set(group, values):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish(group, values, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def sa(client, make_user):
    u, p = make_user(username="f5_sa", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _closed_case(no, updated):
    import json
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "客戶", "專案", 1000, 952, json.dumps({"dealTag": "已結案"}, ensure_ascii=False), "2026-01-01T00:00:00", updated, "已結案"))
        c.commit()
    finally:
        c.close()


def test_settle_overdue_list_waits_n_days(client, sa):
    today = date.today()
    _closed_case("Q-F5-OLD", (today - timedelta(days=30)).isoformat() + "T00:00:00")
    _closed_case("Q-F5-NEW", (today - timedelta(days=2)).isoformat() + "T00:00:00")
    def nos():
        j = client.get("/api/reports/financial", headers=sa).json()
        return {x["quoteNo"] for x in j.get("settleOverdue", [])}
    assert {"Q-F5-OLD", "Q-F5-NEW"} <= nos()                               # 預設 0：一結案就列
    _set("finance_reports", {"settle_overdue_days": 14})
    got = nos()
    assert "Q-F5-OLD" in got and "Q-F5-NEW" not in got


def test_raising_the_receivable_grace_goes_pending(client):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        up = SR.publish("finance_cashier", {"receivable_grace_days": 5}, reason="t", user="t62", conn=c)
        c.commit()
        assert up["pending"] and SR.get("finance_cashier", "receivable_grace_days", conn=c) == 0, "調大＝放寬＝待生效，現值不變"
    finally:
        c.close()
