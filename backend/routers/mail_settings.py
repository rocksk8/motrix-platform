# -*- coding: utf-8 -*-
"""信件與通知收件設定（L1；CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

- `GET  /api/mail-types`：所有登記的信件類型（分類、預設收件人、影響、建議處理）＋目前的覆寫（僅超級管理員）
- `PUT  /api/mail-types/{key}/recipients`：{mode: default|superadmin_only|custom, users: [...], roles: [...],
  mailOff?: bool（信件關閉，MAIL-CAL 階段 1）, confirm?: bool（關閉簽核／系統類要帶 true）}
- `GET  /api/mail-types/receivable?user_id=`：某位使用者**收得到**哪些類型（使用者管理頁的個人退訂清單用）

個人退訂（`users.notification_muted`）只能移除自己收得到的類型；受限的類型不會出現在可勾選的清單裡，
也沒有任何設定能把自己加進去（加人只能由超級管理員在本頁設定）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user, _audit, _tok
from helpers import mail_types as mt
from helpers import notify_matrix as nm
from helpers.settings import _get_setting, _set_setting

router = APIRouter()


def _overrides():
    return _get_setting(mt.OVERRIDES_KEY, {}) or {}


def _no_recipient(t):
    """事件收件人以外，群組收件人（依目前的覆寫與個人退訂）是否一個人都沒有（稽核 M-S1）。
    只看沒有事件收件人的類型（有事件收件人的，每一封信的收件人不同）。"""
    if t.event or t.key in mt.MANAGED_ELSEWHERE or nm.is_mail_off(t.key, _overrides()):      # 公司刻意關閉的不算「沒人收」
        return False
    from helpers import email_notify as en
    return not en._group_emails(t.key)


def _calendar_view(t, sw):
    """矩陣的行事曆格：有對應事件 ⇒ {code, enabled, primary, note}；沒有 ⇒ None ＋ 停用原因。"""
    link = nm.calendar_link_of_mail(t.key)
    if link:
        return {**link, "enabled": bool(sw.get(link["code"])), "disabledReason": ""}
    return {"code": "", "enabled": False, "primary": False, "note": "", "disabledReason": nm.calendar_disabled_reason(t.key)}


def _type_view(t, o, sw=None):
    return {"key": t.key, "name": t.name, "category": t.category, "categoryLabel": mt.CATEGORIES[t.category],
            "group": t.group, "groupLabel": mt.GROUPS[t.group], "event": t.event,
            "impact": t.impact, "action": t.action, "owner": t.owner,
            "override": o.get(t.key) or {"mode": "default", "users": [], "roles": []},
            "managedElsewhere": mt.MANAGED_ELSEWHERE.get(t.key, ""),
            "mailOff": nm.is_mail_off(t.key, o), "mailOffLockReason": nm.mail_off_lock_reason(t.key),
            "mailOffConfirm": nm.mail_off_needs_confirm(t.key),
            "calendar": _calendar_view(t, sw if sw is not None else {})}


def _calendar_matrix():
    """⇒ (事件開關 {代碼: bool}, 僅行事曆的列, 行事曆狀態)。開關就是 `google_calendar.events`（缺項＝EVENT_TYPES 預設），與行事曆設定頁同一份。"""
    from helpers import google_calendar as gc
    cfg = _get_setting("google_calendar", {}) or {}
    sw = gc.event_switches(cfg)
    types = {x["code"]: x for x in gc.event_types()}
    only = [{"code": c, "name": types[c]["label"], "group": types[c]["group"], "description": types[c]["description"],
             "enabled": sw[c], "default": types[c]["default"]} for c in nm.calendar_only_codes(gc.EVENT_CODES)]
    status = {"enabled": bool(cfg.get("enabled")), "connected": bool(cfg.get("refresh_token"))}
    return sw, only, status


@router.get("/api/mail-types")
def list_mail_types(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    o = _overrides()
    sw, cal_only, cal_status = _calendar_matrix()
    order = list(mt.CATEGORIES)
    items = sorted((_type_view(t, o, sw) for t in mt.all_types()),
                   key=lambda v: (order.index(v["category"]), v["name"]))
    for v in items:
        v["noRecipient"] = _no_recipient(mt.get(v["key"]))
    return {"items": items, "categories": mt.CATEGORIES, "groups": mt.GROUPS, "roles": list(mt.ROLES),
            "modes": {"default": "照預設", "superadmin_only": "僅超級管理員", "custom": "指定帳號／角色"},
            "calendarOnly": cal_only, "calendarStatus": cal_status}


@router.put("/api/mail-types/{key}/recipients")
def set_mail_recipients(key: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    t = mt.get(key)
    if t is None:
        raise HTTPException(404, "信件類型不存在：%s" % key)
    if key in mt.MANAGED_ELSEWHERE:
        raise HTTPException(400, mt.MANAGED_ELSEWHERE[key] + "，不在本頁設定。")
    body = body or {}
    mode = body.get("mode")
    if mode not in mt.MODES:
        raise HTTPException(400, "mode 必須是 %s 其中之一" % "／".join(mt.MODES))
    users = [u for u in (body.get("users") or []) if isinstance(u, str) and u.strip()]
    roles = [r for r in (body.get("roles") or []) if isinstance(r, str)]
    bad_roles = [r for r in roles if r not in mt.ROLES]
    if bad_roles:
        raise HTTPException(400, "不認得的角色：%s" % "、".join(bad_roles))
    if users:
        conn = get_db()
        try:
            found = {r["username"] for r in conn.execute(
                "SELECT username FROM users WHERE username IN (%s)" % ",".join("?" * len(users)), users)}
        finally:
            conn.close()
        missing = [u for u in users if u not in found]
        if missing:
            raise HTTPException(400, "找不到帳號：%s" % "、".join(missing))
    if mode == "custom" and not users and not roles:
        raise HTTPException(400, "指定收件人時，至少要選一個帳號或角色。")
    o = _overrides()
    was_off = bool((o.get(key) or {}).get("off") is True)
    if "mailOff" in body:
        if not isinstance(body["mailOff"], bool):
            raise HTTPException(400, "mailOff 必須是 true 或 false")
        now_off = body["mailOff"]
    else:
        now_off = was_off                       # 舊的呼叫端（沒帶 mailOff）不改信件開關
    if now_off and not was_off:
        lock = nm.mail_off_lock_reason(key)
        if lock:
            raise HTTPException(400, "「%s」的信件不能關閉：%s" % (t.name, lock))
        if nm.mail_off_needs_confirm(key) and body.get("confirm") is not True:
            raise HTTPException(409, "關閉「%s」（%s類）的信件後，相關人員不會再收到通知，流程或告警可能因此被忽略；確認請帶 confirm=true 再送一次" % (t.name, mt.CATEGORIES[t.category]))
    new_override = {"mode": mode, "users": users if mode == "custom" else [], "roles": roles if mode == "custom" else []}
    blocked = [] if now_off else custom_override_blockers(key, new_override)      # 關閉中不需要有人收得到
    if blocked:
        raise HTTPException(400, blocked[0])
    if mode == "default" and not now_off:
        o.pop(key, None)
    else:
        o[key] = {**new_override, **({"off": True} if now_off else {})}
    _set_setting(mt.OVERRIDES_KEY, o)
    _audit(_tok(authorization), "mail_types.recipients", "settings", key,
           "信件收件人：%s → %s%s" % (t.name, mode, "（信件關閉）" if now_off and not was_off else ("（信件重新開啟）" if was_off and not now_off else "")))
    return {"ok": True, "override": o.get(key) or {"mode": "default", "users": [], "roles": []}, "mailOff": now_off}


def _has_email(v) -> bool:
    """與寄信端 SQL `email IS NOT NULL AND email != ''` 同一個判準（D 稽核 O-1：不 strip，只有空白也算有）。"""
    return v is not None and v != ""


def last_superadmin_blockers(conn, user_id, new_muted=None, new_email=None, new_role=None) -> list:
    """U15（使用者 2026-09-26 表單）：系統技術類信件**永遠至少有一人收得到**。

    以「套用這個請求之後」的狀態判斷（D 稽核 M-1）：這位使用者套用 new_muted／new_email／new_role（None＝不變）
    之後，某個系統技術類型的收件人若從「至少一人」變成「零人」⇒ 回傳該類型名稱（空＝放行）。
    收件人依目前的覆寫計算，與寄信端（email_notify._group_emails）同一套規則：預設與 superadmin_only＝超級管理員；
    custom＝指定的帳號與角色（D 稽核 O-2：custom 名單也會因為名單上的人退訂、清空 Email、改角色而變成沒人收得到）。
    「收得到」＝啟用中、有 Email（與 SQL `email != ''` 同判準）、未退訂。"""
    import json
    from helpers.notification_prefs import is_enabled
    me = conn.execute("SELECT username, role, active, email, notification_muted FROM users WHERE id=?",
                      (user_id,)).fetchone()
    if me is None:
        return []
    after = {"role": me["role"] if new_role is None else new_role,
             "email": me["email"] if new_email is None else new_email,
             "muted": me["notification_muted"] if new_muted is None else json.dumps(list(new_muted), ensure_ascii=False)}
    rows = conn.execute("SELECT id, username, role, active, email, notification_muted FROM users WHERE active=1").fetchall()
    o = _overrides()

    def in_group(ov, username, role):
        mode = ov.get("mode", "default")
        if mode == "custom":
            custom_roles = ov.get("roles") or []
            return username in (ov.get("users") or []) or role in custom_roles
        return role == "superadmin"          # 系統技術類的預設群組一律是僅超級管理員（mail_types.register 已守）

    def receivers(key, ov, swap):
        n = 0
        for r in rows:
            role, email, muted = r["role"], r["email"], r["notification_muted"]
            if swap and r["id"] == user_id:
                role, email, muted = after["role"], after["email"], after["muted"]
            if in_group(ov, r["username"], role) and _has_email(email) and is_enabled(muted, key):
                n += 1
        return n

    out = []
    for t in mt.all_types():
        if t.category != "system" or t.event or t.key in mt.MANAGED_ELSEWHERE or nm.is_mail_off(t.key, o):
            continue
        ov = o.get(t.key) or {"mode": "default"}
        if receivers(t.key, ov, False) > 0 and receivers(t.key, ov, True) == 0:
            out.append(t.name)
    return sorted(out)


def custom_override_blockers(key, override) -> list:
    """D 稽核 S-1：系統技術類型存成 custom 覆寫時，名單上至少要有一人收得到（啟用中、有 Email、未退訂），
    否則系統信一樣沒人收。回傳問題說明（空＝放行）。"""
    t = mt.get(key)
    if t is None or t.category != "system" or override.get("mode") != "custom":
        return []
    from helpers import email_notify as en
    if en._custom_emails(override, key):
        return []
    return ["「%s」是系統技術類信件，指定的帳號／角色裡沒有任何啟用中、設定了 Email、未退訂的人收得到" % t.name]


def receivable(t, o, username, role):
    """這位使用者**可能**收到這類信嗎（退訂清單只列這些）。"""
    ov = o.get(t.key) or {}
    if nm.is_mail_off(t.key, o):
        return False                            # 公司關閉的信件：沒有人收得到，退訂清單不列
    mode = ov.get("mode", "default")
    if mode == "superadmin_only":
        return role == "superadmin"
    group_hit = {"none": False, "admins": role in ("admin", "superadmin"),
                 "superadmins": role == "superadmin",
                 "finance": role in ("finance", "superadmin")}.get(t.group, False)          # 第42班：新增 finance 群組（未知群組 ⇒ 不收，不丟 KeyError）
    if t.key == "module_activity" and role == "finance":
        group_hit = True          # 付款／匯款／沖銷類的模組通知（audience="finance"）會寄給財務角色 ⇒ 退訂清單要列出來
    if mode == "custom":
        chosen = ov.get("roles") or []
        group_hit = username in (ov.get("users") or []) or role in chosen
    return group_hit or bool(t.event)


@router.get("/api/mail-types/receivable")
def list_receivable(user_id: int, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        u = conn.execute("SELECT username, role FROM users WHERE id=?", (user_id,)).fetchone()
    finally:
        conn.close()
    if u is None:
        raise HTTPException(404, "使用者不存在")
    o = _overrides()
    order = list(mt.CATEGORIES)
    items = [{"key": t.key, "name": t.name, "categoryLabel": mt.CATEGORIES[t.category],
              "receivable": receivable(t, o, u["username"], u["role"])}
             for t in sorted(mt.all_types(), key=lambda t: (order.index(t.category), t.name))]
    return {"items": items}
