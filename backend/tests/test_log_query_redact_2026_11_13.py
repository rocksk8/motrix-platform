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
import re
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
    ("pt=SECRETPT", "pt=***"),                                           # 名字留、值遮
    ("token=SECRETTOKEN&code=SECRETCODE", "token=***&code=***"),
    ("v=abc123", "v=***"),
    ("type=quote&id=123", "type=***&id=***"),                            # 除錯看得出是哪一類請求（PM 裁示：留名字、遮值）
    ("pt=S&v=abc&token=T&page=2", "pt=***&v=***&token=***&page=***"),
    ("abc123", "***"),                                                   # 沒有 `=` 的裸 token：整段遮
    ("abc123&def456", "***"),                                            # 相鄰的整段遮合併成一個
    ("=SECRET", "***"),
    ("%70t=SECRET", "***"),                                              # 名字有 `%`（編碼過）不當名字留
    ("a" * 41 + "=SECRET", "***"),                                      # 名字太長（像 token 本身）
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig==", "***"),   # JWT 當 key＋`=` 補位
    ("a=%26pt=SECRET", "a=***"),                                         # `%26` 夾帶不會被拆成新參數
    ("", ""),
    ("&&", ""),
])
def test_redact_query_rules(q, want):
    assert ls.redact_query(q) == want
    assert "SECRET" not in ls.redact_query(q)


def test_redact_query_is_idempotent():
    once = ls.redact_query("pt=S&v=abc&token=T")
    assert ls.redact_query(once) == once


@pytest.mark.parametrize("target,want", [
    ("/api/x", "/api/x"),                                                # 沒有 query ⇒ 原樣
    ("/api/x?pt=SECRETPT", "/api/x?pt=***"),
    ("/static/a.js?v=1f2e3d", "/static/a.js?v=***"),
    ("/api/x?token=T#frag", "/api/x?token=***"),
    ("/api/x?", "/api/x"),
])
def test_redact_target(target, want):
    assert ls.redact_target(target) == want
    assert ls.redact_target(ls.redact_target(target)) == want


def test_redact_text_handles_urls_in_sentences():
    t = "outbound failed: https://maps.example.com/geocode?address=A&key=AIzaSIMKEY (retry) and url: /geo/json?address=x&key=TRBKEY123 (Caused by X)"
    out = ls.redact_text(t)
    assert "AIzaSIMKEY" not in out and "TRBKEY123" not in out and "address=A" not in out
    assert "https://maps.example.com/geocode?address=***&key=***" in out and "/geo/json?address=***&key=***" in out
    assert out.endswith("(Caused by X)") and "(retry)" in out                       # 非網址的文字不動
    assert ls.redact_text("沒有問號的訊息") == "沒有問號的訊息"
    assert ls.redact_text("為什麼這樣？不確定 a/b?") == "為什麼這樣？不確定 a/b?"            # 不誤傷一般句子
    assert ls.redact_text("Is it OK? yes?no") == "Is it OK? yes?no"


@pytest.mark.parametrize("text", [
    "GET /api/files/a+b.pdf?token=SECRET failed",                         # hichan-10 L1：路徑裡有 + : @ , = ( ) 也要遮
    "Max retries exceeded with url: /v1/models/x:generateContent?key=SECRET (Caused by X)",
    "calendar /calendars/a@b.com/events?token=SECRET",
    "GET /a/b,c?token=SECRET",
    "GET /a/b(1)?code=SECRET",
    "GET /a/b=c?pt=SECRET",
    "see (https://x.example.com:8443/p?token=SECRET#frag).",              # 括號包著、有埠、有 fragment、句尾標點
    'json {"url": "https://x.example.com/p?token=SECRET"}',
    "uppercase HTTPS://X.EXAMPLE.COM/P?token=SECRET",
    "wss://x.example.com/s?token=SECRET&a=1",
])
def test_redact_text_covers_path_characters_and_shapes(text):
    out = ls.redact_text(text)
    assert "SECRET" not in out, out
    assert "?" in out or "#" not in out


def test_redact_text_masks_url_userinfo():
    out = ls.redact_text("connect failed https://user:SECRETPW@host.example.com:8080/path?x=1 and postgres://u:SECRETPW2@db/x")
    assert "SECRETPW" not in out and "SECRETPW2" not in out
    assert "https://***@host.example.com:8080/path?x=***" in out and "postgres://***@db/x" in out
    assert ls.redact_text("mail me at a@b.com about https://h.example.com/p") == "mail me at a@b.com about https://h.example.com/p"   # 沒有 scheme 的 @ 不動


@pytest.mark.parametrize("make", [
    lambda n: "x " + "/" * n + " ?",
    lambda n: "/-" * (n // 2) + " ?",
    lambda n: "/api/" * (n // 5) + " ?",
    lambda n: "?" * n,
    lambda n: "a/b?" * (n // 4),
    lambda n: "http://" + "a@" * n,
    lambda n: "https://h/p?" + "&".join(["a=1"] * (n // 4)),
])
def test_redact_text_is_linear_and_bounded(make):
    """hichan-10 M1：正則版每個 `/` 都重試一次（O(n²)，16000 個 `/` 要 1 秒以上）；訊息裡有攻擊者可控的解碼路徑（%3F＝? %20＝空白）。
    現在是線性：16000 字元 < 0.5 秒（正則版 ≥ 1 秒；CI 在負載下也夠寬），而且 8 倍長度的輸入不能慢到 32 倍以上。"""
    import time
    t0 = time.perf_counter()
    ls.redact_text(make(16000))
    short = time.perf_counter() - t0
    assert short < 0.5, short
    t0 = time.perf_counter()
    ls.redact_text(make(128000))
    long = time.perf_counter() - t0
    assert long < 5.0, long


def test_very_long_url_token_is_truncated():
    out = ls.redact_text("GET /" + "a" * 10000 + "?token=SECRET")
    assert len(out) < 2200 and "SECRET" not in out and "chars]" in out


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
    assert 'GET /api/print?pt=***&token=***&code=***&v=*** HTTP/1.1" 200' in out
    assert not any(s in out for s in SECRETS)


def test_other_loggers_and_exception_text_are_redacted(redacted_logging):
    lg = logging.getLogger("some.app.module")
    lg.warning("geocode failed https://maps.example.com/api?address=A&key=AIzaSIMKEY")
    try:
        raise ConnectionError("Max retries exceeded with url: /geo/json?address=x&key=TRBKEY123 (Caused by X)")
    except ConnectionError:
        lg.exception("outbound call failed")
    out = redacted_logging["root"].getvalue()
    assert "geocode failed https://maps.example.com/api?address=***&key=***" in out
    assert "ConnectionError" in out and "/geo/json?address=***&key=***" in out                  # traceback 還在，只是網址被遮
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
    assert "/ping?pt=***&token=***&code=***&v=***" in logs["access.log"]
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


# ── 守門：日誌呼叫裡不得出現會帶憑證的寫法 ──────────────────────────────────────────

_LOG_CALL = re.compile(r"""\b(?:logger|logging|log|_log|_req_log|_logger|LOG)\.(?:debug|info|warning|warn|error|exception|critical|log)\(""")
#: 禁止寫進日誌呼叫的東西：整個 request.url（含 query）、query_params／query_string、`url=`／`token=` 等後面接變數或 dict／repr
_BAD_IN_LOG_CALL = [
    (re.compile(r"request\.url\b(?!\.path)"), "request.url（含 query；只能記 request.url.path）"),
    (re.compile(r"\bquery_params\b|\bquery_string\b"), "query_params／query_string"),
    (re.compile(r"""(?i)\b(?:url|uri|token|pt|secret|password|passwd|api_?key|code|authorization|bearer)\s*=\s*(?:%[sdr]|\{|f?["']?\s*\+|[A-Za-z_])"""),
     "url=／token=／secret=／password=／api_key=… 後面接變數"),
    (re.compile(r"""f["'][^"']*\{[^}]*(?i:token|secret|password|api_?key|authorization)[^}]*\}"""), "f-string 插入 token／secret／password"),
    (re.compile(r"://[^/\s\"']*:[^/\s\"'@]*@"), "帶 userinfo 的網址（user:password@host）"),
]
#: 既有、已逐條審過的例外：(檔名片段, 行內容片段) ⇒ 理由。新增例外要寫理由，而且只准減少
_LOG_GUARD_ALLOW = {
    # 回收筒的「token」是 recycle_bin 表的列識別（請求範圍內用來問「這筆暫存資料列有沒有 commit」），不是登入／簽章憑證
    ("helpers/recycle_bin.py", "token=%s"): "回收筒暫存列識別，不是憑證",
}
#: 註：單獨的 `key=` 不在禁止清單——本專案的 `key` 是業務鍵（設定鍵、冪等鍵、權限鍵、登入鎖定鍵＝IP＋帳號），記了不洩漏憑證；
#: 真的憑證要叫 token／secret／password／api_key／authorization，守門認這些名字


def _backend_py_files():
    root = Path(BACKEND)
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if any(part in ("tests", ".venv", "venv", "node_modules", "__pycache__") for part in p.parts) or rel.startswith(("tests/", ".work/")):
            continue
        if "/tests/" in "/" + rel or rel.endswith("conftest.py") or "/tests_" in rel:
            continue
        yield p, rel


def _log_call_statements(text):
    """⇒ [(起始行號, 整個呼叫的文字)]：從 `logger.xxx(` 起、括號配對到結束（跨行）。"""
    out = []
    for m in _LOG_CALL.finditer(text):
        depth, i, n = 0, m.end() - 1, len(text)
        j = i
        while j < n:
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((text.count("\n", 0, m.start()) + 1, text[m.start():j + 1]))
    return out


def test_no_log_call_can_write_a_url_query_or_a_credential_variable():
    hits = []
    n_calls = 0
    for p, rel in _backend_py_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for line, stmt in _log_call_statements(text):
            n_calls += 1
            for rx, why in _BAD_IN_LOG_CALL:
                m = rx.search(stmt)
                if m and not any(a in rel and b in stmt for (a, b) in _LOG_GUARD_ALLOW):
                    hits.append("%s:%d  %s ⇒ %s" % (rel, line, why, stmt.replace("\n", " ")[:160]))
    assert n_calls > 200, "掃到的日誌呼叫太少（%d）⇒ 量法壞了" % n_calls
    assert not hits, "日誌呼叫裡有會帶憑證／整段網址的寫法（請只記 path、不記 query／token；真的需要例外就登記到 _LOG_GUARD_ALLOW 並寫理由）：\n" + "\n".join(hits)


def test_the_log_guard_catches_what_it_should():
    """正對照：量具認得這些壞寫法，也放過正常寫法。"""
    bad = [
        'logger.warning("fail %s", request.url)',
        'logger.info("q=%s", request.query_params)',
        'logger.warning("GET url=%s failed", url)',
        'logger.error("token=%s", tok)',
        'logger.warning(f"bad {token}")',
        'logger.error("connect https://u:pw@host/x")',
        'log.info("params=%r api_key=%s", params, k)',
    ]
    good = [
        'logger.warning("Validation error %s %s", request.method, request.url.path)',
        'logger.info("loaded %d rows", n)',
        'logger.error("card %s has no href", card_id)',
    ]
    for s in bad:
        stmts = _log_call_statements(s)
        assert stmts and any(rx.search(stmts[0][1]) for rx, _ in _BAD_IN_LOG_CALL), s
    for s in good:
        stmts = _log_call_statements(s)
        assert stmts and not any(rx.search(stmts[0][1]) for rx, _ in _BAD_IN_LOG_CALL), s
