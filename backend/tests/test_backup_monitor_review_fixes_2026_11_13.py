# -*- coding: utf-8 -*-
"""「備份與監控」頁的對抗式審查修補（2026-11-13；審查者 hichan-11：1 High／4 Medium／5 Low）。

每一題都對應審查報告的一條，且用**審查者的同款探針**驗：
- H1 轉址：本機起兩台真的伺服器，A 回 3xx 指向 B；`safe_ping.get`、測試心跳、`heartbeat_job._http_get`（正式機上現成的程式）都不准去打 B。
- M1 位址檢查：IPv4 對映／6to4／Teredo／NAT64、`127.1`／`2130706433`／`0x7f.0.0.1`／`0`、尾端的點、`.localhost`、單標籤名、帳密、非 80／443 埠；
  解析後混著內網位址的答案；連線釘在檢查過的 IP（解析只做一次）。
- M2 `scrub_paths`：含空白、中文、UNC、相對路徑、單段 `/data` 全遮。
- M3 備份互斥：跨行程檔案鎖、行程死掉鎖自動放掉、`_daily_tick`／`_weekly_tick`／`backup_job.py`／立即備份互相讓。
- M4 心跳網址：換網址一定寄信＋稽核；停用要原因，多位最高管理者時要第二人核准、申請人不能核准自己的。
- L1～L5：時間戳只在執行緒啟動後才寫、時鐘倒退仍擋、稽核失敗不回 500、今天已備份的白話訊息、整體時限。
另外：`heartbeat_job` 的 log 只有主機名＋狀態碼／例外類別，不含網址（密鑰在路徑裡）。
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import helpers.email_notify as en

_MAKE_USER_DEFAULT_ROLE = "superadmin"
BACKEND = Path(__file__).resolve().parents[1]
SECRET = "https://hc-ping.example.com/SECRET-UUID-9999"
loopback_net = pytest.mark.allow_outbound


# ── 共用夾具 ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """safe_ping 走 http.client，conftest 的 `_netguard` 攔不到它；這裡自己守：只准連 127.0.0.1，連別處＝那一題紅。
    網域解析預設回公開位址（假的），寄信一律記下來不寄。"""
    from core import safe_ping
    real = safe_ping._connect_pinned

    def guarded(conn, ip, timeout):
        assert ip.startswith("127."), "測試不准連到 %s" % ip
        return real(conn, ip, timeout)
    monkeypatch.setattr(safe_ping, "_connect_pinned", guarded)
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["93.184.216.34"])
    mails = []
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: (mails.append((key, kw)), True)[1])
    return mails


@pytest.fixture()
def mails(_no_real_network):
    return _no_real_network


@pytest.fixture()
def hb_cfg(monkeypatch, tmp_path):
    from core import paths
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "heartbeat_config.json"))
    return tmp_path / "heartbeat_config.json"


@pytest.fixture()
def fresh(monkeypatch):
    from helpers import backup_monitor as bm
    monkeypatch.setitem(bm._hb_last, "at", 0.0)
    monkeypatch.setitem(bm._running, "on", False)
    bm._set_setting(bm._LAST_KEY, "")                                  # 資料庫在同一支測試檔裡是共用的：上一題的時間戳不能影響這一題
    yield bm
    bm._set_setting(bm._LAST_KEY, "")


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


class _Srv:
    """本機 HTTP 伺服器；`script(path)` ⇒ (status, headers)。記下每次被打的 (path, Host)。"""

    def __init__(self, script):
        self.hits = []
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                srv.hits.append((self.path, self.headers.get("Host", "")))
                code, headers = script(self.path)
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def servers():
    made = []

    def make(script):
        s = _Srv(script)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


@pytest.fixture()
def local_target(monkeypatch):
    """讓 safe_ping 可以連本機測試伺服器：假解析到 127.0.0.1、放行該位址與埠。回 `allow(*servers)`。"""
    from core import safe_ping
    monkeypatch.setattr(safe_ping, "ip_is_public", lambda ip: True)
    calls = []

    def fake_resolve(host, port):
        calls.append((host, port))
        return ["127.0.0.1"]
    monkeypatch.setattr(safe_ping, "resolve_host", fake_resolve)

    def allow(*srvs):
        monkeypatch.setattr(safe_ping, "ALLOWED_PORTS", (80, 443) + tuple(s.port for s in srvs))
        return calls
    return allow


# ══ M1：位址檢查 ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_are_public(ip):
    from core import safe_ping
    assert safe_ping.ip_is_public(ip) is True


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.8.8.8", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.0.1", "169.254.169.254", "100.64.0.1", "100.127.255.254",
    "224.0.0.1", "239.255.255.250", "240.0.0.1", "255.255.255.255", "0.0.0.0", "192.0.2.1", "198.18.0.1",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "2002:7f00:0001::", "2002:0a00:0001::", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "garbage",
])
def test_non_public_addresses_are_rejected(ip):
    from core import safe_ping
    assert safe_ping.ip_is_public(ip) is False


@pytest.mark.parametrize("url", [
    "https://hc-ping.com/abc", "http://hc-ping.com/abc", "https://hc-ping.com:443/abc", "http://hc-ping.com:80/abc", "https://hc-ping.com./abc",
    "https://HC-PING.COM/abc", "https://93.184.216.34/abc", "https://[2606:4700:4700::1111]/abc", "https://hc-ping.com/a?b=c&d=e",
])
def test_check_url_accepts_ordinary_public_urls(url):
    from core import safe_ping
    scheme, host, port = safe_ping.check_url(url)
    assert scheme in ("http", "https") and not host.endswith(".") and port in (80, 443)


@pytest.mark.parametrize("url", [
    "https://localhost/x", "https://LOCALHOST./x", "https://localhost.:443/x", "https://a.localhost/x", "https://a.b.localhost./x",
    "https://127.0.0.1/x", "https://127.1/x", "https://2130706433/x", "https://0x7f.0.0.1/x", "https://0x7f000001/x", "https://0/x",
    "https://017700000001/x", "https://0177.0.0.1/x", "https://10.0.0.5/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/x",
    "https://[::ffff:7f00:1]/x", "https://[::ffff:127.0.0.1]/x", "https://[fe80::1]/x",
    "https://intranet/x", "https://nas/x", "https://nas.local/x", "https://metadata.google.internal/x", "https://printer.lan/x", "https://x.home.arpa/x",
    "https://hc-ping.com@127.0.0.1/x", "https://user:pw@hc-ping.com/x", "https://127.0.0.1@hc-ping.com/x", "https://@hc-ping.com/x",
    "https://hc-ping.com:8080/x", "https://hc-ping.com:22/x", "https://hc-ping.com:6379/x", "https://hc-ping.com:0/x", "https://hc-ping.com:abc/x",
    "ftp://hc-ping.com/x", "file:///etc/passwd", "gopher://hc-ping.com/x", "https://", "hc-ping.com/x", "", "https://.",
])
def test_check_url_rejects_dangerous_forms_with_a_plain_reason(url):
    from core import safe_ping
    with pytest.raises(safe_ping.UnsafeTarget) as ei:
        safe_ping.check_url(url)
    assert any("\u4e00" <= c <= "\u9fff" for c in ei.value.reason)


def test_public_addresses_rejects_mixed_answers_and_mapped_ipv6(monkeypatch):
    from core import safe_ping
    for answer in (["93.184.216.34", "127.0.0.1"], ["10.0.0.5"], ["::ffff:127.0.0.1"], ["::1", "93.184.216.34"], ["169.254.169.254"]):
        monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p, a=answer: a)
        with pytest.raises(safe_ping.UnsafeTarget):
            safe_ping.public_addresses("hc-ping.com", 443)
    monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: ["93.184.216.34", "2606:4700:4700::1111"])
    assert safe_ping.public_addresses("hc-ping.com", 443) == ["93.184.216.34", "2606:4700:4700::1111"]


def test_public_addresses_dns_failure_is_a_dns_failure(monkeypatch):
    from core import safe_ping

    def boom(h, p):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(safe_ping, "resolve_host", boom)
    with pytest.raises(safe_ping.PingFailed) as ei:
        safe_ping.public_addresses("nope.example.com", 443)
    assert ei.value.kind == "dns" and not isinstance(ei.value, safe_ping.UnsafeTarget)
    monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: [])
    with pytest.raises(safe_ping.PingFailed):
        safe_ping.public_addresses("nope.example.com", 443)


def test_save_time_check_resolves_the_name_and_rejects_internal_answers(client, make_user, hb_cfg, monkeypatch):
    from core import safe_ping
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    h = _login(client, make_user, "m1_sa")
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["10.0.0.7"])        # 名字看起來正常、解析出來是內網
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": "https://sneaky.example.com/x"})
    assert r.status_code == 422 and "內網" in r.json()["detail"]
    assert json.loads(hb_cfg.read_text(encoding="utf-8"))["ping_url"] == SECRET
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["93.184.216.34", "127.0.0.1"])
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": "https://mixed.example.com/x"}).status_code == 422


def test_save_time_check_lets_an_unresolvable_name_through(client, make_user, hb_cfg, monkeypatch):
    """離線／DNS 暫時壞掉也要存得下去；真正連線前（測試心跳、心跳排程）會再檢查一次。"""
    from core import safe_ping

    def boom(host, port):
        raise socket.gaierror("temporary failure")
    monkeypatch.setattr(safe_ping, "resolve_host", boom)
    h = _login(client, make_user, "m1_sa2")
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200


def test_test_heartbeat_resolves_again_at_test_time(client, make_user, hb_cfg, fresh, monkeypatch):
    """存的時候是公開位址、測的時候 DNS 被換成內網（DNS rebinding）⇒ 測試心跳拒絕，不連。"""
    from core import safe_ping
    h = _login(client, make_user, "m1_sa3")
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200
    monkeypatch.setattr(safe_ping, "resolve_host", lambda host, port: ["169.254.169.254"])
    r = client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is False and "內網" in r.json()["message"]


# ══ H1：不跟隨轉址；連線釘在檢查過的 IP；只准 80／443；整體時限 ═══════════════════════

@loopback_net
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_get_does_not_follow_redirects(servers, local_target, code):
    from core import safe_ping
    target = servers(lambda p: (200, {}))
    first = servers(lambda p: (code, {"Location": "http://127.0.0.1:%d/internal-admin" % target.port}))
    local_target(first, target)
    with pytest.raises(safe_ping.RedirectBlocked) as ei:
        safe_ping.get("http://hc-ping.example.com:%d/ping/SECRET-UUID" % first.port)
    assert ei.value.status == code and "SECRET" not in str(ei.value)
    assert len(first.hits) == 1 and target.hits == []


@loopback_net
def test_get_returns_status_for_non_redirects(servers, local_target):
    from core import safe_ping
    srv = servers(lambda p: (200, {}) if p.startswith("/ok") else (404, {}))
    local_target(srv)
    assert safe_ping.get("http://hc-ping.example.com:%d/ok?x=1" % srv.port) == 200
    assert safe_ping.get("http://hc-ping.example.com:%d/missing" % srv.port) == 404
    assert srv.hits[0][0] == "/ok?x=1"                                 # 路徑與查詢字串原樣送出


@loopback_net
def test_get_resolves_once_and_connects_to_the_checked_ip_keeping_the_host_header(servers, local_target):
    """DNS rebinding：解析只做一次，連線用那一次的結果；Host 標頭仍是原主機名（TLS 的 SNI／憑證比對同理）。"""
    from core import safe_ping
    srv = servers(lambda p: (200, {}))
    calls = local_target(srv)
    assert safe_ping.get("http://pinned.example.com:%d/x" % srv.port) == 200
    assert calls == [("pinned.example.com", srv.port)]
    assert srv.hits[0][1] == "pinned.example.com:%d" % srv.port


@loopback_net
def test_get_never_connects_when_the_answer_is_internal(servers, monkeypatch):
    from core import safe_ping
    srv = servers(lambda p: (200, {}))
    monkeypatch.setattr(safe_ping, "ALLOWED_PORTS", (80, 443, srv.port))
    monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: ["127.0.0.1"])             # ip_is_public 沒被放寬
    with pytest.raises(safe_ping.UnsafeTarget):
        safe_ping.get("http://evil.example.com:%d/x" % srv.port)
    assert srv.hits == []


@loopback_net
def test_get_refuses_ports_other_than_80_and_443(servers, local_target):
    from core import safe_ping
    srv = servers(lambda p: (200, {}))
    local_target()                                                                          # 沒把測試埠加進允許清單
    with pytest.raises(safe_ping.UnsafeTarget):
        safe_ping.get("http://hc-ping.example.com:%d/x" % srv.port)
    assert srv.hits == []


@loopback_net
def test_get_has_an_overall_deadline_against_slow_drip_responses(local_target, monkeypatch):
    """L5：對方慢慢滴水（每秒一個位元組，永遠不結束標頭）⇒ 整體時限一到就強制關線，不會拖到逐次讀取的逾時。"""
    from core import safe_ping
    stop = threading.Event()
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(5)
    port = lsock.getsockname()[1]

    def drip():
        lsock.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = lsock.accept()
            except OSError:
                continue
            try:
                c.recv(4096)
                for b in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 200:
                    if stop.is_set():
                        break
                    c.sendall(bytes([b]))
                    time.sleep(0.5)
            except OSError:
                pass
            finally:
                c.close()
    t = threading.Thread(target=drip, daemon=True)
    t.start()
    try:
        monkeypatch.setattr(safe_ping, "ALLOWED_PORTS", (80, 443, port))
        monkeypatch.setattr(safe_ping, "ip_is_public", lambda ip: True)
        monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: ["127.0.0.1"])
        t0 = time.monotonic()
        with pytest.raises(safe_ping.PingFailed):
            safe_ping.get("http://slow.example.com:%d/x" % port, timeout=10, deadline=1.5)
        assert time.monotonic() - t0 < 6, "整體時限沒有生效（被逐次讀取的逾時拖住）"
    finally:
        stop.set()
        lsock.close()


def test_error_messages_never_contain_the_url(monkeypatch):
    from core import safe_ping
    monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: ["10.0.0.1"])
    with pytest.raises(safe_ping.UnsafeTarget) as ei:
        safe_ping.get("https://hc-ping.example.com/SECRET-UUID/fail")
    assert "SECRET" not in str(ei.value) and "hc-ping" not in str(ei.value)


# ── 心跳排程（獨立行程；正式機現成的程式）────────────────────────────────────────

def _hb_module(monkeypatch, tmp_path):
    from core import paths
    logs = tmp_path / "hblogs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    sys.modules.pop("heartbeat_job", None)
    import heartbeat_job
    return heartbeat_job


@loopback_net
def test_heartbeat_job_external_ping_does_not_follow_redirects(servers, local_target, monkeypatch, tmp_path):
    target = servers(lambda p: (200, {}))
    first = servers(lambda p: (302, {"Location": "http://127.0.0.1:%d/internal" % target.port}))
    local_target(first, target)
    hb = _hb_module(monkeypatch, tmp_path)
    try:
        assert hb._http_get("http://hc-ping.example.com:%d/uuid" % first.port) is False
        assert len(first.hits) == 1 and target.hits == []
    finally:
        sys.modules.pop("heartbeat_job", None)


@loopback_net
def test_heartbeat_job_local_probe_does_not_follow_redirects_either(servers, monkeypatch, tmp_path):
    target = servers(lambda p: (200, {}))
    first = servers(lambda p: (302, {"Location": "http://127.0.0.1:%d/internal" % target.port}))
    hb = _hb_module(monkeypatch, tmp_path)
    try:
        assert hb._http_get("http://127.0.0.1:%d/api/ping" % first.port) is False
        assert target.hits == []
    finally:
        sys.modules.pop("heartbeat_job", None)


@loopback_net
def test_heartbeat_job_local_probe_still_works(servers, monkeypatch, tmp_path):
    ok = servers(lambda p: (200, {}))
    hb = _hb_module(monkeypatch, tmp_path)
    try:
        assert hb._http_get("http://127.0.0.1:%d/api/ping" % ok.port) is True
    finally:
        sys.modules.pop("heartbeat_job", None)


def test_heartbeat_job_refuses_internal_ping_url(monkeypatch, tmp_path):
    """設定檔被改成內網位址（手動編輯）⇒ 排程也不打。"""
    hb = _hb_module(monkeypatch, tmp_path)
    try:
        assert hb._http_get("https://169.254.169.254/latest/meta-data/") is False
        assert hb._http_get("https://metadata.internal/x") is False
        assert hb._http_get("https://hc-ping.com:8080/x") is False
    finally:
        sys.modules.pop("heartbeat_job", None)


@pytest.mark.parametrize("mode", ["connect_error", "http_500", "unsafe", "exception_text_has_url"])
def test_heartbeat_job_log_has_host_and_reason_but_never_the_url(monkeypatch, tmp_path, caplog, mode):
    """PM：`logger.warning("GET %s failed", url)` 把完整網址（healthchecks 的密鑰在路徑裡）寫進 heartbeat_job.log。
    改成只記主機名＋狀態碼或例外類別。"""
    import logging
    from core import safe_ping
    hb = _hb_module(monkeypatch, tmp_path)
    url = "https://hc-ping.example.com/SECRET-UUID-9999/fail?token=TOPSECRET"

    def fake_get(u, **k):
        if mode == "connect_error":
            raise safe_ping.PingFailed("connect")
        if mode == "http_500":
            return 500
        if mode == "unsafe":
            raise safe_ping.UnsafeTarget("x")
        raise OSError("failed to reach %s" % u)
    monkeypatch.setattr(safe_ping, "get", fake_get)
    try:
        with caplog.at_level(logging.DEBUG, logger="heartbeat_job"):
            assert hb._http_get(url) is False
    finally:
        sys.modules.pop("heartbeat_job", None)
    text = caplog.text
    assert "hc-ping.example.com" in text
    assert "SECRET" not in text and "TOPSECRET" not in text and "/fail" not in text and "token" not in text
    if mode == "http_500":
        assert "500" in text
    else:
        assert {"connect_error": "PingFailed", "unsafe": "UnsafeTarget", "exception_text_has_url": "OSError"}[mode] in text


def test_heartbeat_job_source_never_logs_a_raw_url_and_never_calls_urlopen():
    import ast
    src = (BACKEND / "heartbeat_job.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    urlopens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "urlopen"]
    assert not urlopens, "對外請求不准再直接 urlopen（會跟著轉址）"
    for n in ast.walk(tree):                                           # 任何 logger.* 呼叫的引數都不能直接帶 url／ping_url 變數
        if isinstance(n, ast.Call) and getattr(n.func, "value", None) is not None and getattr(n.func.value, "id", "") == "logger":
            for a in n.args[1:]:
                assert not (isinstance(a, ast.Name) and a.id in ("url", "ping_url")), "log 不准直接帶網址（密鑰在路徑裡）：行 %d" % n.lineno


# ══ M2：scrub_paths ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,gone,kept", [
    (r"失敗 C:\Users\Jane Doe\Google Drive\MOTRIX\a.db。下一句", ("Jane", "Doe", "Drive", "MOTRIX", "a.db"), "下一句"),
    (r"copy to C:\Program Files (x86)\Acme Corp\y.db: access denied", ("Program", "Acme", "y.db"), "access denied"),
    (r"路徑 G:\我的雲端硬碟\備份 2026\x 失敗", ("我的雲端硬碟", "備份", "2026"), "路徑"),
    (r"\\nas01\share dir\x y.db 無法存取", ("nas01", "share", "x y"), ""),
    (r"relative backend\db_backups\a.db failed", ("backend", "db_backups", "a.db"), "relative"),
    (r"relative backend\my backups\a b.db; next", ("backend", "my backups", "a b"), "next"),
    ("mount /data not found", ("/data",), "not found"),
    ("see /home/jane/x.db now", ("jane", "x.db"), "now"),
    ("相對 data/db_backups/a.db 失敗", ("db_backups", "a.db"), "失敗"),
    ("檔案 ../data/a.db", ("data", "a.db"), "檔案"),
    ("存到 data/a.db 了", ("a.db",), "了"),
    ("~/backups/motrix/x.db", ("motrix", "backups"), ""),
    (r"file:///C:/Users/Jane Doe/x.txt end", ("Jane", "x.txt"), ""),
])
def test_scrub_paths_masks_spaces_relative_unc_and_single_segment(raw, gone, kept):
    from helpers.backup_monitor import scrub_paths
    out = scrub_paths(raw)
    assert "路徑已隱藏" in out
    for g in gone:
        assert g not in out, (raw, out)
    if kept:
        assert kept in out, (raw, out)


@pytest.mark.parametrize("text", ["2026/11/13 備份完成", "n/a", "50/50", "A/B 測試", "已經超過 36 小時沒有備份（含 1/2 比例）", "是/否", "and/or", "備份成功。", ""])
def test_scrub_paths_leaves_ordinary_text_alone(text):
    from helpers.backup_monitor import scrub_paths
    assert scrub_paths(text) == text


def test_alerts_block_masks_spaced_paths_end_to_end(client, make_user, monkeypatch, tmp_path):
    from core import paths
    d = tmp_path / "alertdir"
    d.mkdir()
    monkeypatch.setattr(paths, "BACKUP_ALERT_DIR", str(d))
    (d / "BACKUP_ALERT.txt").write_text("原因:雲端路徑不可用 C:\\Users\\Jane Doe\\Google Drive\\MOTRIX\\備份。請檢查\n", encoding="utf-8")
    h = _login(client, make_user, "m2_sa")
    body = client.get("/api/system/backup-monitor", headers=h).text
    assert "Jane" not in body and "Google Drive" not in body and "MOTRIX" not in body


# ══ M3：備份互斥 ═══════════════════════════════════════════════════════════════

@pytest.fixture()
def lock_dir(monkeypatch, tmp_path):
    from core import paths
    d = tmp_path / "locklogs"
    d.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", str(d))
    return d


def test_lock_is_exclusive_within_a_process_and_reusable(lock_dir):
    import archive
    with archive.backup_run_lock():
        with pytest.raises(archive.BackupInProgress):
            with archive.backup_run_lock():
                pytest.fail("不該進得來")
    with archive.backup_run_lock():
        pass


_HOLDER = r'''
import os, sys, time
path = sys.argv[1]
fh = open(path, "a+b")
fh.seek(0)
if os.name == "nt":
    import msvcrt
    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
print("held", flush=True)
sys.stdin.read()
'''


def test_lock_excludes_another_process_and_dies_with_it(lock_dir):
    """跨行程：另一個行程（模擬排程的 backup_job.py）持有鎖時這裡拿不到；那個行程被強制終止後鎖自動放掉（不需要過期時間）。"""
    import archive
    path = archive._backup_lock_path()
    p = subprocess.Popen([sys.executable, "-I", "-c", _HOLDER, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held"
        with pytest.raises(archive.BackupInProgress):
            with archive.backup_run_lock():
                pytest.fail("另一個行程持有鎖，不該進得來")
    finally:
        p.kill()
        p.wait(10)
    end = time.time() + 5
    while True:
        try:
            with archive.backup_run_lock():
                break
        except archive.BackupInProgress:
            assert time.time() < end, "行程死掉後鎖沒有放掉"
            time.sleep(0.1)


def _unopenable(monkeypatch):
    real_open = open

    def fake_open(file, *a, **k):
        if str(file).endswith("backup_run.lock"):
            raise PermissionError("denied")
        return real_open(file, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)


def test_scheduled_backup_with_unopenable_lock_file_still_runs_but_logs_error_and_raises_an_alert(lock_dir, monkeypatch, caplog):
    """審查 N4／PM：鎖檔打不開時排程備份照常跑（不能因此整天沒備份），但不安靜降級：記 ERROR、寫系統告警（同一行程只寫一次）。"""
    import logging
    import archive
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda reason, level="WARN": alerts.append((reason, level)))
    monkeypatch.setitem(archive._LOCK_ALERTED, "on", False)
    _unopenable(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="archive"):
        with archive.backup_run_lock():
            with pytest.raises(archive.BackupInProgress):          # 同行程的互斥還在
                with archive.backup_run_lock():
                    pass
        with archive.backup_run_lock():
            pass
    assert len(alerts) == 1 and alerts[0][1] == "ERROR" and "鎖檔" in alerts[0][0]
    assert "鎖檔打不開" in caplog.text


def test_manual_backup_is_refused_when_the_lock_file_cannot_be_opened(client, make_user, fresh, lock_dir, monkeypatch):
    import archive
    called = []
    monkeypatch.setattr(archive, "_daily_backup", lambda: called.append(1))
    _unopenable(monkeypatch)
    with pytest.raises(archive.BackupLockUnavailable):
        with archive.backup_run_lock(strict=True):
            pass
    h = _login(client, make_user, "n4_sa")
    r = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
    assert r.status_code == 503 and "無法確認" in r.json()["detail"] and "權限" in r.json()["detail"]
    assert called == [] and fresh._running["on"] is False
    assert (fresh._get_setting(fresh._LAST_KEY, "") or "") == ""
    monkeypatch.undo()
    with archive.backup_run_lock():                                    # 嚴格模式失敗後執行緒鎖有放掉
        pass


def test_daily_and_weekly_ticks_yield_to_a_running_backup(lock_dir, monkeypatch):
    import archive
    calls = []
    monkeypatch.setattr(archive, "_daily_backup", lambda: calls.append("daily"))
    monkeypatch.setattr(archive, "_weekly_backup", lambda: calls.append("weekly"))
    monkeypatch.setattr(archive, "_cleanup_sessions", lambda: calls.append("sessions"))
    timers = []
    monkeypatch.setattr(archive, "_start_timer", lambda sec, fn: timers.append(fn))
    with archive.backup_run_lock():
        archive._daily_tick()
        archive._weekly_tick()
    assert calls == [] and len(timers) == 2                       # 讓出去，但下一輪照排
    archive._daily_tick()
    archive._weekly_tick()
    assert calls == ["daily", "sessions", "weekly"]


def test_manual_backup_and_scheduled_tick_never_overlap(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive
    gate = threading.Event()
    running = []
    peak = [0]

    def daily():
        running.append(1)
        peak[0] = max(peak[0], len(running))
        gate.wait(10)
        running.pop()
    monkeypatch.setattr(archive, "_daily_backup", daily)
    monkeypatch.setattr(archive, "_weekly_backup", lambda: None)
    monkeypatch.setattr(archive, "_cleanup_sessions", lambda: None)
    monkeypatch.setattr(archive, "_start_timer", lambda s, f: None)
    bm.run_backup_now()
    try:
        end = time.time() + 5
        while not running and time.time() < end:
            time.sleep(0.02)
        archive._daily_tick()                                      # 排程的這一輪撞上手動備份 ⇒ 略過
        assert peak[0] == 1
    finally:
        gate.set()
        end = time.time() + 10
        while bm._running["on"] and time.time() < end:
            time.sleep(0.02)
    assert not bm._running["on"]
    with archive.backup_run_lock():                                 # 手動備份結束後鎖已放掉
        pass


def test_manual_backup_is_busy_when_another_process_holds_the_lock(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive
    called = []
    monkeypatch.setattr(archive, "_daily_backup", lambda: called.append(1))
    path = archive._backup_lock_path()
    p = subprocess.Popen([sys.executable, "-I", "-c", _HOLDER, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held"
        with pytest.raises(bm.BackupBusy):
            bm.run_backup_now()
        assert bm._running["on"] is False and called == []
        assert (bm._get_setting(bm._LAST_KEY, "") or "") == "", "沒有真的開始，不該蓋 30 分鐘限制的時間戳"
    finally:
        p.kill()
        p.wait(10)


def test_busy_message_is_plain(client, make_user, fresh, lock_dir, monkeypatch):
    import archive
    h = _login(client, make_user, "m3_sa")
    with archive.backup_run_lock():
        r = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
    assert r.status_code == 409 and "已有備份在進行中" in r.json()["detail"]


def _run_backup_job(monkeypatch, tmp_path, lock_busy=False, daily_raises=False):
    import runpy
    import types
    from core import paths
    logs = tmp_path / "bjlogs"
    logs.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "LOGS_DIR", str(logs))
    calls = []

    class InProgress(Exception):
        pass

    class Lock:
        def __enter__(self):
            if lock_busy:
                raise InProgress()
            return self

        def __exit__(self, *a):
            calls.append("unlock")
            return False

    def daily():
        calls.append("daily")
        if daily_raises:
            raise RuntimeError("boom")
    stub = types.ModuleType("archive")
    stub.BackupInProgress = InProgress
    stub.backup_run_lock = Lock
    stub._daily_backup = daily
    stub._weekly_backup = lambda: calls.append("weekly")
    monkeypatch.setitem(sys.modules, "archive", stub)
    with pytest.raises(SystemExit) as ei:
        runpy.run_path(str(BACKEND / "backup_job.py"), run_name="__main__")
    return ei.value.code, calls


def test_backup_job_runs_both_inside_the_lock(monkeypatch, tmp_path):
    code, calls = _run_backup_job(monkeypatch, tmp_path)
    assert code == 0 and calls == ["daily", "weekly", "unlock"]


def test_backup_job_skips_quietly_when_a_backup_is_already_running(monkeypatch, tmp_path):
    code, calls = _run_backup_job(monkeypatch, tmp_path, lock_busy=True)
    assert code == 0 and calls == []


def test_backup_job_weekly_still_runs_when_daily_fails_and_exit_code_is_1(monkeypatch, tmp_path):
    code, calls = _run_backup_job(monkeypatch, tmp_path, daily_raises=True)
    assert code == 1 and calls == ["daily", "weekly", "unlock"]


# ══ L1～L4 ═══════════════════════════════════════════════════════════════════

def test_stamp_is_written_only_after_the_thread_really_started(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive

    class Boom:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(bm.threading, "Thread", Boom)
    with pytest.raises(RuntimeError):
        bm.run_backup_now()
    assert (bm._get_setting(bm._LAST_KEY, "") or "") == ""          # 啟動失敗不鎖使用者 30 分鐘
    assert bm._running["on"] is False
    with archive.backup_run_lock():                                  # 鎖也放掉了
        pass


def test_clock_moved_back_is_still_rate_limited(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive
    monkeypatch.setattr(archive, "_daily_backup", lambda: None)
    monkeypatch.setattr(archive, "_weekly_backup", lambda: None)
    now = datetime.now()
    bm._set_setting(bm._LAST_KEY, (now + timedelta(minutes=10)).isoformat(timespec="seconds"))      # 上次啟動在「未來」＝時鐘被往回撥
    with pytest.raises(bm.BackupRateLimited) as ei:
        bm.run_backup_now(now)
    assert ei.value.wait_seconds >= bm.RUN_MIN_INTERVAL_SECONDS
    assert bm._wait_after((now + timedelta(minutes=10)).isoformat(), now) > 0
    # 倒退超過 1 天＝時鐘被重設：記錄無效，不會把備份鈕卡死
    assert bm._wait_after((now + timedelta(days=3)).isoformat(), now) == 0
    assert bm._wait_after("garbage", now) == 0 and bm._wait_after("", now) == 0
    assert bm._wait_after((now - timedelta(minutes=29)).isoformat(), now) > 0
    assert bm._wait_after((now - timedelta(minutes=31)).isoformat(), now) == 0
    # 狀態頁顯示的等待時間用同一個函式
    assert bm.status()["manual"]["waitSeconds"] >= bm.RUN_MIN_INTERVAL_SECONDS


def test_audit_failure_after_the_action_is_not_a_500(client, make_user, hb_cfg, fresh, lock_dir, monkeypatch):
    import archive
    from routers import backup_monitor as rt
    monkeypatch.setattr(archive, "_daily_backup", lambda: None)
    monkeypatch.setattr(archive, "_weekly_backup", lambda: None)

    def boom(*a, **k):
        raise RuntimeError("audit db locked")
    monkeypatch.setattr(rt, "_audit", boom)
    monkeypatch.setattr(fresh, "_ping", lambda u: (True, "監控服務有收到這次打卡。"))
    h = _login(client, make_user, "l3_sa")
    r = client.post("/api/system/backup-monitor/backup-now", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["ok"] is True                      # 備份已經開始，不能回 500 讓人重按
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200
    assert client.post("/api/system/backup-monitor/heartbeat-test", headers=h, json={"confirm": True}).status_code == 200


def test_already_done_today_says_so(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive
    monkeypatch.setattr(archive, "_daily_backup", lambda: None)
    monkeypatch.setattr(archive, "_weekly_backup", lambda: None)
    monkeypatch.setattr(bm, "_daily_already_done", lambda: True)
    bm.run_backup_now()
    end = time.time() + 10
    while bm._running["on"] and time.time() < end:
        time.sleep(0.02)
    last = bm.status()["manual"]["lastResult"]
    assert last["ok"] is True and last["message"] == bm.MSG_ALREADY_DONE and "沒有重做" in last["message"]


def test_normal_run_says_done(fresh, lock_dir, monkeypatch):
    bm = fresh
    import archive
    monkeypatch.setattr(archive, "_daily_backup", lambda: None)
    monkeypatch.setattr(archive, "_weekly_backup", lambda: None)
    monkeypatch.setattr(bm, "_daily_already_done", lambda: False)
    bm.run_backup_now()
    end = time.time() + 10
    while bm._running["on"] and time.time() < end:
        time.sleep(0.02)
    assert bm.status()["manual"]["lastResult"]["message"] == "完成"


# ══ M4：換網址要通知；停用要原因＋第二人核准 ════════════════════════════════════════

def _cfg_url(p):
    return json.loads(p.read_text(encoding="utf-8")).get("ping_url")


def _audit_actions(*actions):
    import db
    conn = db.get_db()
    try:
        ph = ",".join("?" * len(actions))
        return conn.execute("SELECT action, target_label, detail FROM audit_log WHERE action IN (%s) ORDER BY id" % ph, list(actions)).fetchall()
    finally:
        conn.close()


@pytest.fixture()
def only_me(monkeypatch):
    """把其他在職最高管理者暫時停用，測「只有一位」的路徑；測完還原。"""
    import db
    changed = []

    def go(username):
        conn = db.get_db()
        try:
            rows = conn.execute("SELECT id FROM users WHERE role='superadmin' AND active=1 AND username<>?", (username,)).fetchall()
            for r in rows:
                conn.execute("UPDATE users SET active=0 WHERE id=?", (r[0],))
                changed.append(r[0])
            conn.commit()
        finally:
            conn.close()
    yield go
    conn = db.get_db()
    try:
        for i in changed:
            conn.execute("UPDATE users SET active=1 WHERE id=?", (i,))
        conn.commit()
    finally:
        conn.close()


def test_changing_the_url_mails_every_superadmin_and_audits_old_and_new_host(client, make_user, hb_cfg, mails):
    hb_cfg.write_text(json.dumps({"ping_url": "https://hc-ping.example.com/OLD-SECRET"}), encoding="utf-8")
    h = _login(client, make_user, "m4_sa")
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET})
    assert r.status_code == 200 and r.json()["changed"] is True and "SECRET" not in r.text
    assert len(mails) == 1
    key, kw = mails[0]
    assert key == "heartbeat_stale" and kw["to_group"] is True
    blob = json.dumps(kw, ensure_ascii=False, default=str)
    assert "hc-ping.example.com" in blob and "SECRET" not in blob
    (row,) = _audit_actions("system.heartbeat_url_set")
    assert "SECRET" not in (row[1] + row[2]) and "oldHost" in row[2] and "hc-ping.example.com" in row[2]


def test_first_time_setting_also_mails_and_same_url_does_not(client, make_user, hb_cfg, mails):
    h = _login(client, make_user, "m4_sa2")
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200
    assert len(mails) == 1
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET})
    assert r.status_code == 200 and r.json()["changed"] is False and len(mails) == 1
    assert len(_audit_actions("system.heartbeat_url_set")) == 1


def test_a_mail_failure_does_not_undo_the_change(client, make_user, hb_cfg, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(en, "send_registered", boom)
    h = _login(client, make_user, "m4_sa3")
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET}).status_code == 200
    assert _cfg_url(hb_cfg) == SECRET


def test_disable_needs_a_reason_and_a_url_to_disable(client, make_user, hb_cfg):
    h = _login(client, make_user, "m4_sa4")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    for body in ({"confirm": True}, {"confirm": True, "reason": ""}, {"confirm": True, "reason": " "}, {"confirm": True, "reason": "a"}, {"confirm": True, "reason": "x" * 301}):
        r = client.post("/api/system/backup-monitor/heartbeat-disable", headers=h, json=body)
        assert r.status_code == 422, body
    assert client.post("/api/system/backup-monitor/heartbeat-disable", headers=h, json={"reason": "不用了"}).status_code == 400    # 沒 confirm
    assert client.post("/api/system/backup-monitor/heartbeat-disable", headers=h, json={"confirm": True, "reason": 5}).status_code == 400
    assert _cfg_url(hb_cfg) == SECRET
    hb_cfg.write_text(json.dumps({"ping_url": ""}), encoding="utf-8")
    r = client.post("/api/system/backup-monitor/heartbeat-disable", headers=h, json={"confirm": True, "reason": "不用了"})
    assert r.status_code == 422 and "沒有設定" in r.json()["detail"]


def test_sole_superadmin_can_disable_immediately_and_everyone_is_mailed(client, make_user, hb_cfg, mails, only_me):
    h = _login(client, make_user, "m4_only")
    only_me("m4_only")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET, "keep": 1}), encoding="utf-8")
    r = client.post("/api/system/backup-monitor/heartbeat-disable", headers=h, json={"confirm": True, "reason": "改用別家監控"})
    assert r.status_code == 200 and r.json()["disabled"] is True and r.json()["pending"] is False
    assert json.loads(hb_cfg.read_text(encoding="utf-8")) == {"ping_url": "", "keep": 1}
    assert len(mails) == 1 and mails[0][0] == "heartbeat_stale" and mails[0][1]["to_group"] is True
    assert "改用別家監控" in json.dumps(mails[0][1], ensure_ascii=False, default=str)
    (row,) = _audit_actions("system.heartbeat_disabled")
    assert "改用別家監控" in row[2] and "SECRET" not in row[2]


def _two_admins(client, make_user, a, b):
    ha = _login(client, make_user, a)
    hb = _login(client, make_user, b)
    return ha, hb


def test_with_another_superadmin_disable_waits_for_approval(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "m4_a", "m4_b")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    r = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"})
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["disabled"] is False
    cid = r.json()["id"]
    assert _cfg_url(hb_cfg) == SECRET                                           # 核准前什麼都沒變
    assert len(mails) == 1 and "等待另一位最高管理者核准" in json.dumps(mails[0][1], ensure_ascii=False, default=str)
    # 狀態頁：申請人看到「自己的」、另一位看到可以核准的
    sa = client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"]
    sb = client.get("/api/system/backup-monitor", headers=hb).json()["heartbeat"]["disableRequest"]
    assert sa["id"] == sb["id"] == cid and sa["mine"] is True and sb["mine"] is False
    assert sa["reason"] == "要搬機房" and "requestedByUser" not in sa
    # 申請人不能核准自己的
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=ha, json={"confirm": True})
    assert r.status_code == 422 and "另一位" in r.json()["detail"] and _cfg_url(hb_cfg) == SECRET
    # 第二位核准 ⇒ 真的停用
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True})
    assert r.status_code == 200 and r.json()["disabled"] is True
    assert _cfg_url(hb_cfg) == ""
    assert len(mails) == 2
    assert client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"] is None
    # 不能重複核准
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True}).status_code == 422
    acts = [r[0] for r in _audit_actions("system.heartbeat_disable_requested", "system.heartbeat_disabled")]
    assert acts == ["system.heartbeat_disable_requested", "system.heartbeat_disabled"]


def test_approve_requires_confirm_and_a_real_request(client, make_user, hb_cfg):
    ha, hb = _two_admins(client, make_user, "m4_c", "m4_d")
    assert client.post("/api/system/backup-monitor/heartbeat-disable/999999/approve", headers=hb, json={"confirm": True}).status_code == 422
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"}).json()["id"]
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={}).status_code == 400
    assert _cfg_url(hb_cfg) == SECRET


def test_cannot_approve_some_other_ledger_row(client, make_user, hb_cfg):
    """核准端點只認停用申請，不能拿來核准設定中心等其他變更的 id。"""
    import db
    from helpers import config_ledger as L
    ha, hb = _two_admins(client, make_user, "m4_e", "m4_f")
    conn = db.get_db()
    try:
        rec = L.record(conn, "setting:monitoring", "monitoring", [{"field": "backup_stale_hours", "old": 36, "new": 48}], "x", "m4_e",
                       risk="ops", effective_at="2099-01-01T00:00:00", approvals_required=1)
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % rec["ids"][0], headers=hb, json={"confirm": True})
    assert r.status_code == 422


def test_only_the_requester_can_cancel_and_config_stays(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "m4_g", "m4_h")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"}).json()["id"]
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/cancel" % cid, headers=hb, json={})       # 別人不能撤回
    assert r.status_code == 422 and "申請" in r.json()["detail"] and _audit_actions("system.heartbeat_disable_cancelled") == []
    assert client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"]["id"] == cid
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/cancel" % cid, headers=ha, json={})
    assert r.status_code == 200 and _cfg_url(hb_cfg) == SECRET
    assert client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"] is None
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True}).status_code == 422   # 撤回後不能再核准
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/cancel" % cid, headers=ha, json={}).status_code == 422
    assert [r[0] for r in _audit_actions("system.heartbeat_disable_cancelled")] == ["system.heartbeat_disable_cancelled"]


def test_a_new_request_replaces_the_old_one(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "m4_i", "m4_j")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    first = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "第一次"}).json()["id"]
    second = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "第二次"}).json()["id"]
    assert first != second
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % first, headers=hb, json={"confirm": True}).status_code == 422
    assert _cfg_url(hb_cfg) == SECRET
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % second, headers=hb, json={"confirm": True}).status_code == 200
    assert _cfg_url(hb_cfg) == ""


def test_setting_a_new_url_voids_a_pending_disable_request(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "m4_k", "m4_l")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"}).json()["id"]
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": "https://hc-ping.example.com/NEW"}).status_code == 200
    assert client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"] is None
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True}).status_code == 422
    assert _cfg_url(hb_cfg) == "https://hc-ping.example.com/NEW"


def test_approval_that_cannot_write_the_config_is_rolled_back_and_can_be_retried(client, make_user, hb_cfg, mails, monkeypatch):
    from helpers import backup_monitor as bm
    ha, hb = _two_admins(client, make_user, "m4_m", "m4_n")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"}).json()["id"]
    real = bm._write_config
    monkeypatch.setattr(bm, "_write_config", lambda url: (_ for _ in ()).throw(PermissionError("locked")))
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True})
    assert r.status_code == 500 and "再按一次" in r.json()["detail"]
    assert _cfg_url(hb_cfg) == SECRET
    monkeypatch.setattr(bm, "_write_config", real)
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True})
    assert r.status_code == 200 and _cfg_url(hb_cfg) == ""                       # 票沒有被失敗的那一次吃掉


def test_disable_request_text_does_not_leak_paths(client, make_user, hb_cfg):
    ha, _hb = _two_admins(client, make_user, "m4_o", "m4_p")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": r"檔案在 C:\Users\Jane Doe\x.txt 之後"})
    body = client.get("/api/system/backup-monitor", headers=ha).text
    assert "Jane" not in body and "SECRET" not in body


# ══ N1：scrub_paths 不能被長串破折號拖慢 ═══════════════════════════════════════════

_LINEAR_CASES = {"dashes": "-" * 20000, "a-dash": "a-" * 40000, "dash-dot": "-." * 10000, "a-slash": "a/" * 20000,
                 "a-backslash": "a\\" * 20000, "a-b-slash": "a-b/" * 10000, "plain": "x" * 100000}


@pytest.mark.parametrize("text", list(_LINEAR_CASES.values()), ids=list(_LINEAR_CASES))     # 短 id：id 是整串會超過 Windows 環境變數 32767 字上限（PYTEST_CURRENT_TEST）
def test_scrub_paths_is_linear_and_bounded(text):
    """審查 N1：lookbehind 沒排除 `-` 而 token 字元含 `-`，每個破折號之後都重掃一遍＝O(n²)（4 萬字 30 秒）。
    現在 lookbehind 補上 `-`，輸入另外截到 2000 字。"""
    from helpers.backup_monitor import scrub_paths, _PATH_RE
    t0 = time.perf_counter()
    scrub_paths(text)
    assert time.perf_counter() - t0 < 0.05
    t0 = time.perf_counter()                                           # 正則本身（不靠截斷）也要是線性
    _PATH_RE.sub("x", text[:40000])
    assert time.perf_counter() - t0 < 0.5


def test_scrub_paths_still_masks_after_the_cap_and_after_dashes():
    from helpers.backup_monitor import scrub_paths
    assert "Jane" not in scrub_paths("a-b " + "C:\\Users\\Jane Doe\\x.db")
    assert "秘密" not in scrub_paths("失敗-- /srv/秘密/x.db 了")
    assert len(scrub_paths("z" * 5000)) <= 2000


# ══ N3：解析網域也算在整體時限內 ═══════════════════════════════════════════════════

def test_slow_dns_is_inside_the_overall_deadline(monkeypatch):
    from core import safe_ping

    def slow(host, port):
        time.sleep(6)
        return ["93.184.216.34"]
    monkeypatch.setattr(safe_ping, "resolve_host", slow)
    t0 = time.monotonic()
    with pytest.raises(safe_ping.PingFailed) as ei:
        safe_ping.get("https://slow-dns.example.com/x", deadline=1.5)
    assert time.monotonic() - t0 < 4 and ei.value.kind == "timeout"


def test_slow_dns_at_save_time_does_not_hang_and_is_let_through(client, make_user, hb_cfg, monkeypatch):
    from core import safe_ping
    monkeypatch.setattr(safe_ping, "resolve_host", lambda h, p: (time.sleep(8), ["93.184.216.34"])[1])
    h = _login(client, make_user, "n3_sa")
    t0 = time.monotonic()
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET})
    assert r.status_code == 200 and time.monotonic() - t0 < 7


# ══ N2：換成另一個主機＝等於關掉原本的監控，同樣要原因＋第二人核准 ══════════════════════

OTHER = "https://other-monitor.example.org/NEW-SECRET-0001"


def _pending_file(hb_cfg):
    return Path(str(hb_cfg) + ".pending")


def test_first_time_and_same_host_path_change_are_immediate_with_mail(client, make_user, hb_cfg, mails):
    h = _login(client, make_user, "n2_a")
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET})
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["pending"] is False and _cfg_url(hb_cfg) == SECRET
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": "https://hc-ping.example.com/ROTATED-CHECK-ID"})
    assert r.status_code == 200 and r.json()["pending"] is False and _cfg_url(hb_cfg).endswith("ROTATED-CHECK-ID")
    assert len(mails) == 2


def test_host_change_needs_a_reason(client, make_user, hb_cfg, mails):
    h = _login(client, make_user, "n2_b")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    for body in ({"pingUrl": OTHER}, {"pingUrl": OTHER, "reason": ""}, {"pingUrl": OTHER, "reason": "a"}, {"pingUrl": OTHER, "reason": 5}):
        r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json=body)
        assert r.status_code == 422 and "原因" in r.json()["detail"], body
    assert _cfg_url(hb_cfg) == SECRET and mails == [] and not _pending_file(hb_cfg).exists()


def test_host_change_with_only_one_superadmin_is_immediate_and_mailed(client, make_user, hb_cfg, mails, only_me):
    h = _login(client, make_user, "n2_c")
    only_me("n2_c")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": OTHER, "reason": "換成公司自己的監控"})
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["pending"] is False and _cfg_url(hb_cfg) == OTHER
    assert len(mails) == 1 and "換成公司自己的監控" in json.dumps(mails[0][1], ensure_ascii=False, default=str)
    assert "NEW-SECRET" not in r.text


def test_host_change_with_other_superadmins_waits_for_approval_then_applies(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "n2_d", "n2_e")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET, "keep": 1}), encoding="utf-8")
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": OTHER, "reason": "換成公司自己的監控"})
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["changed"] is False
    cid = r.json()["id"]
    assert "NEW-SECRET" not in r.text
    assert json.loads(hb_cfg.read_text(encoding="utf-8")) == {"ping_url": SECRET, "keep": 1}        # 核准前不動
    assert json.loads(_pending_file(hb_cfg).read_text(encoding="utf-8")) == {"ping_url": OTHER}
    # 網址不進資料庫與稽核、不在畫面上；ledger 只有主機名
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT old_json, new_json, reason FROM config_changes WHERE id=?", (cid,)).fetchone()
        audit = " ".join((a[1] or "") + (a[2] or "") for a in _audit_actions("system.heartbeat_change_requested"))
    finally:
        conn.close()
    assert "NEW-SECRET" not in (row[0] + row[1] + row[2] + audit) and "other-monitor.example.org" in row[1]
    page = client.get("/api/system/backup-monitor", headers=hb).json()["heartbeat"]["disableRequest"]
    assert page["kind"] == "change" and page["newHost"] == "other-monitor.example.org" and page["mine"] is False and "NEW-SECRET" not in json.dumps(page)
    assert len(mails) == 1 and "other-monitor.example.org" in json.dumps(mails[0][1], ensure_ascii=False, default=str)
    # 自己不能核准；第二位核准後才生效，其他設定鍵保留、暫存檔清掉
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=ha, json={"confirm": True}).status_code == 422
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True})
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["disabled"] is False
    assert json.loads(hb_cfg.read_text(encoding="utf-8")) == {"ping_url": OTHER, "keep": 1}
    assert not _pending_file(hb_cfg).exists()
    assert [a[0] for a in _audit_actions("system.heartbeat_change_requested", "system.heartbeat_changed")] == ["system.heartbeat_change_requested", "system.heartbeat_changed"]
    assert client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["pingHost"] == "other-monitor.example.org"


def test_cancel_or_replace_removes_the_pending_url_file(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "n2_f", "n2_g")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": OTHER, "reason": "要換"}).json()["id"]
    assert _pending_file(hb_cfg).exists()
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/cancel" % cid, headers=ha, json={}).status_code == 200
    assert not _pending_file(hb_cfg).exists() and _cfg_url(hb_cfg) == SECRET
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True}).status_code == 422
    # 新的停用申請取代舊的換主機申請
    cid2 = client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": OTHER, "reason": "要換"}).json()["id"]
    cid3 = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "改成停用"}).json()["id"]
    assert not _pending_file(hb_cfg).exists()
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid2, headers=hb, json={"confirm": True}).status_code == 422
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid3, headers=hb, json={"confirm": True}).status_code == 200
    assert _cfg_url(hb_cfg) == ""


def test_approving_a_change_whose_pending_file_is_gone_fails_cleanly_and_keeps_the_vote(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "n2_h", "n2_i")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": OTHER, "reason": "要換"}).json()["id"]
    _pending_file(hb_cfg).unlink()
    r = client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True})
    assert r.status_code == 422 and "暫存檔" in r.json()["detail"] and _cfg_url(hb_cfg) == SECRET


def test_a_later_immediate_change_voids_a_pending_host_change(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "n2_j", "n2_k")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": OTHER, "reason": "要換"}).json()["id"]
    assert client.put("/api/system/backup-monitor/heartbeat-url", headers=ha, json={"pingUrl": "https://hc-ping.example.com/ANOTHER"}).status_code == 200
    assert not _pending_file(hb_cfg).exists()
    assert client.post("/api/system/backup-monitor/heartbeat-disable/%d/approve" % cid, headers=hb, json={"confirm": True}).status_code == 422
    assert _cfg_url(hb_cfg).endswith("ANOTHER")


def test_mail_failure_is_reported_to_the_user_not_swallowed(client, make_user, hb_cfg, monkeypatch):
    monkeypatch.setattr(en, "send_registered", lambda key, **kw: False)
    h = _login(client, make_user, "n2_l")
    r = client.put("/api/system/backup-monitor/heartbeat-url", headers=h, json={"pingUrl": SECRET})
    assert r.status_code == 200 and "通知信沒有寄出去" in r.json()["message"]


# ══ N5：待核准的新網址檔等同密碼，要和 heartbeat_config.json 一樣不進 git、不進回滾快照、不被還原蓋掉 ══════════════

def _repo_root():
    return Path(__file__).resolve().parents[2]


def test_pending_url_file_is_gitignored():
    lines = [l.strip() for l in (_repo_root() / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "backend/heartbeat_config.json" in lines and "backend/heartbeat_config.json.pending" in lines


def test_update_and_rollback_scripts_exclude_the_pending_url_file_wherever_they_exclude_the_config():
    """每個排除 heartbeat_config.json 的 robocopy 行都要同時排除 .pending；備份 backend/ 的快照行也要排除 .pending。"""
    checked = 0
    for name in ("apply_update.ps1", "rollback_update.ps1"):
        text = (_repo_root() / "backend" / "tools" / name).read_text(encoding="utf-8-sig")
        for n, line in enumerate(text.splitlines(), 1):
            if "heartbeat_config.json" in line and "/XF" in line:
                checked += 1
                assert "heartbeat_config.json.pending" in line, "%s:%d 排除了設定檔卻沒排除 .pending" % (name, n)
        if name == "apply_update.ps1":
            snap = [l for l in text.splitlines() if 'robocopy $BackendDir (Join-Path $rollbackDir "backend")' in l]
            assert snap and all("/XF" in l and "heartbeat_config.json.pending" in l for l in snap)
    assert checked >= 8                                                  # 掃得到才算數（不是掃空）


# ══ PM 追加：待核准時畫面要說清楚在等誰、等多久，只有申請人能撤回 ═══════════════════════════════

def test_pending_request_tells_who_it_waits_for_and_for_how_long(client, make_user, hb_cfg, mails):
    ha, hb = _two_admins(client, make_user, "w_a", "w_b")
    hb_cfg.write_text(json.dumps({"ping_url": SECRET}), encoding="utf-8")
    cid = client.post("/api/system/backup-monitor/heartbeat-disable", headers=ha, json={"confirm": True, "reason": "要搬機房"}).json()["id"]
    rq = client.get("/api/system/backup-monitor", headers=ha).json()["heartbeat"]["disableRequest"]
    assert rq["mine"] is True and rq["hoursWaiting"] == 0 and "w_b" in rq["waitingFor"] and "w_a" not in rq["waitingFor"] and "requestedByUser" not in rq
    # 送出 5 小時又 20 分鐘後：整小時
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT at FROM config_changes WHERE id=?", (cid,)).fetchone()
    finally:
        conn.close()
    from helpers import backup_monitor as bm
    real = bm.datetime
    start = datetime.fromisoformat(row[0])

    class _Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return start + timedelta(hours=5, minutes=20)
    bm.datetime = _Later
    try:
        assert client.get("/api/system/backup-monitor", headers=hb).json()["heartbeat"]["disableRequest"]["hoursWaiting"] == 5
    finally:
        bm.datetime = real
    assert bm._hours_waiting("not a time") == 0 and bm._hours_waiting(None) == 0


def test_the_page_text_for_a_pending_request_is_wired():
    """頁面文字（e2e 才能點的畫面，這裡先鎖字串，避免被改掉）。"""
    html = (_repo_root() / "frontend" / "pages" / "backup-monitor.html").read_text(encoding="utf-8")
    for needle in ("若對方長期不在，可請對方登入核准，或撤回這次變更", "已送出", "bm-disable-waiting", "bm-disable-cancel",
                   "s.heartbeat.disableRequest && s.heartbeat.disableRequest.mine\" :disabled=\"busy\" @click=\"ask('cancelreq')\""):
        assert needle in html, needle
