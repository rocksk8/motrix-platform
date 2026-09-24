"""W-6 量測（2026-09-24）：未處理例外的 log 要記 sqlite 擴充錯誤碼，以及請求從開始到出錯的秒數。

走查伺服器在 0.3 秒內出現 6 筆 `database is locked`（edit_presence 心跳、case-record 的 BEGIN IMMEDIATE）。
原本的 log 只有例外被寫出的時間，分不出兩種完全不同的成因：
- 立即失敗（SQLITE_BUSY_SNAPSHOT／BUSY_RECOVERY 這類不經 busy handler 的路徑）
- 一起等了 30 秒 busy_timeout 才一起逾時（有人握著寫鎖 ≥30 秒）
只加記錄、不改行為（hichan-0a 准）。這一題造一個真的 SQLITE_BUSY 驗 log 裡有兩個欄位。
"""
import logging
import sqlite3

from fastapi.testclient import TestClient


def test_unhandled_sqlite_error_logs_errname_and_elapsed(client, make_user, monkeypatch, caplog):
    import db
    import main
    import routers.system as system
    u = make_user(username="w6_log", role="admin")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]

    holder = sqlite3.connect(db.DB_PATH, timeout=0.1)
    holder.execute("BEGIN IMMEDIATE")          # 握住寫鎖
    def _short_timeout_conn():
        # 真的 SQLITE_BUSY：同一個檔、busy_timeout 0.1 秒（不讓題目等 30 秒）
        c = sqlite3.connect(db.DB_PATH, timeout=0.1)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(system, "get_db", _short_timeout_conn)
    try:
        with TestClient(main.app, raise_server_exceptions=False) as tc, caplog.at_level(logging.ERROR):
            r = tc.post("/api/edit-presence", headers={"Authorization": "Bearer " + tok},
                        json={"doc_type": "case", "doc_id": "MQ-W6LOG"})
    finally:
        holder.rollback()
        holder.close()
    assert r.status_code == 500
    rec = [m for m in caplog.messages if "Unhandled OperationalError" in m]
    assert rec, caplog.messages
    assert "sqlite_errorname=SQLITE_BUSY" in rec[0], rec[0]
    assert "sqlite_errorcode=5" in rec[0], rec[0]
    assert "elapsed=" in rec[0] and "elapsed=None" not in rec[0], rec[0]
