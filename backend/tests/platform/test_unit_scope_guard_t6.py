# -*- coding: utf-8 -*-
"""T6 新表單位守門（U0b 地基班）：每一張資料表要嘛有 `owner_unit_id INTEGER NOT NULL DEFAULT 1`（或是 U0a 的 `unit_id` 表），
要嘛逐表列在 unit_scope_global_tables.json 並寫明為什麼不分單位。只准減不准增。只測不改產品行為。

- 正對照：U0a 預留的 owner_unit_id／unit_id 表全數合格且不在宣告裡；U0a 新建的 5 張單位功能表都在宣告裡。
- 反對照：合成一張兩者皆無的新表 ⇒ 判為違規；欄位宣告不對（可為 NULL／預設不是 1）也違規。
- 縮減：宣告筆數不得超過釘死的上限（要增加得動測試檔，審查看得見）；宣告的表若已補上 owner_unit_id、或根本不存在 ⇒ 過期，要刪。"""
import json
import sqlite3
from pathlib import Path

import pytest

from core import migrations as M

DECL = Path(__file__).with_name("unit_scope_global_tables.json")
#: 宣告筆數上限——只准往下改（U0b／U1／U3 補欄位後刪掉宣告、同步調低）。調高＝新增例外，審查必須逐筆看理由。
SHRINK_CEILING = 139
MIN_REASON_LEN = 8
OWNER_COL = "owner_unit_id"
U0A_NEW_TABLES = ("org_units", "org_unit_closure", "user_units", "system_settings_unit", "seq_by_entity")


def _declared():
    doc = json.loads(DECL.read_text(encoding="utf-8"))
    return doc["tables"]


def _tables(conn):
    return sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def _has_unit_col(conn, table, col):
    for r in conn.execute('PRAGMA table_info("%s")' % table):
        if r[1] == col:
            return r[2].upper() == "INTEGER" and r[3] == 1 and str(r[4]) == "1"
    return False


def _keyed(conn, table):
    """有合格的單位鍵：owner_unit_id，或 U0a 清單內的 unit_id 表（稽核、通知隨所屬記錄的單位）。"""
    return _has_unit_col(conn, table, OWNER_COL) or (table in M.U0A_UNIT_ID_TABLES and _has_unit_col(conn, table, "unit_id"))


def _check(conn, declared):
    """回 (違規, 過期)：違規＝沒單位鍵也沒宣告；過期＝宣告了但表不存在或已有單位鍵。"""
    tabs = _tables(conn)
    bad = [t for t in tabs if not _keyed(conn, t) and t not in declared]
    stale = [t for t in declared if t not in tabs or _keyed(conn, t)]
    return bad, stale


def _reason_problems(declared):
    return [t for t, why in declared.items() if not isinstance(why, str) or len(why.strip()) < MIN_REASON_LEN]


@pytest.fixture
def real(client):
    import db
    conn = db.get_db()
    yield conn
    conn.close()


# ── 宣告檔本身 ───────────────────────────────────────────────────────────────

def test_declaration_has_a_reason_for_every_table_and_never_grows():
    declared = _declared()
    assert _reason_problems(declared) == [], "每張表都要寫理由（至少 %d 字）" % MIN_REASON_LEN
    assert len(declared) <= SHRINK_CEILING, "宣告只准減不准增（%d > %d）：新表請直接加 owner_unit_id" % (len(declared), SHRINK_CEILING)
    assert not set(declared) & (set(M.U0A_OWNER_UNIT_TABLES) | set(M.U0A_UNIT_ID_TABLES)), "U0a 預留單位鍵的表不該出現在宣告裡"
    raw = json.loads(DECL.read_text(encoding="utf-8"))["tables"]
    assert list(raw) == sorted(raw), "宣告依表名排序（讓差異好審）"


# ── 真實啟動庫 ───────────────────────────────────────────────────────────────

def test_every_table_in_a_booted_database_is_unit_keyed_or_declared(real):
    bad, stale = _check(real, _declared())
    assert bad == [], "新表沒有 owner_unit_id（INTEGER NOT NULL DEFAULT 1）也沒在 unit_scope_global_tables.json 宣告：%s" % bad
    assert stale == [], "宣告過期（表已不存在或已補上單位鍵），請從 unit_scope_global_tables.json 刪除：%s" % stale


def test_positive_controls_u0a_reserved_tables_and_new_tables(real):
    declared = _declared()
    assert len(M.U0A_OWNER_UNIT_TABLES) == 36 and len(M.U0A_UNIT_ID_TABLES) == 2
    for t in M.U0A_OWNER_UNIT_TABLES:
        assert _has_unit_col(real, t, OWNER_COL) and t not in declared, t
    for t in M.U0A_UNIT_ID_TABLES:
        assert _has_unit_col(real, t, "unit_id") and _keyed(real, t) and t not in declared, t
    for t in U0A_NEW_TABLES:
        assert t in declared and not _keyed(real, t), t
    assert _keyed(real, "vouchers_all") and "vouchers" not in _tables(real), "VIEW 不是資料表，不在守門範圍"


# ── 合成：反對照 ─────────────────────────────────────────────────────────────

def _mem(*ddl):
    c = sqlite3.connect(":memory:")
    for d in ddl:
        c.execute(d)
    return c


def test_negative_control_a_new_table_with_neither_fails():
    c = _mem("CREATE TABLE t6_synthetic_new (id INTEGER PRIMARY KEY, name TEXT)")
    bad, stale = _check(c, {})
    assert bad == ["t6_synthetic_new"] and stale == []


def test_negative_control_wrong_column_definition_does_not_count():
    c = _mem("CREATE TABLE a (id INTEGER PRIMARY KEY, owner_unit_id INTEGER)",                          # 可為 NULL
             "CREATE TABLE b (id INTEGER PRIMARY KEY, owner_unit_id INTEGER NOT NULL DEFAULT 0)",      # 預設不是根單位
             "CREATE TABLE c (id INTEGER PRIMARY KEY, owner_unit_id TEXT NOT NULL DEFAULT 1)",         # 型別不對
             "CREATE TABLE d (id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL DEFAULT 1)")            # unit_id 只有 U0a 清單內的表算數
    assert _check(c, {})[0] == ["a", "b", "c", "d"]


def test_synthetic_accepts_a_keyed_table_a_declared_table_and_flags_stale_entries():
    c = _mem("CREATE TABLE ok_keyed (id INTEGER PRIMARY KEY, owner_unit_id INTEGER NOT NULL DEFAULT 1)",
             "CREATE TABLE ok_declared (id INTEGER PRIMARY KEY)",
             "CREATE TABLE gained (id INTEGER PRIMARY KEY, owner_unit_id INTEGER NOT NULL DEFAULT 1)")
    bad, stale = _check(c, {"ok_declared": "synthetic reason", "gained": "should have been removed", "gone": "table no longer exists"})
    assert bad == [] and stale == ["gained", "gone"]


def test_reason_check_rejects_missing_or_trivial_reasons():
    assert _reason_problems({"x": "", "y": "  短  ", "z": None, "w": "a real reason here"}) == ["x", "y", "z"]
