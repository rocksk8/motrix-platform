# -*- coding: utf-8 -*-
"""LINE 通知的收件人過濾：角色允許清單＋個人勾選（2026-11-12；PM 裁示 D1／D2）。

[單位] helper:line_recipients    [層] L1    [穩定度] 實作
[公開介面] PREFS_KEY, allowed_roles, filter_usernames, is_muted, muted_events, prefs_view, role_choices, set_muted
[契約題] tests/test_line_recipients_2026_11_12.py
[不變式]
  ① 語意是**交集（只縮不擴）**：LINE 最終收件人 ＝ 呼叫端給的帳號（＝信件已解析、已套超管覆寫與個人信件退訂的收件人）
     ∩ 該類型的「允許角色」 ∩ 沒有被本人退訂 ∩（之後由 `line_notify.ids_for`）已綁定。
     這個檔**絕不會讓不在呼叫端清單裡的人收到任何東西**。
  ② 角色允許清單存 `system_settings.line_notify.event_roles = {event_key: [role…]}`（寫入在 `line_notify.set_event_roles`，與事件開關共用同一把鎖）：
     **鍵不存在＝所有角色**（沿用現行行為，既有部署不變）；`[]`＝沒有任何角色；角色只收 `mail_types.ROLES`；以 `users.role` 判斷（與信件 custom 覆寫同一來源）。
     值壞掉（不是 list／含未知角色）⇒ **fail-closed**（視為沒有任何角色允許）並記 WARNING——LINE 是附帶通道，漏推的代價小於推錯人。
  ③ 個人勾選存 `system_settings.line_prefs = {username: [被退訂的 event_key…]}`：**opt-out 清單**（與 `users.notification_muted` 同慣例：
     新增接線類型不會讓任何人被靜音）。預設＝收；只有本人按勾選才寫（寫入量最小）。個人只能設定「自己角色被允許」的類型（`prefs_view` 不列、`set_muted` 拒收其餘）。
  ④ 本檔不 import `line_notify` 於模組層（`line_notify.notify_users` 會呼叫本檔；循環）：需要 `WIRED_EVENTS` 時在函式內惰性 import。
  ⑤ `filter_usernames` 永不丟例外；查不到使用者角色（資料庫錯誤）＝回空清單並記 WARNING（fail-closed）。
     **有角色限制時**，停用或不存在的帳號會被濾掉（要查角色就一併查 `active=1`）；**沒有任何限制且沒人退訂的快速路徑**不查資料庫、原樣回傳呼叫端的清單
     ——與舊版行為相同（呼叫端給的帳號本來就是信件解析出的在職收件人；停用者之後在 `ids_for`／信件端另有處理）。
  ⑥ `line_prefs` 不主動清理已刪除／停用使用者的條目：資料量極小（每人最多接線類型數個字串）、無安全影響（過濾只看呼叫端給的帳號）。
"""
import logging
import threading

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

PREFS_KEY = "line_prefs"
_lock = threading.Lock()
_CHUNK = 400            # SQLite 變數上限 999；留餘裕


def role_choices() -> list:
    """可選的角色（與信件收件人覆寫同一份清單）。"""
    from .mail_types import ROLES
    return list(ROLES)


def _roles_map() -> dict:
    c = _get_setting("line_notify", {}) or {}
    r = c.get("event_roles") if isinstance(c, dict) else None
    return r if isinstance(r, dict) else {}


def allowed_roles(event_key: str):
    """該類型允許的角色（list）；沒有設定＝None（所有角色）。值壞掉 ⇒ []（fail-closed）並記 WARNING。"""
    m = _roles_map()
    if event_key not in m:
        return None
    v = m[event_key]
    valid = set(role_choices())
    if not isinstance(v, list) or not all(isinstance(x, str) and x in valid for x in v):
        logger.warning("LINE event_roles[%r] 的值不合法（%r），視為沒有任何角色允許", event_key, type(v).__name__)
        return []
    return list(dict.fromkeys(v))


def _prefs() -> dict:
    v = _get_setting(PREFS_KEY, {}) or {}
    return v if isinstance(v, dict) else {}


def muted_events(username: str) -> set:
    """這個人退訂的 LINE 通知類型。壞資料（不是 list）＝沒有退訂任何一個。"""
    v = _prefs().get(username)
    return {x for x in v if isinstance(x, str)} if isinstance(v, list) else set()


def is_muted(username: str, event_key: str) -> bool:
    return event_key in muted_events(username)


def _role_of(usernames: list) -> dict:
    """{username: role}，只含「啟用中」的帳號。"""
    from db import get_db
    out = {}
    conn = get_db()
    try:
        for i in range(0, len(usernames), _CHUNK):
            chunk = usernames[i:i + _CHUNK]
            rows = conn.execute("SELECT username, role FROM users WHERE active=1 AND username IN (%s)" % ",".join("?" * len(chunk)),
                                chunk).fetchall()
            out.update({r["username"]: r["role"] for r in rows})
    finally:
        conn.close()
    return out


def filter_usernames(event_key: str, usernames) -> list:
    """從呼叫端給的帳號裡，留下「角色被允許、且本人沒退訂」的（保持順序、去重）。永不丟例外；出錯 ⇒ 空清單（fail-closed）。"""
    try:
        names = [u for u in dict.fromkeys(usernames or []) if isinstance(u, str) and u]
        if not names:
            return []
        allowed = allowed_roles(event_key)
        prefs = _prefs()
        if allowed is None and not any(prefs.get(u) for u in names):
            return names                      # 沒有角色限制、也沒有人退訂：不必查資料庫（也維持舊行為：不額外丟掉任何人）
        if allowed is not None:
            roles = _role_of(names)
            names = [u for u in names if roles.get(u) in allowed]
        return [u for u in names if event_key not in muted_events(u)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 收件人過濾失敗（event=%r），這一則不推：%s", event_key, type(exc).__name__)
        return []


def prefs_view(username: str, role: str) -> list:
    """本人設定頁用：`[{key, name, enabled}]`——只列「已接線、公司已勾選、且我的角色被允許」的類型；enabled＝我有沒有要收。"""
    from . import line_notify as _ln
    from . import mail_types as _mt
    out = []
    muted = muted_events(username)
    for k in _ln.WIRED_EVENTS:
        if not _ln.events_view().get(k):
            continue
        allowed = allowed_roles(k)
        if allowed is not None and role not in allowed:
            continue
        t = _mt.get(k)
        out.append({"key": k, "name": t.name if t else k, "enabled": k not in muted})
    return out


def set_muted(username: str, event_key: str, muted: bool, role: str = None) -> None:
    """本人退訂／恢復某類型。類型不是已接線的 ⇒ `ValueError`；給了 `role` 且該角色不被允許 ⇒ `ValueError`（不留沒意義的勾選）。
    恢復（muted=False）時不留空清單：沒有任何退訂就把這個人的鍵拿掉（設定值不會越長越大）。"""
    from . import line_notify as _ln
    if event_key not in _ln.WIRED_EVENTS:
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if not isinstance(muted, bool):
        raise ValueError("enabled 必須是 true 或 false")
    if role is not None:
        allowed = allowed_roles(event_key)
        if allowed is not None and role not in allowed:
            raise ValueError("這種 LINE 通知不開放給你的角色")
    with _lock:
        prefs = dict(_prefs())
        before = muted_events(username)
        cur = set(before)
        (cur.add if muted else cur.discard)(event_key)
        if cur == before:
            return                            # 沒有變化就不寫（硬碟寫入越少越好）
        if cur:
            prefs[username] = sorted(cur)
        else:
            prefs.pop(username, None)
        _set_setting(PREFS_KEY, prefs)
