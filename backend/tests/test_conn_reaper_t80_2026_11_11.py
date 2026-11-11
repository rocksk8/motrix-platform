"""T80 R1：請求層級連線收尾網（docs/platform/GET-DB-CONNECTION-LEAK-AUDIT-T80.md §7）。

要證明的不是「函式能呼叫」，而是**真的把寫鎖放掉了**：
  寫入後丟例外、沒 rollback／close 的連線 ⇒ 另一條連線（timeout 很短）寫入不會被擋。
負對照（收尾網關掉 ⇒ 鎖確實還在）一定要有，否則上面那題在連線早就被 GC 時也會綠。
"""
import gc
import sqlite3
import threading
import time

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
def table(client):
    """依賴 conftest 的 `client`：它先安全地 import main（BK20）、再把 db.DB_PATH 指到每題自己的暫存庫。
    ⇒ 本檔任何順序下都不會讓後面的 client 題炸、也不會把 `_t80` 表寫進開發庫。"""
    c = db.get_db()
    c.execute("CREATE TABLE IF NOT EXISTS _t80 (x int)")
    c.commit()
    c.close()
    yield
    gc.collect()


def _mini_app():
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
    monkeypatch.setattr(db, "_REAP_REQUEST_CONNECTIONS", False)
    client = TestClient(_mini_app(), raise_server_exceptions=False)
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
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    gc.collect()
    gc.disable()
    try:
        r = client.get("/leak-raise")
        assert r.status_code == 500
        assert _other_can_write() is True
    finally:
        gc.enable()


def test_reaper_releases_lock_after_http_exception(table):
    client = TestClient(_mini_app(), raise_server_exceptions=False)
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
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    client.get("/leak-raise")
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM _t80").fetchone()[0] == 0
    finally:
        c.close()


def test_clean_request_unchanged(table):
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    assert client.get("/clean").json() == {"ok": True}
    assert client.get("/read-leak").json() == {"ok": True}


def test_background_thread_connection_not_reaped(table):
    """spawn_bg_thread 開的連線比請求活得久，不可以被請求結束的收尾網登記／關掉。"""
    _BG_RELEASE.clear()
    _BG_RESULT.clear()
    _BG_RESULT["done"] = threading.Event()
    client = TestClient(_mini_app(), raise_server_exceptions=False)
    r = client.get("/bg")
    assert r.json() == {"registered": 0}
    _BG_RELEASE.set()                                   # 請求已結束、收尾網已跑完
    assert _BG_RESULT["done"].wait(10)
    assert _BG_RESULT["alive"] is True


def test_reap_logs_warning_only_for_connections_in_transaction(table, caplog):
    token, reg = db._track_request_connections()
    try:
        held = db.get_db()
        held.execute("INSERT INTO _t80 VALUES (7)")      # 在交易中
        idle = db.get_db()
        idle.execute("SELECT 1").fetchone()              # 沒在交易中，沒關
        done = db.get_db()
        done.close()                                     # 正常關閉
    finally:
        with caplog.at_level("WARNING", logger="db"):
            n = db._reap_request_connections(token, reg)
    assert n == 1
    warns = [r for r in caplog.records if "conn-reaper" in r.getMessage()]
    assert len(warns) == 1 and "test_conn_reaper_t80" in warns[0].getMessage()
    for c in (held, idle):
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")
    assert reg == []


def test_reap_from_other_thread_than_creator(table):
    """請求內連線在 worker 執行緒開、收尾網在別條執行緒回收（check_same_thread=False 才行）。"""
    token, reg = db._track_request_connections()
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
    assert db._reap_request_connections(token, reg) == 1
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


# ───────── 真正的 main.app：順序與登記簿跨執行緒可見 ─────────

def _real_leak_route(kind):
    from fastapi.routing import APIRoute

    def leak():
        conn = db.get_db()
        conn.execute("INSERT INTO _t80 VALUES (4)")
        if kind == "http":
            raise HTTPException(409, "x")
        raise ValueError("boom")
    return APIRoute("/api/_t80_leak", leak, methods=["GET"])


def test_reaper_is_innermost_user_middleware_in_real_app(client):
    """收尾網必須比 auth_middleware／license_gate 更**內**層（user_middleware 的 index 越大越內）：
    auth_middleware 在 call_next 之後還有同步寫入（操作軌跡），收尾網若在它外面，處理函式漏的寫鎖要等那幾筆寫入
    卡滿 30 秒才被回收。"""
    import main
    from starlette.middleware.base import BaseHTTPMiddleware
    layers = list(main.app.user_middleware)
    idx = {}
    for i, m in enumerate(layers):
        if m.cls is main._ConnReaperMiddleware:
            idx["reaper"] = i
        d = m.kwargs.get("dispatch")
        if m.cls is BaseHTTPMiddleware and d is not None:
            idx[getattr(d, "__name__", "")] = i
    assert "reaper" in idx and "auth_middleware" in idx and "license_gate_middleware" in idx, idx
    assert idx["reaper"] == len(layers) - 1, "收尾網不是最內層：%r" % (idx,)


@pytest.mark.parametrize("kind", ["http", "value"])
def test_real_app_stack_releases_lock_and_logs_request(client, make_user, table, caplog, kind):
    """整條真實堆疊（auth／license gate／BaseHTTPMiddleware 鏈）下：registry 對 worker 執行緒可見、
    被回收的鎖放得掉、warning 帶得出是哪個請求（N2：請求資訊在開連線當下記）。"""
    import main
    from tests.test_stock_batch_payment_2026_09_01 import _auth, _login
    u, p = make_user(username="t80_reaper_" + kind, role="superadmin")
    token = _login(client, u, p)
    route = _real_leak_route(kind)
    main.app.router.routes.insert(0, route)
    gc.collect()
    gc.disable()
    t0 = time.monotonic()
    try:
        with caplog.at_level("WARNING", logger="db"):
            if kind == "value":
                with pytest.raises(ValueError):
                    client.get("/api/_t80_leak", headers=_auth(token))
            else:
                assert client.get("/api/_t80_leak", headers=_auth(token)).status_code == 409
        elapsed = time.monotonic() - t0
        assert _other_can_write() is True
    finally:
        gc.enable()
        main.app.router.routes.remove(route)
    # 沒回收在 auth_middleware 之內的話，它在回應後的操作軌跡寫入會卡滿 30 秒 busy timeout（事件迴圈上）
    assert elapsed < 10, "請求花了 %.1f 秒：處理函式漏的寫鎖在 middleware 後續寫入之前沒被放掉" % elapsed
    msgs = [r.getMessage() for r in caplog.records if "conn-reaper" in r.getMessage()]
    assert len(msgs) == 1, msgs
    assert "/api/_t80_leak" in msgs[0] and "test_conn_reaper_t80" in msgs[0], msgs[0]


def test_warns_once_when_a_request_opens_many_connections(table, caplog):
    token, reg = db._track_request_connections()
    try:
        with caplog.at_level("WARNING", logger="db"):
            for _ in range(db._REQ_CONNS_WARN_AT + 5):
                db.get_db().close()
    finally:
        db._reap_request_connections(token, reg)
    msgs = [r.getMessage() for r in caplog.records if "單一請求已開" in r.getMessage()]
    assert len(msgs) == 1, msgs


def test_response_start_reaps_only_connections_in_transaction(table):
    """回應開始送出時只回收『在交易中』的（握著寫鎖，會卡後面 middleware 的寫入）；
    沒在交易中的（串流回應的產生器可能還要用）不動，留到請求結束。"""
    token, reg = db._track_request_connections()
    try:
        held = db.get_db()
        held.execute("INSERT INTO _t80 VALUES (11)")
        idle = db.get_db()
        idle.execute("SELECT 1").fetchone()
        n = db._reap_request_connections(None, reg, only_in_tx=True)
        assert n == 1
        with pytest.raises(sqlite3.ProgrammingError):
            held.execute("SELECT 1")
        idle.execute("SELECT 1").fetchone()               # 還活著
        assert len(reg) == 2                              # 登記簿不清
    finally:
        db._reap_request_connections(token, reg)
    with pytest.raises(sqlite3.ProgrammingError):
        idle.execute("SELECT 1")


def test_streaming_response_can_still_use_idle_connection_after_start(table):
    """串流回應的產生器在回應開始之後才讀資料庫：沒在交易中的連線不可以在 response.start 被關掉。"""
    from fastapi.responses import StreamingResponse
    from main import _ConnReaperMiddleware
    app = FastAPI()
    app.add_middleware(_ConnReaperMiddleware)

    @app.get("/stream")
    def stream():
        conn = db.get_db()
        conn.execute("SELECT 1").fetchone()

        def gen():
            yield b"a"
            yield str(conn.execute("SELECT 2").fetchone()[0]).encode()   # 開始送出之後才用
        return StreamingResponse(gen(), media_type="text/plain")

    r = TestClient(app, raise_server_exceptions=False).get("/stream")
    assert r.status_code == 200 and r.content == b"a2"


# ───────── R6：async 中介層的同步 SQLite 寫入不可以卡事件迴圈 ─────────

def _asgi_get(app, path, token):
    """直接呼叫 ASGI app（不經 TestClient，才能在同一個事件迴圈裡同時量心跳）。回 (狀態碼, 秒)。"""
    async def run():
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"authorization", b"Bearer " + token.encode()), (b"host", b"test")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80)}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            sent.append(m)
        t0 = time.monotonic()
        await app(scope, receive, send)
        return next(m["status"] for m in sent if m["type"] == "http.response.start"), time.monotonic() - t0
    return run()


def test_async_middleware_writes_do_not_block_the_event_loop(client, make_user, table, monkeypatch):
    """別的連線握著寫鎖時，auth_middleware 回應後的操作軌跡寫入會等 busy timeout——那段等待不可以發生在事件迴圈上：
    同一個迴圈裡的心跳（每 50ms 一次）最大間隔必須遠小於那個等待時間。（R6 之前＝整個等待時間，全站一起卡。）"""
    import asyncio
    import main
    from tests.test_stock_batch_payment_2026_09_01 import _login
    orig = db._connect

    def short_timeout(path, *a, **kw):
        c = orig(path, *a, **kw)
        c.execute("PRAGMA busy_timeout=1500")            # 測試用：等 1.5 秒就放棄（正式是 30 秒）
        return c
    monkeypatch.setattr(db, "_connect", short_timeout)
    u, p = make_user(username="t80_r6", role="superadmin")
    token = _login(client, u, p)
    holder = sqlite3.connect(db.DB_PATH, timeout=1)
    holder.execute("BEGIN IMMEDIATE")                    # 別人握著寫鎖
    try:
        async def scenario():
            gaps = []
            stop = asyncio.Event()

            async def heartbeat():
                last = time.monotonic()
                while not stop.is_set():
                    await asyncio.sleep(0.05)
                    now = time.monotonic()
                    gaps.append(now - last)
                    last = now
            hb = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.2)
            status, took = await _asgi_get(main.app, "/api/parts", token)
            stop.set()
            await hb
            return status, took, max(gaps)
        status, took, worst = asyncio.run(scenario())
    finally:
        holder.rollback()
        holder.close()
    assert status == 200, status
    assert took > 1.0, "請求沒有被寫鎖擋到——這題沒量到東西（took=%.2f）" % took
    assert worst < 0.6, "事件迴圈被卡住 %.2f 秒（請求共 %.2f 秒）：middleware 的同步寫入又回到事件迴圈上了" % (worst, took)


# ───────── R6 的代價：軌跡／失敗稽核搬進 threadpool 後，原本靠「事件迴圈上一次一個」的去重要自己撐住 ─────────

class _SlowWrites:
    """轉發給真連線；每句 INSERT／UPDATE 前睡一下，把「查有沒有前一列」到「寫入」之間的窗口撐大（讓競態每次都發生）。"""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, *a, **k):
        head = sql.lstrip()[:6].upper()
        if head in ("INSERT", "UPDATE"):
            time.sleep(0.15)
        return self._c.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


def _run_parallel(n, fn):
    barrier = threading.Barrier(n)
    out, errs = [], []

    def work():
        try:
            barrier.wait(5)
            out.append(fn())
        except Exception as e:      # noqa: BLE001
            errs.append(e)
    ths = [threading.Thread(target=work) for _ in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    assert not errs, errs
    return out


def _trail_rows(path):
    c = db.get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM user_request_log WHERE path=?", (path,)).fetchone()[0]
    finally:
        c.close()


def _trail_setup(client, make_user, monkeypatch):
    import main
    u, p = make_user(username="t80_trail", role="superadmin")
    c = db.get_db()
    uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0]
    c.close()
    real = main.get_db
    monkeypatch.setattr(main, "get_db", lambda: _SlowWrites(real()))
    main._TRAIL_CLAIMS.clear()
    return main, uid


def test_trail_dedupe_holds_when_same_group_requests_finish_together(client, make_user, table, monkeypatch):
    """開一張案件會同時回來好幾支（一次點擊）：搬進 threadpool 後同時寫軌跡，仍只能留一筆。"""
    from datetime import datetime
    main, uid = _trail_setup(client, make_user, monkeypatch)
    now = datetime.now()
    _run_parallel(6, lambda: main._record_request_trail(uid, now, "GET", "/api/parts/zz-t80", "", 200))
    assert _trail_rows("/api/parts/zz-t80") == 1


def test_trail_dedupe_negative_control_without_claim_duplicates(client, make_user, table, monkeypatch):
    """負對照：拿掉認領（＝搬進 threadpool 又沒補去重）⇒ 同樣的並行情境會寫出重複列。"""
    from datetime import datetime
    main, uid = _trail_setup(client, make_user, monkeypatch)
    monkeypatch.setattr(main, "_trail_claim", lambda key, now_dt: True)
    now = datetime.now()
    _run_parallel(6, lambda: main._record_request_trail(uid, now, "GET", "/api/parts/zz-t80b", "", 200))
    assert _trail_rows("/api/parts/zz-t80b") > 1, "沒有認領也只寫一列——這組測試量不到競態"


def test_trail_claim_released_when_write_fails(client, make_user, table, monkeypatch):
    """寫入失敗（例如資料庫忙到逾時）⇒ 放掉認領；下一個同群組請求還能記。"""
    from datetime import datetime
    main, uid = _trail_setup(client, make_user, monkeypatch)
    now = datetime.now()
    real = main.get_db

    def boom():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(main, "get_db", boom)
    main._record_request_trail(uid, now, "GET", "/api/parts/zz-t80c", "", 200)       # 失敗、被吞
    monkeypatch.setattr(main, "get_db", real)
    main._record_request_trail(uid, now, "GET", "/api/parts/zz-t80c", "", 200)
    assert _trail_rows("/api/parts/zz-t80c") == 1


def test_failure_audit_concurrent_identical_failures_write_one_row_and_count_repeats(client, make_user, table, monkeypatch):
    """同一個人、同一個路由、同一個狀態碼的失敗並行到達：只能一列 new，其餘併入 repeat，計數不可被蓋掉。"""
    import json
    from helpers import audit as A
    u, p = make_user(username="t80_fail", role="superadmin")
    c = db.get_db()
    uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0]
    c.close()
    real = A.get_db
    monkeypatch.setattr(A, "get_db", lambda: _SlowWrites(real()))
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    # 先寫第一列（new），再讓 5 條並行 repeat：計數必須 +5
    assert A._audit_failure(uid, u, "t", "POST", "/api/t80/zz", 409) == "new"
    res = _run_parallel(5, lambda: A._audit_failure(uid, u, "t", "POST", "/api/t80/zz", 409))
    assert res.count("repeat") == 5, res
    c = db.get_db()
    try:
        rows = c.execute("SELECT detail FROM audit_log WHERE target_label='/api/t80/zz' AND action='fail.POST'").fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    assert json.loads(rows[0]["detail"])["repeat"] == 5


def test_failure_audit_concurrent_first_failures_write_one_row(client, make_user, table, monkeypatch):
    from helpers import audit as A
    u, p = make_user(username="t80_fail2", role="superadmin")
    c = db.get_db()
    uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0]
    c.close()
    real = A.get_db
    monkeypatch.setattr(A, "get_db", lambda: _SlowWrites(real()))
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    _run_parallel(5, lambda: A._audit_failure(uid, u, "t", "POST", "/api/t80/yy", 409))
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM audit_log WHERE target_label='/api/t80/yy' AND action='fail.POST'").fetchone()[0]
    finally:
        c.close()
    assert n == 1
