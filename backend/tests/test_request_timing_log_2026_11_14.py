# -*- coding: utf-8 -*-
"""請求耗時記錄 logs/request_timing.log（T86，PM 裁示 C：不動資料表，核心 V9 基準 118 不變）。設計見 helpers/log_setup.py 檔頭「請求耗時」。

守的事：
① 一行一筆「時間 方法 路由樣板 狀態碼 耗時ms」；路由樣板去掉編號；沒比對到路由寫 (unmatched)，不寫原始路徑。
② 不含使用者、IP、查詢參數、標頭（含 token／Authorization）。
③ 只記 /api/；沒啟用時中介層完全放行、不建檔。
④ 寫入不拖慢請求：檔案很慢時請求照樣立刻回；佇列滿了丟掉並計數，不擋。
⑤ 打不開檔 ⇒ 不啟用（回 None），請求照常。
⑥ 處理丟例外 ⇒ 記 500 並把例外原樣丟出去；串流回應算到最後一塊送完。
⑦ 輪替出來的 request_timing.log.N.gz 超過保留天數會被清；現行檔不刪。
⑧ main.app 有掛這支中介層，且不是最外層（InternalColsMiddleware 仍是最後加的）。
"""
import os
import re
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from helpers import log_setup as ls

LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ([A-Z]+) (\S+) (\d+) (\d+)$")


def _app():
    app = FastAPI()

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: int):
        return {"id": case_id}

    @app.post("/api/cases/{case_id}/notes")
    def add_note(case_id: int):
        return {"ok": True}

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("kaboom")

    @app.get("/api/teapot")
    def teapot():
        raise HTTPException(418, "short and stout")

    @app.get("/api/stream")
    def stream():
        def gen():
            yield b"a"
            time.sleep(0.15)
            yield b"b"
        return StreamingResponse(gen())

    @app.get("/pages/x.html")
    def page():
        return {"page": True}

    app.add_middleware(ls.RequestTimingMiddleware)
    return app


@pytest.fixture()
def timing(tmp_path):
    inst = ls.install_request_timing(str(tmp_path), max_bytes=100000, backups=2)
    assert inst is not None
    try:
        yield inst, tmp_path
    finally:
        inst.stop()


def _lines(tmp_path):
    p = tmp_path / ls.TIMING_LOG_NAME
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def test_one_line_per_request_with_route_template_and_no_ids(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/api/cases/12345").status_code == 200
    assert c.post("/api/cases/987/notes").status_code == 200
    inst.stop()
    lines = _lines(tmp)
    assert len(lines) == 2
    m1, m2 = (LINE_RE.match(x) for x in lines)
    assert m1 and m2, lines
    assert m1.groups()[:3] == ("GET", "/api/cases/{case_id}", "200")
    assert m2.groups()[:3] == ("POST", "/api/cases/{case_id}/notes", "200")
    assert all("12345" not in x and "987" not in x for x in lines)
    assert int(m1.group(4)) >= 0


def test_no_query_user_ip_or_headers_in_the_file(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    c.get("/api/cases/7?token=SECRET123&user=alice", headers={"Authorization": "Bearer ZZZ-TOKEN", "X-Forwarded-For": "203.0.113.9",
                                                               "Cookie": "session=COOKIEVALUE", "Referer": "http://h/pages/alice.html"})
    inst.stop()
    text = (tmp / ls.TIMING_LOG_NAME).read_text(encoding="utf-8")
    for leak in ("SECRET123", "alice", "ZZZ-TOKEN", "203.0.113.9", "COOKIEVALUE", "testclient", "127.0.0.1", "?"):
        assert leak not in text, leak


def test_unmatched_api_path_is_not_written_raw(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/api/secret-customer-name-123/xyz").status_code == 404
    inst.stop()
    lines = _lines(tmp)
    assert len(lines) == 1 and "(unmatched)" in lines[0] and "404" in lines[0]
    assert "secret-customer" not in lines[0]


def test_only_api_requests_are_recorded(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    c.get("/pages/x.html")
    inst.stop()
    assert _lines(tmp) == []


def test_http_exception_and_unhandled_exception_status(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/api/teapot").status_code == 418
    assert c.get("/api/boom").status_code == 500
    inst.stop()
    codes = [LINE_RE.match(x).group(3) for x in _lines(tmp)]
    assert sorted(codes) == ["418", "500"]


def test_exception_is_logged_as_500_and_reraised_by_the_middleware():
    """直接對 ASGI 層：內層丟例外 ⇒ 記 500、原樣往外丟。"""
    import asyncio
    recorded = []
    orig = ls.record_request_timing
    ls.record_request_timing = lambda *a: recorded.append(a)
    inst = type("X", (), {})()
    prev = ls._TIMING
    ls._TIMING = inst                                   # 只要不是 None，中介層就會量
    try:
        async def inner(scope, receive, send):
            raise ValueError("inner failed")

        mw = ls.RequestTimingMiddleware(inner)
        scope = {"type": "http", "path": "/api/x", "method": "GET"}

        async def run():
            await mw(scope, None, None)

        with pytest.raises(ValueError):
            asyncio.run(run())
    finally:
        ls.record_request_timing = orig
        ls._TIMING = prev
    assert len(recorded) == 1 and recorded[0][0] == "GET" and recorded[0][2] == 500


def test_streaming_response_is_timed_until_the_last_chunk(timing):
    inst, tmp = timing
    c = TestClient(_app(), raise_server_exceptions=False)
    assert c.get("/api/stream").content == b"ab"
    inst.stop()
    ms = int(LINE_RE.match(_lines(tmp)[0]).group(4))
    assert ms >= 100, ms


def test_disabled_means_pass_through_and_no_file(tmp_path):
    assert ls._TIMING is None
    c = TestClient(_app())
    assert c.get("/api/cases/1").status_code == 200
    assert not (tmp_path / ls.TIMING_LOG_NAME).exists()


def test_slow_file_does_not_slow_requests(tmp_path, monkeypatch):
    """檔案寫入很慢（每行 0.3 秒）時，請求端照樣立刻回——寫入在背景執行緒。"""
    inst = ls.install_request_timing(str(tmp_path))
    assert inst is not None
    orig_emit = inst.file_handler.emit

    def slow_emit(record):
        time.sleep(0.3)
        orig_emit(record)

    inst.file_handler.emit = slow_emit
    try:
        c = TestClient(_app())
        c.get("/api/cases/1")                            # 暖機
        t0 = time.perf_counter()
        for i in range(10):
            c.get("/api/cases/%d" % i)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.5, "10 個請求花了 %.2f 秒；若寫檔在請求執行緒上至少要 3 秒" % elapsed
    finally:
        inst.file_handler.emit = orig_emit
        inst.stop()


def test_full_queue_drops_and_counts_without_blocking(tmp_path):
    inst = ls.install_request_timing(str(tmp_path), queue_max=2)
    assert inst is not None
    try:
        inst.listener.stop()                             # 背景執行緒停掉 ⇒ 佇列不會被消化
        t0 = time.perf_counter()
        for _ in range(50):
            ls.record_request_timing("GET", "/api/x", 200, 5)
        assert time.perf_counter() - t0 < 1.0
        assert inst.dropped == 48
    finally:
        inst.stop()


def test_unopenable_file_means_not_installed(tmp_path, capsys):
    blocker = tmp_path / "logs_is_a_file"
    blocker.write_text("x")
    assert ls.install_request_timing(str(blocker)) is None
    assert ls._TIMING is None
    assert "請求耗時記錄沒有啟用" in capsys.readouterr().err


def test_bad_method_is_not_written_verbatim(timing):
    inst, tmp = timing
    ls.record_request_timing("GET /api/x?token=abc", "/api/x", 200, 3)
    inst.stop()
    lines = _lines(tmp)
    assert len(lines) == 1 and " ? /api/x 200 3" in lines[0] and "token" not in lines[0]


def test_rotated_timing_files_are_pruned_but_current_is_kept(tmp_path):
    cur = tmp_path / "request_timing.log"
    old_gz = tmp_path / "request_timing.log.1.gz"
    new_gz = tmp_path / "request_timing.log.2.gz"
    for p in (cur, old_gz, new_gz):
        p.write_bytes(b"x")
    long_ago = time.time() - 90 * 86400
    for p in (cur, old_gz):
        os.utime(p, (long_ago, long_ago))
    removed = ls.prune_rotated_logs(str(tmp_path), 30)
    assert removed == ["request_timing.log.1.gz"]
    assert cur.exists() and new_gz.exists()


def test_rotation_uses_gzip_naming(tmp_path):
    inst = ls.install_request_timing(str(tmp_path), max_bytes=300, backups=2)
    assert inst is not None
    try:
        for i in range(40):
            ls.record_request_timing("GET", "/api/rotate/{id}", 200, i)
    finally:
        inst.stop()
    time.sleep(0.5)                                      # gzip 在背景執行緒
    names = sorted(os.listdir(tmp_path))
    assert "request_timing.log" in names
    assert any(re.match(r"^request_timing\.log\.\d+\.gz$", n) for n in names), names


def test_main_app_has_the_middleware_and_internal_cols_stays_outermost(client):
    import main
    classes = [m.cls for m in main.app.user_middleware]        # 第一個＝最外層
    assert classes[0].__name__ == "InternalColsMiddleware"
    assert ls.RequestTimingMiddleware in classes
    assert classes.index(ls.RequestTimingMiddleware) == 1


def test_cancelled_request_before_response_is_not_logged_as_500():
    import asyncio
    recorded = []
    orig, prev = ls.record_request_timing, ls._TIMING
    ls.record_request_timing = lambda *a: recorded.append(a)
    ls._TIMING = object()
    try:
        async def inner(scope, receive, send):
            raise asyncio.CancelledError()

        mw = ls.RequestTimingMiddleware(inner)

        async def run():
            await mw({"type": "http", "path": "/api/x", "method": "GET"}, None, None)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())
    finally:
        ls.record_request_timing, ls._TIMING = orig, prev
    assert recorded == []


def test_installing_twice_stops_the_previous_instance(tmp_path):
    first = ls.install_request_timing(str(tmp_path / "a"))
    second = ls.install_request_timing(str(tmp_path / "b"))
    try:
        assert first is not None and second is not None and first._stopped
        assert ls._TIMING is second
    finally:
        second.stop()


def test_install_request_timing_does_not_rescan_pending_files(tmp_path, monkeypatch):
    """recover_pending 只由 install() 跑一次；這裡再跑會對同一個 .gz.pending 起第二條壓縮執行緒。"""
    calls = []
    monkeypatch.setattr(ls, "recover_pending", lambda d: calls.append(d) or 0)
    inst = ls.install_request_timing(str(tmp_path))
    try:
        assert calls == []
    finally:
        inst.stop()
