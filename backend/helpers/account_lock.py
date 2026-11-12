# -*- coding: utf-8 -*-
"""單一帳號登入鎖定（不分來源 IP；2026-11-12「外網登入強化」票）。

[單位] helper:account_lock    [層] L1    [穩定度] 實作
[公開介面] DEFAULTS, KEY_PREFIX, SETTINGS_GROUP, audit_event, check, clear, clear_failures, config, is_locked, list_locks, load_from_db, record_failure, reset_for_tests, unlock
[契約題] tests/test_external_login_hardening_2026_11_12.py
[為什麼要有] 原本只有「每個來源 IP 錯 5 次鎖 15 分鐘」：攻擊者換很多 IP（或經 Cloudflare 換出口）就能對同一個帳號持續猜密碼。這裡補「同一個帳號、不分 IP」的鎖。
[取捨與預設（模式 1＝只鎖外網，預設）]
  經典做法（任何來源失敗 N 次就整個帳號鎖死）有 DoS：任何人故意輸錯就能把別人鎖在門外，包含在公司內網的本人。所以預設：
    · **只計外網來源的失敗**（內網打錯不計入——內網使用者已受區網與每 IP 鎖定保護）；
    · 鎖住時**只擋外網來源**的登入，內網照常能登入——攻擊者最多讓「這個帳號暫時不能從外網登入」，不能讓人進不了系統；
    · **內網登入成功會解除該帳號的鎖**（本人回到公司就能解），超級管理員也能手動解除；30 分鐘後自動解除；
    · 鎖定期間的外網嘗試一律被擋、**不計數也不延長鎖定**（攻擊者無法靠持續送請求把鎖無限延長）；
    · 任何帳號名（含不存在的）都照同一套計數與回應 ⇒ 鎖定回應不洩漏帳號是否存在。
  模式 2（設定中心可選）＝不分來源計數、鎖住時連內網也擋：最嚴，代價是有 DoS 風險（只建議在遭受持續攻擊時暫時使用）。
[不變式]
  ① 計數窗口：滾動 `window_s` 秒內失敗次數達 `threshold` ⇒ 鎖 `lock_s` 秒；鎖定寫進 `login_rate_limit`（鍵 `acct:<小寫帳號>`），重啟後仍有效。
  ② 失敗計數只在記憶體（重啟歸零；最壞情況只是少算）；表有上限（`_MAX_ENTRIES`），超過清最舊的。
  ③ 鎖定的那一刻：寫一筆稽核（`auth.account_locked`，記帳號、來源 IP、門檻、鎖定分鐘數、**不記密碼**）並呼叫 `helpers.auth_alert.on_lockout(scope="account")`
     （告警由 hichan-3 的 auth_lockout 事件負責節流與發送；任何例外只記 log，不影響登入回應）。
  ④ 本模組**永不讓登入流程多出例外**：`record_failure` 內部例外全吞掉並記 log；`check` 讀不到設定時用預設門檻。
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

KEY_PREFIX = "acct:"
SETTINGS_GROUP = "external_login"
DEFAULTS = {"lock_threshold": 10, "lock_window_min": 30, "lock_minutes": 30, "lock_scope": 1}
_MAX_ENTRIES = 10_000
_MAX_NAME = 64

_lock = threading.Lock()
_fails: dict = {}          # name -> [monotonic 失敗時間, ...]
_locks: dict = {}          # name -> locked_until（monotonic）


def _name(username) -> str:
    return str(username or "").strip().lower()[:_MAX_NAME]


def config() -> dict:
    """⇒ {threshold, window_s, lock_s, scope}（scope 1＝只鎖外網、2＝連內網也擋）。讀不到設定 ⇒ 預設。"""
    vals = {}
    try:
        from helpers import settings_registry as SR
        for k, d in DEFAULTS.items():
            v = SR.get(SETTINGS_GROUP, k)
            vals[k] = d if isinstance(v, bool) or not isinstance(v, int) else v
    except Exception:                                        # noqa: BLE001
        vals = dict(DEFAULTS)
    return {"threshold": max(1, vals.get("lock_threshold", 10)), "window_s": max(60, vals.get("lock_window_min", 30) * 60),
            "lock_s": max(60, vals.get("lock_minutes", 30) * 60), "scope": 2 if vals.get("lock_scope", 1) == 2 else 1}


def reset_for_tests() -> None:
    with _lock:
        _fails.clear()
        _locks.clear()


def _applies(external: bool, scope: int) -> bool:
    """這次嘗試是否受帳號鎖管：模式 1 只管外網；模式 2 全管。"""
    return bool(external) or scope == 2


def is_locked(username, external: bool = True, now: Optional[float] = None) -> int:
    """⇒ 還要鎖幾秒（0＝沒鎖、或這個來源不受管）。"""
    name = _name(username)
    if not name:
        return 0
    mono = time.monotonic() if now is None else now
    cfg = config()
    with _lock:
        until = _locks.get(name)
        if until is None:
            return 0
        if until <= mono:
            _locks.pop(name, None)
            expired = True
        else:
            expired = False
    if expired:
        _db_clear(name)
        return 0
    return int(until - mono) + 1 if _applies(external, cfg["scope"]) else 0


def check(username, external: bool = True) -> int:
    """登入入口呼叫：⇒ 剩餘鎖定秒數（0＝可繼續）。呼叫端自己決定回 429 的文字。"""
    try:
        return is_locked(username, external)
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.check 失敗（放行，由其他防線處理）", exc_info=True)
        return 0


def record_failure(username, ip: str, external: bool, source: str = "password", now: Optional[float] = None) -> str:
    """記一次登入失敗。⇒ `locked`（這次剛好達到門檻而鎖定）／`counted`／`ignored`（內網失敗在模式 1 不計）／`already`（已鎖定中）／`error`。**永不丟例外**。"""
    try:
        name = _name(username)
        if not name:
            return "ignored"
        cfg = config()
        if not _applies(external, cfg["scope"]):
            return "ignored"
        mono = time.monotonic() if now is None else now
        with _lock:
            until = _locks.get(name)
            if until is not None and until > mono:
                return "already"                            # 鎖定期間不計數、不延長
            lst = [t for t in _fails.get(name, ()) if mono - t < cfg["window_s"]]
            lst.append(mono)
            if len(lst) < cfg["threshold"]:
                _fails[name] = lst
                if len(_fails) > _MAX_ENTRIES:
                    _prune_locked(mono, cfg["window_s"])
                return "counted"
            _fails.pop(name, None)
            _locks[name] = mono + cfg["lock_s"]
            fails = len(lst)
        _on_locked(name, str(username or "")[:_MAX_NAME], ip, external, source, fails, cfg)
        return "locked"
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.record_failure 失敗（不影響登入回應）", exc_info=True)
        return "error"


def _prune_locked(mono: float, window_s: float) -> None:
    """（持有 `_lock`）表超過上限：清掉整窗都沒再失敗的列；還是太多就清最舊的一半。"""
    for k in [k for k, v in _fails.items() if not v or mono - v[-1] >= window_s]:
        del _fails[k]
    if len(_fails) > _MAX_ENTRIES:
        for k in sorted(_fails, key=lambda n: _fails[n][-1])[: len(_fails) // 2]:
            del _fails[k]
    for k in [k for k, u in _locks.items() if u <= mono]:
        del _locks[k]


def _on_locked(name: str, shown: str, ip: str, external: bool, source: str, fails: int, cfg: dict) -> None:
    logger.warning("Account lockout: account=%s ip=%s external=%s source=%s locked for %ds", name, ip, external, source, cfg["lock_s"])
    _db_write(name, cfg["lock_s"])
    _audit("auth.account_locked", shown, ip, {"ip": ip or "", "external": bool(external), "source": source, "fails": fails,
                                             "windowMinutes": cfg["window_s"] // 60, "lockMinutes": cfg["lock_s"] // 60, "scope": cfg["scope"]},
           "account_locked", 429)
    try:
        from helpers import auth_alert
        auth_alert.on_lockout(KEY_PREFIX + name, ip, [shown], fails, cfg["lock_s"], scope="account")
    except Exception as exc:                                  # noqa: BLE001  告警永遠不能讓登入回應變 500
        logger.warning("帳號鎖定告警呼叫失敗（不影響登入）：%s", type(exc).__name__)


def clear_failures(username) -> None:
    """登入成功：清掉該帳號的失敗計數（不動已存在的鎖）。"""
    name = _name(username)
    with _lock:
        _fails.pop(name, None)


def clear(username, ip: str = "", by: str = "", reason: str = "", audit: bool = True) -> bool:
    """解除鎖定＋清計數。⇒ 原本有鎖才回 True；有鎖且 `audit` 時寫稽核 `auth.account_unlocked`（手動解鎖由端點用 `_audit` 記操作者，這裡傳 audit=False）。"""
    name = _name(username)
    with _lock:
        _fails.pop(name, None)
        had = _locks.pop(name, None) is not None
    _db_clear(name)
    if had and audit:
        _audit("auth.account_unlocked", name, ip, {"ip": ip or "", "by": by, "reason": reason}, "", 200, result="ok")
    return had


def unlock(username, by: str) -> bool:
    """超級管理員手動解鎖（稽核由呼叫端端點寫，帶操作者身分）。"""
    return clear(username, by=by, reason="manual", audit=False)


def list_locks() -> list:
    """目前有效的帳號鎖 ⇒ [{username, secondsLeft}]（給超級管理員的解鎖清單）。"""
    mono = time.monotonic()
    with _lock:
        return [{"username": n, "secondsLeft": int(u - mono) + 1} for n, u in sorted(_locks.items()) if u > mono]


# ── 持久化（沿用 `login_rate_limit` 表，鍵 `acct:<帳號>`；不新增資料表）────────────────────────
def _db_write(name: str, lock_s: int) -> None:
    try:
        from db import get_db
        until = (datetime.now() + timedelta(seconds=lock_s)).isoformat()
        conn = get_db()
        try:
            conn.execute("INSERT INTO login_rate_limit (ip, locked_until) VALUES (?, ?) "
                         "ON CONFLICT(ip) DO UPDATE SET locked_until=excluded.locked_until", (KEY_PREFIX + name, until))
            conn.commit()
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock: 寫入鎖定失敗（記憶體內仍有效）", exc_info=True)


def _db_clear(name: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        try:
            conn.execute("DELETE FROM login_rate_limit WHERE ip=?", (KEY_PREFIX + name,))
            conn.commit()
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock: 清除鎖定失敗", exc_info=True)


def load_from_db() -> int:
    """啟動時把仍有效的帳號鎖載回記憶體。⇒ 載入筆數。"""
    n = 0
    try:
        from db import get_db
        conn = get_db()
        try:
            rows = conn.execute("SELECT ip, locked_until FROM login_rate_limit WHERE ip LIKE ?", (KEY_PREFIX + "%",)).fetchall()
        finally:
            conn.close()
        now_wall, now_mono = datetime.now(), time.monotonic()
        with _lock:
            for r in rows:
                try:
                    delta = (datetime.fromisoformat(r["locked_until"]) - now_wall).total_seconds()
                except Exception:                            # noqa: BLE001
                    continue
                if delta > 0:
                    _locks[r["ip"][len(KEY_PREFIX):]] = now_mono + delta
                    n += 1
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock: 載入帳號鎖失敗", exc_info=True)
    return n


# ── 稽核（直接寫 audit_log，欄位與 helpers.audit._audit_login_failed 相同；不記密碼）────────────────
def _audit(action: str, username: str, ip: str, detail: dict, reason_code: str, status: int, result: str = "fail") -> None:
    try:
        from db import get_db
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
                "module,case_no,ref_no,result,reason_code,status_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(), None, (username or "")[:64], "", action, "user", (username or "")[:64], (username or "")[:64],
                 json.dumps(detail, ensure_ascii=False), "auth", "", "", result, reason_code or "", status))
            conn.commit()
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock: 稽核寫入失敗", exc_info=True)


def audit_event(action: str, username: str, ip: str, detail: dict, reason_code: str, status: int) -> None:
    """給 routers/auth 寫『外網強制 TOTP 拒絕』等稽核用（同一套欄位）。"""
    _audit(action, username, ip, detail, reason_code, status)
