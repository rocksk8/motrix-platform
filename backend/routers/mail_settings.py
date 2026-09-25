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
