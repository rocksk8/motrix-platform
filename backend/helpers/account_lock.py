# -*- coding: utf-8 -*-
"""單一帳號登入鎖定（不分來源 IP；2026-11-12「外網登入強化」票）。

[單位] helper:account_lock    [層] L1    [穩定度] 實作
[公開介面] DEFAULTS, KEY_PREFIX, SETTINGS_GROUP, audit_event, begin_attempt, check, clear, clear_failures, config, is_locked, list_locks, load_from_db, record_failure, release, reset_for_tests, safe_label, unlock
[契約題] tests/test_external_login_hardening_2026_11_12.py、tests/test_attack_h1_extlogin_2026_11_12.py
[為什麼要有] 原本只有「每個來源 IP 錯 5 次鎖 15 分鐘」：攻擊者換很多 IP（或經 Cloudflare 換出口）就能對同一個帳號持續猜密碼。這裡補「同一個帳號、不分 IP」的鎖。
[取捨與預設（模式 1＝只鎖外網，預設）]
  經典做法（任何來源失敗 N 次就整個帳號鎖死）有 DoS：任何人故意輸錯就能把別人鎖在門外，包含在公司內網的本人。所以預設：
    · **只計外網來源的嘗試**（內網打錯不計入——內網使用者已受區網與每 IP 鎖定保護）；
    · 鎖住時**只擋外網來源**的登入，內網照常能登入——攻擊者最多讓「這個帳號暫時不能從外網登入」，不能讓人進不了系統；
    · **內網登入成功會解除該帳號的鎖**（本人回到公司就能解），超級管理員也能手動解除；30 分鐘後自動解除；
    · 鎖定期間的外網嘗試一律被擋、**不計數也不延長鎖定**（攻擊者無法靠持續送請求把鎖無限延長）；
    · 任何帳號名（含不存在的）都照同一套計數與回應 ⇒ 鎖定回應不洩漏帳號是否存在。
  ⚠ 已知殘留（維持原取捨，交由使用者決定）：外網攻擊者仍可讓指定帳號「無法從外網登入」（持續性 DoS，鎖到期後可立刻續鎖）——只影響外網，
    內網登入與超管解鎖不受影響。模式 2（設定中心可選）＝不分來源計數、鎖住時連內網也擋：最嚴，但這個 DoS 會擴大到內網，只建議遭受持續攻擊時暫用。
[不變式]
  ① **預占計數**（hichan-1 審查 F4）：登入入口一進來就呼叫 `begin_attempt`——**同一把鎖裡**檢查有沒有鎖、把這次嘗試先算進去；窗口內已放行滿 `threshold` 次，
     第 `threshold`+1 次當場鎖定並拒絕。所以併發 N 個請求最多放行 `threshold` 次密碼驗證（以前是「驗完才計數」，40 個併發都能通過檢查、遠超過門檻）；
     循序的情況與舊行為相同（失敗 10 次後第 11 次被擋）。成功登入清掉計數；
     密碼正確但要走 TOTP 第二步（或被外網強制 TOTP 拒絕）時 `release` 退回那一次預占（密碼對不算猜錯）。
  ② 窗口：滾動 `window_s` 秒內達 `threshold` 次嘗試 ⇒ 鎖 `lock_s` 秒；鎖定寫進 `login_rate_limit`（鍵 `acct:<雜湊>`），重啟後仍有效。
  ③ 計數只在記憶體（重啟歸零；最壞情況只是少算）。表有上限 `_MAX_ENTRIES`，清表**先丟計數低、再丟舊的**，保留接近門檻的列
     （F5：攻擊者塞滿大量一次性帳號名，擠不掉已經累積到 9 次的受害帳號）。
  ④ **帳號名是攻擊者可控的字串，而且可能是被貼錯欄位的密碼**（F6）：記憶體與資料庫的鍵一律用雜湊（`acct:` ＋ SHA-256 前 20 碼），**資料庫不存帳號明文**；
     稽核／告警／log 只顯示「已存在的帳號」的名稱（去控制字元、限長）；不存在的帳號名只顯示雜湊前 8 碼與長度，**明文不進稽核、告警、log**。
  ⑤ 鎖定的那一刻：稽核 `auth.account_locked`（不含密碼）＋ `helpers.auth_alert.on_lockout(scope="account")`（hichan-3 的 auth_lockout 事件，負責節流與發送）。
     auth_alert 載入不了（模組缺）⇒ `logger.error`（告警等於沒發，要看得到）；其他例外 ⇒ warning；都不影響登入回應。
  ⑥ **永不讓登入流程多出例外**：`begin_attempt`／`record_failure` 內部例外吞掉並記 log（讀不到設定用預設值）。
"""
import hashlib
import json
import logging
import re
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
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")

_lock = threading.Lock()
_fails: dict = {}          # key -> [monotonic 嘗試時間, ...]
_locks: dict = {}          # key -> locked_until（monotonic）


def _name(username) -> str:
    return str(username or "").strip().lower()[:_MAX_NAME]


def _key(username) -> str:
    """記憶體／資料庫用的鍵：帳號名的雜湊（帳號名不落地、不進 log）。空名稱 ⇒ ''。"""
    n = _name(username)
    return hashlib.sha256(("acct-lock:" + n).encode("utf-8", "replace")).hexdigest()[:20] if n else ""


def safe_label(username) -> str:
    """給稽核／告警／log 用的帳號顯示字串：已存在（啟用中）的帳號 ⇒ 名稱（去控制字元、限長 32）；其餘 ⇒ `（不存在的帳號 #雜湊 長度 N）`，**不含明文**。"""
    n = _name(username)
    if not n:
        return "（空白）"
    try:
        from db import get_db
        conn = get_db()
        try:
            row = conn.execute("SELECT username FROM users WHERE lower(username)=? AND active=1", (n,)).fetchone()
        finally:
            conn.close()
        if row:
            return _CTRL.sub(" ", str(row["username"]))[:32]
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.safe_label：查帳號失敗，改用不含明文的標記", exc_info=True)
    return "（不存在的帳號 #%s 長度 %d）" % (_key(n)[:8], len(n))


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


def _remaining(key: str, mono: float) -> int:
    """（持有 `_lock`）⇒ 剩餘鎖定秒數；0＝沒鎖；-1＝剛發現已過期（已從記憶體移除，呼叫端之後清資料庫）。"""
    until = _locks.get(key)
    if until is None:
        return 0
    if until <= mono:
        _locks.pop(key, None)
        return -1
    return int(until - mono) + 1


def is_locked(username, external: bool = True, now: Optional[float] = None) -> int:
    """唯讀：⇒ 還要鎖幾秒（0＝沒鎖、或這個來源不受管）。"""
    key = _key(username)
    if not key:
        return 0
    mono = time.monotonic() if now is None else now
    cfg = config()
    with _lock:
        rem = _remaining(key, mono)
    if rem < 0:
        _db_clear(key)
        return 0
    return rem if (rem > 0 and _applies(external, cfg["scope"])) else 0


def check(username, external: bool = True) -> int:
    """唯讀檢查（不計數）。登入入口請用 `begin_attempt`。"""
    try:
        return is_locked(username, external)
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.check 失敗（放行，由其他防線處理）", exc_info=True)
        return 0


def begin_attempt(username, ip: str, external: bool, source: str = "password", now: Optional[float] = None) -> int:
    """登入入口呼叫（預占計數，見不變式①）。⇒ 0＝放行（這次嘗試已先算進去）；>0＝帳號鎖定中，剩餘秒數，**呼叫端必須拒絕**。**永不丟例外**。"""
    try:
        key = _key(username)
        if not key:
            return 0
        cfg = config()
        if not _applies(external, cfg["scope"]):
            return 0
        mono = time.monotonic() if now is None else now
        expired = False
        newly_locked = False
        with _lock:
            rem = _remaining(key, mono)
            if rem > 0:
                return rem                                  # 鎖定期間：擋掉、不計數、不延長
            expired = rem < 0
            lst = [t for t in _fails.get(key, ()) if mono - t < cfg["window_s"]]
            if len(lst) >= cfg["threshold"]:                # 窗口內已放行滿門檻次 ⇒ 這次（第 threshold+1 次）當場鎖並拒絕
                _fails.pop(key, None)
                _locks[key] = mono + cfg["lock_s"]
                fails = len(lst)
                newly_locked = True
            else:
                lst.append(mono)
                _fails[key] = lst
                if len(_fails) > _MAX_ENTRIES:
                    _prune_locked(mono, cfg["window_s"], keep=key)
        if expired:
            _db_clear(key)
        if newly_locked:
            _on_locked(username, ip, external, source, fails, cfg)
            return cfg["lock_s"]
        return 0
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.begin_attempt 失敗（放行，不影響登入回應）", exc_info=True)
        return 0


def _count_locked(key: str, mono: float, cfg: dict) -> int:
    """（持有 `_lock`）把一次嘗試記進窗口，⇒ 窗口內的次數。表太大時清表。"""
    lst = [t for t in _fails.get(key, ()) if mono - t < cfg["window_s"]]
    lst.append(mono)
    _fails[key] = lst
    if len(_fails) > _MAX_ENTRIES:
        _prune_locked(mono, cfg["window_s"], keep=key)
    return len(lst)


def release(username) -> None:
    """退回最近一次預占（密碼正確但還要第二步／被外網強制 TOTP 拒絕：不算猜錯）。"""
    key = _key(username)
    with _lock:
        lst = _fails.get(key)
        if lst:
            lst.pop()
            if not lst:
                _fails.pop(key, None)


def record_failure(username, ip: str, external: bool, source: str = "password", now: Optional[float] = None) -> str:
    """直接記一次失敗（不檢查鎖）。⇒ `locked`／`counted`／`ignored`／`already`／`error`。登入流程用 `begin_attempt`；這支留給需要單獨計數的呼叫端與測試。**永不丟例外**。"""
    try:
        key = _key(username)
        if not key:
            return "ignored"
        cfg = config()
        if not _applies(external, cfg["scope"]):
            return "ignored"
        mono = time.monotonic() if now is None else now
        with _lock:
            if _remaining(key, mono) > 0:
                return "already"
            fails = _count_locked(key, mono, cfg)
            if fails < cfg["threshold"]:
                return "counted"
            _fails.pop(key, None)
            _locks[key] = mono + cfg["lock_s"]
        _on_locked(username, ip, external, source, fails, cfg)
        return "locked"
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.record_failure 失敗（不影響登入回應）", exc_info=True)
        return "error"


def _prune_locked(mono: float, window_s: float, keep: str = "") -> None:
    """（持有 `_lock`）表超過上限：先丟整窗都沒再嘗試的；還太多就**依（窗內次數少 → 最近一次舊）**丟前半，保留接近門檻的列（F5）。`keep` 這一列不丟。"""
    for k in [k for k, v in _fails.items() if k != keep and (not v or mono - v[-1] >= window_s)]:
        del _fails[k]
    if len(_fails) > _MAX_ENTRIES:
        ranked = sorted((k for k in _fails if k != keep), key=lambda k: (len(_fails[k]), _fails[k][-1]))
        for k in ranked[: len(ranked) // 2]:
            del _fails[k]
    for k in [k for k, u in _locks.items() if u <= mono]:
        del _locks[k]


def _on_locked(username, ip: str, external: bool, source: str, fails: int, cfg: dict) -> None:
    key = _key(username)
    shown = safe_label(username)
    logger.warning("Account lockout: account=%r ip=%r external=%s source=%s locked for %ds",
                   _CTRL.sub(" ", shown)[:80], _CTRL.sub(" ", str(ip or ""))[:45], bool(external), _CTRL.sub(" ", str(source))[:16], cfg["lock_s"])
    _db_write(key, cfg["lock_s"])
    _audit("auth.account_locked", shown, ip, {"ip": _CTRL.sub(" ", str(ip or ""))[:45], "external": bool(external), "source": str(source)[:16], "fails": fails,
                                             "windowMinutes": cfg["window_s"] // 60, "lockMinutes": cfg["lock_s"] // 60, "scope": cfg["scope"]},
           "account_locked", 429)
    try:
        from helpers import auth_alert
        auth_alert.on_lockout(KEY_PREFIX + key, ip, [shown], fails, cfg["lock_s"], scope="account")
    except ImportError:
        logger.error("帳號鎖定告警沒有送出：helpers.auth_alert 不存在（本分支必須在 hichan-3 的 auth_lockout 告警之後合併；鎖定本身與稽核仍有效）")
    except Exception as exc:                                  # noqa: BLE001  告警永遠不能讓登入回應變 500
        logger.warning("帳號鎖定告警呼叫失敗（不影響登入）：%s", type(exc).__name__)


def clear_failures(username) -> None:
    """登入成功：清掉該帳號的嘗試計數（不動已存在的鎖）。"""
    key = _key(username)
    with _lock:
        _fails.pop(key, None)


def clear(username, ip: str = "", by: str = "", reason: str = "", audit: bool = True) -> bool:
    """解除鎖定＋清計數。⇒ 原本有鎖才回 True；有鎖且 `audit` 時寫稽核 `auth.account_unlocked`（手動解鎖由端點用 `_audit` 記操作者，這裡傳 audit=False）。"""
    key = _key(username)
    with _lock:
        _fails.pop(key, None)
        had = _locks.pop(key, None) is not None
    _db_clear(key)
    if had and audit:
        _audit("auth.account_unlocked", safe_label(username), ip, {"ip": _CTRL.sub(" ", str(ip or ""))[:45], "by": by, "reason": reason}, "", 200, result="ok")
    return had


def unlock(username, by: str) -> bool:
    """超級管理員手動解鎖（稽核由呼叫端端點寫，帶操作者身分）。"""
    return clear(username, by=by, reason="manual", audit=False)


def list_locks() -> list:
    """目前有效的帳號鎖 ⇒ [{username, secondsLeft}]（給超級管理員的解鎖清單）。帳號名由雜湊對回「已存在的帳號」；對不回去的顯示 `#雜湊前 8 碼`。"""
    mono = time.monotonic()
    with _lock:
        active = {k: int(u - mono) + 1 for k, u in _locks.items() if u > mono}
    if not active:
        return []
    names = {}
    try:
        from db import get_db
        conn = get_db()
        try:
            for r in conn.execute("SELECT username FROM users WHERE active=1").fetchall():
                names[_key(r["username"])] = _CTRL.sub(" ", str(r["username"]))[:32]
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock.list_locks：查帳號失敗", exc_info=True)
    return sorted(({"username": names.get(k, "#" + k[:8]), "secondsLeft": s} for k, s in active.items()), key=lambda x: x["username"])


# ── 持久化（沿用 `login_rate_limit` 表，鍵 `acct:<雜湊>`；不新增資料表、不存帳號明文）──────────────
def _db_write(key: str, lock_s: int) -> None:
    try:
        from db import get_db
        until = (datetime.now() + timedelta(seconds=lock_s)).isoformat()
        conn = get_db()
        try:
            conn.execute("INSERT INTO login_rate_limit (ip, locked_until) VALUES (?, ?) "
                         "ON CONFLICT(ip) DO UPDATE SET locked_until=excluded.locked_until", (KEY_PREFIX + key, until))
            conn.commit()
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001
        logger.warning("account_lock: 寫入鎖定失敗（記憶體內仍有效）", exc_info=True)


def _db_clear(key: str) -> None:
    try:
        from db import get_db
        conn = get_db()
        try:
            conn.execute("DELETE FROM login_rate_limit WHERE ip=?", (KEY_PREFIX + key,))
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


# ── 稽核（直接寫 audit_log，欄位與 helpers.audit._audit_login_failed 相同；不記密碼、不記不存在帳號的明文）────────
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
    """給 routers/auth 寫『外網強制 TOTP 拒絕』等稽核用（同一套欄位）。`username` 由呼叫端保證是已存在的帳號。"""
    _audit(action, username, ip, detail, reason_code, status)
