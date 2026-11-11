# -*- coding: utf-8 -*-
"""heartbeat 本機 ping 要打 HTTPS（2026-11-11）。

背景：666 埠自 2026-09-07 起只講 HTTPS（mkcert 自簽憑證），heartbeat_job 卻還打
http://127.0.0.1:666/api/ping ⇒ 每 5 分鐘連不上、誤報 local_down 並對外 /fail，
兩個多月沒有真正的當機監控。

這支測試起一個「真的只講 TLS」的本機伺服器（自簽憑證），驗：
- 修前的寫法（http:// 打純 HTTPS 服務）確實會失敗 ⇒ 重現原 bug；
- 修後 https:// ＋ loopback 略過驗證 ⇒ 判定存活；
- 略過驗證只限 loopback 的 https，對外 ping_url 仍走預設憑證驗證；
- 卡住的 heartbeat_state.json（local_down）修好後下次執行自動回 ok，不必手動清檔。
"""
import datetime as _dt
import importlib
import json
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# conftest 的 _netguard 會擋 urlopen。這支測試要驗「真的 TLS 握手」，所以用到本機伺服器的題
# 標 allow_outbound：連線目標一律是自己起的 127.0.0.1 臨時埠，不碰任何對外網路（對外 ping_url
# 一律被 fake 掉，見 _external_ok）。
loopback_net = pytest.mark.allow_outbound


@pytest.fixture
def hb(monkeypatch, tmp_path):
    from core import paths
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "hb.json"))
    sys.modules.pop("heartbeat_job", None)
    mod = importlib.import_module("heartbeat_job")
    mod._lines = []
    monkeypatch.setattr(mod.logger, "log", lambda level, msg, *a, **k: mod._lines.append(("log", msg)))
    monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **k: mod._lines.append(("error", msg)))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *a, **k: mod._lines.append(("warning", msg)))
    monkeypatch.setattr(mod.logger, "info", lambda msg, *a, **k: mod._lines.append(("info", msg)))
    yield mod
    sys.modules.pop("heartbeat_job", None)


def _self_signed_cert(tmp_path):
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "heartbeat-test")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(days=1)).not_valid_after(now + _dt.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    crt, pem = tmp_path / "srv.crt", tmp_path / "srv.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
    return str(crt), str(pem)


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": true}'
        self.send_response(200 if self.path == "/api/ping" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):   # http:// 打進來的 TLS 握手失敗是預期的
        pass


@pytest.fixture
def https_only_server(tmp_path):
    """只講 TLS、自簽憑證的 127.0.0.1 伺服器（等同正式機 666 埠）。回傳 port。"""
    crt, key = _self_signed_cert(tmp_path)
    srv = _QuietServer(("127.0.0.1", 0), _Ping)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def test_local_ping_urls_are_loopback_https_first_then_http(hb):
    """2026-11-11 起兩種協定都試（見 heartbeat_job 檔頭）；https 先。"""
    assert hb._local_urls() == ["https://127.0.0.1:666/api/ping", "http://127.0.0.1:666/api/ping"]


@loopback_net
def test_old_http_ping_against_https_only_server_fails_the_bug_repro(hb, https_only_server):
    """修前的寫法：http:// 打純 HTTPS 服務 ⇒ 判成掛了（誤報 local_down 的根因）。"""
    assert hb._http_get(f"http://127.0.0.1:{https_only_server}/api/ping") is False


@loopback_net
def test_https_loopback_ping_with_self_signed_cert_is_alive(hb, https_only_server):
    assert hb._http_get(f"https://127.0.0.1:{https_only_server}/api/ping") is True


@loopback_net
def test_non_2xx_is_still_a_failure(hb, https_only_server):
    assert hb._http_get(f"https://127.0.0.1:{https_only_server}/nope") is False


def test_cert_skip_is_limited_to_loopback_https(hb):
    ctx = hb._ssl_context_for("https://127.0.0.1:666/api/ping")
    assert ctx is not None and ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False
    assert hb._ssl_context_for("https://localhost:666/api/ping") is not None
    # 對外打卡（healthchecks.io 等）與任何非 loopback ⇒ None ＝ urllib 預設驗證
    for url in ("https://hc-ping.com/abc-uuid", "https://hc-ping.com/abc-uuid/fail",
                "https://127.0.0.1.evil.example/api/ping",      # 主機名只是「長得像」loopback
                "https://evil.example/?h=127.0.0.1",            # loopback 字樣只出現在 query
                "https://evil.example/127.0.0.1",
                "http://127.0.0.1:666/api/ping"):                # 非 https：沒有憑證可略過
        assert hb._ssl_context_for(url) is None, url


@loopback_net
def test_non_loopback_https_still_verifies_certs(hb, https_only_server, monkeypatch):
    """把 127.0.0.1 當成「非 loopback」⇒ 自簽憑證驗證失敗 ⇒ False。
    證明略過驗證不是全域的，預設驗證路徑還在。"""
    monkeypatch.setattr(hb, "_LOOPBACK_HOSTS", ())
    assert hb._http_get(f"https://127.0.0.1:{https_only_server}/api/ping") is False


def _cfg(hb, ping_url):
    Path(hb._CONFIG_PATH).write_text(json.dumps({"ping_url": ping_url}), encoding="utf-8")


def _external_ok(hb, monkeypatch):
    """本機 URL 走真的 _http_get；對外 hc.example 假裝打卡成功（不碰網路）。"""
    real = hb._http_get
    calls = []

    def fake(url):
        calls.append(url)
        return True if "hc.example" in url else real(url)
    monkeypatch.setattr(hb, "_http_get", fake)
    return calls


@loopback_net
def test_main_reports_ok_against_https_only_service(hb, https_only_server, monkeypatch):
    _cfg(hb, "https://hc.example/x")
    monkeypatch.setattr(hb, "_LOCAL_PORT", https_only_server)
    calls = _external_ok(hb, monkeypatch)
    hb.main()
    st = json.loads(Path(hb._STATE_PATH).read_text(encoding="utf-8"))
    assert st["status"] == "ok" and st["scheme"] == "https"
    assert calls[-1] == "https://hc.example/x" and not any(c.endswith("/fail") for c in calls)
    assert not [k for k, _ in hb._lines if k == "error"]


@loopback_net
def test_main_no_longer_reports_false_local_down_when_only_one_scheme_is_up(hb, https_only_server, monkeypatch):
    """修前（2026-09-07 起的 bug）：腳本寫死 http:// ⇒ 服務明明活著卻 local_down 並對外 /fail。
    現在兩種協定都試：只有 https 活著也判存活，且不送 /fail。（http-only 與全掛的情形見 test_heartbeat_watch_2026_11_11.py）"""
    _cfg(hb, "https://hc.example/x")
    monkeypatch.setattr(hb, "_LOCAL_PORT", https_only_server)
    calls = _external_ok(hb, monkeypatch)
    hb.main()
    assert json.loads(Path(hb._STATE_PATH).read_text(encoding="utf-8"))["status"] == "ok"
    assert not any(c.endswith("/fail") for c in calls)


@loopback_net
def test_stuck_local_down_state_self_heals_without_clearing_state_file(hb, https_only_server, monkeypatch):
    """正式機 heartbeat_state.json 卡在 local_down（同一小時已記過）。
    修好後下一次執行：狀態改變 ⇒ 記 log 並覆寫成 ok，不必手動刪狀態檔。"""
    _cfg(hb, "https://hc.example/x")
    now = _dt.datetime.now()
    Path(hb._STATE_PATH).write_text(json.dumps(
        {"status": "local_down", "day": now.strftime("%Y-%m-%d"), "hour": now.strftime("%Y-%m-%d %H")}),
        encoding="utf-8")
    monkeypatch.setattr(hb, "_LOCAL_PORT", https_only_server)
    _external_ok(hb, monkeypatch)
    hb.main()
    assert json.loads(Path(hb._STATE_PATH).read_text(encoding="utf-8"))["status"] == "ok"
    assert hb._lines and hb._lines[-1][0] == "log" and "外部心跳打卡成功" in hb._lines[-1][1]
