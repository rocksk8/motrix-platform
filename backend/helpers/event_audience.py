# -*- coding: utf-8 -*-
"""事件 ⇒ 業務收件人（帳號）的共用解析層（2026-11-12；使用者裁示「LINE 全部改獨立通道」）。

[單位] helper:event_audience    [層] L1    [穩定度] 實作
[公開介面] group_usernames, resolve_usernames
[契約題] tests/test_auth_lockout_alert_2026_11_12.py
[不變式]
  ① 回答的問題只有一個：「這個事件，業務上該通知哪些**帳號**」。**不看 Email**（沒有 Email 的人也在內）、**不套信件的個人退訂**
     （`users.notification_muted`）、**不套信件類型的公司層關閉**（`mail_recipient_overrides[key].off`）——那三件都是「信件通道」自己的事，
     LINE 另有自己的公司開關、事件勾選、角色允許清單與個人勾選（`line_notify.event_enabled`／`line_recipients.filter_usernames`）。
  ② 與信件**共用同一份**收件人設定（`system_settings.mail_recipient_overrides[key]`：default／superadmin_only／custom 的指定帳號＋角色）：
     「誰該被通知」只有一個來源（`mail_types.MANAGED_ELSEWHERE` 的同一個理由）；兩個通道各自再往下過濾（Email 看 Email＋退訂，LINE 看角色＋勾選＋綁定）。
  ③ 規則與 `email_notify._group_emails`／`_with_event_recipients` 逐項對應（登記的預設群組、superadmin_only 換成超管並丟掉事件收件人、
     custom＝事件收件人＋指定帳號＋指定角色、未登記的類型 ⇒ 只有超管〔fail closed〕）。兩邊的一致性由測試守著：人人有 Email 時兩者必須是同一批人。
  ④ 只回在職（`active=1`）帳號——事件收件人（例如送審人）已停用也不發，兩個通道一致。
  ⑤ 永不丟例外；查詢失敗 ⇒ 空清單並記 WARNING（寧可漏發附帶的 LINE，也不要因為查詢失敗讓呼叫端的流程炸掉）。
  ⑥ 新事件要接 LINE：在 `mail_types` 登記（收件人設定的來源）、加進 `line_notify.WIRED_EVENTS`，呼叫 `email_notify.send_registered`（會同時發信與 LINE）
     或直接 `line_notify.notify_event`（只發 LINE）——不需要自己解析收件人。
"""
import logging

from . import mail_types as _mt
from .settings import _get_setting

logger = logging.getLogger(__name__)

_CHUNK = 400        # SQLite 變數上限 999；留餘裕


def _override_of(event_key) -> dict:
    o = (_get_setting(_mt.OVERRIDES_KEY, {}) or {}).get(event_key) or {}
    return o if isinstance(o, dict) and o.get("mode") in _mt.MODES else {"mode": "default"}


def _query(where: str, params) -> list:
    from db import get_db
    conn = get_db()
    try:
        return [r["username"] for r in conn.execute("SELECT username FROM users WHERE active=1 AND (%s)" % where, list(params)).fetchall()]
    finally:
        conn.close()


def _by_usernames(usernames) -> list:
    names = [u for u in dict.fromkeys(usernames or []) if isinstance(u, str) and u]
    out = []
    for i in range(0, len(names), _CHUNK):
        chunk = names[i:i + _CHUNK]
        out += _query("username IN (%s)" % ",".join("?" * len(chunk)), chunk)
    return out


def _custom(o: dict) -> list:
    users = [u for u in (o.get("users") or []) if isinstance(u, str)]
    roles = [r for r in (o.get("roles") or []) if r in _mt.ROLES]
    parts, params = [], []
    if users:
        parts.append("username IN (%s)" % ",".join("?" * len(users)))
        params += users
    if roles:
        parts.append("role IN (%s)" % ",".join("?" * len(roles)))
        params += roles
    return _query(" OR ".join(parts), params) if parts else []


def _superadmins() -> list:
    return _query("role='superadmin'", ())


def group_usernames(event_key: str, group: str = None, *, mail_key: str = None) -> list:
    """群組收件人（登記的預設群組，或超級管理員在設定頁的覆寫）的帳號。對應 `email_notify._group_emails`。
    `group`（選填）：用這個群組（`mail_types.GROUPS` 的鍵）取代**登記的預設群組**——給「LINE 的群組與信件不同」的事件用（`line_notify.LINE_EVENTS[key]["line_group"]`）。
    超級管理員在設定頁的覆寫（superadmin_only／custom）仍然優先（收件人只有一個來源），所以 `group` 只在覆寫為 default 時生效。
    `mail_key`（選填）：收件人設定（登記的群組與覆寫）改借用另一個信件類型——給 LINE-only／細項事件用（見 `line_catalog`）；沒給＝用 `event_key` 自己。"""
    try:
        event_key = mail_key or event_key
        t = _mt.get(event_key) if event_key else None
        if t is None:
            logger.error("信件類型 %r 未登記（helpers/mail_types.py）⇒ 只通知超級管理員", event_key)
            return _superadmins()
        o = _override_of(event_key)
        if o["mode"] == "superadmin_only":
            return _superadmins()
        if o["mode"] == "custom":
            return _custom(o)
        g = group if group in _mt.GROUPS else t.group
        if g == "admins":
            return _query("role IN ('admin','superadmin')", ())
        if g == "finance":
            return _query("role IN ('finance','superadmin')", ())
        if g == "superadmins":
            return _superadmins()
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("群組收件人（帳號）查詢失敗（%s）：%s", event_key, type(exc).__name__)
        return []


def resolve_usernames(event_key: str, usernames=None, to_group: bool = False, *, group: str = None, exclude=None, mail_key: str = None) -> list:
    """事件的業務收件人（帳號，保持順序、去重）＝（事件收件人 `usernames` 套覆寫）＋（`to_group` 時的群組收件人）。
    與 `email_notify.send_registered` 同一個參數形狀：`usernames`＝事件收件人（送審人、案件業務負責人…），`to_group`＝要不要加登記的群組。
    `group`：用另一個群組取代登記的預設群組（見 `group_usernames`）；`exclude`：要排除的帳號（例如操作者本人；套在最後，連群組與覆寫指定的也排除）；
    `mail_key`：收件人設定借用另一個信件類型（見 `group_usernames`）。"""
    try:
        event_key = mail_key or event_key
        names = []
        if usernames:
            event_part = _by_usernames(usernames)
            t = _mt.get(event_key) if event_key else None
            o = _override_of(event_key) if t is not None else {"mode": "superadmin_only"}
            if o["mode"] == "superadmin_only":
                event_part = _superadmins()                       # 覆寫（或未登記）把事件收件人換成超級管理員
            elif o["mode"] == "custom":
                event_part = event_part + _custom(o)              # 事件收件人＋指定帳號／角色
            names += event_part
        if to_group:
            names += group_usernames(event_key, group)
        skip = {u for u in (exclude or []) if isinstance(u, str)}
        return [u for u in dict.fromkeys(names) if u not in skip]
    except Exception as exc:  # noqa: BLE001
        logger.warning("事件收件人（帳號）解析失敗（%s）：%s", event_key, type(exc).__name__)
        return []
