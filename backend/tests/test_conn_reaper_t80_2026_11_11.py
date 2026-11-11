"""T80 R1：請求層級連線收尾網（docs/platform/GET-DB-CONNECTION-LEAK-AUDIT-T80.md §7）。

要證明的不是「函式能呼叫」，而是**真的把寫鎖放掉了**：
  寫入後丟例外、沒 rollback／close 的連線 ⇒ 另一條連線（timeout 很短）寫入不會被擋。
負對照（收尾網關掉 ⇒ 鎖確實還在）一定要有，否則上面那題在連線早就被 GC 時也會綠。
"""
import gc
import sqlite3
import threading

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import db


def _other_can_write(timeout=0.4):
    """另開一條連線嘗試寫入；被擋回 False。"""
    c = sqlite3.connect(db.DB_PATH, timeout=timeout)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS _t80 (x int)")
        c.execute("INSERT INTO _t80 VALUES (1)")
        c.commit()
        return True
    except sqlite3.OperationalError as e:
        assert "locked" in str(e)
        return False
    finally:
        c.close()


@pytest.fixture
def table():
    c = db.get_db()
    c.execute("CREATE TABLE IF NOT EXISTS _t80 (x int)")
    c.commit()
    c.close()
    yield
    gc.collect()


def _app():
    from main import _ConnReaperMiddleware
    app = FastAPI()
    app.add_middleware(_ConnReaperMiddleware)

    @app.get("/leak-raise")
    def leak_raise():                       # payslip 舊版的形狀：寫入後丟例外，沒 close
        conn = db.get_db()
        conn.execute("INSERT INTO _t80 VALUES (1)")
        raise ValueError("boom")

    @app.get("/leak-http")
    def leak_http():
        conn = db.get_db()
        conn.execute("INSERT INTO _t80 VALUES (2)")
        raise HTTPException(409, "x")

    @app.get("/clean")
    def clean():
        conn = db.get_db()
        try:
            conn.execute("INSERT INTO _t80 VALUES (3)")
            conn.commit()
        finally:
            conn.close()
        return {"ok": True}

    @app.get("/read-leak")
    def read_leak():
        conn = db.get_db()
        conn.execute("SELECT 1").fetchone()
        return {"ok": True}

    @app.get("/bg")
    def bg():
        started = threading.Event()

        def work():
            c = db.get_db()                 # 背景執行緒：不可被收尾網登記
            c.execute("INSERT INTO _t80 VALUES (9)")
            c.commit()
            started.set()
            _BG_RELEASE.wait(10)            # 等請求結束（收尾網跑完）之後才用這條連線
            try:
                c.execute("SELECT 1").fetchone()
                _BG_RESULT["alive"] = True
            except sqlite3.ProgrammingError:
                _BG_RESULT["alive"] = False
            finally:
                try:
                    c.close()
                except sqlite3.ProgrammingError:
                    pass
            _BG_RESULT["done"].set()
        db.spawn_bg_thread(work)
        started.wait(5)
        return {"registered": len(db._REQ_CONNS.get())}

    return app


_BG_RELEASE = threading.Event()
_BG_RESULT = {}


def test_negative_control_without_reaper_lock_persists(table, monkeypatch):
    """負對照：收尾網關掉 ⇒ 例外後的寫鎖確實還在（GC 停掉，排除『剛好被回收』）。"""
    monkeypatch.setattr(db, "REAP_REQUEST_CONNECTIONS", False)
    client = TestClient(_app(), raise_server_exceptions=False)
    gc.collect()
    gc.disable()
    try:
        r = client.get("/leak-raise")
        assert r.status_code == 500
        assert _other_can_write() is False, "沒有收尾網時鎖應該還在（否則這組測試證明不了什麼）"
    finally:
        gc.enable()
        gc.collect()


def test_reaper_releases_lock_after_unhandled_exception(table):
    client = TestClient(_app(), raise_server_exceptions=False)
    gc.collect()
    gc.disable()
    try:
        r = client.get("/leak-raise")
        assert r.status_code == 500
        assert _other_can_write() is True
    finally:
        gc.enable()


def test_reaper_releases_lock_after_http_exception(table):
    client = TestClient(_app(), raise_server_exceptions=False)
    gc.collect()
    gc.disable()
    try:
        r = client.get("/leak-http")
        assert r.status_code == 409
        assert _other_can_write() is True
    finally:
        gc.enable()


def test_rolled_back_not_committed(table):
    """被回收的交易是 rollback，不是 commit：寫入後丟例外的那筆資料不可以留下來。"""
    c = db.get_db()
    c.execute("DELETE FROM _t80")
    c.commit()
    c.close()
    client = TestClient(_app(), raise_server_exceptions=False)
    client.get("/leak-raise")
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM _t80").fetchone()[0] == 0
    finally:
        c.close()


def test_clean_request_unchanged(table):
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/clean").json() == {"ok": True}
    assert client.get("/read-leak").json() == {"ok": True}


def test_background_thread_connection_not_reaped(table):
    """spawn_bg_thread 開的連線比請求活得久，不可以被請求結束的收尾網登記／關掉。"""
    _BG_RELEASE.clear()
    _BG_RESULT.clear()
    _BG_RESULT["done"] = threading.Event()
    client = TestClient(_app(), raise_server_exceptions=False)
    r = client.get("/bg")
    assert r.json() == {"registered": 0}
    _BG_RELEASE.set()                                   # 請求已結束、收尾網已跑完
    assert _BG_RESULT["done"].wait(10)
    assert _BG_RESULT["alive"] is True


def test_reap_logs_warning_only_for_connections_in_transaction(table, caplog):
    token, reg = db.track_request_connections()
    try:
        held = db.get_db()
        held.execute("INSERT INTO _t80 VALUES (7)")      # 在交易中
        idle = db.get_db()
        idle.execute("SELECT 1").fetchone()              # 沒在交易中，沒關
        done = db.get_db()
        done.close()                                     # 正常關閉
    finally:
        with caplog.at_level("WARNING", logger="db"):
            n = db.reap_request_connections(token, reg)
    assert n == 1
    warns = [r for r in caplog.records if "conn-reaper" in r.getMessage()]
    assert len(warns) == 1 and "test_conn_reaper_t80" in warns[0].getMessage()
    for c in (held, idle):
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")
    assert reg == []


def test_reap_from_other_thread_than_creator(table):
    """請求內連線在 worker 執行緒開、收尾網在別條執行緒回收（check_same_thread=False 才行）。"""
    token, reg = db.track_request_connections()
    box = {}

    def worker():
        c = db.get_db()
        c.execute("INSERT INTO _t80 VALUES (5)")
        box["c"] = c

    import contextvars
    ctx = contextvars.copy_context()                     # 在呼叫端複製（anyio／starlette 的 run_in_threadpool 也是這樣帶 context）
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()
    t.join()
    assert db.reap_request_connections(token, reg) == 1
    assert _other_can_write() is True


def test_outside_request_connections_untouched(table):
    """沒有登記簿（背景排程、測試直接呼叫）⇒ get_db() 與從前一樣，綁建立它的執行緒、不被登記。"""
    c = db.get_db()
    try:
        assert db._REQ_CONNS.get() is None
        result = {}

        def other():
            try:
                c.execute("SELECT 1")
                result["ok"] = True
            except sqlite3.ProgrammingError:
                result["ok"] = False
        t = threading.Thread(target=other)
        t.start()
        t.join()
        assert result["ok"] is False                     # check_same_thread 預設行為沒變
    finally:
        c.close()
