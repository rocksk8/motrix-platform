# -*- coding: utf-8 -*-
"""外網來源判定＋外網強制兩步驟驗證（TOTP）的規則（2026-11-12「外網登入強化」票）。

[單位] helper:external_access    [層] L1    [穩定度] 實作
[公開介面] DEFAULT_ENFORCED_ROLES, DEFAULT_EXTERNAL_HOSTS, DEFAULT_INTERNAL_NETWORKS, ENFORCEABLE_ROLES, INTERNAL_PEER_NAMES, SETTINGS_GROUP, classify, enforced_roles,
    external_hosts, internal_networks, totp_refusal_message, totp_required_for
[契約題] tests/test_external_login_hardening_2026_11_12.py
[不變式]
  ① **「外網」＝請求不是從公司內網來的**。判斷順序（任何一條成立就是外網；**判斷不出來一律當外網**，保守預設）：
       a. 帶 Cloudflare 隧道標頭（`CF-Connecting-IP`／`CF-Ray`／`CF-Visitor`／`CF-IPCountry`）⇒ 外網（經隧道進來的請求一定有，本機／區網直連不會有）；
       b. `Host` 標頭是設定的外網網域（預設空：外網通道的標頭與來源位址已能判出；要加第二層就在設定中心填網域）⇒ 外網；
       c. 帶 `X-Forwarded-*`／`Forwarded`／`X-Real-IP` 任一代理標頭 ⇒ 外網（區網使用者的瀏覽器不會送；有代理介入就不當內網）；
       d. 來源 IP（`helpers.client_ip.client_ip`，**永遠不讀偽造得了的 XFF**，只信 T80 的可信判斷）解析不出來、是 loopback（除非打開開關，見②b）、或不在「內網網段」⇒ 外網；
       e. 其餘（沒有任何代理痕跡、且來源 IP 在內網網段）⇒ 內網。
     偽造只會往「更嚴」的方向：區網使用者自己加 CF 標頭或改 Host ⇒ 被當外網（要 TOTP）；外網使用者**無法**把自己變成內網——標頭由 Cloudflare 加上、
     來源 IP 由 T80 可信判斷（對端 loopback 才採信 `CF-Connecting-IP`；其餘用 TCP 對端）。
  ②b **本機直連（loopback：127.x／::1）預設不算內網**（hichan-1 審查 F2）：對端是 loopback、又沒有任何 Cloudflare／代理標頭的請求，
     可能是在伺服器本機操作的人，也可能是同機的非 Cloudflare 代理（netsh portproxy、frp、同機 nginx 去掉標頭後轉進來）——後者代表任何外部使用者都能變成「內網」
     而免除 TOTP 與帳號鎖定，所以保守判成外網。影響：直接在正式機上開 `https://localhost:666` 登入的人，若角色被要求 TOTP 就必須已啟用（最高管理者已啟用）；
     真的需要本機免 TOTP，由最高管理者在設定中心打開「本機直連算內網」（`loopback_is_internal`，放寬方向，走確認期間＋第二位最高管理者核准）。
  ② 「內網網段」可在設定中心調整，但**只收私有／loopback／link-local 網段**（`ipaddress` 的 `is_private`）：填公網網段或 0.0.0.0/0 的那一筆直接忽略，
     所以設定不可能把「全世界」變成內網（安全類設定只准加嚴，不能被濫用成放行）。全部都被忽略／讀不到 ⇒ 退回預設的私有網段。
  ③ 強制 TOTP 的角色清單與總開關存在設定中心群組 `external_login`；讀不到設定 ⇒ `settings_registry.get` 回程式預設（總開關開、三種角色）＝**往嚴的一邊**。
  ④ 只管「登入」（建立 session 的那一刻）；已發出的 session 不綁來源。內網登入行為完全不變。
  ⑤ `demo` 示範帳號不受強制（它只碰獨立的示範資料庫，不碰正式資料）。
只依賴標準庫與 `settings_registry`（讀取），不認識任何業務。
"""
import ipaddress
import logging
from typing import Optional

from helpers.client_ip import CLOUDFLARE_HEADERS, client_ip as _trusted_client_ip, has_proxy_headers

logger = logging.getLogger(__name__)

SETTINGS_GROUP = "external_login"
DEFAULT_EXTERNAL_HOSTS = ""            # 不寫死公司網域（框架優先）；正式機由超管在設定中心填
DEFAULT_INTERNAL_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10"
#: 可以被設定「外網強制 TOTP」的角色（= `helpers.auth.VALID_ROLES`）；預設前三種開
ENFORCEABLE_ROLES = ("superadmin", "admin", "finance", "sales", "engineer", "viewer")
DEFAULT_ENFORCED_ROLES = ("superadmin", "admin", "finance")
#: 不是 IP、但視為內網的「對端名稱」。正式環境是空的（對端一定是 IP）；測試的 TestClient 對端叫 "testclient"，由 conftest 暫時放進來。
INTERNAL_PEER_NAMES: frozenset = frozenset()


def _get(key: str, default):
    try:
        from helpers import settings_registry as SR
        v = SR.get(SETTINGS_GROUP, key)
        return default if v is None else v
    except Exception:                                        # noqa: BLE001
        return default


def _split(text: str):
    return [p.strip() for p in str(text or "").replace(";", ",").replace("\n", ",").replace(" ", ",").split(",") if p.strip()]


def external_hosts() -> frozenset:
    """設定的外網網域（小寫、去掉埠號）。空 ⇒ 沒有 Host 規則（其他規則照常）。"""
    return frozenset(h.lower().rstrip(".") for h in _split(_get("external_hosts", DEFAULT_EXTERNAL_HOSTS)))


def internal_networks() -> list:
    """內網網段清單（只收私有／loopback／link-local；其餘忽略並記 warning）。全部無效 ⇒ 預設網段。"""
    nets = []
    for raw in _split(_get("internal_networks", DEFAULT_INTERNAL_NETWORKS)):
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            logger.warning("external_access: 內網網段格式不合法，忽略：%r", raw[:64])
            continue
        if net.is_loopback:                                  # loopback 不由網段清單決定（見不變式②b），只看 `loopback_is_internal`
            logger.warning("external_access: loopback 網段不收進內網清單（請用「本機直連算內網」開關），忽略：%s", net)
            continue
        if not (net.is_private or net.is_link_local):
            logger.warning("external_access: 內網網段不是私有網段，忽略：%s", net)
            continue
        nets.append(net)
    if not nets:
        nets = [ipaddress.ip_network(p) for p in _split(DEFAULT_INTERNAL_NETWORKS)]
    return nets


def _host_of(request) -> str:
    raw = (request.headers.get("host") or "").strip().lower()
    if raw.startswith("["):                                  # [::1]:666
        return raw[1:].split("]", 1)[0]
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def classify(request, ip: Optional[str] = None) -> tuple:
    """⇒ `(is_external: bool, reason: str)`。規則見模組說明①。**永不丟例外**（任何例外 ⇒ 外網）。"""
    try:
        headers = request.headers
        keys = {str(k).lower() for k in headers.keys()}
        if keys & set(CLOUDFLARE_HEADERS):
            return True, "cloudflare_header"
        hosts = external_hosts()
        if hosts and _host_of(request) in hosts:
            return True, "external_host"
        if has_proxy_headers(headers):                       # X-Forwarded-*／Forwarded／X-Real-IP：讀標頭的邏輯只放在 helpers.client_ip
            return True, "proxy_header"
        addr = ip if ip else _trusted_client_ip(request)
        if addr in INTERNAL_PEER_NAMES:
            return False, "internal_peer"
        try:
            parsed = ipaddress.ip_address(str(addr).strip())
        except ValueError:
            return True, "unknown_ip"
        mapped = getattr(parsed, "ipv4_mapped", None)
        if mapped is not None:
            parsed = mapped
        if parsed.is_loopback:
            return (False, "loopback_internal") if _get("loopback_is_internal", 0) not in (0, False, "0") else (True, "loopback")
        for net in internal_networks():
            if parsed.version == net.version and parsed in net:
                return False, "internal_network"
        return True, "public_ip"
    except Exception:                                        # noqa: BLE001
        logger.warning("external_access.classify 失敗，保守當成外網", exc_info=True)
        return True, "error"


def enforced_roles() -> frozenset:
    """外網登入必須先啟用 TOTP 的角色集合（總開關關閉 ⇒ 空集合）。"""
    try:
        on = _get("ext_totp_enabled", 1)
        if on in (0, False, "0"):
            return frozenset()
        out = set()
        for role in ENFORCEABLE_ROLES:
            default = 1 if role in DEFAULT_ENFORCED_ROLES else 0
            if _get("ext_totp_role_" + role, default) not in (0, False, "0"):
                out.add(role)
        return frozenset(out)
    except Exception:                                        # noqa: BLE001
        return frozenset(DEFAULT_ENFORCED_ROLES)


def totp_required_for(role: str, username: str = "") -> bool:
    """這個角色從外網登入時，是否必須已啟用 TOTP。`demo` 示範帳號不適用。"""
    if (username or "") == "demo":
        return False
    return (role or "") in enforced_roles()


def totp_refusal_message() -> str:
    return "從外網登入需要先啟用兩步驟驗證。請先在公司內網登入，到個人設定啟用兩步驟驗證後，再從外網登入。"
