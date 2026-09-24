"""（不是測試檔，檔名不符合 test_*.py；由 test_bg_thread_isolation_2026_09_25 以子行程單獨跑）

重現：前一題的背景執行緒在那一題結束後才寫入 ⇒ 落到下一題的庫。
兩題必須依序在同一個行程裡跑（xdist 會拆開，所以由外層用子行程、不帶 -n 跑這個檔）。
"""
import sqlite3
import threading

import db

_release = threading.Event()
_written = threading.Event()


def test_a_starts_a_late_background_writer(client):
    def late():
        # 等到「下一題」開始才寫（或最多 3 秒）——模擬背景產 PDF／寄信等比題目本身慢的工作
        _release.wait(3)
        conn = db.get_db()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS zz_bg_leak (who TEXT)")
            conn.execute("INSERT INTO zz_bg_leak VALUES ('a')")
            conn.commit()
        finally:
            conn.close()
        _written.set()
    db.spawn_bg_thread(late)


def test_b_does_not_receive_the_previous_tests_write(client):
    _release.set()
    assert _written.wait(10), "前一題的背景寫入沒有發生（探針本身壞了）"
    conn = sqlite3.connect(db.DB_PATH)
    try:
        leaked = conn.execute("SELECT 1 FROM sqlite_master WHERE name='zz_bg_leak'").fetchone()
    finally:
        conn.close()
    assert not leaked, "前一題的背景執行緒寫進了這一題的庫"
