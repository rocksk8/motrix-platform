"""以案件為中心的獎金分潤（v112）：編寫紀錄刪不掉、改不了；展示重置照樣清得掉且保護還在。

比照 `test_edit_log_no_delete_trigger_2026_09_24.py`（v109）。hichan-0a 補的條件：
「重置兩次都成功、TRIGGER 仍在」——reset_demo_db() 的 TRIGGER 清單是寫死的名字，
新 TRIGGER 沒加進去的話，展示帳號一重置就丟例外。
"""
import sqlite3

import pytest

import db

TRIGGERS = {"bonus_case_award_edit_log_no_delete", "bonus_case_award_edit_log_no_update"}
TABLES = ("bonus_case_award_edit_log", "bonus_case_award_lines", "bonus_case_awards")


@pytest.fixture()
def demo_sandbox(tmp_path, monkeypatch):
    for name in dir(db):
        if name.startswith("DEMO_") and isinstance(getattr(db, name), str):
            monkeypatch.setattr(db, name, str(tmp_path / name.lower()))
    monkeypatch.setattr(db, "DEMO_DB_PATH", str(tmp_path / "demo.db"))
    return tmp_path


def _trigger_sql(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN (%s)"
        % ",".join("'%s'" % t for t in sorted(TRIGGERS)))}


def _seed(conn):
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO bonus_case_awards (quote_no, net_profit, rate_bp, split_json, pool_amount,"
                 " created_by, created_at, updated_by, updated_at)"
                 " VALUES ('MQ-X','100',1000,'{}',10,'s','t','s','t')")
    conn.execute("INSERT INTO bonus_case_award_lines (award_id, category, username, amount)"
                 " VALUES (1,'sales','u',5)")
    conn.execute("INSERT INTO bonus_case_award_edit_log (award_id, changed_by, changed_at, action)"
                 " VALUES (1,'seed','2026-09-24','create')")
    conn.commit()


def test_demo_reset_twice_clears_tables_and_keeps_triggers(demo_sandbox):
    assert set(TABLES) <= db.DEMO_CLEARED_TABLES, "三張新表都是使用者資料，要整張清（DM1）"
    db.reset_demo_db()
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        before = _trigger_sql(conn)
        assert set(before) == TRIGGERS, before
        _seed(conn)
    finally:
        conn.close()

    db.reset_demo_db()      # ☠️ 清單沒登記新 TRIGGER 的話，這一行丟 IntegrityError
    db.reset_demo_db()      # 第二次：重置後的庫再重置一次也要成功
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        assert [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES] == [0, 0, 0]
        assert _trigger_sql(conn) == before, "重置之後 TRIGGER 不見了或定義變了"
    finally:
        conn.close()


def test_production_db_refuses_delete_and_update(client):
    conn = db.get_db()
    try:
        _seed(conn)
        with pytest.raises(sqlite3.IntegrityError, match="不可刪除"):
            conn.execute("DELETE FROM bonus_case_award_edit_log")
        with pytest.raises(sqlite3.IntegrityError, match="不可修改"):
            conn.execute("UPDATE bonus_case_award_edit_log SET action='x'")
        assert conn.execute("SELECT action FROM bonus_case_award_edit_log").fetchone()[0] == "create"
    finally:
        conn.close()
