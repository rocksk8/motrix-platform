# -*- coding: utf-8 -*-
"""core.migrations 的「未完成」回傳值慣例與 incomplete(db_path)（CORE 1.58；B，2026-09-28 使用者裁示「該補就補」）。

① 回原因字串 ⇒ 版號不前進、ERROR、該模組後面的版號這次不跑、其他模組照跑、run_all 不丟例外；
   條件具備後再跑 ⇒ 補上並記版號、incomplete 清空（正反兩向）。
② 回其他值（True）＝寫錯 ⇒ 同樣不記＋ERROR（反向控制：不可以因為「有回東西」就當完成）。
③ incomplete 依庫分開：主庫未完成、demo 庫完成 ⇒ 主庫那筆仍在；沒跑過的庫 ⇒ None（不是「全部完成」）。
合成模組名、合成函式，不依賴任何 L2 模組。
"""
import logging
import sqlite3

import pytest

from core import migrations


@pytest.fixture
def iso(monkeypatch):
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    monkeypatch.setattr(migrations, "_INCOMPLETE", {})


def _db(path):
    import db
    conn = sqlite3.connect(str(path))
    db._ensure_module_schema_versions(conn)
    return conn


def _cols(conn):
    return {r[1] for r in conn.execute("PRAGMA table_info(zz_items)").fetchall()}


def _needs_table_v1(conn):
    if not _cols(conn):
        return "zz_items 表不存在，下次再補"
    if "note" not in _cols(conn):
        conn.execute("ALTER TABLE zz_items ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _register(v2_hits, other_hits):
    migrations.register("zz_inc", 1, _needs_table_v1)
    migrations.register("zz_inc", 2, lambda conn: v2_hits.append(1))
    migrations.register("zz_other", 1, lambda conn: other_hits.append(1))


def test_reason_string_holds_the_version_then_completes_when_possible(tmp_path, iso, caplog):
    v2, other = [], []
    _register(v2, other)
    conn = _db(tmp_path / "main.db")
    try:
        with caplog.at_level(logging.ERROR, logger="motrix.migrations"):
            ran = migrations.run_all(conn)                                   # 不丟例外
        assert migrations.current_version(conn, "zz_inc") == 0 and "zz_inc" not in ran
        assert v2 == [], "未完成的模組，後面的版號這次不可以跑（不跳號）"
        assert other == [1] and migrations.current_version(conn, "zz_other") == 1, "其他模組照跑"
        assert migrations.incomplete(str(tmp_path / "main.db")) == {"zz_inc": (1, "zz_items 表不存在，下次再補")}
        assert any("zz_inc" in r.getMessage() and "未完成" in r.getMessage() for r in caplog.records), caplog.text

        conn.execute("CREATE TABLE zz_items (id INTEGER PRIMARY KEY)")      # 條件具備 ⇒ 下次補上
        conn.commit()
        ran = migrations.run_all(conn)
        assert "note" in _cols(conn) and migrations.current_version(conn, "zz_inc") == 2 and v2 == [1]
        assert ran == {"zz_inc": (0, 2)} and other == [1]
        assert migrations.incomplete(str(tmp_path / "main.db")) == {}
    finally:
        conn.close()


def test_reverse_control_any_other_return_value_is_not_completion(tmp_path, iso, caplog):
    migrations.register("zz_bad", 1, lambda conn: True)
    conn = _db(tmp_path / "bad.db")
    try:
        with caplog.at_level(logging.ERROR, logger="motrix.migrations"):
            migrations.run_all(conn)
        assert migrations.current_version(conn, "zz_bad") == 0
        v, why = migrations.incomplete(str(tmp_path / "bad.db"))["zz_bad"]
        assert v == 1 and "回傳值只能是 None" in why and "True" in why, why
        assert any("zz_bad" in r.getMessage() for r in caplog.records)
    finally:
        conn.close()


def test_incomplete_is_kept_per_database(tmp_path, iso):
    v2, other = [], []
    _register(v2, other)
    main, demo = _db(tmp_path / "main.db"), _db(tmp_path / "demo.db")
    try:
        demo.execute("CREATE TABLE zz_items (id INTEGER PRIMARY KEY)")
        demo.commit()
        migrations.run_all(main)                                             # 主庫：未完成
        migrations.run_all(demo)                                             # demo 庫：完成（init_db 的第二次呼叫）
        assert migrations.incomplete(str(tmp_path / "main.db")) == {"zz_inc": (1, "zz_items 表不存在，下次再補")}
        assert migrations.incomplete(str(tmp_path / "demo.db")) == {}
        assert migrations.incomplete(str(tmp_path / "never.db")) is None, "沒跑過 ≠ 全部完成"
    finally:
        main.close()
        demo.close()
