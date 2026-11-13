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

from helpers.client_ip import client_ip, has_proxy_headers, is_loopback, rate_limit_key


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


# ── T80 稽核 IP-M1／LG-S7：登入鎖定的鍵（rate_limit_key，只給 routers/auth.py 用） ──────

def test_rate_limit_key_ipv4_is_unchanged():
    assert rate_limit_key("203.0.113.9") == "203.0.113.9"
    assert rate_limit_key("127.0.0.1") == "127.0.0.1"


def test_rate_limit_key_aggregates_ipv6_to_slash_64():
    # 同一個 /64 的三個不同位址要得到同一個鍵——這就是 IP-M1 的核心：不聚合的話，
    # 一般住宅網路的 /64（2^64 個位址）讓登入鎖定形同沒鎖。
    a = rate_limit_key("2001:db8:1:2::1")
    b = rate_limit_key("2001:db8:1:2::2")
    c = rate_limit_key("2001:db8:1:2::3")
    assert a == b == c == "2001:db8:1:2::/64"
    # 不同 /64 要分開，不可以聚合過頭變成同一個桶
    assert rate_limit_key("2001:db8:1:3::1") != a


def test_rate_limit_key_unwraps_ipv4_mapped_ipv6_before_decidin_v4_vs_v6():
    # LG-S7：雙棧 socket 下對端位址可能是 ::ffff:a.b.c.d；沒先展開的話兩個不同的
    # IPv4 用戶端會一起落進同一個 ::/64 桶（等於所有 IPv4 用戶端共用一把鎖）。
    assert rate_limit_key("::ffff:1.2.3.4") == "1.2.3.4"
    assert rate_limit_key("::ffff:5.6.7.8") == "5.6.7.8"
    assert rate_limit_key("::ffff:1.2.3.4") != rate_limit_key("::ffff:5.6.7.8")


def test_rate_limit_key_passes_through_non_ip_values():
    assert rate_limit_key("unknown") == "unknown"
    assert rate_limit_key("testclient") == "testclient"


# ── 登入鎖定實際以 rate_limit_key 分桶（routers/auth.py），稽核紀錄仍用完整位址 ──────

def test_login_lockout_shares_one_bucket_across_the_same_v64_but_not_across_v4(client, make_user):
    """T80稽核IP-M1關閉條件：同 /64 不同位址連續失敗，第 5 次起 429；不同 /64／IPv4 不受影響。
    對端固定成 127.0.0.1（cloudflared 與本程式同機的樣子）才會採信 CF-Connecting-IP。"""
    from fastapi.testclient import TestClient

    user, pw = make_user(username="ipm1_v64_user")
    tunnel = TestClient(client.app, client=("127.0.0.1", 5000))
    same_64 = ["2001:db8:9:9::1", "2001:db8:9:9::2", "2001:db8:9:9::3",
               "2001:db8:9:9::4", "2001:db8:9:9::5"]
    for addr in same_64:
        r = _fail(tunnel, user, **{"CF-Connecting-IP": addr})
        assert r.status_code == 401, (addr, r.status_code, r.text[:120])
    # 第 6 次：換了一個新位址，但仍是同一個 /64 ⇒ 鎖定要生效（429）——M3 突變：拿掉 /64 聚合會在這裡紅。
    r = _fail(tunnel, user, **{"CF-Connecting-IP": "2001:db8:9:9::99"})
    assert r.status_code == 429, (r.status_code, r.text[:120])

    # 不同 /64 的另一位使用者不受連坐
    other_user, other_pw = make_user(username="ipm1_v64_other", role="sales")
    r = tunnel.post("/api/auth/login", json={"username": other_user, "password": other_pw},
                     headers={"CF-Connecting-IP": "2001:db8:aa:bb::1"})
    assert r.status_code == 200, r.text[:120]


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
    victim, victim_pw = make_user(username="xff_victim", role="sales")
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


# ── 稽核紀錄之外：跟 uvicorn 那一層疊在一起（hichan-13 K 審 S1）──────────────────

def _through_uvicorn_proxy_layer(client, peer, allow="127.0.0.1"):
    """把 app 包上真正的 uvicorn ProxyHeadersMiddleware（就像 `uvicorn main:app` 預設會做的），再用指定的 TCP 對端打。"""
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    return TestClient(ProxyHeadersMiddleware(client.app, trusted_hosts=allow), client=(peer, 5000))


def _six_logins(c, user, pw, header_for):
    codes = []
    for i in range(5):
        codes.append(c.post("/api/auth/login", json={"username": user, "password": "wrong"}, headers=header_for(i)).status_code)
    codes.append(c.post("/api/auth/login", json={"username": user, "password": pw}, headers=header_for(99)).status_code)
    return codes


def test_cloudflare_shaped_request_through_the_uvicorn_layer_locks_the_real_visitor(client, make_user):
    """隧道同機：對端 127.0.0.1、XFF＝「攻擊者塞的假值, Cloudflare 附加的真實 IP」、CF-Connecting-IP＝真實 IP。
    uvicorn 取最右邊不受信任的那個（真實 IP）⇒ 假值被略過 ⇒ 第 6 次被鎖。"""
    user, pw = make_user()
    c = _through_uvicorn_proxy_layer(client, "127.0.0.1")
    codes = _six_logins(c, user, pw, lambda i: {"X-Forwarded-For": "9.9.9.%d, 198.51.100.7" % i, "CF-Connecting-IP": "198.51.100.7"})
    assert codes == [401] * 5 + [429], codes


def test_lan_peer_with_rotating_xff_through_the_uvicorn_layer_is_locked(client, make_user):
    """區網對端不在 forwarded_allow_ips ⇒ uvicorn 不理 XFF；這支 helper 也不讀 XFF ⇒ 鎖得住。"""
    user, pw = make_user()
    c = _through_uvicorn_proxy_layer(client, "192.168.1.50")
    codes = _six_logins(c, user, pw, lambda i: {"X-Forwarded-For": "203.0.113.%d" % (10 + i)})
    assert codes == [401] * 5 + [429], codes


def _uvicorn_launch_lines():
    """所有「把 main:app 綁在 0.0.0.0」的啟動行：[(相對路徑, 行)]。掃 backend/*.bat／*.cmd、repo 根目錄 *.ps1、各層 tools 下的 *.ps1。"""
    root = _BACKEND.parent
    files = set(_BACKEND.glob("*.bat")) | set(_BACKEND.glob("*.cmd")) | set(root.glob("*.ps1"))
    for d in (root / "tools", _BACKEND / "tools"):
        if d.is_dir():
            files |= set(d.rglob("*.ps1"))
    out = []
    for f in sorted(files):
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            low = ln.lower()
            if "uvicorn" in low and "main:app" in low and "0.0.0.0" in ln and not ln.lstrip().startswith(("::", "#", "rem ", "REM ")):
                out.append((f.relative_to(root).as_posix(), ln))
    return out


def _launcher_line_problem(ln):
    """一行 uvicorn 啟動行有沒有把 forwarded-allow-ips 釘在 127.0.0.1？⇒ 問題說明或 None（真測試與正對照走同一條路）。"""
    import re
    m = re.search(r"--forwarded-allow-ips[= ]+(\S+)", ln)
    if not m:
        return "沒有明寫 --forwarded-allow-ips 127.0.0.1"
    if m.group(1).strip("'\"") != "127.0.0.1":
        return "forwarded-allow-ips 必須只信 127.0.0.1（不可 *）：" + m.group(1)
    if "--no-proxy-headers" in ln:
        return "不可用 --no-proxy-headers（會丟掉 X-Forwarded-Proto 的 scheme 處理）"
    return None


def test_every_launcher_that_binds_all_interfaces_pins_uvicorn_forwarded_allow_ips():
    """uvicorn 的 forwarded_allow_ips 若被環境變數 FORWARDED_ALLOW_IPS／複製來的指令改成 `*`，uvicorn 會對任何對端取 XFF 第一個值
    ⇒ 原本的漏洞回來而 helper 擋不住（它信 request.client.host）。命令列優先於環境變數，所以每個綁 0.0.0.0 的啟動行都明寫死
    （正式機 autostart.bat、手動重啟 restart.bat、開發用 start.bat／start_server.ps1；綁 127.0.0.1 的演練腳本不用）。
    已知限制：掃描器要求 uvicorn／main:app／0.0.0.0 在**同一行**；用 `^`／反引號斷行、或 `--host %HOST%` 這種寫法的啟動檔會被略過
    （現有四個都是單行）——新增啟動檔請保持單行，或把它加進這裡。"""
    lines = _uvicorn_launch_lines()
    names = {rel for rel, _ in lines}
    assert "backend/autostart.bat" in names and len(names) >= 2, "掃描器沒找到啟動行（不可靜默掃空）：%s" % sorted(names)
    bad = ["%s：%s\n%s" % (rel, _launcher_line_problem(ln), ln) for rel, ln in lines if _launcher_line_problem(ln)]
    assert not bad, "uvicorn 啟動行不合格：\n" + "\n".join(bad)


def test_launcher_check_positive_control_rejects_a_launcher_without_the_flag():
    """正對照：同一個檢查函式——真的 restart.bat 啟動行合格；拿掉旗標、改成 `*`、加 --no-proxy-headers 都不合格。"""
    import re
    ok = {rel: ln for rel, ln in _uvicorn_launch_lines()}
    assert "backend/restart.bat" in ok, "restart.bat 啟動行沒被掃到"
    line = ok["backend/restart.bat"]
    assert _launcher_line_problem(line) is None
    assert _launcher_line_problem(re.sub(r"--forwarded-allow-ips[= ]+\S+\s*", "", line))
    assert _launcher_line_problem(line.replace("--forwarded-allow-ips 127.0.0.1", "--forwarded-allow-ips *"))
    assert _launcher_line_problem(line + " --no-proxy-headers")


def test_scoped_ipv6_in_cf_header_is_not_adopted():
    assert client_ip(_req("127.0.0.1", **{"CF-Connecting-IP": "fe80::1%eth0"})) == "127.0.0.1"


# ── 守門：以後不准再自己讀 XFF／request.client.host ──────────────────────────

_BACKEND = Path(__file__).resolve().parent.parent
_ALLOWED = {
    "helpers/client_ip.py",                 # 唯一的實作
    "tools/deploy_dashboard.py",            # 本機判斷（對端是否 loopback＋是否帶代理標頭），自成一體
}
_PROXY_HEADER_NAMES = {"x-forwarded-for", "x-real-ip", "cf-connecting-ip", "forwarded"}


def _const_text(node):
    v = getattr(node, "value", None)
    if isinstance(v, bytes):
        v = v.decode("latin-1")
    return v.strip().lower() if isinstance(v, str) else None


def _is_client_attr(node):
    return isinstance(node, ast.Attribute) and node.attr == "client"


def _is_scope(node):
    return (isinstance(node, ast.Attribute) and node.attr == "scope") or (isinstance(node, ast.Name) and node.id == "scope")


def _offences(source: str):
    """AST 掃描（不看註解與文件字串，只看程式碼）：回傳 [(行號, 說明)]——
    ① 字串／bytes 常數恰為 X-Forwarded-For／X-Real-IP／CF-Connecting-IP／Forwarded（不分大小寫；讀標頭的各種寫法）；
    ② 屬性鏈 `….client.host`；③ `….client[0]`、`h, p = ….client`、`getattr(….client, "host")`、`getattr(x, "client")`；
    ④ `….scope["client"]`、`scope.get("client")`（繞過 request.client 直接讀 ASGI scope）；⑤ `c = r.client` 別名、拼接／f-string 組出的 forwarded 標頭名。
    已知限制（靜態掃描不可能完整，價值在攔住顯而易見的）：變數當 scope 鍵（`K="client"`; `scope[K]`）、逐個比對原始 scope["headers"] 的前綴、
    其他廠商的來源 IP 標頭（True-Client-IP、X-Client-IP）不會被抓到。"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and _const_text(node) in _PROXY_HEADER_NAMES:
            out.append((node.lineno, "讀代理標頭 %s" % _const_text(node)))
        if isinstance(node, ast.Attribute) and node.attr == "host" and _is_client_attr(node.value):
            out.append((node.lineno, "直接讀 .client.host"))
        if isinstance(node, ast.Subscript):
            if _is_client_attr(node.value):
                out.append((node.lineno, "直接取 .client[…]"))
            if _is_scope(node.value) and _const_text(node.slice) == "client":
                out.append((node.lineno, 'scope["client"]'))
        if isinstance(node, ast.Assign) and _is_client_attr(node.value):       # 拆解 `h, p = r.client`、別名 `c = r.client`
            out.append((node.lineno, "取走 .client（拆解／別名）"))
        if isinstance(node, (ast.BinOp, ast.JoinedStr)) and "forwarded" in "".join(
                str(getattr(n, "value", "")).lower() for n in ast.walk(node) if isinstance(n, ast.Constant)):
            out.append((node.lineno, "拼出 forwarded 標頭名"))
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "getattr" and len(node.args) >= 2:
                if _const_text(node.args[1]) == "client" or (_is_client_attr(node.args[0]) and _const_text(node.args[1]) == "host"):
                    out.append((node.lineno, "getattr 讀 client／host"))
            if isinstance(f, ast.Attribute) and f.attr == "get" and _is_scope(f.value) and node.args and _const_text(node.args[0]) == "client":
                out.append((node.lineno, 'scope.get("client")'))
    return out


def _scanned_files():
    roots = [_BACKEND]
    if (_BACKEND.parent / "tools").is_dir():
        roots.append(_BACKEND.parent / "tools")
    for root in roots:
        for p in root.rglob("*.py"):
            rel = p.relative_to(root).as_posix()
            if root is not _BACKEND:
                rel = "../tools/" + rel
            if rel.startswith("tests/") or "/tests/" in rel or ".venv" in rel or "node_modules" in rel or p.name == "conftest.py":
                continue
            if rel in _ALLOWED:
                continue
            yield rel, p


def test_no_code_outside_the_helper_reads_xff_or_the_raw_peer_address():
    offenders = []
    for rel, p in _scanned_files():
        try:
            found = _offences(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        offenders += ["%s:%d  %s" % (rel, n, what) for n, what in found]
    assert not offenders, "來源 IP 一律走 helpers.client_ip.client_ip(request)（不可自己讀 XFF／client.host／scope client）：\n" + "\n".join(offenders)


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
#: 每種繞過寫法一個正對照（K 審 N1）：掃描器要全部抓得到
_BYPASS_SNIPPETS = {
    "client[0]": "def f(r):\n    return r.client[0]\n",
    "unpack client": "def f(r):\n    h, p = r.client\n    return h\n",
    "getattr host": "def f(r):\n    return getattr(r.client, 'host')\n",
    "getattr client": "def f(r):\n    return getattr(r, 'client')\n",
    "scope subscript": "def f(r):\n    return r.scope['client']\n",
    "scope.get": "def f(r):\n    return r.scope.get('client')\n",
    "bare scope": "def f(scope):\n    return scope['client'][0]\n",
    "x-real-ip": "def f(r):\n    return r.headers.get('X-Real-IP')\n",
    "cf-connecting-ip": "def f(r):\n    return r.headers.get('cf-connecting-ip')\n",
    "forwarded": "def f(r):\n    return r.headers['Forwarded']\n",
    "alias client": "def f(r):\n    c = r.client\n    return c.host\n",
    "concat header": "def f(r):\n    return r.headers.get('x-forwarded-' + 'for')\n",
    "fstring header": "def f(r, k):\n    return r.headers.get(f'x-forwarded-{k}')\n",
    "bytes header": "def f(scope):\n    return dict(scope['headers']).get(b'x-forwarded-for')\n",
}


def test_guard_positive_control_the_scanner_flags_the_old_code_and_ignores_prose():
    assert [w for _n, w in _offences(_OLD_CODE)] == ["讀代理標頭 x-forwarded-for", "直接讀 .client.host"]
    assert _offences(_PROSE_ONLY) == []


@pytest.mark.parametrize("name", sorted(_BYPASS_SNIPPETS))
def test_guard_positive_control_every_bypass_spelling_is_flagged(name):
    assert _offences(_BYPASS_SNIPPETS[name]), "掃描器漏掉這種寫法：%s" % name


def test_guard_does_not_flag_the_normal_call():
    assert _offences("from helpers.client_ip import client_ip\ndef f(r):\n    return client_ip(r)\n") == []
