# -*- coding: utf-8 -*-
"""來源 IP 只信該信的（2026-11-11，外網存取 go-live 前必修的安全項）。

問題（hichan-9 設計手機外勤時發現）：`routers/auth.py::_client_ip` 無條件信 request 的 `X-Forwarded-For` 第一個值。登入鎖定
（5 次失敗／15 分鐘）以來源 IP 計 ⇒ 應用一旦對外可連，任何人每次攻擊換一個 XFF 就繞過鎖定 ⇒ 無限次密碼猜測。
並發問題：cloudflared 與本程式同機時，所有外部使用者的 `request.client.host` 都是 127.0.0.1 ⇒ 鎖定把全部外部使用者綁成同一個桶
（一個人輸錯 5 次鎖住所有人）、稽核紀錄的 IP 全變 127.0.0.1。
修法：`helpers/client_ip.py`——永遠不讀 XFF；只有 TCP 對端本身是 loopback 才採信 `CF-Connecting-IP`（且必須是合法 IP）。
另：部署儀表板用「對端是不是 loopback」判斷本機 ⇒ 隧道轉進來的請求會被誤判成本機；帶 Cloudflare／代理標頭的請求一律 fail closed
（那幾題在 `tests/test_deploy_dashboard_local_only_2026_09_22.py` 的 HC1d：repo 規定只有 `test_deploy_dashboard*` 檔可以載入儀表板、而且要用它的 `dash` 夾具拆掉會動手的路徑）。
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from helpers.client_ip import client_ip, has_proxy_headers, is_loopback


def _req(peer, **headers):
    return SimpleNamespace(client=(SimpleNamespace(host=peer) if peer is not None else None), headers=Headers(headers))


# ── 單元：規則本身 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("host,expect", [
    ("127.0.0.1", True), ("127.5.6.7", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.20", False), ("203.0.113.9", False), ("::ffff:192.168.1.20", False),
    ("testclient", False), ("localhost", False), ("", False), (None, False),
])
def test_is_loopback(host, expect):
    assert is_loopback(host) is expect


def test_xff_is_never_trusted_whatever_the_peer_is():
    assert client_ip(_req("203.0.113.9", **{"X-Forwarded-For": "1.2.3.4"})) == "203.0.113.9"
    assert client_ip(_req("127.0.0.1", **{"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})) == "127.0.0.1"


def test_cf_connecting_ip_is_ignored_unless_the_tcp_peer_is_loopback():
    assert client_ip(_req("203.0.113.9", **{"CF-Connecting-IP": "1.2.3.4"})) == "203.0.113.9"
    assert client_ip(_req("192.168.1.20", **{"CF-Connecting-IP": "1.2.3.4"})) == "192.168.1.20"
    assert client_ip(_req("testclient", **{"CF-Connecting-IP": "1.2.3.4"})) == "testclient"


def test_cf_connecting_ip_is_trusted_from_a_loopback_peer_and_normalised():
    assert client_ip(_req("127.0.0.1", **{"CF-Connecting-IP": "198.51.100.7"})) == "198.51.100.7"
    assert client_ip(_req("::1", **{"CF-Connecting-IP": "2001:db8::1"})) == "2001:db8::1"
    assert client_ip(_req("::ffff:127.0.0.1", **{"CF-Connecting-IP": "::ffff:198.51.100.7"})) == "198.51.100.7"
    assert client_ip(_req("127.0.0.1", **{"CF-Connecting-IP": " 198.51.100.7 "})) == "198.51.100.7"


@pytest.mark.parametrize("junk", ["not-an-ip", "1.2.3.4, 5.6.7.8", "999.1.1.1", "' OR 1=1 --", "x" * 500])
def test_garbage_cf_header_falls_back_to_the_peer_address(junk):
    assert client_ip(_req("127.0.0.1", **{"CF-Connecting-IP": junk})) == "127.0.0.1"


def test_no_header_and_no_peer():
    assert client_ip(_req("127.0.0.1")) == "127.0.0.1"
    assert client_ip(_req(None)) == "unknown"
    assert client_ip(_req(None, **{"CF-Connecting-IP": "1.2.3.4"})) == "unknown"          # 沒有對端 ⇒ 不是 loopback ⇒ 不採信


def test_has_proxy_headers():
    assert has_proxy_headers(Headers({"CF-Ray": "abc"}))
    assert has_proxy_headers(Headers({"cf-connecting-ip": "1.2.3.4"}))
    assert has_proxy_headers(Headers({"X-Forwarded-For": "1.2.3.4"}))
    assert not has_proxy_headers(Headers({"User-Agent": "x", "Accept": "*/*"}))


# ── 整合：真的打登入端點 ─────────────────────────────────────────────────────

def _fail(c, user, **headers):
    return c.post("/api/auth/login", json={"username": user, "password": "wrong"}, headers=headers)


def test_rotating_xff_no_longer_bypasses_the_login_lockout(client, make_user):
    """舊行為：每次換一個 XFF ⇒ 每次都是新的 IP 桶 ⇒ 永遠不會鎖 ⇒ 無限次猜密碼。"""
    user, pw = make_user()
    for i in range(5):
        assert _fail(client, user, **{"X-Forwarded-For": "203.0.113.%d" % (10 + i)}).status_code == 401
    r = client.post("/api/auth/login", json={"username": user, "password": pw}, headers={"X-Forwarded-For": "203.0.113.250"})
    assert r.status_code == 429, "第 6 次（換了新的 XFF、密碼還是對的）要被鎖：%s" % r.text[:120]


def test_rotating_cf_connecting_ip_from_a_non_loopback_peer_does_not_bypass_either(client, make_user):
    user, pw = make_user()
    for i in range(5):
        assert _fail(client, user, **{"CF-Connecting-IP": "198.51.100.%d" % (10 + i)}).status_code == 401
    r = client.post("/api/auth/login", json={"username": user, "password": pw}, headers={"CF-Connecting-IP": "198.51.100.250"})
    assert r.status_code == 429


def test_behind_a_same_host_tunnel_each_visitor_has_their_own_lockout_bucket(client, make_user):
    """cloudflared 與本程式同機：對端是 127.0.0.1、真實來源在 CF-Connecting-IP。
    攻擊者（198.51.100.7）輸錯 5 次只鎖他自己；另一位使用者（203.0.113.9）照常能登入；攻擊者換 XFF 也繞不過。"""
    from fastapi.testclient import TestClient
    tunnel = TestClient(client.app, client=("127.0.0.1", 5000))
    attacker, _ = make_user(username="xff_attacker_target")
    victim, victim_pw = make_user(username="xff_victim")
    for i in range(5):
        r = _fail(tunnel, attacker, **{"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "9.9.9.%d" % i})
        assert r.status_code == 401
    r = _fail(tunnel, attacker, **{"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "9.9.9.200"})
    assert r.status_code == 429, "攻擊者那個 IP 要被鎖（換 XFF 也一樣）"
    r = tunnel.post("/api/auth/login", json={"username": victim, "password": victim_pw},
                    headers={"CF-Connecting-IP": "203.0.113.9"})
    assert r.status_code == 200, "別的外部使用者不可被連坐鎖住：%s" % r.text[:120]


# ── 稽核紀錄的 IP ────────────────────────────────────────────────────────────

def test_audit_ip_of_duty_roles_and_settings_center_uses_the_trusted_ip():
    from routers import duty_roles
    assert duty_roles._ip(_req("127.0.0.1", **{"CF-Connecting-IP": "198.51.100.7"})) == "198.51.100.7"
    assert duty_roles._ip(_req("203.0.113.9", **{"X-Forwarded-For": "1.2.3.4"})) == "203.0.113.9"
    assert duty_roles._ip(None) == ""


# ── 守門：以後不准再自己讀 XFF／request.client.host ──────────────────────────

_BACKEND = Path(__file__).resolve().parent.parent
_ALLOWED = {
    "helpers/client_ip.py",                 # 唯一的實作
    "tools/deploy_dashboard.py",            # 本機判斷（對端是否 loopback＋是否帶代理標頭），自成一體
}
def _offences(source: str):
    """AST 掃描（不看註解與文件字串，只看程式碼）：回傳 [(行號, 說明)]——
    ① 字串常數恰為 `X-Forwarded-For`（不分大小寫；讀標頭的寫法）；② 屬性鏈 `….client.host`（直接讀對端位址）。"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip().lower() == "x-forwarded-for":
            out.append((node.lineno, "讀 X-Forwarded-For"))
        if (isinstance(node, ast.Attribute) and node.attr == "host"
                and isinstance(node.value, ast.Attribute) and node.value.attr == "client"):
            out.append((node.lineno, "直接讀 .client.host"))
    return out


def test_no_code_outside_the_helper_reads_xff_or_the_raw_peer_address():
    offenders = []
    for p in _BACKEND.rglob("*.py"):
        rel = p.relative_to(_BACKEND).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel or rel in _ALLOWED or ".venv" in rel or "node_modules" in rel:
            continue
        if p.name == "conftest.py":
            continue
        try:
            found = _offences(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        offenders += ["%s:%d  %s" % (rel, n, what) for n, what in found]
    assert not offenders, "來源 IP 一律走 helpers.client_ip.client_ip(request)（不可自己讀 XFF／client.host）：\n" + "\n".join(offenders)


_OLD_CODE = (
    "def f(request):\n"
    "    xff = request.headers.get('X-Forwarded-For', '')\n"
    "    return request.client.host if request.client else ''\n"
)
_PROSE_ONLY = (
    "def f(r):\n"
    "    '''說明：不讀 X-Forwarded-For，也不用 request.client.host'''\n"
    "    # request.client.host\n"
    "    return client_ip(r)\n"
)


def test_guard_positive_control_the_scanner_flags_the_old_code_and_ignores_prose():
    assert [w for _n, w in _offences(_OLD_CODE)] == ["讀 X-Forwarded-For", "直接讀 .client.host"]
    assert _offences(_PROSE_ONLY) == []
