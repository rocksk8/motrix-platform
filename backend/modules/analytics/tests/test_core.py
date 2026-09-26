"""自 `tests/test_core.py` 拆出：營運報表的期別解析與達成率（M08 搬遷反向控制）。"""
import pytest  # noqa: F401

from modules.analytics.api.reports import _parse_period, _compute_achievement
from tests.test_core import _make_case  # noqa: E402


class TestParsePeriod:
    def test_annual(self):
        label, d0, d1 = _parse_period("2026")
        assert label == "2026 年度"
        assert d0 == "2026-01-01"
        assert d1 == "2026-12-31"

    def test_monthly(self):
        label, d0, d1 = _parse_period("2026-07")
        assert label == "2026 年 7 月"
        assert d0 == "2026-07-01"
        assert d1 == "2026-07-31"

    def test_monthly_jan(self):
        label, d0, d1 = _parse_period("2026-01")
        assert label == "2026 年 1 月"
        assert d0 == "2026-01-01"
        assert d1 == "2026-01-31"

    def test_monthly_feb_leap(self):
        _, d0, d1 = _parse_period("2024-02")
        assert d1 == "2024-02-29"  # 2024 is a leap year

    def test_monthly_feb_non_leap(self):
        _, d0, d1 = _parse_period("2025-02")
        assert d1 == "2025-02-28"

    def test_quarter_q1(self):
        label, d0, d1 = _parse_period("2026-Q1")
        assert label == "2026 年第 1 季"
        assert d0 == "2026-01-01"
        assert d1 == "2026-03-31"

    def test_quarter_q2(self):
        label, d0, d1 = _parse_period("2026-Q2")
        assert label == "2026 年第 2 季"
        assert d0 == "2026-04-01"
        assert d1 == "2026-06-30"

    def test_quarter_q3(self):
        _, d0, d1 = _parse_period("2026-Q3")
        assert d0 == "2026-07-01"
        assert d1 == "2026-09-30"

    def test_quarter_q4(self):
        _, d0, d1 = _parse_period("2026-Q4")
        assert d0 == "2026-10-01"
        assert d1 == "2026-12-31"


@pytest.mark.usefixtures("client")
class TestComputeAchievement:
    def test_no_targets(self):
        result = _compute_achievement(2026, {}, [])
        assert result == {"year": 2026, "hasTargets": False}

    def test_wrong_year(self):
        result = _compute_achievement(2026, {"year": 2025, "annual": {}}, [])
        assert result == {"year": 2026, "hasTargets": False}

    def test_zero_cases(self):
        targets = {
            "year": 2026,
            "annual": {"revenue": 10_000_000, "newCases": 20, "collectionAmount": 8_000_000,
                       "collectionRate": 80, "avgNetMarginPct": 15, "grossProfit": 1_500_000},
            "salesperson": [],
        }
        r = _compute_achievement(2026, targets, [])
        assert r["hasTargets"] is True
        assert r["annual"]["revenue"]["actual"] == 0
        assert r["annual"]["newCases"]["actual"] == 0
        assert r["annual"]["collectionRate"]["actual"] == 0.0

    def test_single_case_metrics(self):
        targets = {
            "year": 2026,
            "annual": {"revenue": 1_000_000, "newCases": 10, "collectionAmount": 800_000,
                       "collectionRate": 80, "avgNetMarginPct": 20, "grossProfit": 200_000},
            "salesperson": [{"name": "Alice", "revenue": 500_000, "cases": 5}],
        }
        cases = [_make_case(total=200_000, received=100_000, gross_profit=40_000,
                            margin_pct=20.0, sales="Alice")]
        r = _compute_achievement(2026, targets, cases)
        assert r["annual"]["revenue"]["actual"] == 200_000
        assert r["annual"]["newCases"]["actual"] == 1
        assert r["annual"]["collectionAmt"]["actual"] == 100_000
        assert r["annual"]["grossProfit"]["actual"] == 40_000
        assert r["annual"]["avgMarginPct"]["actual"] == 20.0

    def test_salesperson_breakdown(self):
        targets = {
            "year": 2026,
            "annual": {"revenue": 1_000_000, "newCases": 10},
            "salesperson": [
                {"name": "Alice", "revenue": 600_000, "cases": 6},
                {"name": "Bob",   "revenue": 400_000, "cases": 4},
            ],
        }
        cases = [
            _make_case(total=300_000, sales="Alice"),
            _make_case(total=200_000, sales="Alice"),
            _make_case(total=150_000, sales="Bob"),
        ]
        r = _compute_achievement(2026, targets, cases)
        sp = {s["name"]: s for s in r["salesperson"]}
        assert sp["Alice"]["ytdRevenue"] == 500_000
        assert sp["Alice"]["ytdCases"] == 2
        assert sp["Bob"]["ytdRevenue"] == 150_000
        assert sp["Bob"]["ytdCases"] == 1

    def test_collection_rate_calc(self):
        targets = {"year": 2026, "annual": {"revenue": 1_000_000, "collectionRate": 80}}
        cases = [
            _make_case(total=100_000, received=80_000),
            _make_case(total=100_000, received=60_000),
        ]
        r = _compute_achievement(2026, targets, cases)
        # 140_000 / 200_000 = 70.0%
        assert r["annual"]["collectionRate"]["actual"] == 70.0

    def test_cases_filtered_by_year(self):
        targets = {"year": 2026, "annual": {"revenue": 1_000_000, "newCases": 5}}
        cases = [
            _make_case(quote_date="2026-06-01", total=100_000),
            _make_case(quote_date="2025-12-31", total=999_000),  # prior year, must be excluded
        ]
        r = _compute_achievement(2026, targets, cases)
        assert r["annual"]["revenue"]["actual"] == 100_000
        assert r["annual"]["newCases"]["actual"] == 1
