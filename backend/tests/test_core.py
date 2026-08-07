"""Unit tests for pure business-logic functions (no DB required)."""
import pytest

from routers.reports import _parse_period, _compute_achievement
from routers.payslips import _calc, _get_tax_rules
from helpers.quotations import _steps_to_tiers, payment_item_amounts
from helpers.auth import _hash_pw, _verify_pw, is_weak_password, MIN_PASSWORD_LEN
from routers.quotations import _active_tiers, _current_tier_idx
from routers.projects import _resolve_upload_path, UPLOADS_ROOT
import archive


# ── _parse_period ─────────────────────────────────────────────────────────────

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


# ── _compute_achievement ──────────────────────────────────────────────────────

def _make_case(quote_date="2026-03-01", total=100_000, pretax=None, received=50_000,
               settle_status="finalized", gross_profit=20_000,
               margin_pct=20.0, sales="Alice"):
    return {
        "quoteDate":      quote_date,
        "total":          total,
        "pretax":         pretax if pretax is not None else total,
        "receivedAmount": received,
        "settleStatus":   settle_status,
        "grossProfit":    gross_profit,
        "actualMarginPct": margin_pct,
        "salesPerson":    sales,
    }


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


# ── _calc (payslip tax) ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rules():
    return _get_tax_rules()


class TestCalc:
    def test_resident_50_below_threshold(self, rules):
        # gross 50000 < resident 50 threshold 90501 → no withholding
        r = _calc(50_000, "50", "本國籍", False, rules)
        assert r["taxWithheld"] == 0
        assert r["taxRate"] == 0.0

    def test_resident_50_above_threshold(self, rules):
        # gross 100000 >= 90501 → 5%
        r = _calc(100_000, "50", "本國籍", False, rules)
        assert r["taxRate"] == 0.05
        assert r["taxWithheld"] == 5_000

    def test_resident_9A_above_threshold(self, rules):
        # gross 30000 >= 20010 → 10%
        r = _calc(30_000, "9A", "本國籍", False, rules)
        assert r["taxRate"] == 0.10
        assert r["taxWithheld"] == 3_000

    def test_non_resident_50_high_salary(self, rules):
        # 44250 > 29500*1.5=44250? no, 29500*1.5=44250, so 44251 → 18%
        r = _calc(44_251, "50", "外國籍（未滿183天）", False, rules)
        assert r["taxRate"] == 0.18

    def test_non_resident_50_low_salary(self, rules):
        # gross 29500 <= 44250 → low_salary_rate = 6%
        r = _calc(29_500, "50", "外國籍（未滿183天）", False, rules)
        assert r["taxRate"] == 0.06
        assert r["taxWithheld"] == 1_770  # floor(29500 * 0.06)

    def test_nhi_supplement_no_union(self, rules):
        # type 50, resident, no union, gross 50000 >= nhi threshold 29500
        r = _calc(50_000, "50", "本國籍", False, rules)
        assert r["nhiRate"] == 0.0211
        expected = round(50_000 * 0.0211)
        assert r["nhiSupplement"] == expected

    def test_nhi_supplement_has_union(self, rules):
        # has_union=True → no NHI supplement
        r = _calc(50_000, "50", "本國籍", True, rules)
        assert r["nhiRate"] == 0.0
        assert r["nhiSupplement"] == 0

    def test_net_amount(self, rules):
        # gross=100000, 5% tax=5000, nhi=round(100000*0.0211)=2110 → net=92890
        r = _calc(100_000, "50", "本國籍", False, rules)
        expected_net = 100_000 - r["taxWithheld"] - r["nhiSupplement"]
        assert r["netAmount"] == expected_net

    def test_nhi_below_threshold(self, rules):
        # gross 20000 < nhi threshold 29500 for type 50
        r = _calc(20_000, "50", "本國籍", False, rules)
        assert r["nhiSupplement"] == 0


# ── _steps_to_tiers ───────────────────────────────────────────────────────────

class TestStepsToTiers:
    def test_empty(self):
        assert _steps_to_tiers([]) == []

    def test_single_step(self):
        steps = [{"userId": 1, "username": "alice", "displayName": "Alice"}]
        result = _steps_to_tiers(steps)
        assert len(result) == 1
        assert result[0]["order"] == 0
        assert result[0]["approvers"] == [{"userId": 1, "username": "alice", "displayName": "Alice"}]

    def test_multiple_steps_order(self):
        steps = [
            {"userId": 1, "username": "alice", "displayName": "Alice"},
            {"userId": 2, "username": "bob",   "displayName": "Bob"},
        ]
        result = _steps_to_tiers(steps)
        assert result[0]["order"] == 0
        assert result[1]["order"] == 1
        assert result[1]["approvers"][0]["username"] == "bob"

    def test_missing_display_name_falls_back_to_username(self):
        steps = [{"userId": 5, "username": "carol"}]
        result = _steps_to_tiers(steps)
        assert result[0]["approvers"][0]["displayName"] == "carol"

    def test_missing_user_id_defaults_to_zero(self):
        steps = [{"username": "dave", "displayName": "Dave"}]
        result = _steps_to_tiers(steps)
        assert result[0]["approvers"][0]["userId"] == 0

    def test_no_status_fields(self):
        steps = [{"userId": 1, "username": "eve", "displayName": "Eve", "status": "approved"}]
        result = _steps_to_tiers(steps)
        # _steps_to_tiers should NOT carry over status
        assert "status" not in result[0]["approvers"][0]


# ── _active_tiers ─────────────────────────────────────────────────────────────

class TestActiveTiers:
    def test_empty(self):
        assert _active_tiers({}) == []

    def test_modern_tiers_passthrough(self):
        tiers = [{"order": 0, "approvers": [{"userId": 1, "username": "a", "status": "pending"}]}]
        assert _active_tiers({"tiers": tiers}) is tiers

    def test_old_steps_backward_compat(self):
        steps = [
            {"userId": 1, "username": "alice", "displayName": "Alice", "status": "approved", "approvedAt": "2026-01-01"},
            {"userId": 2, "username": "bob",   "displayName": "Bob",   "status": "pending",  "approvedAt": None},
        ]
        result = _active_tiers({"steps": steps})
        assert len(result) == 2
        assert result[0]["approvers"][0]["status"] == "approved"
        assert result[0]["approvers"][0]["approvedAt"] == "2026-01-01"
        assert result[1]["approvers"][0]["status"] == "pending"

    def test_old_steps_missing_status_defaults_pending(self):
        steps = [{"userId": 1, "username": "alice", "displayName": "Alice"}]
        result = _active_tiers({"steps": steps})
        assert result[0]["approvers"][0]["status"] == "pending"

    def test_prefers_tiers_over_steps(self):
        tiers = [{"order": 0, "approvers": [{"userId": 1, "username": "a", "status": "pending"}]}]
        steps = [{"userId": 99, "username": "ignored"}]
        result = _active_tiers({"tiers": tiers, "steps": steps})
        assert result[0]["approvers"][0]["username"] == "a"


# ── _current_tier_idx ─────────────────────────────────────────────────────────

class TestCurrentTierIdx:
    def test_modern_current_tier(self):
        assert _current_tier_idx({"currentTier": 2}) == 2

    def test_legacy_current_step(self):
        assert _current_tier_idx({"currentStep": 1}) == 1

    def test_neither_defaults_zero(self):
        assert _current_tier_idx({}) == 0

    def test_modern_takes_precedence(self):
        assert _current_tier_idx({"currentTier": 3, "currentStep": 0}) == 3


# ── Password helpers ──────────────────────────────────────────────────────────

class TestPasswordHelpers:
    def test_hash_and_verify_roundtrip(self):
        pw = "SecurePass!99"
        stored = _hash_pw(pw)
        assert _verify_pw(pw, stored)

    def test_wrong_password_fails(self):
        stored = _hash_pw("correct")
        assert not _verify_pw("wrong", stored)

    def test_different_salts_same_password(self):
        pw = "SamePass#1"
        h1 = _hash_pw(pw)
        h2 = _hash_pw(pw)
        assert h1 != h2              # different salts
        assert _verify_pw(pw, h1)    # both verify correctly
        assert _verify_pw(pw, h2)

    def test_legacy_sha256_hash_verify(self):
        import hashlib
        pw = "legacyPass"
        legacy_hash = hashlib.sha256(pw.encode()).hexdigest()
        assert _verify_pw(pw, legacy_hash)


# ── _resolve_upload_path (path traversal guard) ────────────────────────────────

class TestResolveUploadPath:
    def test_normal_path_within_uploads(self):
        full = _resolve_upload_path("projects/1/photo.jpg")
        assert full is not None
        assert full.startswith(UPLOADS_ROOT)

    def test_traversal_to_backend_db_is_blocked(self):
        assert _resolve_upload_path("..\\backend\\motrix_erp.db") is None
        assert _resolve_upload_path("../backend/motrix_erp.db") is None

    def test_traversal_to_backend_main_is_blocked(self):
        assert _resolve_upload_path("../backend/main.py") is None

    def test_deep_traversal_outside_repo_is_blocked(self):
        assert _resolve_upload_path("../../../../../../Windows/win.ini") is None


# ── archive._mirror_uploads (uploads/ → cloud mirror) ───────────────────────

class TestMirrorUploads:
    def _patch_dirs(self, monkeypatch, tmp_path):
        uploads = tmp_path / "uploads"
        mirror = tmp_path / "mirror"
        uploads.mkdir()
        monkeypatch.setattr(archive, "_UPLOADS_DIR", str(uploads))
        monkeypatch.setattr(archive, "_UPLOADS_MIRROR_DIR", str(mirror))
        return uploads, mirror

    def test_copies_new_files_preserving_subdirs(self, monkeypatch, tmp_path):
        uploads, mirror = self._patch_dirs(monkeypatch, tmp_path)
        (uploads / "projects" / "1").mkdir(parents=True)
        (uploads / "projects" / "1" / "photo.jpg").write_bytes(b"fake-jpeg-bytes")

        copied = archive._mirror_uploads()

        assert copied == 1
        mirrored = mirror / "projects" / "1" / "photo.jpg"
        assert mirrored.exists()
        assert mirrored.read_bytes() == b"fake-jpeg-bytes"

    def test_skips_unchanged_files_on_rerun(self, monkeypatch, tmp_path):
        uploads, mirror = self._patch_dirs(monkeypatch, tmp_path)
        (uploads / "a.jpg").write_bytes(b"data")
        assert archive._mirror_uploads() == 1
        assert archive._mirror_uploads() == 0, "unchanged file should not be re-copied"

    def test_recopies_changed_files(self, monkeypatch, tmp_path):
        uploads, mirror = self._patch_dirs(monkeypatch, tmp_path)
        f = uploads / "a.jpg"
        f.write_bytes(b"v1")
        archive._mirror_uploads()
        f.write_bytes(b"v2-longer-content")
        assert archive._mirror_uploads() == 1
        assert (mirror / "a.jpg").read_bytes() == b"v2-longer-content"

    def test_demo_directories_are_excluded(self, monkeypatch, tmp_path):
        uploads, mirror = self._patch_dirs(monkeypatch, tmp_path)
        (uploads / "_demo_projects").mkdir()
        (uploads / "_demo_projects" / "should-not-sync.jpg").write_bytes(b"demo-only")
        (uploads / "projects").mkdir()
        (uploads / "projects" / "real.jpg").write_bytes(b"real-data")

        copied = archive._mirror_uploads()

        assert copied == 1
        assert (mirror / "projects" / "real.jpg").exists()
        assert not (mirror / "_demo_projects").exists()

    def test_no_uploads_dir_is_a_noop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(archive, "_UPLOADS_DIR", str(tmp_path / "does-not-exist"))
        monkeypatch.setattr(archive, "_UPLOADS_MIRROR_DIR", str(tmp_path / "mirror"))
        assert archive._mirror_uploads() == 0

    def test_is_weak_too_short(self):
        assert is_weak_password("abc")
        assert is_weak_password("a" * (MIN_PASSWORD_LEN - 1))

    def test_is_weak_known_passwords(self):
        assert is_weak_password("rock1125")
        assert is_weak_password("password")
        assert is_weak_password("admin123")
        assert is_weak_password("123456")

    def test_is_weak_case_insensitive(self):
        assert is_weak_password("PASSWORD")
        assert is_weak_password("Admin123")

    def test_strong_password_not_weak(self):
        assert not is_weak_password("Str0ng!Pass#2026")
        assert not is_weak_password("allowtec@666secure")


# ── payment_item_amounts (regression for dashboard/reports vs edit-UI drift) ──

class TestPaymentItemAmounts:
    def test_empty_list(self):
        assert payment_item_amounts(100_000, []) == []

    def test_prefers_stored_amount_when_present(self):
        # Mirrors what case-management.js actually saves — the last item balances
        # the total, and every item ends up with an explicit `amount`.
        items = [
            {"pct": 30, "amount": 30_000},
            {"pct": 30, "amount": 30_000},
            {"pct": 40, "amount": 40_000},
        ]
        assert payment_item_amounts(100_000, items) == [30_000, 30_000, 40_000]

    def test_stored_amounts_sum_exactly_even_if_pct_rounds_oddly(self):
        # 1/3 + 1/3 + 1/3 of 100 can't split evenly by pct alone — but if the UI
        # already saved amounts that sum to the total, that must be respected
        # verbatim rather than recomputed from the (necessarily imprecise) pct.
        items = [
            {"pct": 33.33, "amount": 33_333},
            {"pct": 33.33, "amount": 33_333},
            {"pct": 33.34, "amount": 33_334},
        ]
        amounts = payment_item_amounts(100_000, items)
        assert amounts == [33_333, 33_333, 33_334]
        assert sum(amounts) == 100_000

    def test_legacy_rows_without_amount_fall_back_to_pct_first_absorbs(self):
        # Pre-existing backend convention for rows saved before `amount` existed:
        # first item absorbs the rounding remainder from the rest.
        items = [{"pct": 33.33}, {"pct": 33.33}, {"pct": 33.34}]
        amounts = payment_item_amounts(100_000, items)
        assert sum(amounts) == 100_000
        assert amounts[0] == 100_000 - amounts[1] - amounts[2]

    def test_mixed_stored_and_legacy_items(self):
        items = [{"pct": 50, "amount": 50_000}, {"pct": 50}]
        assert payment_item_amounts(100_000, items) == [50_000, 50_000]

    def test_single_item_gets_full_total(self):
        assert payment_item_amounts(100_000, [{"pct": 100}]) == [100_000]
