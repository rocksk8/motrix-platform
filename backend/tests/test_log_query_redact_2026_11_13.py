# -*- coding: utf-8 -*-
"""日誌查詢字串遮罩（2026-11-13；實作 helpers/log_setup.py「查詢字串遮罩」，接線 main.py）。

守的事：`?pt=`、`?token=`、`?code=` 等 query 裡的憑證不可以出現在**任何**日誌檔（access.log、app.log、server.log 兜底）。
- 單元：redact_query／redact_target／redact_text 的規則（白名單名字留名、值一律 ***、裸 token 遮、冪等）。
- 過 logging：uvicorn.access 的請求行、其他 logger 的訊息、例外文字（requests 的錯誤訊息會帶完整網址）。
- 端到端：真的跑 uvicorn（stdout／stderr 導進 server.log，跟 autostart.bat 的 `>>` 一樣）＋真的 install() 分流，打一個帶憑證的請求，
  三個檔都不可以出現憑證。正對照：不掛遮罩的同一段流程，access.log 一定看得到憑證（量具有效）。
"""
import io
import logging
import os
import socket
import subprocess
import sys
import time
import http.client
from pathlib import Path

import pytest

from helpers import log_setup as ls

BACKEND = str(Path(__file__).resolve().parents[1])
SECRETS = ("SECRETPT", "SECRETTOKEN", "SECRETCODE", "AIzaSIMKEY", "TRBKEY123")


# ── 單元 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,want", [
    ("pt=SECRETPT", "***"),
    ("token=SECRETTOKEN&code=SECRETCODE", "***"),                       # 相鄰的遮罩併成一個
    ("v=abc123", "v=***"),                                               # 白名單名字留名、值遮掉
    ("pt=S&v=abc&token=T&page=2", "***&v=***&***&page=***"),
    ("abc123", "***"),                                                   # 沒有 `=` 的裸 token
    ("=SECRET", "***"),
    ("%70t=SECRET", "***"),                                              # 編碼過的名字不在白名單 ⇒ 遮
    ("V=abc", "***"),                                                    # 大小寫不同不算白名單（保守）
    ("", ""),
    ("&&", ""),
])
def test_redact_query_rules(q, want):
    assert ls.redact_query(q) == want


def test_redact_query_is_idempotent():
    once = ls.redact_query("pt=S&v=abc&token=T")
    assert ls.redact_query(once) == once


@pytest.mark.parametrize("target,want", [
    ("/api/x", "/api/x"),                                                # 沒有 query ⇒ 原樣
    ("/api/x?pt=SECRETPT", "/api/x?***"),
    ("/static/a.js?v=1f2e3d", "/static/a.js?v=***"),
    ("/api/x?token=T#frag", "/api/x?***"),
    ("/api/x?", "/api/x"),
])
def test_redact_target(target, want):
    assert ls.redact_target(target) == want
    assert ls.redact_target(ls.redact_target(target)) == want


def test_redact_text_handles_urls_in_sentences():
    t = "outbound failed: https://maps.example.com/geocode?address=A&key=AIzaSIMKEY (retry) and url: /geo/json?address=x&key=TRBKEY123 (Caused by X)"
    out = ls.redact_text(t)
    assert "AIzaSIMKEY" not in out and "TRBKEY123" not in out and "address=A" not in out
    assert "https://maps.example.com/geocode?***" in out and "/geo/json?***" in out
    assert ls.redact_text("沒有問號的訊息") == "沒有問號的訊息"
    assert ls.redact_text("為什麼這樣？不確定 a/b?") == "為什麼這樣？不確定 a/b?"            # 不誤傷一般句子


# ── 過 logging ──────────────────────────────────────────────────────────────

@pytest.fixture()
def redacted_logging():
    """假的 uvicorn.access／root console handler；掛上遮罩，結束拆掉。"""
    root, acc = logging.getLogger(), logging.getLogger("uvicorn.access")
    bufs, added = {}, []
    for name, lg in (("access", acc), ("root", root)):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        lg.addHandler(h)
        bufs[name] = buf
        added.append((lg, h))
    old = (root.level, acc.level, acc.propagate)
    root.setLevel(logging.INFO)
    acc.setLevel(logging.INFO)
    acc.propagate = False
    ls.attach_redact_filter()
    try:
        yield bufs
    finally:
        for lg, h in added:
            lg.removeHandler(h)
            h.removeFilter(ls._REDACT)
        root.setLevel(old[0])
        acc.setLevel(old[1])
        acc.propagate = old[2]


def test_uvicorn_access_line_keeps_only_the_path(redacted_logging):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET",
                                             "/api/print?pt=SECRETPT&token=SECRETTOKEN&code=SECRETCODE&v=abc", "1.1", 200)
    out = redacted_logging["access"].getvalue()
    assert 'GET /api/print?***&v=*** HTTP/1.1" 200' in out
    assert not any(s in out for s in SECRETS)


def test_other_loggers_and_exception_text_are_redacted(redacted_logging):
    lg = logging.getLogger("some.app.module")
    lg.warning("geocode failed https://maps.example.com/api?address=A&key=AIzaSIMKEY")
    try:
        raise ConnectionError("Max retries exceeded with url: /geo/json?address=x&key=TRBKEY123 (Caused by X)")
    except ConnectionError:
        lg.exception("outbound call failed")
    out = redacted_logging["root"].getvalue()
    assert "geocode failed https://maps.example.com/api?***" in out
    assert "ConnectionError" in out and "/geo/json?***" in out                  # traceback 還在，只是網址被遮
    assert not any(s in out for s in SECRETS)


def test_filter_never_raises_on_odd_records(redacted_logging):
    lg = logging.getLogger("uvicorn.access")
    lg.info("short %s", "args")                                                   # 參數數量不是 uvicorn 的形狀
    lg.info("%s", object())
    lg.info("no args at all /x?pt=SECRETPT")
    logging.getLogger("x").info("%d %s", 5, "bad /x?pt=SECRETPT")
    assert "SECRETPT" not in redacted_logging["access"].getvalue() + redacted_logging["root"].getvalue()


def test_validation_error_log_has_no_user_input():
    src = (Path(BACKEND) / "main.py").read_text(encoding="utf-8")
    i = src.index("async def _validation_handler")
    body = src[i:i + 900]
    assert '"input"' in body and '"ctx"' in body and "exc.errors()" in body        # 只留位置與訊息：原值（token／body 密碼）不進日誌
    assert 'logger.warning("Validation error %s %s: %s", request.method, request.url.path, exc.errors())' not in src


def test_main_attaches_the_filter_regardless_of_split():
    src = (Path(BACKEND) / "main.py").read_text(encoding="utf-8")
    a, b = src.index("_log_setup.attach_redact_filter()"), src.index("if _log_setup.enabled_by_environment():")
    assert a < b                                                                  # 分流沒啟用（MOTRIX_FILE_LOGS=0／打不開檔）時也要遮


# ── 端到端：真的 uvicorn ──────────────────────────────────────────────────────

_SIM_APP = r'''
import logging, sys
sys.path.insert(0, %(backend)r)
logging.basicConfig(level=logging.INFO, format="%%(asctime)s %%(levelname)s %%(message)s")
from helpers import log_setup as ls
if %(redact)s:
    ls.attach_redact_filter()
else:
    ls.attach_redact_filter = lambda: None        # 對照組＝舊程式：main.py 不掛、install() 也不會掛
ls.install(%(logdir)r)
log = logging.getLogger("simapp")

async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    log.warning("outbound failed: https://maps.example.com/geocode?address=A&key=AIzaSIMKEY")
    try:
        raise ConnectionError("HTTPSConnectionPool: Max retries exceeded with url: /geo/json?address=x&key=TRBKEY123 (Caused by X)")
    except ConnectionError:
        log.exception("geocode failed")
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})
'''


def _loopback_get(port, target, timeout=5):
    """對自己起的 loopback uvicorn 發 GET。⚠️ 不用 urllib 的 urlopen：conftest 的 NETGUARD 把它換成「記帳＋丟例外」，
    而這裡連的是這一題自己起的 127.0.0.1 子行程（不是對外連線），用 http.client 直接連。"""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", target)
        r = c.getresponse()
        r.read()
        return r.status
    finally:
        c.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _run_real_uvicorn(tmp_path, redact):
    pytest.importorskip("uvicorn")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    (tmp_path / "simapp.py").write_text(_SIM_APP % {"backend": BACKEND, "redact": "True" if redact else "False", "logdir": str(logdir)}, encoding="utf-8")
    port = _free_port()
    server_log = logdir / "server.log"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(tmp_path))
    with open(server_log, "ab") as out:                                         # 跟 autostart.bat 的 `>> logs\server.log 2>&1` 一樣
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "simapp:app", "--host", "127.0.0.1", "--port", str(port)],
                             cwd=str(tmp_path), stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.time() + 40
            while time.time() < deadline:
                if p.poll() is not None:
                    raise AssertionError("uvicorn 提早結束：" + server_log.read_text(encoding="utf-8", errors="replace")[-800:])
                try:
                    _loopback_get(port, "/ready", timeout=2)
                    break
                except Exception:                                               # noqa: BLE001
                    time.sleep(0.3)
            else:
                raise AssertionError("uvicorn 40 秒內沒起來：" + server_log.read_text(encoding="utf-8", errors="replace")[-1500:])
            assert _loopback_get(port, "/ping?pt=SECRETPT&token=SECRETTOKEN&code=SECRETCODE&v=abc123") == 200
            access = logdir / "access.log"
            deadline = time.time() + 15
            while time.time() < deadline and "/ping" not in (access.read_text(encoding="utf-8", errors="replace") if access.exists() else ""):
                time.sleep(0.2)
        finally:
            p.terminate()
            try:
                p.wait(10)
            except Exception:                                                   # noqa: BLE001
                p.kill()
    return {n: (logdir / n).read_text(encoding="utf-8", errors="replace") if (logdir / n).exists() else "" for n in ("server.log", "access.log", "app.log")}


def test_real_uvicorn_no_credential_in_any_log_file(tmp_path):
    logs = _run_real_uvicorn(tmp_path, redact=True)
    assert "/ping" in logs["access.log"], logs                                  # 請求有被記到（不是因為根本沒記才乾淨）
    assert "/ping?***&v=***" in logs["access.log"]
    for name, text in logs.items():
        leaked = [s for s in SECRETS if s in text]
        assert not leaked, "%s 出現憑證 %s：\n%s" % (name, leaked, text[-1500:])
    assert "geocode failed" in logs["app.log"] or "geocode failed" in logs["server.log"]      # 例外有記、只是網址被遮
    assert "ConnectionError" in logs["server.log"]


def test_positive_control_without_the_filter_the_credentials_do_leak(tmp_path):
    """量具有效：不掛遮罩的同一段流程，access.log 一定看得到憑證；否則上一題的「乾淨」不代表什麼。"""
    logs = _run_real_uvicorn(tmp_path, redact=False)
    assert "SECRETPT" in logs["access.log"] and "SECRETTOKEN" in logs["access.log"]
    assert "AIzaSIMKEY" in logs["server.log"] or "AIzaSIMKEY" in logs["app.log"]
