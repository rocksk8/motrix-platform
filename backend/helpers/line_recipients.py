# -*- coding: utf-8 -*-
"""LINE 通知的收件人過濾：角色允許清單＋個人勾選（2026-11-12；PM 裁示 D1／D2）。

[單位] helper:line_recipients    [層] L1    [穩定度] 實作
[公開介面] PREFS_KEY, allowed_roles, allowed_roles_view, audience_of, audience_view, filter_usernames, ineligible_users, is_muted, muted_events, permitted_users, prefs_view, resolve_audience, role_choices, set_muted, visible_to
[契約題] tests/test_line_recipients_2026_11_12.py
[不變式]
  ① 語意是**交集（只縮不擴）**：LINE 最終收件人 ＝ 呼叫端給的帳號（2026-11-12 起＝`helpers.event_audience` 解析出的「事件業務收件人」，**不看 Email、不看信件退訂**）
     ∩ 該類型的「允許角色」 ∩ 沒有被本人退訂 LINE ∩（之後由 `line_notify.ids_for`）已綁定。
     `filter_usernames` **絕不會讓不在呼叫端清單裡的人收到任何東西**；唯一會「加人」的是管理員明確指定（⑦，`resolve_audience`），預設不啟用。
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
  ⑦ 管理員指定「誰要發」（2026-11-13；存 `system_settings.line_notify.audiences[event_key] = {mode, roles, users}`，寫入在 `line_notify.set_audience`）。三種模式：
     `business`（預設；沒設定＝此模式）＝呼叫端給的業務收件人 ∩ 角色允許清單 ∩ 沒退訂（與 ① 逐位元相同）；
     `business_plus`＝上列 ∪ 管理員指定的角色與個人；`only`＝**只有**管理員指定的角色與個人（業務收件人不看）。
     規則：A. 指定的角色／個人只取**在職**帳號；B. 明確指定的人**不受**角色允許清單過濾（那是縮小「業務收件人」用的）；
     C. **個人退訂一律尊重**（含管理員指定的人）——手機是本人的；D. `exclude`（操作者本人）只在 `event_audience` 套用於業務收件人，不影響明確指定的人；
     E. 設定值壞掉（mode 不合法、型別不對）⇒ **fail-closed**（這一則不推）並記 WARNING，不退回 `business`（否則「只發給某幾位」會變成發給所有人）；
     F. `resolve_audience` 永不丟例外；查不到使用者（資料庫錯誤）⇒ 空清單並記 WARNING。
"""
import logging
import threading

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

PREFS_KEY = "line_prefs"
_lock = threading.Lock()
_CHUNK = 400            # SQLite 變數上限 999；留餘裕


# 事件的收件人範圍＝群組（見 line_notify.LINE_EVENTS[...]["audience"]）。用具名常數比對：與獎金群組來源檢查（bonus 的 "group" 字面比對守門）無關，避免被它當成散落的比對
_AUDIENCE_GROUP = "group"

def role_choices() -> list:
    """可選的角色（與信件收件人覆寫同一份清單）。"""
    from .mail_types import ROLES
    return list(ROLES)


def _roles_map() -> dict:
    c = _get_setting("line_notify", {}) or {}
    r = c.get("event_roles") if isinstance(c, dict) else None
    return r if isinstance(r, dict) else {}


def _allowed_from(m: dict, event_key: str):
    if event_key not in m:
        return None
    v = m[event_key]
    valid = set(role_choices())
    if not isinstance(v, list) or not all(isinstance(x, str) and x in valid for x in v):
        logger.warning("LINE event_roles[%r] 的值不合法（%r），視為沒有任何角色允許", event_key, type(v).__name__)
        return []
    return list(dict.fromkeys(v))


def allowed_roles(event_key: str):
    """該類型允許的角色（list）；沒有設定＝None（所有角色）。值壞掉 ⇒ []（fail-closed）並記 WARNING。"""
    return _allowed_from(_roles_map(), event_key)


def allowed_roles_view(keys) -> dict:
    """⇒ {key: [role…]|None}（設定頁一次讀完：只讀一次設定，不是每個事件一次）。"""
    m = _roles_map()
    return {k: _allowed_from(m, k) for k in keys}


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


_VALID_MODES = ("business", "business_plus", "only")


def _audiences_map() -> dict:
    c = _get_setting("line_notify", {}) or {}
    a = c.get("audiences") if isinstance(c, dict) else None
    return a if isinstance(a, dict) else {}


def _audience_from(aud: dict, event_key: str, for_view: bool) -> dict:
    if event_key not in aud:
        return {"mode": "business", "roles": [], "users": []}
    a = aud[event_key]
    from .mail_types import ROLES
    ok = (isinstance(a, dict) and a.get("mode") in _VALID_MODES and isinstance(a.get("roles"), list) and isinstance(a.get("users"), list)
          and all(isinstance(r, str) and r in ROLES for r in a["roles"]) and all(isinstance(u, str) and u for u in a["users"]))
    if not ok:
        logger.warning("LINE audiences[%r] 的值不合法，視為壞設定", event_key)
        return ({"mode": "business", "roles": [], "users": [], "invalid": True} if for_view
                else {"mode": "invalid", "roles": [], "users": []})
    return {"mode": a["mode"], "roles": list(dict.fromkeys(a["roles"])), "users": list(dict.fromkeys(a["users"]))}


def audience_of(event_key: str, for_view: bool = False) -> dict:
    """⇒ {"mode", "roles", "users"}。沒設定＝`business`＋空清單。值壞掉：給畫面看（`for_view=True`）＝`business`＋空清單＋`invalid: True`；
    給發送用（預設）＝`mode: "invalid"`（`resolve_audience` 見到就 fail-closed）。"""
    return _audience_from(_audiences_map(), event_key, for_view)


def audience_view(keys) -> dict:
    """⇒ {key: audience}（設定頁一次讀完：只讀一次設定）。"""
    m = _audiences_map()
    return {k: _audience_from(m, k, True) for k in keys}


def _picked_usernames(a: dict) -> list:
    """管理員指定的角色與個人 ⇒ 在職帳號（保持「個人在前、角色在後」的順序，去重）。"""
    from db import get_db
    users, roles = a["users"], a["roles"]
    parts, params = [], []
    if users:
        parts.append("username IN (%s)" % ",".join("?" * len(users)))
        params += users
    if roles:
        parts.append("role IN (%s)" % ",".join("?" * len(roles)))
        params += roles
    if not parts:
        return []
    conn = get_db()
    try:
        rows = conn.execute("SELECT username FROM users WHERE active=1 AND (%s) ORDER BY id" % " OR ".join(parts), params).fetchall()
    finally:
        conn.close()
    got = [r["username"] for r in rows]
    first = [u for u in users if u in got]
    return list(dict.fromkeys(first + got))


def _cat_needs_business_perm(event_key: str) -> bool:
    try:
        from . import line_catalog as _cat
        return _cat.needs_business_perm(event_key)
    except Exception:  # noqa: BLE001
        return False


def _has_need(need, role, mods) -> bool:
    """`need`＝`line_catalog.modules_needed`：`()`＝不檢查；含 `"@admin"`＝角色要是 admin 以上；否則任一模組在 `mods` 內。superadmin 一律通過。"""
    if role == "superadmin" or not need:
        return True
    if "@admin" in need:
        return role == "admin"
    return any(m in mods for m in need)


def _perm_rows(usernames, active_only=True) -> dict:
    """{username: (role, 有效模組清單)}（有效模組＝套過職責角色與財務規則；與選單／API 看到的同一份）。查不到的帳號不在結果裡。"""
    from db import get_db
    from .auth import effective_modules
    names = [u for u in dict.fromkeys(usernames or []) if isinstance(u, str) and u]
    out = {}
    if not names:
        return out
    conn = get_db()
    try:
        for i in range(0, len(names), _CHUNK):
            chunk = names[i:i + _CHUNK]
            rows = conn.execute("SELECT id, username, role, modules FROM users WHERE %susername IN (%s)"
                                % ("active=1 AND " if active_only else "", ",".join("?" * len(chunk))), chunk).fetchall()
            for r in rows:
                out[r["username"]] = (r["role"], effective_modules(r["role"], r["modules"], user_id=r["id"], conn=conn))
    finally:
        conn.close()
    return out


def permitted_users(event_key: str, usernames) -> set:
    """這些帳號裡，具備該事件所屬模組權限的（在職）。永不丟例外；查不到 ⇒ 空集合（fail-closed）。"""
    try:
        from . import line_catalog as _cat
        need = _cat.modules_needed(event_key)
        return {u for u, (role, mods) in _perm_rows(usernames).items() if _has_need(need, role, mods)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 權限檢查失敗（event=%r），這些人這一則不推：%s", event_key, type(exc).__name__)
        return set()


def ineligible_users(event_key: str, usernames) -> list:
    """設定「誰要發」時用：指定的人裡沒有該事件所屬模組權限的（含停用的帳號也算入檢查；不存在的由呼叫端另外擋）。保持輸入順序。"""
    from . import line_catalog as _cat
    need = _cat.modules_needed(event_key)
    rows = _perm_rows(usernames, active_only=False)
    return [u for u in dict.fromkeys(usernames or []) if u in rows and not _has_need(need, *rows[u])]


def resolve_audience(event_key: str, business_usernames) -> list:
    """LINE 最終收件人（帳號）＝依該事件的「誰要發」模式，把業務收件人與管理員指定的人合成一份，再套個人退訂（見不變式 ⑦）。
    `business_usernames`＝呼叫端（`line_notify.deliver_event`）解析好的業務收件人。永不丟例外；出錯 ⇒ 空清單。"""
    try:
        a = audience_of(event_key)
        if a["mode"] == "invalid":
            return []
        base = [] if a["mode"] == "only" else filter_usernames(event_key, business_usernames)
        if base and _cat_needs_business_perm(event_key):
            ok_b = permitted_users(event_key, base)                     # 業務收件人也要有該分組的模組權限（例：案件業務沒有「業務開發」權限就不發）
            base = [u for u in base if u in ok_b]
        if a["mode"] == "business":
            return base
        picked_all = _picked_usernames(a)
        ok = permitted_users(event_key, picked_all)                     # 審查 h8 M1：指定的人（含角色成員）要有該事件所屬模組的權限，沒有就不發
        picked = [u for u in picked_all if u in ok and event_key not in muted_events(u)]
        return list(dict.fromkeys(base + picked))
    except Exception as exc:  # noqa: BLE001
        logger.warning("LINE 收件人解析失敗（event=%r），這一則不推：%s", event_key, type(exc).__name__)
        return []


def _visible(event_key: str, username: str, role, mods, roles_map: dict, aud_map: dict) -> bool:
    """`visible_to` 的本體（設定已讀好；`prefs_view` 一次讀完設定後逐事件呼叫，不是每個事件各讀一次設定／資料庫）。"""
    a = _audience_from(aud_map, event_key, False)
    if a["mode"] == "invalid":
        return False
    from . import line_catalog as _cat
    perm = _has_need(_cat.modules_needed(event_key), role, mods)
    picked = perm and (username in a["users"] or (role in a["roles"]))        # 指定的人要有該事件所屬模組權限（審查 h8 M1）
    if a["mode"] == "only":
        return picked
    allowed = _allowed_from(roles_map, event_key)
    business = (allowed is None or role in allowed) and (perm or not _cat_needs_business_perm(event_key))
    if business and (_ln_spec(event_key).get("audience") == _AUDIENCE_GROUP) and not _in_group(event_key, username):
        business = False                     # 這個事件的業務收件人只有群組收件人（例：登入失敗告警）；同仁不是收件人，列出來只會誤導
    return business or (a["mode"] == "business_plus" and picked)


def visible_to(event_key: str, username: str, role) -> bool:
    """這位使用者的個人設定頁要不要列這個事件：業務模式＝角色被允許；另外加上＝角色被允許或被管理員指定（且有該事件所屬模組的權限）；只發＝被管理員指定（同上）。"""
    rows = _perm_rows([username])
    mods = rows[username][1] if username in rows else []
    return _visible(event_key, username, role, mods, _roles_map(), _audiences_map())


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


def _ln_spec(event_key: str) -> dict:
    try:
        from . import line_notify as _ln
        return _ln.event_spec(event_key)
    except Exception:  # noqa: BLE001
        return {}


def _in_group(event_key: str, username: str) -> bool:
    """我是不是這個事件的群組收件人（查不到＝False，fail-closed：寧可不列）。"""
    try:
        from . import event_audience as _ea
        from . import line_notify as _ln
        lg = _ln.event_spec(event_key).get("line_group", "inherit")
        return username in set(_ea.group_usernames(event_key, group=lg if lg not in (None, "inherit") else None))
    except Exception as exc:  # noqa: BLE001
        logger.warning("line_recipients: 查群組收件人失敗（%r）：%s", event_key, type(exc).__name__)
        return False


def prefs_view(username: str, role: str) -> list:
    """本人設定頁用：`[{key, name, enabled, group, kind}]`——只列「已接線、公司已勾選、且輪得到我（角色被允許或被管理員指定）」的事件；enabled＝我有沒有要收。
    `group`＝模組分組、`kind`＝"mail"／"line_only"（僅 LINE）／"sub"（LINE 細項）。
    事件規格 `audience="group"`（例如登入失敗告警）的「業務收件人」只有群組收件人；其他同仁除非被管理員指定（`visible_to`），不列，免得以為勾了會收到。"""
    from . import line_catalog as _cat
    from . import line_notify as _ln
    out = []
    muted = muted_events(username)
    sw = _ln.events_view()
    roles_map, aud_map = _roles_map(), _audiences_map()                      # 一次讀完（審查 h8 L7）：不是每個事件各讀一次設定／資料庫
    rows = _perm_rows([username])
    mods = rows[username][1] if username in rows else []
    for k in _ln.WIRED_EVENTS:
        if not sw.get(k):
            continue
        if not _visible(k, username, role, mods, roles_map, aud_map):
            continue
        out.append({"key": k, "name": _cat.name_of(k), "enabled": k not in muted, "group": _cat.group_of(k), "kind": _cat.kind_of(k)})
    return out


def set_muted(username: str, event_key: str, muted: bool, role: str = None) -> None:
    """本人退訂／恢復某類型。類型不是已接線的 ⇒ `ValueError`；給了 `role` 且這件事輪不到我（角色不被允許、也沒被管理員指定）⇒ `ValueError`（不留沒意義的勾選）。
    恢復（muted=False）時不留空清單：沒有任何退訂就把這個人的鍵拿掉（設定值不會越長越大）。"""
    from . import line_notify as _ln
    if event_key not in _ln.WIRED_EVENTS:
        raise ValueError("這種通知尚未支援 LINE：%s" % event_key)
    if not isinstance(muted, bool):
        raise ValueError("enabled 必須是 true 或 false")
    if role is not None and not visible_to(event_key, username, role):
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
