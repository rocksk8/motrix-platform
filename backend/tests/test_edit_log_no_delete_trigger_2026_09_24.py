"""`JV22 §3`／`BN17`：編寫紀錄在**資料庫層**刪不掉，而展示重置照樣清得乾淨。

```
正式資料庫  DELETE FROM voucher_edit_log／bonus_award_edit_log  => RAISE(ABORT)
展示資料庫  reset_demo_db() 要能清空兩張表（它們在 DEMO_CLEARED_TABLES 裡）
            ⇒ 清完之後 TRIGGER **仍然要在**（否則重置一次，展示庫從此沒有保護）
```
☠️ 裝了 TRIGGER 而沒改重置：展示帳號第二次登入 500（`DM1` 的 account_items 同一個坑）。
⚙️ 本檔驗 `voucher_edit_log` 那一半；`bonus_award_edit_log` 在正式庫被擋，
   由 `test_bonus_award_reject_edit_log_2026_09_23.py::test_bn17_*` 走產品路徑驗。
"""
import sqlite3

import pytest

import db

TRIGGERS = {"voucher_edit_log_no_delete", "bonus_award_edit_log_no_delete"}


@pytest.fixture()
def demo_sandbox(tmp_path, monkeypatch):
    """比照 `test_demo_reset_2026_09_23.py`：每一個 DEMO_* 路徑改指暫存目錄（重置會刪檔）。"""
    for name in dir(db):
        if name.startswith("DEMO_") and isinstance(getattr(db, name), str):
            monkeypatch.setattr(db, name, str(tmp_path / name.lower()))
    monkeypatch.setattr(db, "DEMO_DB_PATH", str(tmp_path / "demo.db"))
    return tmp_path


def _triggers(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}


def _trigger_sql(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN (%s)"
        % ",".join("'%s'" % t for t in sorted(TRIGGERS)))}


def _seed_logs(conn):
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO voucher_edit_log (voucher_id, changed_by, changed_at, changes_json)"
                 " VALUES (1,'seed','2026-09-24','[]')")
    conn.execute("INSERT INTO bonus_award_edit_log (award_id, changed_by, changed_at, changes_json)"
                 " VALUES (1,'seed','2026-09-24','[]')")
    conn.commit()


def test_the_demo_reset_still_clears_the_edit_logs_and_keeps_the_triggers(demo_sandbox):
    db.reset_demo_db()
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        assert TRIGGERS <= _triggers(conn), "展示庫建好之後沒有 TRIGGER：%r" % _triggers(conn)
        before = _trigger_sql(conn)
        _seed_logs(conn)
    finally:
        conn.close()

    db.reset_demo_db()          # ☠️ 若重置沒處理 TRIGGER，這一行會丟 IntegrityError
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        n = [conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
             for t in ("voucher_edit_log", "bonus_award_edit_log")]
        assert n == [0, 0], "展示重置沒有清空編寫紀錄：%r" % n
        assert TRIGGERS <= _triggers(conn), (
            "重置之後 TRIGGER 不見了：%r —— 展示庫從此沒有保護。" % _triggers(conn))
        assert _trigger_sql(conn) == before, (
            "重置之後 TRIGGER 的定義變了 —— 展示庫的保護與 migration 建的那一份不一樣：%r → %r"
            % (before, _trigger_sql(conn)))
    finally:
        conn.close()


def test_the_production_db_refuses_to_delete_voucher_edit_log(client):
    """`client` 不可以拿掉：它建立的是隔離後的「正式」資料庫（不是 demo）。"""
    conn = db.get_db()
    try:
        _seed_logs(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM voucher_edit_log")
            conn.commit()
    finally:
        conn.rollback()
        conn.close()
