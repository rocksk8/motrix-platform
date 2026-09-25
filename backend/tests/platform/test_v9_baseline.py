# -*- coding: utf-8 -*-
"""V9 基準比對（DATA-COMPAT §3、CORE-SPEC「使用者裁示」③）。

- 新版的 `_MIGRATIONS` 就是 V9 的 v1~v116，不再往後接；新 schema 走模組 migration。
- 庫版本 > 基準 ⇒ 拒絕升級（V9 原版新增了 migration 而沒追進來）。
- 庫版本 ≤ 基準 ⇒ 照常補跑到基準（V9 舊庫的升級路徑）。
- `module_schema_versions` 存在（還沒有模組 migration，先建表）。
"""
import sqlite3

import pytest

import db


def _version(path):
    c = sqlite3.connect(str(path))
    try:
        return c.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
    finally:
        c.close()


def _set(path, v):
    c = sqlite3.connect(str(path))
    try:
        c.execute("UPDATE schema_version SET version=? WHERE id=1", (v,))
        c.commit()
    finally:
        c.close()


def _tables(path):
    c = sqlite3.connect(str(path))
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def test_baseline_is_v116_and_is_the_whole_migration_list():
    """基準改了卻沒同步 ⇒ 紅：三個數字必須相同。"""
    assert db.V9_BASELINE == 116
    assert db.CURRENT_VERSION == db.V9_BASELINE
    assert len(db._MIGRATIONS) == db.V9_BASELINE


def test_newer_than_baseline_is_refused(tmp_path):
    p = tmp_path / "v9_newer.db"
    db.init_db(str(p))
    _set(p, db.V9_BASELINE + 1)
    with pytest.raises(db.SchemaNewerThanBaseline) as ei:
        db.init_db(str(p))
    assert str(db.V9_BASELINE + 1) in str(ei.value) and str(db.V9_BASELINE) in str(ei.value)
    assert _version(p) == db.V9_BASELINE + 1          # 不可以改寫證據


def test_at_baseline_passes(tmp_path):
    p = tmp_path / "v9_same.db"
    db.init_db(str(p))
    assert _version(p) == db.V9_BASELINE
    db.init_db(str(p))                                # 第二次啟動不拒絕
    assert _version(p) == db.V9_BASELINE


def test_older_v9_db_is_upgraded_to_baseline(tmp_path):
    """V9 舊庫（例：v110）⇒ 補跑 v111~v116。migration 冪等（U10 守著），重跑安全。"""
    p = tmp_path / "v9_older.db"
    db.init_db(str(p))
    _set(p, db.V9_BASELINE - 6)
    db.init_db(str(p))
    assert _version(p) == db.V9_BASELINE


def test_module_schema_versions_table_exists(tmp_path):
    p = tmp_path / "fresh.db"
    db.init_db(str(p))
    assert "module_schema_versions" in _tables(p)
    assert "schema_versions" not in _tables(p)       # 與 V9 的 schema_version 只差一個 s 的名字不可以出現
    c = sqlite3.connect(str(p))
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(module_schema_versions)")]
    finally:
        c.close()
    assert cols == ["module", "version", "applied_at"]


def test_refusal_happens_before_module_table_is_touched(tmp_path):
    """拒絕升級時連模組版本表都不可以建——拒絕＝這個庫原封不動。"""
    p = tmp_path / "v9_newer2.db"
    db.init_db(str(p))
    c = sqlite3.connect(str(p))
    try:
        c.execute("DROP TABLE module_schema_versions")
        c.commit()
    finally:
        c.close()
    _set(p, db.V9_BASELINE + 3)
    with pytest.raises(db.SchemaNewerThanBaseline):
        db.init_db(str(p))
    assert "module_schema_versions" not in _tables(p)
