# -*- coding: utf-8 -*-
"""本公司環境的預設值（去識別化）：伺服器 IP 不寫在程式碼裡。

## 來源（優先序）
1. **資料庫設定** `system_settings.own_network`（`{"server_ip": "…"}`）——穩態的來源：寫進庫之後不再依賴任何檔案。
2. **own 資料檔**的 `network` 區段（tools/platform/own_payload.py；綁定「取自哪一版 main.py」）——升級後第一次啟動、庫裡還沒有值時用。
兩者都沒有 ⇒ 空字串：CORS 預設只有本機四筆、通知信「系統網址」預設留空（客戶環境的正確行為，要在通知設定頁填）。

## 啟動時（`ensure_own_network()`，main.py 在 init_db 之後呼叫；冪等、不擋啟動）
- 庫裡已有 ⇒ 什麼都不做（`present`）；沒有而資料檔給得出 ⇒ 寫進庫（`stored`）。
- 都沒有：若這個安裝是「本公司」（公司資料符合開發者身分指紋，E4） ⇒ **不拒絕啟動**，記 ERROR、發站內通知給預設管理員（`missing`），
  每次啟動重試；否則是客戶環境（`customer`），什麼都不說。
  ——不回退到「寫死的舊預設值」：那正是要從程式庫移走的東西。本公司環境升級時 own 包一定帶資料檔（建包強制），
  所以第一次啟動一定拿得到值並存進庫；之後資料檔遺失也沒有影響（用庫裡的）。
永不丟例外。
"""
import ipaddress
import json
import logging
import os

logger = logging.getLogger(__name__)

#: 取出伺服器 IP 的來源：去識別化之前的 backend/main.py（git 歷史，含寫死的位址）。
NETWORK_SOURCE_BLOB = "ffd66139d69f340e87cb99b9205d0bd9b707d03f"
SETTING_KEY = "own_network"
PORT = 666


def _valid_ip(v) -> str:
    try:
        return str(ipaddress.IPv4Address(v)) if isinstance(v, str) else ""
    except ValueError:
        return ""


def own_section(name: str, source_blob: str) -> dict:
    try:
        from db import _frozen_own_payload
        sec = _frozen_own_payload().get(name)
        if isinstance(sec, dict) and sec.get("source_blob") == source_blob:
            return sec
    except Exception:                                            # noqa: BLE001 — 缺檔（客戶環境）是正常情況
        pass
    return {}


def _payload_ip() -> str:
    return _valid_ip(own_section("network", NETWORK_SOURCE_BLOB).get("server_ip"))


def _db_ip() -> str:
    """唯讀讀庫（不建庫、不寫入）；任何錯誤（沒有庫、沒有表、JSON 壞）⇒ 空字串。main.py 在 init_db 之前就會呼叫（CORS 在載入時建立）。"""
    try:
        import sqlite3
        from pathlib import Path
        from db import DB_PATH
        if not os.path.isfile(DB_PATH):
            return ""
        conn = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (SETTING_KEY,)).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return ""
        v = json.loads(row[0])
        return _valid_ip(v.get("server_ip") if isinstance(v, dict) else None)
    except Exception:                                            # noqa: BLE001
        return ""


def server_ip() -> str:
    """本公司伺服器 IP（IPv4 字串）；庫裡的設定優先，其次資料檔；都沒有 ⇒ 空字串。"""
    return _db_ip() or _payload_ip()


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


def _is_own_install() -> bool:
    try:
        from helpers.company_setup import is_developer_identity
        from helpers.settings import _get_setting
        profile = _get_setting("company_profile", {}) or {}
        return bool(isinstance(profile, dict) and is_developer_identity(profile))
    except Exception:                                            # noqa: BLE001
        return False


def ensure_own_network() -> str:
    """啟動時（init_db 之後）呼叫。⇒ present／stored／customer／missing（見模組說明）。永不丟例外。"""
    try:
        if _db_ip():
            return "present"
        ip = _payload_ip()
        if ip:
            from helpers.settings import _set_setting
            _set_setting(SETTING_KEY, {"server_ip": ip})
            logger.info("own_network：已把伺服器位址存進系統設定（%s）", SETTING_KEY)
            return "stored"
        if _is_own_install():
            msg = ("本公司安裝缺少伺服器位址設定（system_settings.own_network 與 own 資料檔都沒有）："
                   "CORS 預設只有本機、通知信系統網址為空。請把 own_payload.json 放回 backend/migrations_frozen/ 後重啟。")
            logger.error("own_network：%s", msg)
            try:
                from helpers.audit import _notify
                from helpers.startup import builtin_admin_username
                _notify(builtin_admin_username(), "system_alert", SETTING_KEY, "系統位址設定", msg)
            except Exception:                                    # noqa: BLE001 — 告警是盡力而為，不可以擋啟動
                logger.warning("own_network：站內通知寫不進去", exc_info=True)
            return "missing"
        return "customer"
    except Exception:                                            # noqa: BLE001
        logger.warning("own_network：檢查失敗（不擋啟動）", exc_info=True)
        return "customer"
