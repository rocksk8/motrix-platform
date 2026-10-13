# -*- coding: utf-8 -*-
"""U0a 組織單位預留（FRAMEWORK-ORG-UNITS-T57 §14.10）：core migration 只做加法、冪等、模組自有表不動、舊程式照常、VIEW 與 quote_seq 不動。
合成資料庫的題（不依賴 L2 模組）＋真實啟動庫的題（`client`）。分類棘輪：新增的表必須歸類，否則紅（§14.10 #6）。"""
import re
import sqlite3
from pathlib import Path

import pytest

from core import migrations as M

BACKEND = Path(__file__).resolve().parents[2]

#: 不加單位欄位的表：子表（隨父表）／全域參照／系統。新增的表若不在任何一桶 ⇒ 紅，請在這裡歸類（並說明為何不加 owner_unit_id）。
CHILD_TABLES = {
    "bonus_award_edit_log", "bonus_award_lines", "bonus_case_award_edit_log", "bonus_case_award_lines", "bonus_group_members",
    "bonus_item_people", "daily_task_completions", "daily_task_edit_log", "custom_record_files", "custom_record_finance_outbox",
    "custom_record_log", "custom_record_revisions", "custom_record_snapshots", "custom_record_values",
    "voucher_attachments", "voucher_edit_log", "voucher_lines",
}
GLOBAL_TABLES = {
    "access_categories", "access_fit", "access_products", "access_scenarios", "automation_categories", "automation_fit",
    "automation_products", "automation_scenarios", "gateway_categories", "gateway_fit", "gateway_products", "gateway_scenarios",
    "monitor_categories", "monitor_fit", "monitor_products", "monitor_scenarios", "switch_categories", "switch_fit",
    "switch_products", "switch_scenarios", "netarch_families", "netarch_generations", "netarch_products",
    "account_items", "approval_delegates", "bonus_groups", "bonus_items", "bonus_template_versions", "bonus_templates",
    "config_change_events", "config_changes", "custom_record_counters", "departments", "divisions", "duty_roles", "edit_presence",
    "env_guide_environments", "env_guide_links", "env_guide_recommendations", "geocode_cache", "geocode_usage", "item_reads",
    "login_rate_limit", "module_schema_versions", "module_versions", "payslip_seq", "permission_changes", "purchase_suggestion_status",
    "quote_seq", "schema_version", "sessions", "system_settings", "t100_export_confirmations", "tender_fetch_log", "ui_definitions",
    "user_activity_daily", "user_duty_roles", "user_list_prefs", "user_perm_subtracts", "user_request_log", "users",
    "voucher_template_versions", "voucher_templates", "webauthn_credentials",
}
#: U0a 新建的表（單位功能自己的表）
NEW_TABLES = {"org_units", "org_unit_closure", "user_units", "system_settings_unit", "seq_by_entity"}
#: 模組自有表（由各模組自己的 migration 在 U1／U3 補欄；覆蓋率棘輪只增不減）。以前綴或精確名稱列出
MODULE_OWNED_PREFIXES = ("gl_", "fa_", "case_material_", "lodging_", "perm_")
MODULE_OWNED_TABLES = {"expense_categories", "bonus_corrections", "bonus_correction_log", "payslip_dispatch_links", "user_bank_accounts",
                       "recycle_bin", "dispatch_file_delete_requests"}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _cols(conn, table):
    return {r[1]: r for r in conn.execute('PRAGMA table_info("%s")' % table).fetchall()}


@pytest.fixture
def real(client):
    import db
    conn = db.get_db()
    yield conn
    conn.close()


# ── 清單本身 ─────────────────────────────────────────────────────────────────────

def test_table_lists_are_well_formed():
    lists = {"owner": M.U0A_OWNER_UNIT_TABLES, "unit": M.U0A_UNIT_ID_TABLES, "legal": M.U0A_LEGAL_ENTITY_TABLES}
    assert not hasattr(M, "U0A_SCOPE_JSON_TABLES"), "scope_json 屬 permmatrix 自己的 migration"
    assert len(M.U0A_LEGAL_ENTITY_TABLES) == 5
    for k, v in lists.items():
        assert len(v) == len(set(v)), "%s 清單有重複" % k
    assert len(M.U0A_OWNER_UNIT_TABLES) == 36 and len(M.U0A_UNIT_ID_TABLES) == 2
    assert set(M.U0A_LEGAL_ENTITY_TABLES) <= set(M.U0A_OWNER_UNIT_TABLES), "法人快照的表一定也是業務表"
    assert "vouchers" not in M.U0A_OWNER_UNIT_TABLES and "vouchers_all" in M.U0A_OWNER_UNIT_TABLES, "欄位加在實表，不加在 VIEW"
    assert "quote_seq" not in M.U0A_OWNER_UNIT_TABLES, "quote_seq 不動"
    assert not set(M.U0A_OWNER_UNIT_TABLES) & (CHILD_TABLES | GLOBAL_TABLES | MODULE_OWNED_TABLES)


# ── 合成資料庫：行為 ──────────────────────────────────────────────────────────────

def _mini():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT)")
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT)")
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    c.execute("CREATE TABLE quote_seq (month TEXT PRIMARY KEY, seq INTEGER NOT NULL DEFAULT 0)")
    c.execute("INSERT INTO quotations (quote_no) VALUES ('MQ-1')")
    c.execute("INSERT INTO users (username) VALUES ('a'), ('b')")
    c.commit()
    return c


def test_runs_on_a_partial_database_and_skips_missing_tables():
    c = _mini()
    assert M._core_next_org_units(c) is None
    assert "owner_unit_id" in _cols(c, "quotations") and "owner_unit_id" in _cols(c, "payslips") and "legal_entity_id" in _cols(c, "payslips")
    assert "legal_entity_id" not in _cols(c, "quotations")
    assert "customers" not in _tables(c) and "audit_log" not in _tables(c) and "perm_role_caps" not in _tables(c)     # 沒有的表不憑空建立（含模組自有表）
    assert NEW_TABLES <= _tables(c)
    assert c.execute("SELECT owner_unit_id FROM quotations").fetchone()[0] == 1                                          # 既有列＝根單位


def test_is_idempotent_and_does_not_reseed_user_units():
    c = _mini()
    assert M._core_next_org_units(c) is None
    snap = {t: sorted(_cols(c, t)) for t in _tables(c)}
    c.execute("DELETE FROM user_units WHERE user_id=2")                       # 管理者改過歸屬
    c.commit()
    assert M._core_next_org_units(c) is None and M._core_next_org_units(c) is None
    assert {t: sorted(_cols(c, t)) for t in _tables(c)} == snap
    assert [r[0] for r in c.execute("SELECT user_id FROM user_units ORDER BY user_id")] == [1], "重跑不可把改過的歸屬又寫回去"
    assert c.execute("SELECT COUNT(*) FROM org_units").fetchone()[0] == 1 and c.execute("SELECT COUNT(*) FROM org_unit_closure").fetchone()[0] == 1


def test_no_index_is_created_and_the_root_takes_the_company_name():
    c = _mini()
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
    c.execute("INSERT INTO system_settings VALUES ('company_profile', '{\"name\": \"  某某科技  \"}')")
    c.commit()
    M._core_next_org_units(c)
    assert [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")] == [], "U0a 不建索引"
    assert c.execute("SELECT name FROM org_units WHERE id=1").fetchone()[0] == "某某科技"
    c2 = _mini()
    M._core_next_org_units(c2)
    assert c2.execute("SELECT name FROM org_units WHERE id=1").fetchone()[0] == "本公司"
    c3 = _mini()
    c3.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
    c3.execute("INSERT INTO system_settings VALUES ('company_profile', 'not json')")
    M._core_next_org_units(c3)
    assert c3.execute("SELECT name FROM org_units WHERE id=1").fetchone()[0] == "本公司"                 # 壞資料不拖垮 migration


def test_new_tables_are_in_the_daily_backup_and_cleared_by_demo_reset():
    import archive
    import db
    sql = " ".join(archive._daily_backup_tables().values())
    for t in NEW_TABLES:
        assert "FROM %s " % t in sql + " " or "FROM %s" % t in sql, "%s 沒進每日 JSON 備份" % t
        assert t in db.DEMO_CLEARED_TABLES, "%s 沒進 demo 重置清單" % t


def test_seeds_the_root_unit_and_attaches_every_user():
    c = _mini()
    M._core_next_org_units(c)
    root = c.execute("SELECT * FROM org_units").fetchall()
    assert len(root) == 1 and root[0]["id"] == 1 and root[0]["parent_id"] is None and root[0]["is_legal_entity"] == 1
    assert [tuple(r) for r in c.execute("SELECT ancestor_id, descendant_id, depth FROM org_unit_closure")] == [(1, 1, 0)]
    assert sorted(tuple(r) for r in c.execute("SELECT user_id, unit_id, is_primary FROM user_units")) == [(1, 1, 1), (2, 1, 1)]
    for t in ("system_settings_unit", "seq_by_entity"):
        assert c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] == 0


def test_seq_by_entity_has_the_composite_key_and_quote_seq_is_untouched():
    c = _mini()
    before = [tuple(r) for r in c.execute("PRAGMA table_info(quote_seq)")]
    M._core_next_org_units(c)
    assert [tuple(r) for r in c.execute("PRAGMA table_info(quote_seq)")] == before
    pk = sorted((r[5], r[1]) for r in c.execute("PRAGMA table_info(seq_by_entity)") if r[5])
    assert [n for _, n in pk] == ["entity_id", "kind", "period"]
    c.execute("INSERT INTO seq_by_entity (entity_id, kind, period, seq) VALUES (2, 'voucher', '20261014', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO seq_by_entity (entity_id, kind, period, seq) VALUES (2, 'voucher', '20261014', 2)")


def test_old_code_inserts_still_work_and_land_on_the_root_unit():
    c = _mini()
    M._core_next_org_units(c)
    c.execute("INSERT INTO quotations (quote_no) VALUES ('MQ-2')")           # 舊程式的 INSERT 不帶新欄位
    c.execute("INSERT INTO payslips (slip_no) VALUES ('PS-2610-001')")
    assert [r[0] for r in c.execute("SELECT owner_unit_id FROM quotations ORDER BY id")] == [1, 1]
    assert c.execute("SELECT owner_unit_id, legal_entity_id FROM payslips").fetchone()[:] == (1, 1)


def test_sqlite_errors_become_a_reason_string_not_an_exception(monkeypatch):
    c = _mini()

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(M, "_u0a_add_column", boom)
    why = M._core_next_org_units(c)
    assert isinstance(why, str) and "未完成" in why and "locked" in why
    monkeypatch.undo()
    assert M._core_next_org_units(c) is None                                  # 修好後重跑補完


def test_a_view_is_never_altered():
    c = _mini()
    c.execute("CREATE TABLE vouchers_all (id INTEGER PRIMARY KEY, voided_at TEXT NOT NULL DEFAULT '')")
    c.execute("CREATE VIEW vouchers AS SELECT * FROM vouchers_all WHERE voided_at = ''")
    c.execute("INSERT INTO vouchers_all DEFAULT VALUES")
    M._core_next_org_units(c)
    assert c.execute("SELECT type FROM sqlite_master WHERE name='vouchers'").fetchone()[0] == "view"
    assert "owner_unit_id" in _cols(c, "vouchers_all") and "legal_entity_id" in _cols(c, "vouchers_all")
    assert c.execute("SELECT owner_unit_id FROM vouchers").fetchone()[0] == 1       # VIEW 查詢時展開，自動帶出新欄位（之後由回應剝除）
    assert M._u0a_add_column(c, "vouchers", "owner_unit_id", "INTEGER") == "no_table"      # 對 VIEW 動手 ⇒ 不做


def test_migration_is_registered_exactly_once_as_core_either_unnumbered_or_numbered():
    """分支上＝未取號（register("core", NEXT, fn) ⇒ 在 _PENDING）；列車取號後＝整數版號（>= 10）。兩種狀態都要綠，且只登記一次。"""
    fn = M._core_next_org_units
    pending = [f for f in M._PENDING if f is fn]
    numbered = sorted(v for v, f in M._REGISTRY.get("core", {}).items() if f is fn)
    assert len(pending) + len(numbered) == 1, (len(pending), numbered)
    assert all(isinstance(v, int) and v >= 10 for v in numbered), numbered
    assert [m for m, per in M._REGISTRY.items() if m != "core" and fn in per.values()] == [], "只准登記在 core"
    assert M.U0A_ROOT_UNIT_ID == 1


# ── 真實啟動庫 ───────────────────────────────────────────────────────────────────

def test_real_database_gets_every_listed_column_with_default_one(real):
    tabs = _tables(real)
    missing = [t for t in M.U0A_OWNER_UNIT_TABLES + M.U0A_UNIT_ID_TABLES if t not in tabs]
    assert missing == [], "清單裡有表在真實庫不存在（拼錯、或已改名）：%s" % missing
    for table, col in ([(t, "owner_unit_id") for t in M.U0A_OWNER_UNIT_TABLES] + [(t, "unit_id") for t in M.U0A_UNIT_ID_TABLES]
                       + [(t, "legal_entity_id") for t in M.U0A_LEGAL_ENTITY_TABLES]):
        info = _cols(real, table).get(col)
        assert info is not None, "%s 缺 %s" % (table, col)
        assert info["notnull"] == 1 and str(info["dflt_value"]) == "1", (table, col, tuple(info))


def test_real_database_keeps_view_quote_seq_and_schema_version(real):
    import db
    assert real.execute("SELECT type FROM sqlite_master WHERE name='vouchers'").fetchone()[0] == "view"
    assert [r[1] for r in real.execute("PRAGMA table_info(quote_seq)") if r[5]] == ["month"]
    assert "owner_unit_id" not in _cols(real, "quote_seq")
    assert real.execute("SELECT version FROM schema_version").fetchone()[0] == db.CURRENT_VERSION == 118
    assert real.execute("SELECT COUNT(*) FROM org_units WHERE id=1").fetchone()[0] == 1


def test_module_owned_tables_are_untouched_by_the_core_migration(real):
    tabs = _tables(real)
    owned = [t for t in tabs if t.startswith(MODULE_OWNED_PREFIXES) or t in MODULE_OWNED_TABLES]
    assert len(owned) >= 20, "模組自有表一張都沒找到——檢查空轉"
    for t in owned:
        cols = _cols(real, t)
        assert not {"owner_unit_id", "unit_id", "legal_entity_id"} & set(cols), "%s 不該被 core migration 動到" % t


def test_every_table_is_classified_so_a_new_table_cannot_skip_the_unit_question(real):
    """§14.10 #6 守門①：新建的表必須歸類（業務表加 owner_unit_id／子表／全域／模組自有），否則紅。基線只減不增。"""
    known = (set(M.U0A_OWNER_UNIT_TABLES) | set(M.U0A_UNIT_ID_TABLES) | CHILD_TABLES | GLOBAL_TABLES | NEW_TABLES | MODULE_OWNED_TABLES)
    unclassified = sorted(t for t in _tables(real) if t not in known and not t.startswith(MODULE_OWNED_PREFIXES))
    assert unclassified == [], "這些表還沒歸類（加 owner_unit_id，或寫進 test_org_units_u0a.py 的子表／全域／模組自有並說明）：%s" % unclassified


def test_perm_tables_gain_scope_json_through_the_permmatrix_migration_not_core(real):
    tabs = _tables(real)
    for t in ("perm_role_caps", "perm_user_overrides"):
        if t in tabs:                                                   # permmatrix 沒安裝 ⇒ 表不存在 ⇒ 略過
            info = _cols(real, t).get("scope_json")
            assert info is not None and info["notnull"] == 0 and info["dflt_value"] is None, t


def test_permmatrix_v2_migration_is_additive_idempotent_and_reports_a_missing_table():
    import importlib
    v1 = importlib.import_module("modules.permmatrix.migrations.0001_permission_matrix")
    v2 = importlib.import_module("modules.permmatrix.migrations.0002_scope_json")
    c = sqlite3.connect(":memory:")
    assert "不存在" in v2.up(c)                                          # v1 還沒跑 ⇒ 回原因，不丟例外
    v1.up(c)
    c.execute("INSERT INTO perm_role_caps (role, cap, granted) VALUES ('admin', 'x.y', 1)")
    assert v2.up(c) is None and v2.up(c) is None
    assert c.execute("SELECT scope_json FROM perm_role_caps").fetchone()[0] is None          # 既有列＝NULL＝全部
    assert [r[1] for r in c.execute("PRAGMA table_info(perm_user_overrides)")][-1] == "scope_json"
    import modules.permmatrix as PM
    assert [v for v, _ in PM.MODULE.migrations] == [1, 2]


# ── 不可從請求寫入／名稱一致 ──────────────────────────────────────────────────────

def test_no_product_code_writes_the_unit_columns_yet():
    """U0a 只預留欄位：除 migration、回應剝除與測試外，沒有任何產品程式碼提到這三個欄位名（之後由 U1 的集中寫入點負責，不可由請求本文寫入）。"""
    pat = re.compile(r"\b(owner_unit_id|legal_entity_id)\b")
    from tests.platform.test_u0a_sinks import QUOTED_NAMES_ALLOW as allowed         # 唯一一份允許清單（與 2b 的洩漏防線守門共用）
    hits = []
    for p in list((BACKEND / "modules").rglob("*.py")) + list((BACKEND / "routers").rglob("*.py")) + list((BACKEND / "helpers").rglob("*.py")):
        rel = p.relative_to(BACKEND).as_posix()
        if "/tests/" in rel or rel in allowed:
            continue
        if pat.search(p.read_text(encoding="utf-8", errors="replace")):
            hits.append(rel)
    assert hits == [], "產品程式碼不應在 U0a 提到單位欄位（寫入點屬 U1）：%s" % hits


def test_column_names_match_the_response_stripper_when_it_exists():
    from core import internal_cols
    assert set(internal_cols.INTERNAL_COLS) >= {"owner_unit_id", "unit_id", "legal_entity_id"}
