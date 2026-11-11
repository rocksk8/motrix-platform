# -*- coding: utf-8 -*-
"""可信的來源 IP（2026-11-11，外網存取 go-live 前必修的安全項）。

[單位] plat:client_ip    [層] L0（只依賴標準庫；不認識任何業務）
[公開介面] client_ip, is_loopback, CLOUDFLARE_HEADERS, has_proxy_headers
[不變式] ① **永遠不讀 `X-Forwarded-For`**（用戶端可任意填；以前 `routers/auth.py::_client_ip` 無條件信第一個值 ⇒ 登入鎖定
           〔5 次失敗／15 分鐘，以來源 IP 計〕只要每次換一個 XFF 就繞過 ⇒ 無限次猜密碼）。
         ② 只有「TCP 對端本身是 loopback」才採信 `CF-Connecting-IP`（cloudflared 與本程式同機時，所有外部使用者對本程式而言
           `request.client.host` 都是 127.0.0.1——不採信的話 IP 鎖定會把全部外部使用者綁成同一個桶：一個人輸錯 5 次鎖住所有人，
           稽核紀錄的 IP 也全變 127.0.0.1）。對端不是 loopback（區網、直接連線）⇒ `CF-Connecting-IP` 一律不理。
         ③ `CF-Connecting-IP` 的值必須是合法 IP 才採用（`ipaddress` 解析；亂填、含 scope id 的就退回對端位址），並正規化成標準寫法。
         ④ 拿不到對端 ⇒ "unknown"（跟舊行為一致；不是 loopback，所以不會被當成本機）。

uvicorn 這一層（hichan-13 K 審 S1）：uvicorn 的 ProxyHeadersMiddleware 預設就開，只要 TCP 對端在 `forwarded_allow_ips`（預設 127.0.0.1）
裡，就會用 `X-Forwarded-For` 的「最右邊一個不受信任的位址」改寫 `scope["client"]`——所以 XFF 其實在這支 helper 的**下一層**就被讀過了，
這支只是不再自己讀。這樣仍然安全，前提是兩件事（缺一不可）：
  · `forwarded_allow_ips` 維持 127.0.0.1：所有綁 0.0.0.0 的啟動檔（autostart／restart／start.bat、start_server.ps1）都明寫 `--forwarded-allow-ips 127.0.0.1`（命令列優先於環境變數
    FORWARDED_ALLOW_IPS）；設成 `*` 的話 uvicorn 會對任何對端取 XFF 第一個值 ⇒ 原本的漏洞回來而這支擋不住。守門：
    `test_every_launcher_that_binds_all_interfaces_pins_uvicorn_forwarded_allow_ips`；
  · 前面是 Cloudflare：它會把真實 IP 附加在 XFF 最右邊，攻擊者塞的假值在左邊、被 uvicorn 略過；對端是區網／直連 ⇒ uvicorn 不理 XFF。
    已知殘餘：對端是 loopback、且**沒有**經過 Cloudflare（本機行程、同機的非 Cloudflare 代理）仍可用 XFF 自選桶——外部攻擊者碰不到。
結果：
  · uvicorn 改寫了 ⇒ `request.client.host` 已是真實 IP（非 loopback）⇒ 直接用；
  · 它沒改寫、對端仍是 127.0.0.1 ⇒ 採信 `CF-Connecting-IP`。
"""
import ipaddress
from typing import Optional

#: Cloudflare（含 cloudflared 隧道）一定會帶、而本機瀏覽器直連不會帶的標頭。部署儀表板用來「fail closed」：
#: 帶這些標頭的請求即使對端是 127.0.0.1，也不是「本機使用者」，而是被隧道轉進來的外部請求。
CLOUDFLARE_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-visitor", "cf-ipcountry")


def is_loopback(host: Optional[str]) -> bool:
    """`host` 是不是 loopback 位址（127.0.0.0/8、::1、::ffff:127.x）。空值、非 IP 字串（例如 TestClient 的 "testclient"）都是 False。"""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(str(host).strip())
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback


def _valid_ip(text: str) -> Optional[str]:
    if "%" in text:                                  # IPv6 scope id（fe80::1%eth0）不是來源位址，不採用
        return None
    try:
        ip = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return str(mapped if mapped is not None else ip)


def client_ip(request) -> str:
    """這個請求的來源 IP（給登入鎖定、稽核紀錄用）。規則見模組說明。"""
    client = getattr(request, "client", None)
    peer = (getattr(client, "host", None) or "") if client else ""
    if is_loopback(peer):
        raw = request.headers.get("CF-Connecting-IP", "")
        if raw:
            ok = _valid_ip(raw)
            if ok:
                return ok
    return peer or "unknown"


def has_proxy_headers(headers) -> bool:
    """請求帶了 Cloudflare 隧道的標頭、或任何 X-Forwarded-*／Forwarded？（`headers` 是 Starlette Headers／dict，鍵不分大小寫取）"""
    try:
        keys = {str(k).lower() for k in headers.keys()}
    except Exception:  # noqa: BLE001
        return False
    return bool(keys & set(CLOUDFLARE_HEADERS)) or "x-forwarded-for" in keys or "forwarded" in keys or "x-real-ip" in keys
