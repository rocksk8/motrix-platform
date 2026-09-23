"""`T11`／`BK10` 修補：每日備份自 09-22 起**每天必定判不合格**。

成因（hichan-0a 以雲端 09-22～09-24 副本重現）：
```
_snapshot_sqlite()  拍快照 -> 立刻寫一筆 backup.sqlite_snapshot 稽核
_daily_backup()     之後才匯出 JSON（彙總.json）
BK10 身分對照       快照筆數 < 彙總筆數 ⇒ 不合格
⇒ 彙總的稽核紀錄永遠 ≥ 快照＋1 ⇒ 每天不寫 .done
09-24 實例：快照 audit 3088／彙總 3091，多出 3089～3091 全是備份程式自己寫的
同日重跑沿用早上的快照 ⇒ 期間的新報價／新稽核只會讓差距更大
```
驗收（`HANDOFF-PENDING-2026-09-23.md` 🔴 T11）：
① 正常快照＋快照之後再寫入 ⇒ **現行碼上紅**
② 空庫／他庫快照（08-30 型：表都在、資料沒有）⇒ **仍判不合格**（另以突變證明）
③ 同日重跑沿用早上的快照 ⇒ 不因中間的寫入被判不合格
④ 觀測點：雲端（測試替身）`每日備份/<日>/.done` **真的被寫出來**
"""
import os
import sqlite3
import time
from datetime import date

import pytest


@pytest.fixture
def arch(isolated_archive, monkeypatch):
    """⚠️ 讓身分對照**真的跑**：測試環境裡 `archive.DB_PATH`（匯入當下的值）與
    `db.DB_PATH`（fixture 換過的）不是同一個檔 ⇒ `_summary_is_comparable()` 回 False
    ⇒ 對照被略過 ⇒ 任何題都會假綠。這裡把兩者對齊，並當場驗它生效。"""
    import archive
    import db
    monkeypatch.setattr(archive, "DB_PATH", db.DB_PATH)
    assert archive._summary_is_comparable(), "量尺：身分對照沒有被打開，下面每一題都量不到它"
    return archive


def _today():
    return date.today().isoformat()


def _cloud_done(arch):
    return os.path.exists(os.path.join(arch._daily_dir(), _today(), ".done"))


def _local_snap(arch):
    return os.path.join(arch._LOCAL_DB_BACKUP, _today(), "motrix_erp.db")


def _seed_live(n_audit=20, n_quote=3, n_cust=3, ts="2026-01-01T00:00:00"):
    """正式庫種資料。⚠️ 時間戳給**很早**：這些列是快照之前就在的，不該被當成
    「快照之後才寫的」而得到寬容。"""
    import db
    conn = db.get_db()
    try:
        for i in range(n_audit):
            conn.execute("INSERT INTO audit_log (at, action, target_type, target_id)"
                         " VALUES (?,?,?,?)", (ts, "seed", "t", str(i)))
        for i in range(n_quote):
            conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                         " VALUES (?,?,?,?,?)", ("MQ-T11-%03d" % i, "草稿", "{}", ts, ts))
        for i in range(n_cust):
            conn.execute("INSERT INTO customers (code, name, created_at, updated_at)"
                         " VALUES (?,?,?,?)", ("C-T11-%03d" % i, "客戶%d" % i, ts, ts))
        conn.commit()
    finally:
        conn.close()


def test_t11_a_normal_day_is_marked_done_even_though_the_backup_audits_itself(arch):
    """①④：正常的一天。快照之後備份程式自己寫的稽核，不可以讓這一天判不合格。"""
    _seed_live()
    arch._daily_backup()
    assert _cloud_done(arch), (
        "正常的一天沒有寫出雲端 每日備份/%s/.done —— 快照之後寫進去的稽核（備份自己的"
        " backup.sqlite_snapshot）讓身分對照判成「快照比彙總少」。" % _today())


def test_t11_a_same_day_rerun_reusing_the_morning_snapshot_is_not_rejected(arch):
    """③：早上的快照被沿用；中間有人新增報價、寫了稽核 ⇒ 不可以判不合格。"""
    _seed_live()
    arch._snapshot_sqlite(also_to_cloud=False)          # 早上那一份（本機 .done 會寫）
    snap = _local_snap(arch)
    assert os.path.isfile(snap)
    two_hours_ago = time.time() - 7200
    os.utime(snap, (two_hours_ago, two_hours_ago))     # 模擬「那是早上拍的」

    import db
    conn = db.get_db()
    try:
        from datetime import datetime
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES ('MQ-T11-NOON','草稿','{}',?,?)", (now, now))
        for i in range(5):
            conn.execute("INSERT INTO audit_log (at, action, target_type, target_id)"
                         " VALUES (?,?,?,?)", (now, "noon", "t", str(i)))
        conn.commit()
    finally:
        conn.close()

    arch._daily_backup()                                  # 沿用早上的快照（本機 .done 已在）
    assert _cloud_done(arch), (
        "同日重跑沿用早上的快照，中午新增 1 張報價與 5 筆稽核之後被判不合格 —— "
        "那些列是快照之後才寫的，不是快照漏掉的。")


def test_t11_a_stale_empty_snapshot_is_still_rejected(arch):
    """②：08-30 型 —— 快照的表都在、資料沒有（別的庫／空庫），而正式庫是滿的 ⇒ 仍不合格。

    ⚙️ 造法：當日本機快照位置放一份「結構完整、資料是空的」庫，並放本機 .done
       ⇒ `_snapshot_sqlite()` 沿用它（不重拍）⇒ 身分對照拿它跟正式庫的彙總比。
    ⚠️ 正式庫的列時間戳都很早 ⇒ 不會被當成「快照之後才寫的」而得到寬容。
    """
    _seed_live(n_audit=200, n_quote=30, n_cust=30)
    snap = _local_snap(arch)
    os.makedirs(os.path.dirname(snap), exist_ok=True)
    conn = sqlite3.connect(snap)
    try:
        for t in arch.SNAPSHOT_REQUIRED_TABLES:
            conn.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY)" % t)
        conn.commit()
    finally:
        conn.close()
    with open(os.path.join(os.path.dirname(snap), ".done"), "w", encoding="utf-8") as f:
        f.write("seed")

    arch._daily_backup()
    assert not _cloud_done(arch), (
        "一份空的快照（表都在、0 列）被標記成完成 —— 那正是 2026-08-30／08-31／09-03 的樣子。")


def test_t11_the_real_09_24_numbers():
    """純函式：09-24 實際數字（hichan-0a 從雲端副本量）。
    快照 3088 ／彙總 3091，差的 3 筆都是快照之後寫的 ⇒ 給 3 的寬容要過；不給要擋。"""
    import archive
    counts = {"稽核紀錄": 3088, "報價單": 36, "客戶": 40}
    summary = {"稽核紀錄": 3091, "報價單": 36, "客戶": 40}
    assert archive.snapshot_content_ok(counts, summary, allowance={"稽核紀錄": 3})
    assert not archive.snapshot_content_ok(counts, summary, allowance={"稽核紀錄": 2})
    assert not archive.snapshot_content_ok(counts, summary)
