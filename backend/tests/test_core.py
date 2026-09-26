"""Unit tests for pure business-logic functions (no DB required)."""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
skip_module_unless("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')   # 本檔在模組層就 import M01（或 import 會略過的題檔）
import pytest

from modules.case.quotations import _steps_to_tiers, payment_item_amounts
from helpers.auth import _hash_pw, _verify_pw, is_weak_password, MIN_PASSWORD_LEN
from modules.case.api.quotations import _active_tiers, _current_tier_idx
from routers.uploads import _resolve_upload_path, UPLOADS_ROOT
import archive
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


# ── _parse_period ─────────────────────────────────────────────────────────────


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


# `_compute_achievement` 會開 get_db() 查 users（reports.py 業務員名字→id）⇒ 需要一個已初始化的隔離 DB。
# 沒有這行時，單獨跑或 -n 分到沒有其他題先建表的 worker 就 `no such table: users`（全量順序剛好掩蓋）。


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
        monkeypatch.setattr(archive, "_uploads_mirror_dir", lambda: str(mirror))
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
        monkeypatch.setattr(archive, "_uploads_mirror_dir", lambda: str(tmp_path / "mirror"))
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
