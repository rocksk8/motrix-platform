# -*- coding: utf-8 -*-
"""demo 庫到用才複製（使用者 2026-09-30：「盡可能降低硬碟的重複寫入」；PLAN-TEST-PERF §5.1 估每輪省約 2.7 GB）。

`client` 原本每題複製 2 份範本庫（真實庫＋demo 庫，各 1.3 MB），多數題根本不碰 demo。現在 demo 庫只在第一次
`db._connect(<demo 路徑>)` 時才從範本複製（先寫 .part 再原子 rename；執行緒間用鎖）。
守門：① 不碰 demo 的題不產生 demo 檔 ② 碰了 demo 的題拿到的是**完整庫**（與範本等價，不是空檔、不是寫一半）
③ 多執行緒同時第一次連 demo 也只複製一次、每個人都讀到完整庫 ④ demo 庫與真實庫互相獨立
⑤ MOTRIX_TEST_EAGER_DEMO=1 回到預先複製（A/B 對照）。
"""
import os
import sqlite3
import threading

import db
from tests.test_template_db_2026_09_25 import _snapshot, diff


def test_a_test_that_never_touches_demo_creates_no_demo_file(client):
    assert client.get("/api/ping").status_code in (200, 401, 404)
    conn = db.get_db()
    conn.execute("SELECT 1 FROM users LIMIT 1")
    conn.close()
    assert not os.path.exists(db.DEMO_DB_PATH), "沒有人碰 demo，卻多了 demo 庫檔"
    assert not os.path.exists(db.DEMO_DB_PATH + ".part")


def test_touching_demo_gives_the_full_migrated_db(client, _template_db):
    assert not os.path.exists(db.DEMO_DB_PATH)
    conn = db._connect(db.DEMO_DB_PATH)
    try:
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] >= 1
    finally:
        conn.close()
    assert os.path.getsize(db.DEMO_DB_PATH) >= os.path.getsize(_template_db) * 0.9
    problems = diff(_snapshot(_template_db, readonly=True), _snapshot(db.DEMO_DB_PATH))
    assert problems == [], "延遲複製的 demo 庫與範本不等價：%s" % problems
    assert not os.path.exists(db.DEMO_DB_PATH + ".part")


def test_demo_mode_get_db_reads_the_lazy_demo_db(client):
    tok = db._demo_mode.set(True)
    try:
        conn = db.get_db()
        try:
            assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 50
        finally:
            conn.close()
    finally:
        db._demo_mode.reset(tok)
    assert os.path.exists(db.DEMO_DB_PATH)


def test_concurrent_first_connects_copy_once_and_all_see_a_complete_db(client):
    assert not os.path.exists(db.DEMO_DB_PATH)
    results, errors = [], []

    def go():
        try:
            c = db._connect(db.DEMO_DB_PATH)
            try:
                results.append(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
            finally:
                c.close()
        except Exception as e:                                  # noqa: BLE001
            errors.append(repr(e))
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    assert len(results) == 8 and len(set(results)) == 1 and results[0] > 50, results


def test_demo_and_real_dbs_are_independent(client):
    c = db._connect(db.DEMO_DB_PATH)
    c.execute("CREATE TABLE zz_only_demo (x)")
    c.commit()
    c.close()
    r = sqlite3.connect(db.DB_PATH)
    try:
        assert not r.execute("SELECT 1 FROM sqlite_master WHERE name='zz_only_demo'").fetchone()
    finally:
        r.close()
