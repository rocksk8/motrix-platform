# -*- coding: utf-8 -*-
"""建構器底層支援（helpers.custom_builder_support，core migration v3）的契約題：
可見設定的後端強制、公式洩漏守門、金流 outbox 冪等、migration v3 冪等且只增。"""
import sqlite3

from core import migrations
from helpers import custom_builder_support as S

BODY = {
    "fields": [
        {"key": "cost", "label": "成本", "type": "number", "access": {"visibleTo": {"roles": ["admin"]}}},
        {"key": "g", "label": "倍數", "type": "formula", "formula": "cost * 2"},
        {"key": "n", "label": "備註", "type": "text"},
    ],
    "menu": {"visibleTo": {"users": ["bob"]}},
}


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER, applied_at TEXT)")
    migrations.run_all(c)
    return c


def test_migration_v3_adds_columns_and_tables_and_is_idempotent():
    c = _conn()
    assert migrations.current_version(c, "core") >= 3
    assert {"submitted_by", "submitted_at", "decision_json"} <= {r[1] for r in c.execute("PRAGMA table_info(ui_definitions)")}
    assert {"base_no", "rev", "supersedes_id"} <= {r[1] for r in c.execute("PRAGMA table_info(custom_records)")}
    for t in ("custom_record_revisions", "custom_record_finance_outbox"):
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone()
    assert migrations.run_all(c) == {}


def test_mask_for_removes_restricted_fields_but_not_for_superadmin_or_listed_roles():
    vals = {"cost": 1, "g": 2, "n": "x"}
    assert "cost" not in S.mask_for(BODY, vals, {"role": "user", "username": "a"})
    assert S.mask_for(BODY, vals, {"role": "admin", "username": "a"}) == vals
    assert S.mask_for(BODY, vals, {"role": "superadmin", "username": "z"}) == vals


def test_menu_visible_to_users_and_unset_means_everyone():
    assert S.can_see_menu(BODY["menu"], {"role": "user", "username": "bob"})
    assert not S.can_see_menu(BODY["menu"], {"role": "user", "username": "a"})
    assert S.can_see_menu({}, {"role": "user", "username": "a"})


def test_formula_over_a_restricted_field_with_wider_visibility_is_a_leak():
    assert [p["path"] for p in S.leaking_formulas(BODY)] == ["fields.g.formula"]
    ok = {"fields": [dict(BODY["fields"][0]), dict(BODY["fields"][1], access={"visibleTo": {"roles": ["admin"]}})]}
    assert S.leaking_formulas(ok) == []


def test_access_problems_reject_unknown_keys_and_bad_shapes():
    bad = {"fields": [{"key": "a", "access": {"hidden": True}}, {"key": "b", "access": {"visibleTo": {"roles": "x"}}}]}
    assert [p["path"] for p in S.access_problems(bad)] == ["fields.a.access", "fields.b.access"]
    assert S.access_problems(BODY) == []


def test_finance_outbox_is_idempotent_and_processing_marks_done():
    c = _conn()
    assert S.emit_finance_event(c, S.EVENT_FINANCE_POSTED, "q", 1, "Q-1", "income", {"amt": 5}) is True
    assert S.emit_finance_event(c, S.EVENT_FINANCE_POSTED, "q", 1, "Q-1", "income", {"amt": 5}) is False
    assert S.emit_finance_event(c, S.EVENT_FINANCE_REVERSED, "q", 1, "Q-1", "income", {}) is True
    ev = S.pending_finance_events(c)
    assert [e["event"] for e in ev] == [S.EVENT_FINANCE_POSTED, S.EVENT_FINANCE_REVERSED] and ev[0]["payload"] == {"amt": 5}
    assert S.mark_finance_processed(c, [e["id"] for e in ev]) == 2
    assert S.pending_finance_events(c) == []
