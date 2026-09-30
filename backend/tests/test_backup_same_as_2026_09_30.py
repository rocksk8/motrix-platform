# -*- coding: utf-8 -*-
"""每日備份「同上一份」：資料沒變就不重寫（使用者 2026-09-30：「盡可能降低硬碟的重複寫入」；DR-SOP §3b）。

三份（本機快照、雲端整庫、41 張表 JSON）在資料與前一份相同時：
  本機 ⇒ 硬連結（同一個檔案，寫入 0）＋ SAME_AS.json；雲端 ⇒ 只留 SAME_AS.json（＋當日彙總），不重寫整庫與 JSON；月備份照常完整寫。
守門：① 資料未變不寫（且「備份自己寫的稽核」不算變） ② 變了照寫 ③ 月備份必寫 ④ 還原從標記找得到（含找不到時明說）
⑤ 損毀的庫不被當成「未變」（S-CD02） ⑥ 清理不刪被引用的日子 ⑦ 退路：不支援硬連結／舊版沒有指紋／前一份雲端缺 ⇒ 完整寫。

「前一天」的模擬：先跑一次 `_daily_backup()`（今天），再把今天的三個資料夾改名成昨天，然後再跑一次（今天）。
"""
import os
import shutil
import sqlite3
from datetime import date, timedelta

import pytest


@pytest.fixture
def arch(isolated_archive, monkeypatch):
    import archive
    import db
    monkeypatch.setattr(archive, "DB_PATH", db.DB_PATH)          # 讓快照與 JSON 來自同一個庫（身分對照才真的跑）
    assert archive._summary_is_comparable()
    return archive


@pytest.fixture
def pii_root(isolated_archive, arch):
    root = os.path.join(os.path.dirname(isolated_archive), arch._PII_ARCHIVE_DIRNAME)
    os.makedirs(root)                                             # 人預先建立的個資資料夾（程式不會建）
    return root


def _today():
    return date.today().isoformat()


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


def _seed(n=3, tag="A"):
    import db
    conn = db.get_db()
    try:
        for i in range(n):
            conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at) VALUES (?,?,?,?,?)",
                         ("MQ-SA-%s%03d" % (tag, i), "草稿", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
            conn.execute("INSERT INTO customers (code, name, created_at, updated_at) VALUES (?,?,?,?)",
                         ("C-SA-%s%03d" % (tag, i), "客戶%d" % i, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _dirs(arch, pii_root):
    return {"local": os.path.join(arch._LOCAL_DB_BACKUP, "%s"),
            "daily": os.path.join(arch._daily_dir(), "%s"),
            "pii": os.path.join(pii_root, "每日備份", "%s")}


def _shift_today_to_yesterday(arch, pii_root):
    """模擬「昨天跑過」：把今天的本機／雲端每日／個資每日資料夾改名成昨天（月備份留著）。"""
    for tpl in _dirs(arch, pii_root).values():
        src, dst = tpl % _today(), tpl % _yesterday()
        assert os.path.isdir(src), src
        os.rename(src, dst)


def _jsons(d):
    return [n for n in os.listdir(d) if n.endswith(".json") and n not in ("彙總.json", "SAME_AS.json")]


def _first_day(arch, pii_root):
    _seed()
    arch._daily_backup()
    d = _dirs(arch, pii_root)
    assert os.path.isfile(os.path.join(d["local"] % _today(), "motrix_erp.db")) and os.path.isfile(os.path.join(d["local"] % _today(), ".done"))
    assert os.path.isfile(os.path.join(d["local"] % _today(), arch.FINGERPRINT_FILE)), "完整快照要留指紋（之後的比對基準）"
    assert os.path.isfile(os.path.join(d["pii"] % _today(), "motrix_erp.db")) and len(_jsons(d["daily"] % _today())) > 20
    assert not os.path.exists(os.path.join(d["local"] % _today(), arch.SAME_AS_FILE))
    _shift_today_to_yesterday(arch, pii_root)
    return d


def test_unchanged_data_writes_no_new_snapshot_json_or_cloud_db(arch, pii_root):
    d = _first_day(arch, pii_root)
    arch._daily_backup()                                          # 第二天：資料沒變（只有備份自己的稽核多了幾筆）
    local_today, local_prev = d["local"] % _today(), d["local"] % _yesterday()
    assert os.path.samefile(os.path.join(local_today, "motrix_erp.db"), os.path.join(local_prev, "motrix_erp.db")), \
        "資料沒變，本機快照卻寫了一份新的（要是前一份的硬連結）"
    m = arch._read_json_file(os.path.join(local_today, arch.SAME_AS_FILE))
    assert m["same_as"] == _yesterday() and m["linked"] is True
    assert os.path.isfile(os.path.join(local_today, ".done"))
    pii_today = d["pii"] % _today()
    assert not os.path.exists(os.path.join(pii_today, "motrix_erp.db")), "雲端整庫又寫了一份"
    assert arch._read_json_file(os.path.join(pii_today, arch.SAME_AS_FILE))["same_as"] == _yesterday()
    daily_today = d["daily"] % _today()
    assert _jsons(daily_today) == [], "41 張表 JSON 又寫了一遍：%s" % _jsons(daily_today)[:3]
    assert arch._read_json_file(os.path.join(daily_today, arch.SAME_AS_FILE))["same_as"] == _yesterday()
    assert os.path.isfile(os.path.join(daily_today, "彙總.json")) and os.path.isfile(os.path.join(daily_today, ".done"))
    assert arch._read_json_file(os.path.join(daily_today, "彙總.json"))["same_as"] == _yesterday()


def test_changed_data_is_written_in_full(arch, pii_root):
    d = _first_day(arch, pii_root)
    _seed(2, tag="B")                                             # 前一天之後有新資料
    arch._daily_backup()
    local_today, local_prev = d["local"] % _today(), d["local"] % _yesterday()
    assert not os.path.exists(os.path.join(local_today, arch.SAME_AS_FILE))
    assert not os.path.samefile(os.path.join(local_today, "motrix_erp.db"), os.path.join(local_prev, "motrix_erp.db"))
    assert os.path.isfile(os.path.join(d["pii"] % _today(), "motrix_erp.db"))
    assert not os.path.exists(os.path.join(d["pii"] % _today(), arch.SAME_AS_FILE))
    assert len(_jsons(d["daily"] % _today())) > 20
    conn = sqlite3.connect(os.path.join(local_today, "motrix_erp.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM quotations WHERE quote_no LIKE 'MQ-SA-B%'").fetchone()[0] == 2
    finally:
        conn.close()


def test_the_backups_own_audit_rows_do_not_count_as_a_change(arch, pii_root):
    _seed()
    fp0 = arch._db_content_fingerprint(arch.DB_PATH)
    for _ in range(3):
        arch._system_audit("backup.sqlite_snapshot", "x", {"a": 1})
    assert arch._db_content_fingerprint(arch.DB_PATH) == fp0, "備份自己寫的稽核讓指紋變了 ⇒ 功能永遠不會觸發"
    conn = __import__("db").get_db()
    conn.execute("INSERT INTO audit_log (at, action, target_type, target_id) VALUES ('2026-09-30T00:00:00','user.login','u','1')")
    conn.commit()
    conn.close()
    assert arch._db_content_fingerprint(arch.DB_PATH) != fp0, "真正的稽核（非 backup.*）要算變動"


def test_monthly_backup_is_always_written_in_full(arch, pii_root, monkeypatch):
    d = _first_day(arch, pii_root)
    month = date.today().strftime("%Y-%m")
    shutil.rmtree(os.path.join(arch._monthly_dir(), month), ignore_errors=True)       # 讓這一輪的月備份重做
    shutil.rmtree(os.path.join(pii_root, "月備份", month), ignore_errors=True)
    arch._daily_backup()                                          # 今天是「同上一份」，月備份不可以跟著省
    assert os.path.isfile(os.path.join(d["local"] % _today(), arch.SAME_AS_FILE)), "前提：今天確實是同上一份"
    shutil.rmtree(os.path.join(arch._monthly_dir(), month), ignore_errors=True)   # 上一行的每日備份內含的月備份若被既有健檢擋下，就在這裡重做
    shutil.rmtree(os.path.join(pii_root, "月備份", month), ignore_errors=True)
    monkeypatch.setattr(arch, "_snapshot_health", lambda *a, **k: (True, [], {}))   # 月備份的身分對照沒有「快照之後寫入」寬容（既有行為，與本題無關）
    arch._monthly_backup()
    mdir = os.path.join(arch._monthly_dir(), month)
    assert len(_jsons(mdir)) > 20 and os.path.isfile(os.path.join(mdir, ".done"))
    assert not os.path.exists(os.path.join(mdir, arch.SAME_AS_FILE))
    pdb = os.path.join(pii_root, "月備份", month, "motrix_erp.db")
    assert os.path.isfile(pdb) and os.path.getsize(pdb) > 0, "月備份整庫檔一定要完整寫"


def test_restore_finds_the_real_content_from_the_marker(arch, pii_root, capsys):
    d = _first_day(arch, pii_root)
    arch._daily_backup()
    real_pii = arch.resolve_same_as(d["pii"] % _today())
    assert os.path.normcase(real_pii) == os.path.normcase(d["pii"] % _yesterday())
    assert os.path.isfile(os.path.join(real_pii, "motrix_erp.db"))
    real_daily = arch.resolve_same_as(d["daily"] % _today())
    assert os.path.normcase(real_daily) == os.path.normcase(d["daily"] % _yesterday()) and len(_jsons(real_daily)) > 20
    assert arch.resolve_same_as(d["daily"] % _yesterday()) == d["daily"] % _yesterday()       # 沒有標記 ⇒ 自己
    from tools import find_backup
    assert find_backup.main(["find_backup", d["pii"] % _today()]) == 0
    out = capsys.readouterr().out
    assert "實體資料夾" in out and _yesterday() in out and "motrix_erp.db" in out
    # 標記指向的那一天不在了 ⇒ 明說找不到（不假裝有）
    shutil.rmtree(d["pii"] % _yesterday())
    assert arch.resolve_same_as(d["pii"] % _today()) == ""
    assert find_backup.main(["find_backup", d["pii"] % _today()]) == 1
    assert "找不到" in capsys.readouterr().out
    # 本機是硬連結：就算前一天的資料夾被清掉，今天自己仍有完整的檔
    shutil.rmtree(d["local"] % _yesterday())
    real_local = arch.resolve_same_as(d["local"] % _today())
    assert real_local == d["local"] % _today() and os.path.getsize(os.path.join(real_local, "motrix_erp.db")) > 0


def test_a_corrupt_database_is_never_treated_as_unchanged(arch, tmp_path):
    import struct
    good = tmp_path / "good.db"
    conn = sqlite3.connect(str(good))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,) for _ in range(3000)])
    conn.commit()
    conn.execute("DELETE FROM t WHERE id % 2 = 0")
    conn.commit()
    conn.close()
    assert arch._db_content_fingerprint(str(good))
    # 「壞了、但整張表照樣讀得出來」：只有 quick_check 抓得到（而不是雜湊時丟例外）——這才是 S-CD02 要守的縫
    bad = tmp_path / "bad.db"
    raw = bytearray(good.read_bytes())
    for pg in range(1, len(raw) // 4096):                            # 找一個有 freeblock 的資料頁，把 freeblock 指標改成頁首內
        o = pg * 4096
        if raw[o] == 0x0D and struct.unpack(">H", raw[o + 1:o + 3])[0]:
            raw[o + 1:o + 3] = struct.pack(">H", 5)
            break
    else:
        pytest.fail("造不出測試用的壞庫（沒有含 freeblock 的資料頁）")
    bad.write_bytes(bytes(raw))
    c = sqlite3.connect(str(bad))
    try:
        assert c.execute("PRAGMA quick_check").fetchall()[0][0] != "ok", "前提：這份庫要被 quick_check 判壞"
        assert sum(1 for _ in c.execute("SELECT * FROM t")) > 1000, "前提：這份庫整張表仍讀得出來（否則測不到 quick_check 這一關）"
    finally:
        c.close()
    assert arch._db_content_fingerprint(str(bad)) is None, "quick_check 不是 ok 的庫要回 None（呼叫端走完整寫入，快照健檢會擋下並告警）"
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database" * 100)
    assert arch._db_content_fingerprint(str(garbage)) is None


def test_corrupt_source_falls_back_to_a_full_snapshot(arch, pii_root, monkeypatch):
    d = _first_day(arch, pii_root)
    monkeypatch.setattr(arch, "_db_content_fingerprint", lambda path: None)   # 來源庫讀不了／quick_check 失敗
    arch._daily_backup()
    local_today, local_prev = d["local"] % _today(), d["local"] % _yesterday()
    assert not os.path.exists(os.path.join(local_today, arch.SAME_AS_FILE))
    assert not os.path.samefile(os.path.join(local_today, "motrix_erp.db"), os.path.join(local_prev, "motrix_erp.db"))


def test_fallbacks_hardlink_unsupported_no_fingerprint_and_missing_cloud_reference(arch, pii_root, monkeypatch):
    d = _first_day(arch, pii_root)
    # 舊版備份沒有指紋 ⇒ 不能比 ⇒ 完整寫
    os.remove(os.path.join(d["local"] % _yesterday(), arch.FINGERPRINT_FILE))
    arch._daily_backup()
    assert not os.path.exists(os.path.join(d["local"] % _today(), arch.SAME_AS_FILE))
    assert os.path.isfile(os.path.join(d["local"] % _today(), arch.FINGERPRINT_FILE))
    shutil.rmtree(d["local"] % _today())
    shutil.rmtree(d["daily"] % _today())
    shutil.rmtree(d["pii"] % _today())
    # 檔案系統不支援硬連結 ⇒ 完整寫（快照仍然存在、內容完整）
    with open(os.path.join(d["local"] % _yesterday(), arch.FINGERPRINT_FILE), "w", encoding="utf-8") as f:
        f.write(arch._db_content_fingerprint(os.path.join(d["local"] % _yesterday(), "motrix_erp.db")))
    real_link = os.link
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("no hardlink")))
    arch._snapshot_sqlite(also_to_cloud=False)
    t = os.path.join(d["local"] % _today(), "motrix_erp.db")
    assert os.path.getsize(t) > 0 and not os.path.samefile(t, os.path.join(d["local"] % _yesterday(), "motrix_erp.db"))
    monkeypatch.setattr(os, "link", real_link)                    # 只還原 os.link（不用 undo()：會連 fixture 的隔離一起還原）
    shutil.rmtree(d["local"] % _today())
    # 前一份的雲端整庫不在 ⇒ 雲端完整寫，不留指向不存在內容的標記
    shutil.rmtree(d["pii"] % _yesterday())
    arch._snapshot_sqlite(also_to_cloud=True)
    assert os.path.isfile(os.path.join(d["pii"] % _today(), "motrix_erp.db"))
    assert not os.path.exists(os.path.join(d["pii"] % _today(), arch.SAME_AS_FILE))


def test_prune_never_deletes_a_day_that_a_marker_still_points_to(arch, tmp_path):
    layer = tmp_path / "每日備份"
    for n in ("2026-01-01", "2026-01-02", "2026-01-03"):
        (layer / n).mkdir(parents=True)
    arch._atomic_json_write(str(layer / "2026-01-03" / arch.SAME_AS_FILE), {"same_as": "2026-01-01"})
    assert arch._protect_referenced(["2026-01-01", "2026-01-02"], str(layer), "測試") == ["2026-01-02"]
    assert arch._protect_referenced([], str(layer), "測試") == []
    assert arch._referenced_days(str(layer)) == {"2026-01-01"}
    assert arch._protect_referenced(["2026-01-02"], str(tmp_path / "不存在"), "測試") == ["2026-01-02"]


def test_s3_backend_never_dedupes(arch, monkeypatch):
    monkeypatch.setattr(arch, "_active_backend", lambda: "s3")
    assert arch._cloud_dedupe_ok() is False
    monkeypatch.setattr(arch, "_active_backend", lambda: "local_drive")
    assert arch._cloud_dedupe_ok() is True
