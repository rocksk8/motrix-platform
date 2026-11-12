"""T80 R3：run_daily 的 purge 失敗分支必須先放寫鎖，才可以呼叫自開連線寫入的 _audit。

purge() 在 begin_write 之後遇到非預期例外不會自己 rollback ⇒ 這條連線還握著寫鎖，
`_audit("recyclebin.purge_failed")` 另開連線寫入會卡滿 30 秒且例外被吞（稽核紀錄靜默丟失）。
觀測點：`_audit` 被呼叫的那一刻，別條連線（timeout 很短）寫得進去嗎。
"""
import sqlite3

import db
from core.txn import begin_write
from modules.recyclebin import jobs, service as S


def _other_can_write():
    c = sqlite3.connect(db.DB_PATH, timeout=0.4)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS _t80_rb (x int)")
        c.execute("INSERT INTO _t80_rb VALUES (1)")
        c.commit()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


def _run(monkeypatch):
    seen = []
    monkeypatch.setattr(S, "reconcile", lambda conn: 0)
    monkeypatch.setattr(S, "due_ids", lambda conn, now: [1])
    monkeypatch.setattr(S, "_row", lambda conn, bin_id: {"entity_type": "x", "entity_id": "1", "deleted_at": "", "purge_after": ""})

    def boom(conn, bin_id, by="system", audit=None):
        begin_write(conn)                       # 拿了寫鎖
        raise RuntimeError("unexpected")        # 之後非預期例外，沒 rollback（purge 的真實形狀）
    monkeypatch.setattr(S, "purge", boom)
    monkeypatch.setattr(S, "status", lambda conn: {"overWarn": False, "usedBytes": 0, "warnBytes": 0})
    monkeypatch.setattr(S, "superadmins", lambda conn: [])
    monkeypatch.setattr(jobs, "_audit", lambda *a, **k: seen.append(_other_can_write()))
    out = jobs.run_daily()
    return out, seen


def test_purge_failure_releases_write_lock_before_audit(monkeypatch):
    out, seen = _run(monkeypatch)
    assert out["failed"] == 1
    assert seen == [True], "purge 失敗後呼叫 _audit 時寫鎖仍被這條連線握著（自鎖 30 秒）"
