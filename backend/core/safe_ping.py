# -*- coding: utf-8 -*-
"""對外打卡的安全 GET（2026-11-13；備份與監控頁的對抗式審查 H1／M1／L5）。

[單位] plat:safe_ping    [層] L0    [穩定度] 實作
[公開介面] ALLOWED_PORTS, DEADLINE_SECONDS, PingFailed, RedirectBlocked, UnsafeTarget, check_url, get, ip_is_public, public_addresses, resolve_host
[不變式]
  ① **只用標準庫**（心跳排程 `heartbeat_job.py` 是獨立行程、不載入 app，也用本檔）。
  ② **絕不跟隨轉址**：回 3xx ⇒ `RedirectBlocked`（算失敗）。原因：網址是「外部服務」的位址，但伺服器端收到 302 就會自己去打
     `Location` 指的任何地方（內網、雲端中繼資料位址），那是 SSRF；檢查只對第一跳做就會被繞過。
  ③ **連線前先解析、每個位址都必須是公開位址**（`ip_is_public`：不是 loopback／私網／link-local／CGNAT／組播／保留／未指定，
     IPv4 對映的 IPv6、6to4、Teredo、NAT64 先拆出內嵌的 IPv4 再判斷）；**連線直接連那個已檢查過的 IP**（`Host` 標頭與 TLS 的
     SNI／憑證比對仍用原主機名），所以檢查完到連線之間 DNS 被換掉（DNS rebinding）也沒用。
  ④ **只准 80／443**（`ALLOWED_PORTS`）：不給它掃內網服務的連接埠。
  ⑤ **整體時限**（`DEADLINE_SECONDS`）：連線、握手、讀標頭加起來超過就強制關線，慢速滴水式回應拖不住呼叫端。
  ⑥ 網址字串檢查（`check_url`）：拒絕帳密（`user@`）、`localhost`／`.localhost`／`.local`／`.internal`／`.localdomain`／`.lan`／`.home.arpa`、
     沒有點的單標籤主機名、結尾的點、非標準寫法的數字位址（`127.1`、`2130706433`、`0x7f.0.0.1`、`0`）。
  ⑦ 例外訊息只有類別，**不含網址**（healthchecks 這類服務的密鑰就在路徑裡）。
[契約題] tests/test_backup_monitor_2026_11_13.py
"""
import http.client
import ipaddress
import socket
import ssl
import threading
import time
import urllib.parse

#: 允許的目的連接埠
ALLOWED_PORTS = (80, 443)
#: 整體時限（秒）：解析＋連線＋握手＋讀標頭
DEADLINE_SECONDS = 15
_CONNECT_TIMEOUT = 10
_BAD_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".lan", ".home.arpa", ".intranet", ".corp")


class PingFailed(Exception):
    """打卡沒成功；`kind`＝redirect／unsafe／dns／tls／timeout／connect／response。訊息永遠不含網址。"""

    def __init__(self, kind: str = "response"):
        super().__init__(kind)
        self.kind = kind


class UnsafeTarget(PingFailed):
    """目標位址不合格（內網、本機、不允許的連接埠…）；`reason`＝給使用者看的白話。"""

    def __init__(self, reason: str):
        super().__init__("unsafe")
        self.reason = reason


class RedirectBlocked(PingFailed):
    def __init__(self, status: int):
        super().__init__("redirect")
        self.status = int(status)


_INTERNAL_MSG = "這是本機或公司內網的位址，外部監控服務無法連線至該位址。請貼上監控服務所提供的網址。"


def _embedded_v4(ip):
    """IPv6 位址裡藏的 IPv4（對映／6to4／Teredo／NAT64）；沒有 ⇒ None。"""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def ip_is_public(ip) -> bool:
    """`ip`（字串或 ipaddress 物件）是不是公開位址。"""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0] if isinstance(ip, str) else ip)
    except ValueError:
        return False
    inner = _embedded_v4(a)
    if inner is not None and not ip_is_public(inner):
        return False
    if a.version == 6 and a in ipaddress.ip_network("64:ff9b:1::/48"):
        return False
    return bool(a.is_global) and not (a.is_multicast or a.is_unspecified or a.is_loopback)


def resolve_host(host: str, port: int) -> list:
    """主機名 ⇒ 位址清單（字串）。測試時可替換。"""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out = []
    for fam, _t, _p, _c, sa in infos:
        ip = sa[0]
        if ip not in out:
            out.append(ip)
    return out


def check_url(url: str) -> tuple:
    """只看網址字串（不連網）⇒ `(scheme, host, port)`；不合格 ⇒ `UnsafeTarget`。"""
    sp = urllib.parse.urlsplit((url or "").strip())
    if sp.scheme not in ("http", "https") or not sp.hostname:
        raise UnsafeTarget("網址要以 https:// 開頭，例如 https://hc-ping.com/…（從 healthchecks.io 的 Ping URL 複製）。")
    if sp.username is not None or sp.password is not None or "@" in sp.netloc:
        raise UnsafeTarget("網址裡不能含帳號密碼（「@」前面的部分）。請貼上監控服務所提供的完整 Ping URL。")
    host = sp.hostname.strip().lower()
    while host.endswith("."):
        host = host[:-1]
    if not host:
        raise UnsafeTarget(_INTERNAL_MSG)
    try:
        port = sp.port
    except ValueError:
        raise UnsafeTarget("網址的連接埠不正確。")
    if port is None:
        port = 443 if sp.scheme == "https" else 80
    if port not in ALLOWED_PORTS:
        raise UnsafeTarget("網址的連接埠不能自訂，只能使用一般網站的 80 或 443。請貼上監控服務所提供的原始網址。")
    if host == "localhost" or host.endswith(_BAD_SUFFIXES):
        raise UnsafeTarget(_INTERNAL_MSG)
    literal = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    if literal is None:
        try:
            socket.inet_aton(host)             # 127.1／2130706433／0x7f.0.0.1／0 這類舊式寫法：連得到、但人眼看不出是誰
            raise UnsafeTarget("請用網域名稱，不要用數字位址的簡寫（例如 127.1）。")
        except OSError:
            pass
        if "." not in host:
            raise UnsafeTarget(_INTERNAL_MSG)  # 沒有點的單一名稱＝內網機器名
    elif not ip_is_public(literal):
        raise UnsafeTarget(_INTERNAL_MSG)
    return sp.scheme, host, port


def _resolve_within(host: str, port: int, timeout: float) -> list:
    """在背景執行緒解析、最多等 `timeout` 秒（`getaddrinfo` 本身沒有逾時；DNS 慢或被卡住時不能把呼叫端拖到系統預設的逾時）。
    超時 ⇒ `PingFailed("timeout")`；解析失敗 ⇒ `PingFailed("dns")`。逾時的執行緒是 daemon，結果丟棄。"""
    box = {}

    def run():
        try:
            box["v"] = resolve_host(host, port)
        except Exception as exc:  # noqa: BLE001
            box["e"] = exc
    t = threading.Thread(target=run, name="safe-ping-dns", daemon=True)
    t.start()
    t.join(max(0.05, timeout))
    if t.is_alive():
        raise PingFailed("timeout")
    if "e" in box:
        raise PingFailed("dns") from None
    return box.get("v") or []


def public_addresses(host: str, port: int, timeout: float = 5.0) -> list:
    """解析並確認「每一個」位址都是公開的；回清單。任何一個不是 ⇒ `UnsafeTarget`（不讓攻擊者用一組混合的答案挑位址）。
    解析最多等 `timeout` 秒（`get` 傳入整體時限剩下的時間）。"""
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        addrs = _resolve_within(host, port, timeout)
    if not addrs:
        raise PingFailed("dns")
    if not all(ip_is_public(a) for a in addrs):
        raise UnsafeTarget(_INTERNAL_MSG)
    return addrs


def _connect_pinned(conn, ip: str, timeout: float):
    return socket.create_connection((ip, conn.port), timeout=timeout)


class _PinnedHTTP(http.client.HTTPConnection):
    _pin_ip = None

    def connect(self):
        self.sock = _connect_pinned(self, self._pin_ip, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    _pin_ip = None
    _pin_ctx = None

    def connect(self):
        raw = _connect_pinned(self, self._pin_ip, self.timeout)
        self.sock = raw
        self.sock = self._pin_ctx.wrap_socket(raw, server_hostname=self.host)


def get(url: str, *, timeout: float = _CONNECT_TIMEOUT, deadline: float = None) -> int:
    """對外 GET 一次，回 HTTP 狀態碼（只讀標頭，不讀內文）。
    3xx ⇒ `RedirectBlocked`；位址不合格 ⇒ `UnsafeTarget`；其他連不上 ⇒ `PingFailed`（`kind` 區分）。不跟隨轉址。"""
    deadline = DEADLINE_SECONDS if deadline is None else deadline
    scheme, host, port = check_url(url)
    started = time.monotonic()
    addrs = public_addresses(host, port, timeout=deadline)
    sp = urllib.parse.urlsplit(url.strip())
    target = (sp.path or "/") + ("?" + sp.query if sp.query else "")
    last = PingFailed("connect")
    for ip in addrs:
        left = deadline - (time.monotonic() - started)
        if left <= 0:
            last = PingFailed("timeout")
            break
        conn = (_PinnedHTTPS if scheme == "https" else _PinnedHTTP)(host, port, timeout=min(timeout, left))
        conn._pin_ip = ip
        if scheme == "https":
            conn._pin_ctx = ssl.create_default_context()

        def _kill(c=conn):
            s = getattr(c, "sock", None)
            if s is not None:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    s.close()
                except OSError:
                    pass
        watchdog = threading.Timer(left, _kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            conn.request("GET", target, headers={"User-Agent": "motrix-heartbeat/1", "Connection": "close"})
            status = conn.getresponse().status
        except ssl.SSLError:
            raise PingFailed("tls") from None
        except (socket.timeout, TimeoutError):
            last = PingFailed("timeout")
            continue
        except OSError:
            last = PingFailed("connect")
            continue
        except http.client.HTTPException:
            last = PingFailed("response")
            continue
        finally:
            watchdog.cancel()
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        if 300 <= status < 400:
            raise RedirectBlocked(status)
        return status
    raise last
