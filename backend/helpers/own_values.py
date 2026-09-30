# -*- coding: utf-8 -*-
"""本公司環境的預設值（去識別化）：伺服器 IP 不寫在程式碼裡，放在 own 資料檔的 `network` 區段（tools/platform/own_payload.py）。

- 有資料檔（本公司環境）：CORS 預設白名單、通知信「系統網址」的預設值與舊版逐字相同（行為不變）。
- 沒有資料檔（客戶環境）：CORS 預設只有本機（localhost／127.0.0.1）；系統網址預設留空，要在通知設定頁填。
- 資料檔的 network 區段綁定「取自哪一版 main.py」（`NETWORK_SOURCE_BLOB`）；不符就忽略。永不丟例外。
"""
import ipaddress

#: 取出伺服器 IP 的來源：去識別化之前的 backend/main.py（git 歷史，含寫死的位址）。
NETWORK_SOURCE_BLOB = "ffd66139d69f340e87cb99b9205d0bd9b707d03f"
PORT = 666


def own_section(name: str, source_blob: str) -> dict:
    try:
        from db import _frozen_own_payload
        sec = _frozen_own_payload().get(name)
        if isinstance(sec, dict) and sec.get("source_blob") == source_blob:
            return sec
    except Exception:                                            # noqa: BLE001 — 缺檔（客戶環境）是正常情況
        pass
    return {}


def server_ip() -> str:
    """本公司伺服器 IP（IPv4 字串）；沒有資料檔或格式不對 ⇒ 空字串。"""
    v = own_section("network", NETWORK_SOURCE_BLOB).get("server_ip")
    try:
        return str(ipaddress.IPv4Address(v)) if isinstance(v, str) else ""
    except ValueError:
        return ""


def default_cors_origins() -> list:
    """CORS 預設白名單。順序與舊版相同：http 本機兩筆、（本公司）http IP、https 本機兩筆、（本公司）https IP。"""
    ip = server_ip()
    out = ["http://localhost:%d" % PORT, "http://127.0.0.1:%d" % PORT]
    if ip:
        out.append("http://%s:%d" % (ip, PORT))
    out += ["https://localhost:%d" % PORT, "https://127.0.0.1:%d" % PORT]
    if ip:
        out.append("https://%s:%d" % (ip, PORT))
    return out


def default_base_url() -> str:
    """通知信裡「系統網址」的預設值：本公司環境 ⇒ https://<IP>:666；客戶環境 ⇒ 空（要在通知設定頁填）。"""
    ip = server_ip()
    return "https://%s:%d" % (ip, PORT) if ip else ""
