# -*- coding: utf-8 -*-
"""T38 F9：營運報表／儀表板的「實際毛利」不可在淨利為 0 時退回毛利；儀表板只算 finalized、比的是淨利率。

`settle.get("netProfit") or settle.get("grossProfit")` 把「淨利剛好 0」當成「沒有這個欄位」⇒ 顯示毛利（payroll/bonus.py 的〈null 不等於 0〉）。
舊 finalized（沒有 netProfit／netMarginPct 鍵）仍走毛利，值不改寫。
"""
import json

import pytest

from modules.analytics.tests.test_reports_logic_fixes_2026_08_28 import _insert_case


def _case(quote_no, summary, status="finalized"):
    _insert_case(quote_no, deal_tag="已結案", settlement={"status": status, "summary": summary})


def _mc(quote_no):
    from modules.analytics.api.reports import _collect
    data = _collect("2026-01-01", "2026-12-31")
    return {c["quoteNo"]: c for c in data["marginCases"]}[quote_no]


# ── reports._collect ──────────────────────────────────────────────────────────

def test_net_profit_zero_does_not_fall_back_to_gross(client):
    _case("T38-R1", {"netProfit": 0, "netMarginPct": 0, "grossProfit": 30000, "grossMarginPct": 30.0})
    c = _mc("T38-R1")
    assert c["grossProfit"] == 0
    assert c["actualMarginPct"] == 0.0


def test_net_negative_is_kept(client):
    _case("T38-R2", {"netProfit": -500, "netMarginPct": -0.5, "grossProfit": 30000, "grossMarginPct": 30.0})
    c = _mc("T38-R2")
    assert c["grossProfit"] == -500 and c["actualMarginPct"] == -0.5


def test_net_profit_is_rounded_not_truncated(client):
    _case("T38-R3", {"netProfit": 1234.6, "netMarginPct": 12.3, "grossProfit": 1, "grossMarginPct": 1.0})
    assert _mc("T38-R3")["grossProfit"] == 1235


def test_net_positive_unchanged(client):
    _case("T38-R4", {"netProfit": 5000, "netMarginPct": 5.0, "grossProfit": 30000, "grossMarginPct": 30.0})
    c = _mc("T38-R4")
    assert c["grossProfit"] == 5000 and c["actualMarginPct"] == 5.0


def test_legacy_finalized_without_net_keys_still_uses_gross(client):
    _case("T38-R5", {"grossProfit": 30000, "grossMarginPct": 30.0})
    c = _mc("T38-R5")
    assert c["grossProfit"] == 30000 and c["actualMarginPct"] == 30.0


def test_ytd_and_sales_aggregates_follow_net_zero(client):
    """下游讀者（業務績效 amProfitSum、年度毛利）不得因 0 被吃成毛利。"""
    from modules.analytics.api.reports import _collect
    _case("T38-R6", {"netProfit": 0, "netMarginPct": 0, "grossProfit": 30000, "grossMarginPct": 30.0})
    s = _collect("2026-01-01", "2026-12-31")["summary"]
    assert s["totalActualGrossProfit"] == 0


# ── dashboard.marginComparison ────────────────────────────────────────────────

def _admin_headers(client, make_user):
    username, password = make_user(username="t38_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _set_net_margin(quote_no, pct):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET net_margin_pct=? WHERE quote_no=?", (pct, quote_no))
        conn.commit()
    finally:
        conn.close()


def _comparison(client, make_user):
    h = _admin_headers(client, make_user)
    r = client.get("/api/dashboard/stats", headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    return {x["quoteNo"]: x for x in j["marginComparison"]}, j["settledSummary"]


def test_dashboard_draft_settlement_is_not_counted(client, make_user):
    _case("T38-D1", {"netProfit": 100, "netMarginPct": 10.0, "grossMarginPct": 40.0}, status="draft")
    _set_net_margin("T38-D1", 12.0)
    cmp, summ = _comparison(client, make_user)
    assert "T38-D1" not in cmp and not summ


def test_dashboard_compares_net_margin_not_gross(client, make_user):
    _case("T38-D2", {"netProfit": 1000, "netMarginPct": 10.0, "grossProfit": 4000, "grossMarginPct": 40.0, "quotedPretax": 10000})
    _set_net_margin("T38-D2", 12.0)
    cmp, summ = _comparison(client, make_user)
    assert cmp["T38-D2"]["actualMarginPct"] == 10.0
    assert cmp["T38-D2"]["grossProfit"] == 1000
    assert summ["totalGrossProfit"] == 1000 and summ["avgActualMarginPct"] == 10.0


def test_dashboard_net_zero_is_kept(client, make_user):
    _case("T38-D3", {"netProfit": 0, "netMarginPct": 0, "grossProfit": 4000, "grossMarginPct": 40.0, "quotedPretax": 10000})
    _set_net_margin("T38-D3", 12.0)
    cmp, _ = _comparison(client, make_user)
    assert cmp["T38-D3"]["actualMarginPct"] == 0.0 and cmp["T38-D3"]["grossProfit"] == 0


def test_dashboard_legacy_finalized_without_net_keys_uses_gross(client, make_user):
    _case("T38-D4", {"grossProfit": 4000, "grossMarginPct": 40.0, "quotedPretax": 10000})
    _set_net_margin("T38-D4", 12.0)
    cmp, _ = _comparison(client, make_user)
    assert cmp["T38-D4"]["actualMarginPct"] == 40.0 and cmp["T38-D4"]["grossProfit"] == 4000
