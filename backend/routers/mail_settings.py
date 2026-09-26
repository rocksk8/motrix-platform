# -*- coding: utf-8 -*-
"""信件與通知收件設定（L1；CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

- `GET  /api/mail-types`：所有登記的信件類型（分類、預設收件人、影響、建議處理）＋目前的覆寫（僅超級管理員）
- `PUT  /api/mail-types/{key}/recipients`：{mode: default|superadmin_only|custom, users: [...], roles: [...]}
- `GET  /api/mail-types/receivable?user_id=`：某位使用者**收得到**哪些類型（使用者管理頁的個人退訂清單用）

個人退訂（`users.notification_muted`）只能移除自己收得到的類型；受限的類型不會出現在可勾選的清單裡，
也沒有任何設定能把自己加進去（加人只能由超級管理員在本頁設定）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user, _audit, _tok
from helpers import mail_types as mt
from helpers.settings import _get_setting, _set_setting

router = APIRouter()


def _overrides():
    return _get_setting(mt.OVERRIDES_KEY, {}) or {}


def _no_recipient(t):
    """事件收件人以外，群組收件人（依目前的覆寫與個人退訂）是否一個人都沒有（稽核 M-S1）。
    只看沒有事件收件人的類型（有事件收件人的，每一封信的收件人不同）。"""
    if t.event or t.key in mt.MANAGED_ELSEWHERE:
        return False
    from helpers import email_notify as en
    return not en._group_emails(t.key)


def _type_view(t, o):
    return {"key": t.key, "name": t.name, "category": t.category, "categoryLabel": mt.CATEGORIES[t.category],
            "group": t.group, "groupLabel": mt.GROUPS[t.group], "event": t.event,
            "impact": t.impact, "action": t.action, "owner": t.owner,
            "override": o.get(t.key) or {"mode": "default", "users": [], "roles": []},
            "managedElsewhere": mt.MANAGED_ELSEWHERE.get(t.key, "")}


@router.get("/api/mail-types")
def list_mail_types(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    o = _overrides()
    order = list(mt.CATEGORIES)
    items = sorted((_type_view(t, o) for t in mt.all_types()),
                   key=lambda v: (order.index(v["category"]), v["name"]))
    for v in items:
        v["noRecipient"] = _no_recipient(mt.get(v["key"]))
    return {"items": items, "categories": mt.CATEGORIES, "groups": mt.GROUPS, "roles": list(mt.ROLES),
            "modes": {"default": "照預設", "superadmin_only": "僅超級管理員", "custom": "指定帳號／角色"}}


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
    new_override = {"mode": mode, "users": users if mode == "custom" else [], "roles": roles if mode == "custom" else []}
    blocked = custom_override_blockers(key, new_override)
    if blocked:
        raise HTTPException(400, blocked[0])
    o = _overrides()
    if mode == "default":
        o.pop(key, None)
    else:
        o[key] = {"mode": mode, "users": users if mode == "custom" else [],
                  "roles": roles if mode == "custom" else []}
    _set_setting(mt.OVERRIDES_KEY, o)
    _audit(_tok(authorization), "mail_types.recipients", "settings", key,
           "信件收件人：%s → %s" % (t.name, mode))
    return {"ok": True, "override": o.get(key) or {"mode": "default", "users": [], "roles": []}}


def _has_email(v) -> bool:
    """與寄信端 SQL `email IS NOT NULL AND email != ''` 同一個判準（D 稽核 O-1：不 strip，只有空白也算有）。"""
    return v is not None and v != ""


def last_superadmin_blockers(conn, user_id, new_muted=None, new_email=None, new_role=None) -> list:
    """U15（使用者 2026-09-26 表單）：系統技術類信件**永遠至少一位超級管理員收得到**。

    以「套用這個請求之後」的狀態判斷（D 稽核 M-1：原本只看退訂，同一支端點改 email 為空、改角色照樣讓最後一位消失）：
    這位使用者套用 new_muted／new_email／new_role（None＝不變）之後，若某個系統技術類型從「有人收得到」變成
    「沒有任何啟用中、有 Email、未退訂的超管收得到」⇒ 回傳該類型名稱（空＝放行）。
    判準與寄信端一致（email_notify._users_emails）。覆寫為 custom 的類型由 set_mail_recipients 的檢查負責。"""
    import json
    from helpers.notification_prefs import is_enabled
    me = conn.execute("SELECT role, active, email, notification_muted FROM users WHERE id=?", (user_id,)).fetchone()
    if me is None:
        return []
    before_ok = me["role"] == "superadmin" and bool(me["active"]) and _has_email(me["email"])
    after_role = me["role"] if new_role is None else new_role
    after_email = me["email"] if new_email is None else new_email
    after_muted = me["notification_muted"] if new_muted is None else json.dumps(list(new_muted), ensure_ascii=False)
    after_ok = after_role == "superadmin" and bool(me["active"]) and _has_email(after_email)
    if not before_ok:
        return []                         # 本來就收不到：這次不是「把最後一位拿掉」
    others = conn.execute("SELECT notification_muted FROM users WHERE active=1 AND role='superadmin' "
                          "AND email IS NOT NULL AND email != '' AND id != ?", (user_id,)).fetchall()
    o = _overrides()
    out = []
    for t in mt.all_types():
        if t.category != "system" or t.event or t.key in mt.MANAGED_ELSEWHERE:
            continue
        if (o.get(t.key) or {}).get("mode", "default") == "custom":
            continue
        if not is_enabled(me["notification_muted"], t.key):
            continue                      # 本來就退訂了
        if after_ok and is_enabled(after_muted, t.key):
            continue                      # 套用之後自己仍收得到
        if any(is_enabled(r["notification_muted"], t.key) for r in others):
            continue
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
    mode = ov.get("mode", "default")
    if mode == "superadmin_only":
        return role == "superadmin"
    group_hit = {"none": False, "admins": role in ("admin", "superadmin"),
                 "superadmins": role == "superadmin"}[t.group]
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
