# -*- coding: utf-8 -*-
"""信件與通知收件設定（L1；CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

- `GET  /api/mail-types`：所有登記的信件類型（分類、預設收件人、影響、建議處理）＋目前的覆寫（僅最高管理者）
- `PUT  /api/mail-types/{key}/recipients`：{mode: default|superadmin_only|custom, users: [...], roles: [...],
  mailOff?: bool（信件關閉，MAIL-CAL 階段 1）, confirm?: bool（關閉簽核／系統類要帶 true）}
- `GET  /api/mail-types/receivable?user_id=`：某位使用者**收得到**哪些類型（使用者管理頁的個人退訂清單用）
- `POST /api/settings/mail/batch-preview`／`/batch`／`/batch-undo`：信件矩陣頁（S3b）的草稿儲存。`changes={列代碼: {mode?, users?, roles?, mailOff?, calendar?}}`
  （列代碼＝信件 key；只有行事曆的列是 `cal:<代碼>`）；`expect={列代碼: version}`（載入時的版本，防蓋掉別人的修改）。
  **全部驗證過才寫、任一不合法整批不寫**；信件覆寫與行事曆開關在**同一個交易**寫入；整批一筆稽核（`settings.mail.batch`）＋一則設定變更通知。
- `GET／PUT /api/mail-types/mine`：**本人入口**（設定改版 S6；「我的帳號 → 通知」分頁）：本人看／改自己的 Email 通知退訂清單；
  管理員代設仍走 `PUT /api/users/{id}` 的 `notification_muted`（不變）。

個人退訂（`users.notification_muted`）只能移除自己收得到的類型；受限的類型不會出現在可勾選的清單裡，
也沒有任何設定能把自己加進去（加人只能由最高管理者在本頁設定）。
"""
import hashlib
import json
import threading

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import begin_write
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
        v["version"] = _version_of(_state_of(v["key"], o, sw))
    for c in cal_only:
        c["key"] = "cal:" + c["code"]
        c["version"] = _version_of(_state_of(c["key"], o, sw))
    return {"auditMark": _audit_mark(), "items": items, "categories": mt.CATEGORIES, "groups": mt.GROUPS, "roles": list(mt.ROLES),
            "modes": {"default": "照預設", "superadmin_only": "僅最高管理者", "custom": "指定帳號／角色"},
            "calendarOnly": cal_only, "calendarStatus": cal_status}


# ── 信件矩陣的共用「一列狀態」與驗證（單列 PUT 與批次共用同一份規則，不各寫一套）────────────────────────────────

_MAIL_LOCK = threading.RLock()       # 讀改寫 OVERRIDES_KEY／google_calendar 的互斥（同一程序內；寫入本身是單一交易）
_PATCH_FIELDS = {"mode", "users", "roles", "mailOff", "calendar"}
_ROLE_NAME = {"superadmin": "最高管理者", "admin": "管理員", "sales": "業務", "engineer": "工程", "viewer": "檢視者", "finance": "財務"}


def _norm_list(v):
    return [x for x in (v or []) if isinstance(x, str) and x.strip()]


def _primary_code(key):
    """這個信件列自己擁有的行事曆開關代碼；沒有、或只是「同上」的副列 ⇒ None。"""
    link = nm.calendar_link_of_mail(key)
    return link["code"] if link and link["primary"] else None


def _state_of(key, o, sw):
    """這一列「批次會動到的格」目前的狀態：信件列＝{mode, users, roles, off, cal(None＝沒有自己的行事曆格)}；`cal:代碼` 列＝{cal}。"""
    if key.startswith("cal:"):
        return {"cal": bool(sw.get(key[4:]))}
    ov = o.get(key) or {}
    mode = ov.get("mode") if ov.get("mode") in mt.MODES else "default"
    code = _primary_code(key)
    return {"mode": mode, "users": _norm_list(ov.get("users")) if mode == "custom" else [],
            "roles": [r for r in (ov.get("roles") or []) if isinstance(r, str)] if mode == "custom" else [],
            "off": nm.is_mail_off(key, o), "cal": (bool(sw.get(code)) if code else None)}


def _version_of(state):
    """列的版本指紋（草稿儲存的比對用）：順序無關（users／roles 排序後再雜湊）。"""
    s = dict(state)
    for f in ("users", "roles"):
        if f in s:
            s[f] = sorted(s[f])
    return hashlib.sha1(json.dumps(s, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _entry_of(st):
    """狀態 ⇒ OVERRIDES_KEY 裡這一列的內容（照預設且沒關 ⇒ None＝刪掉這一列）。與舊的單列 PUT 寫出的形狀相同。"""
    if st["mode"] == "default" and not st["off"]:
        return None
    custom = st["mode"] == "custom"
    return {"mode": st["mode"], "users": list(st["users"]) if custom else [], "roles": list(st["roles"]) if custom else [],
            **({"off": True} if st["off"] else {})}


def _check_users_exist(users):
    users = list(dict.fromkeys(users))
    if not users:
        return
    conn = get_db()
    try:
        found = set()
        for i in range(0, len(users), 400):
            chunk = users[i:i + 400]
            found |= {r["username"] for r in conn.execute("SELECT username FROM users WHERE username IN (%s)" % ",".join("?" * len(chunk)), chunk)}
    finally:
        conn.close()
    missing = [u for u in users if u not in found]
    if missing:
        raise HTTPException(400, "找不到帳號：%s" % "、".join(missing))


def _plan_row(key, patch, state):
    """驗證一列的修改 ⇒ `(新狀態, 需要確認關閉)`；不合法 ⇒ HTTPException 400／404（訊息帶列名）。不寫入。
    規則與舊的單列 PUT 完全相同（模式、角色、帳號、指定時至少一人、信件開關鎖、系統技術類至少一人收得到）。"""
    if not isinstance(patch, dict) or not patch:
        raise HTTPException(400, "「%s」的修改必須是 {mode／users／roles／mailOff／calendar} 其中幾項" % key)
    extra = sorted(set(patch) - _PATCH_FIELDS)
    if extra:
        raise HTTPException(400, "「%s」不認得的欄位：%s" % (key, "、".join(str(x) for x in extra[:5])))
    new = dict(state)
    if key.startswith("cal:"):
        if set(patch) != {"calendar"}:
            raise HTTPException(400, "只有行事曆的列只能改 calendar")
        if not isinstance(patch["calendar"], bool):
            raise HTTPException(400, "calendar 必須是 true 或 false")
        new["cal"] = patch["calendar"]
        return new, False
    t = mt.get(key)
    if t is None:
        raise HTTPException(404, "信件類型不存在：%s" % key)
    if set(patch) & {"mode", "users", "roles", "mailOff"} and key in mt.MANAGED_ELSEWHERE:
        raise HTTPException(400, mt.MANAGED_ELSEWHERE[key] + "，不在本頁設定。")
    if "calendar" in patch:
        if not isinstance(patch["calendar"], bool):
            raise HTTPException(400, "calendar 必須是 true 或 false")
        if state["cal"] is None:
            raise HTTPException(400, "「%s」沒有自己的行事曆開關（%s）" % (t.name, nm.calendar_disabled_reason(key) or "同上"))
        new["cal"] = patch["calendar"]
    if set(patch) & {"mode", "users", "roles"}:
        mode = patch.get("mode", state["mode"])
        if mode not in mt.MODES:
            raise HTTPException(400, "mode 必須是 %s 其中之一" % "／".join(mt.MODES))
        users = _norm_list(patch["users"]) if "users" in patch else list(state["users"])
        roles = [r for r in ((patch["roles"] if "roles" in patch else state["roles"]) or []) if isinstance(r, str)]
        bad_roles = [r for r in roles if r not in mt.ROLES]
        if bad_roles:
            raise HTTPException(400, "不認得的角色：%s" % "、".join(bad_roles))
        if mode == "custom" and not users and not roles:
            raise HTTPException(400, "指定收件人時，至少要選一個帳號或角色。")
        new["mode"], new["users"], new["roles"] = mode, (users if mode == "custom" else []), (roles if mode == "custom" else [])
    needs_confirm = False
    if "mailOff" in patch:
        if not isinstance(patch["mailOff"], bool):
            raise HTTPException(400, "mailOff 必須是 true 或 false")
        if patch["mailOff"] and not state["off"]:
            lock = nm.mail_off_lock_reason(key)
            if lock:
                raise HTTPException(400, "「%s」的信件不能關閉：%s" % (t.name, lock))
            needs_confirm = nm.mail_off_needs_confirm(key)
        new["off"] = patch["mailOff"]
    if not new["off"]:                               # 關閉中不需要有人收得到
        blocked = custom_override_blockers(key, {"mode": new["mode"], "users": new["users"], "roles": new["roles"]})
        if blocked:
            raise HTTPException(400, blocked[0])
    return new, needs_confirm


def _read_state():
    o = _overrides()
    sw, cal_only, cal_status = _calendar_matrix()
    return o, sw, cal_only, cal_status


def _diff_states(new_states, o, sw):
    """純計算（不寫入；預覽與實際寫入共用）⇒ `(新覆寫, 行事曆開關變更 {代碼: bool}, [(列代碼, 欄位, 舊, 新)])`。"""
    new_o = dict(o)
    cal_changes = {}
    diffs = []
    for key, st in new_states.items():
        old = _state_of(key, o, sw)
        if st == old:
            continue
        if key.startswith("cal:"):
            cal_changes[key[4:]] = st["cal"]
            diffs.append((key, "calendar", old["cal"], st["cal"]))
            continue
        e = _entry_of(st)
        if e is None:
            new_o.pop(key, None)
        else:
            new_o[key] = e
        if (st["mode"], sorted(st["users"]), sorted(st["roles"])) != (old["mode"], sorted(old["users"]), sorted(old["roles"])):
            diffs.append((key, "recipients", old, st))
        if st["off"] != old["off"]:
            diffs.append((key, "mailOff", old["off"], st["off"]))
        code = _primary_code(key)
        if code and st["cal"] is not None and st["cal"] != old["cal"]:
            cal_changes[code] = st["cal"]
            diffs.append((key, "calendar", old["cal"], st["cal"]))
    return new_o, cal_changes, diffs


def _write_states(new_states, o, sw):
    """把一批新狀態寫入：信件覆寫與行事曆開關**同一個連線、同一次 commit**（要嘛都寫要嘛都不寫）。
    ⇒ [(列代碼, 欄位, 舊, 新)]（給稽核／通知）；沒有實質變動 ⇒ 不寫、回 []。"""
    from routers import system as _sys                 # 行事曆事件開關的驗證與預設值沿用該頁的同一套（延後匯入：避免載入順序問題）
    new_o, cal_changes, diffs = _diff_states(new_states, o, sw)
    if not diffs:
        return []
    from datetime import datetime
    conn = get_db()
    try:
        sql = ("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at")
        now = datetime.now().isoformat()
        if new_o != o:
            conn.execute(sql, (mt.OVERRIDES_KEY, json.dumps(new_o, ensure_ascii=False), now))
        if cal_changes:
            current = _get_setting("google_calendar", {}) or {}
            new_events, _ch = _sys._gcal_event_changes({"events": cal_changes}, current)
            data = {**_sys._GCAL_DEFAULTS, **current, "events": new_events}
            data["refresh_token"] = current.get("refresh_token", "")          # 授權用的 token 只由一次性腳本寫，這裡絕不動
            conn.execute(sql, ("google_calendar", json.dumps(data, ensure_ascii=False), now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return diffs


def _mode_text(st):
    if st["mode"] == "custom":
        return "指定：" + "、".join(st["users"] + [_ROLE_NAME.get(r, r) for r in st["roles"]])
    return {"default": "照預設", "superadmin_only": "僅最高管理者"}.get(st["mode"], st["mode"])


@router.put("/api/mail-types/{key}/recipients")
def set_mail_recipients(key: str, body: dict = Body(...), authorization: str = Header(None)):
    """舊的單列入口（使用者管理頁等舊呼叫端仍在用）。規則與批次完全相同：走同一個 `_plan_row`／`_write_states`。"""
    actor = _require_user(authorization, require_superadmin=True)
    t = mt.get(key)
    if t is None:
        raise HTTPException(404, "信件類型不存在：%s" % key)
    if key in mt.MANAGED_ELSEWHERE:
        raise HTTPException(400, mt.MANAGED_ELSEWHERE[key] + "，不在本頁設定。")
    body = body or {}
    if body.get("mode") not in mt.MODES:
        raise HTTPException(400, "mode 必須是 %s 其中之一" % "／".join(mt.MODES))
    bad_roles = [r for r in (body.get("roles") or []) if isinstance(r, str) and r not in mt.ROLES]
    if bad_roles:
        raise HTTPException(400, "不認得的角色：%s" % "、".join(bad_roles))
    users = _norm_list(body.get("users"))
    _check_users_exist(users)
    if "mailOff" in body and not isinstance(body["mailOff"], bool):
        raise HTTPException(400, "mailOff 必須是 true 或 false")
    patch = {"mode": body["mode"], "users": users, "roles": [r for r in (body.get("roles") or []) if isinstance(r, str)]}
    if "mailOff" in body:
        patch["mailOff"] = body["mailOff"]
    with _MAIL_LOCK:
        o, sw, _co, _cs = _read_state()
        state = _state_of(key, o, sw)
        new, needs_confirm = _plan_row(key, patch, state)
        if needs_confirm and body.get("confirm") is not True:
            raise HTTPException(409, "關閉「%s」（%s類）的信件後，相關人員不會再收到通知，流程或告警可能因此被忽略；確認請帶 confirm=true 再送一次" % (t.name, mt.CATEGORIES[t.category]))
        new["cal"] = state["cal"]                   # 單列舊入口不動行事曆格
        diffs = _write_states({key: new}, o, sw)
    was_off, now_off = state["off"], new["off"]
    _audit(_tok(authorization), "mail_types.recipients", "settings", key,
           "信件收件人：%s → %s%s" % (t.name, body["mode"], "（信件關閉）" if now_off and not was_off else ("（信件重新開啟）" if was_off and not now_off else "")))
    if diffs:
        _notify_mail_diffs(diffs, actor["username"])
    entry = _entry_of(new)
    return {"ok": True, "override": {k: v for k, v in (entry or {"mode": "default", "users": [], "roles": []}).items() if k != "off"}, "mailOff": now_off}


# ── 信件矩陣：草稿儲存（預覽／儲存／復原）──────────────────────────────────────────────────────────────────────────

_BATCH_FIELDS = {"changes", "expect", "since_audit", "confirm_system"}
_BATCH_MAX_ROWS = 200


def _parse_batch(b, need_expect):
    """請求本體的嚴格解析 ⇒ `{changes, expect, since_audit, confirm_system}`；格式不對 ⇒ 400。"""
    if not isinstance(b, dict):
        raise HTTPException(400, "請求本體必須是物件")
    extra = sorted(set(b) - _BATCH_FIELDS)
    if extra:
        raise HTTPException(400, "不認得的欄位：%s（可用：%s）" % ("、".join(str(x) for x in extra[:5]), "、".join(sorted(_BATCH_FIELDS))))
    ch = b.get("changes")
    if not isinstance(ch, dict) or not ch or len(ch) > _BATCH_MAX_ROWS:
        raise HTTPException(400, "changes 必須是 {列代碼: {mode／users／roles／mailOff／calendar}}（1～%d 列）" % _BATCH_MAX_ROWS)
    if "confirm_system" in b and b["confirm_system"] is not None and not isinstance(b["confirm_system"], bool):
        raise HTTPException(400, "confirm_system 必須是 true 或 false")
    since = b.get("since_audit", 0)
    if isinstance(since, bool) or not isinstance(since, int):
        raise HTTPException(400, "since_audit 必須是整數")
    ex = b.get("expect")
    if ex is not None and (not isinstance(ex, dict) or not all(isinstance(v, str) for v in ex.values())):
        raise HTTPException(400, "expect 必須是 {列代碼: 版本字串}")
    if need_expect:                                      # 儲存草稿一定要帶載入時的 version，否則會悄悄蓋掉別人的修改
        if ex is None:
            raise HTTPException(400, "草稿儲存必須帶 expect（{列代碼: 載入時的 version}），否則會蓋掉別人的修改")
        missing = [k for k in ch if k not in ex]
        if missing:
            raise HTTPException(400, "expect 缺少這些列的 version：%s" % "、".join(str(x) for x in missing[:5]))
    return {"changes": ch, "expect": ex, "since_audit": since, "confirm_system": b.get("confirm_system") is True}


def _row_name(key, cal_only_names=None):
    if key.startswith("cal:"):
        return (cal_only_names or {}).get(key[4:]) or key
    t = mt.get(key)
    return t.name if t else key


def _cal_only_names():
    from helpers import google_calendar as gc
    return {x["code"]: x["label"] for x in gc.event_types()}


def _check_keys(changes):
    """列代碼與修改的形狀（不看目前的狀態，所以可以在比對版本之前先擋）；不合法 ⇒ HTTPException 400／404。"""
    names = _cal_only_names()
    users = []
    for key, patch in changes.items():
        if not isinstance(key, str) or not key:
            raise HTTPException(400, "列代碼必須是字串")
        if key.startswith("cal:"):
            if key[4:] not in names or key[4:] not in nm.calendar_only_codes(set(names)):
                raise HTTPException(404, "沒有這個只有行事曆的項目：%s" % key)
        elif mt.get(key) is None:
            raise HTTPException(404, "信件類型不存在：%s" % key)
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(400, "「%s」的修改必須是 {mode／users／roles／mailOff／calendar} 其中幾項" % _row_name(key, names))
        if isinstance(patch.get("users"), list):
            users += _norm_list(patch["users"])
    _check_users_exist(users)


def _plan_batch(changes, o, sw):
    """逐列驗證（任一不合法 ⇒ HTTPException，整批不寫）⇒ `({列代碼: 新狀態（只含真的有變的列）}, [需要確認關閉的列代碼], {列代碼: 舊狀態})`。"""
    _check_keys(changes)
    new_states, confirm_keys, olds = {}, [], {}
    for key, patch in changes.items():
        old = _state_of(key, o, sw)
        new, need = _plan_row(key, patch, old)
        olds[key] = old
        if new != old:
            new_states[key] = new
            if need:
                confirm_keys.append(key)
    return new_states, confirm_keys, olds


def _mail_items(diffs, actor):
    """通知項目（預覽與實際發送共用同一份）：收件＝最高管理者＋該信件原本的收件角色（管理員／財務）。"""
    from helpers import settings_notify as SN
    out = []
    for key, field, old, new in diffs:
        if key.startswith("cal:"):
            out.append(SN.make_item("mail", "行事曆事件「%s」" % _row_name(key, _cal_only_names()), "開啟" if old else "關閉", "開啟" if new else "關閉",
                                    actor=actor, plain=True, link="mail-settings.html"))
            continue
        t = mt.get(key)
        name = t.name if t else key
        roles = {"admins": ("管理員",), "finance": ("財務",)}.get(t.group, ()) if t else ()
        if field == "mailOff":
            out.append(SN.make_item("mail", "信件「%s」／信件" % name, "關閉" if old else "開啟", "關閉" if new else "開啟", actor=actor, plain=True,
                                    risk="ops" if (new and t and t.category in ("approval", "system")) else "none", roles=roles, link="mail-settings.html"))
        elif field == "calendar":
            out.append(SN.make_item("mail", "信件「%s」／行事曆" % name, "開啟" if old else "關閉", "開啟" if new else "關閉", actor=actor, plain=True, roles=roles, link="mail-settings.html"))
        else:
            out.append(SN.make_item("mail", "信件「%s」／收件人" % name, _mode_text(old), _mode_text(new), actor=actor, plain=True, roles=roles, link="mail-settings.html"))
    return out


def _audit_mark():
    from routers import system as _sys
    return _sys._audit_mark()


def _conflict_who(keys, since_id):
    """套用之後、誰在何時改過這些列 ⇒ {"by", "at"}（只給提示；找不到 ⇒ 空字串，不影響是否拒絕）。"""
    by, at = "", ""
    conn = get_db()
    try:
        rows = conn.execute("SELECT at, username, display_name, action, target_id, detail FROM audit_log WHERE id>? AND (action LIKE 'settings.mail.%' OR action='mail_types.recipients' "
                            "OR action LIKE 'settings.google_calendar.%') ORDER BY id DESC LIMIT 200", (int(since_id or 0),)).fetchall()
        want = set(keys)
        codes = {k[4:] if k.startswith("cal:") else (_primary_code(k) or "") for k in want} - {""}
        for r in rows:
            touched = {r["target_id"] or ""}
            try:
                d = json.loads(r["detail"] or "{}")
            except ValueError:
                d = {}
            if isinstance(d, dict):
                for f in ("keys", "changed"):
                    if isinstance(d.get(f), list):
                        touched |= {x for x in d[f] if isinstance(x, str)}
                for f in ("changes", "states"):
                    if isinstance(d.get(f), dict):
                        touched |= {x for x in d[f] if isinstance(x, str)}
                if isinstance(d.get("event"), str):
                    touched.add("google_calendar." + d["event"])
            if touched & want or any(("google_calendar." + c) in touched for c in codes):
                by, at = (r["display_name"] or r["username"] or ""), (r["at"] or "")
                break
    except Exception:                                                     # noqa: BLE001
        pass
    finally:
        conn.close()
    return {"by": by, "at": at}


def _conflict_response(keys, since_id, names):
    who = _conflict_who(keys, since_id)
    return HTTPException(409, {"code": "conflict", "message": "這些信件設定在你載入頁面之後又被改過，為了不蓋掉別人的修改，系統拒絕儲存。",
                               "keys": [{"key": k, "name": names.get(k) or _row_name(k)} for k in keys], **who})


def _cas_conflicts(keys, expect, o, sw):
    return [k for k in keys if _version_of(_state_of(k, o, sw)) != expect[k]]


@router.post("/api/settings/mail/batch-preview")
def preview_mail_batch(body: dict = Body(...), authorization: str = Header(None)):
    """儲存前的預覽（不寫入、不記稽核、不發通知）：每一列套用前後、哪些是系統技術類（確認視窗紅字）、哪些要二次確認關閉、通知會發給誰。"""
    actor = _require_user(authorization, require_superadmin=True)
    p = _parse_batch(body, need_expect=False)
    o, sw, _co, _cs = _read_state()
    new_states, confirm_keys, olds = _plan_batch(p["changes"], o, sw)
    names = _cal_only_names()
    rows = []
    for key in p["changes"]:
        t = None if key.startswith("cal:") else mt.get(key)
        changed = key in new_states
        old, new = olds[key], new_states.get(key, olds[key])
        rows.append({"key": key, "name": _row_name(key, names), "category": t.category if t else "calendar", "categoryLabel": mt.CATEGORIES[t.category] if t else "僅行事曆",
                     "changed": changed, "system": bool(t and t.category == "system"), "confirmClose": key in confirm_keys,
                     "mailOff": [old.get("off"), new.get("off")], "mode": [old.get("mode"), new.get("mode")],
                     "recipients": [_mode_text(old) if "mode" in old else "", _mode_text(new) if "mode" in new else ""],
                     "calendar": [old.get("cal"), new.get("cal")]})
    _no, _cc, diffs = _diff_states(new_states, o, sw)
    recipients = None
    try:
        from helpers import settings_notify as SN
        recipients = SN.preview_recipients(_mail_items(diffs, actor["username"])) if diffs else None
    except Exception:                                                     # noqa: BLE001
        recipients = None
    return {"ok": True, "rows": rows, "changed": len(new_states), "unchanged": len(p["changes"]) - len(new_states),
            "systemRows": [{"key": r["key"], "name": r["name"]} for r in rows if r["changed"] and r["system"]],
            "confirmRequired": [{"key": k, "name": _row_name(k, names)} for k in confirm_keys], "recipients": recipients}


def _audit_batch(authorization, action, summary, detail):
    _audit(_tok(authorization), action, "settings", "", summary, detail)


def _calendar_audit(authorization, diffs):
    """行事曆事件開關的逐筆紀錄維持原樣（誰、哪一種、由什麼改成什麼）——行事曆頁的歷史看的是這一類紀錄。"""
    try:
        labels = _cal_only_names()
        tok = _tok(authorization)
        for key, field, old, new in diffs:
            if field != "calendar":
                continue
            code = key[4:] if key.startswith("cal:") else _primary_code(key)
            if code:
                _audit(tok, "settings.google_calendar.event_toggle", "settings", "google_calendar." + code,
                       "行事曆事件「%s」%s" % (labels.get(code, code), "開啟" if new else "關閉"), {"event": code, "from": old, "to": new})
    except Exception:                                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("行事曆開關稽核失敗（設定已存好）", exc_info=True)


@router.post("/api/settings/mail/batch")
def save_mail_batch(body: dict = Body(...), authorization: str = Header(None)):
    """草稿一次儲存：**全部驗證過才寫、任一不合法 ⇒ 400 且一個都不寫**；信件覆寫＋行事曆開關同一個交易；整批一筆稽核＋一則設定變更通知。
    `expect`（必帶）＝載入時每一列的 `version`；任一列自那時起被別人改過 ⇒ 409 `{code:'conflict', keys, by, at}`、整批不寫。
    本批有「簽核／系統技術類信件被關閉」時必須帶 `confirm_system: true`，否則 400 `{code:'confirm_system_required', critical}`。"""
    actor = _require_user(authorization, require_superadmin=True)
    p = _parse_batch(body, need_expect=True)
    with _MAIL_LOCK:
        _check_keys(p["changes"])                                          # 先擋格式與不存在的列（不看狀態），再比對版本
        o, sw, _co, _cs = _read_state()
        conflicts = _cas_conflicts(list(p["changes"]), p["expect"], o, sw)
        if conflicts:
            raise _conflict_response(conflicts, p["since_audit"], _cal_only_names())
        new_states, confirm_keys, olds = _plan_batch(p["changes"], o, sw)
        if confirm_keys and not p["confirm_system"]:
            names = _cal_only_names()
            raise HTTPException(400, {"code": "confirm_system_required", "message": "下列信件關閉後，相關人員不會再收到通知，流程或告警可能被忽略；請確認後帶 confirm_system=true 再送一次。",
                                      "critical": [{"key": k, "name": _row_name(k, names)} for k in confirm_keys]})
        diffs = _write_states(new_states, o, sw)
        o2, sw2, _a, _b = _read_state()
        after = {k: _version_of(_state_of(k, o2, sw2)) for k in p["changes"]}
    changed = list(new_states)
    if diffs:
        _audit_batch(authorization, "settings.mail.batch", "信件設定儲存草稿：%d 列（變更 %d）" % (len(p["changes"]), len(changed)),
                     {"changes": p["changes"], "changed": changed, "confirm_system": p["confirm_system"] or None})
        _calendar_audit(authorization, diffs)
        _notify_mail_diffs(diffs, actor["username"])
    return {"ok": True, "changed": changed, "unchanged": [k for k in p["changes"] if k not in new_states], "after": after, "audit_mark": _audit_mark()}


def _notify_mail_diffs(diffs, actor, verb=""):
    try:
        from helpers import settings_notify as SN
        with SN.batch(verb=verb):
            SN.emit(_mail_items(diffs, actor))
    except Exception:                                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("信件設定變更通知失敗（設定已存好）", exc_info=True)


@router.post("/api/settings/mail/batch-undo")
def undo_mail_batch(body: dict = Body(...), authorization: str = Header(None)):
    """「復原這一批」：把一批寫回套用前的狀態（`states`＝套用前每列的狀態），前提是這些列從套用到現在沒被別人改過
    （`expect`＝儲存回應裡的 `after`）；被改過 ⇒ 409、整批不復原。成功只寫一次、記一筆稽核（`settings.mail.batch_undo`）、發一則「復原了…」通知。"""
    actor = _require_user(authorization, require_superadmin=True)
    b = body if isinstance(body, dict) else {}
    extra = sorted(set(b) - {"states", "expect", "since_audit", "confirm_system"})
    if extra:
        raise HTTPException(400, "不認得的欄位：%s" % "、".join(str(x) for x in extra[:5]))
    states, ex = b.get("states"), b.get("expect")
    since = b.get("since_audit", 0)
    if isinstance(since, bool) or not isinstance(since, int):
        raise HTTPException(400, "since_audit 必須是整數")
    if not isinstance(states, dict) or not states or len(states) > _BATCH_MAX_ROWS:
        raise HTTPException(400, "states 必須是 {列代碼: 套用前的狀態}（1～%d 列）" % _BATCH_MAX_ROWS)
    if not isinstance(ex, dict) or any(k not in ex or not isinstance(ex[k], str) for k in states):
        raise HTTPException(400, "expect 必須帶每一列套用後的版本")
    names = _cal_only_names()
    targets = {}
    users = []
    for key, st in states.items():
        if not isinstance(st, dict):
            raise HTTPException(400, "「%s」的狀態格式不對" % key)
        if key.startswith("cal:"):
            if key[4:] not in names or not isinstance(st.get("cal"), bool):
                raise HTTPException(400, "「%s」的狀態格式不對" % key)
            targets[key] = {"cal": st["cal"]}
            continue
        t = mt.get(key)
        if t is None:
            raise HTTPException(404, "信件類型不存在：%s" % key)
        mode = st.get("mode")
        if mode not in mt.MODES or not isinstance(st.get("off"), bool) or (st.get("cal") is not None and not isinstance(st.get("cal"), bool)):
            raise HTTPException(400, "「%s」的狀態格式不對" % t.name)
        us, rs = _norm_list(st.get("users")), [r for r in (st.get("roles") or []) if isinstance(r, str)]
        if [r for r in rs if r not in mt.ROLES] or (mode == "custom" and not us and not rs):
            raise HTTPException(400, "「%s」的狀態格式不對" % t.name)
        if key in mt.MANAGED_ELSEWHERE:
            raise HTTPException(400, mt.MANAGED_ELSEWHERE[key] + "，不在本頁設定。")
        if st["off"] and nm.mail_off_lock_reason(key):
            raise HTTPException(400, "「%s」的信件不能關閉" % t.name)
        if not st["off"]:                            # 與一般批次同一條規則：指定收件人時，系統技術類至少要有人收得到（復原也不能繞過）
            blocked = custom_override_blockers(key, {"mode": mode, "users": us if mode == "custom" else [], "roles": rs if mode == "custom" else []})
            if blocked:
                raise HTTPException(400, blocked[0])
        users += us
        targets[key] = {"mode": mode, "users": us if mode == "custom" else [], "roles": rs if mode == "custom" else [], "off": st["off"], "cal": st.get("cal")}
    _check_users_exist(users)
    with _MAIL_LOCK:
        o, sw, _co, _cs = _read_state()
        conflicts = _cas_conflicts(list(targets), ex, o, sw)
        if conflicts:
            raise _conflict_response(conflicts, since, names)
        critical = [k for k, st in targets.items() if not k.startswith("cal:") and st.get("off") and not nm.is_mail_off(k, o) and nm.mail_off_needs_confirm(k)]
        if critical and b.get("confirm_system") is not True:             # 復原成「關閉」的簽核／系統技術類信件：和一般批次一樣要確認
            raise HTTPException(400, {"code": "confirm_system_required", "message": "下列信件復原後會是關閉狀態，相關人員不會再收到通知；請確認後帶 confirm_system=true 再送一次。",
                                      "critical": [{"key": k, "name": _row_name(k, names)} for k in critical]})
        for key, st in targets.items():
            if "cal" in st and st["cal"] is None:
                st["cal"] = _state_of(key, o, sw).get("cal")                  # 這列沒有自己的行事曆格：保持現狀
        diffs = _write_states(targets, o, sw)
        o2, sw2, _a, _b = _read_state()
        after = {k: _version_of(_state_of(k, o2, sw2)) for k in targets}
    if diffs:
        _audit_batch(authorization, "settings.mail.batch_undo", "信件設定批次復原：%d 列" % len(targets), {"keys": list(targets), "states": states})
        _calendar_audit(authorization, diffs)
        _notify_mail_diffs(diffs, actor["username"], verb="復原")
    return {"ok": True, "restored": list(targets), "after": after, "audit_mark": _audit_mark()}


def _has_email(v) -> bool:
    """與寄信端 SQL `email IS NOT NULL AND email != ''` 同一個判準（D 稽核 O-1：不 strip，只有空白也算有）。"""
    return v is not None and v != ""


def last_superadmin_blockers(conn, user_id, new_muted=None, new_email=None, new_role=None) -> list:
    """U15（使用者 2026-09-26 表單）：系統技術類信件**永遠至少有一人收得到**。

    以「套用這個請求之後」的狀態判斷（D 稽核 M-1）：這位使用者套用 new_muted／new_email／new_role（None＝不變）
    之後，某個系統技術類型的收件人若從「至少一人」變成「零人」⇒ 回傳該類型名稱（空＝放行）。
    收件人依目前的覆寫計算，與寄信端（email_notify._group_emails）同一套規則：預設與 superadmin_only＝最高管理者；
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
        return role == "superadmin"          # 系統技術類的預設群組一律是僅最高管理者（mail_types.register 已守）

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


# ── 本人入口：「我的帳號 → 通知」分頁（設定改版 S6；使用者裁示：本人可自己改，管理員仍可代設）──────────────────────────
# 資料還是同一欄 `users.notification_muted`（退訂清單：空＝全收，新增的信件類型不會悄悄被關掉）；本人與管理員代設共用同一套檢查：
#   · 只能動「自己收得到」的類型（`receivable`）；清單裡別的退訂（例如管理員代設、目前收不到）原樣保留。
#   · 退訂簽核類／系統技術類 ⇒ 要 `confirm=true`（畫面會先跳確認視窗；非業務類不能用批次，逐項確認）。
#   · 最後一位收得到系統技術類信件的最高管理者不能退訂（`last_superadmin_blockers`，與管理員代設同一個檢查）。
#   · `expect`（目前版本）不符 ⇒ 409：管理員剛好代設過，不蓋掉別人的修改。
#   · `preview=true` ⇒ 驗證但不寫入（確認視窗用）。
def _mine_muted(raw):
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:                                                  # noqa: BLE001 — 壞值當空清單
        return []
    return [k for k in (v or []) if isinstance(k, str)]


def _mine_version(muted):
    return hashlib.sha1(json.dumps(sorted(set(muted)), ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _mine_row(conn, user_id):
    return conn.execute("SELECT id, username, role, email, notification_muted FROM users WHERE id=?", (user_id,)).fetchone()


def _mine_items(me, muted):
    o = _overrides()
    order = list(mt.CATEGORIES)
    mset = set(muted)
    items = []
    for t in sorted(mt.all_types(), key=lambda t: (order.index(t.category), t.name)):
        if not receivable(t, o, me["username"], me["role"]):
            continue                                                   # 寄不到我的類型不列（也沒辦法把自己加進去）
        items.append({"key": t.key, "name": t.name, "category": t.category, "categoryLabel": mt.CATEGORIES[t.category],
                      "receive": t.key not in mset, "lowRisk": t.category == "business",
                      "event": t.event, "impact": t.impact, "action": t.action,
                      "managedElsewhere": mt.MANAGED_ELSEWHERE.get(t.key, "")})
    return items


@router.get("/api/mail-types/mine")
def my_mail_prefs(authorization: str = Header(None)):
    """本人的 Email 通知清單：只列「寄得到我」的類型，`receive`＝目前有收；`version` 給 PUT 的 `expect` 用。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        me = _mine_row(conn, user["id"])
    finally:
        conn.close()
    if me is None:
        raise HTTPException(404, "使用者不存在")
    muted = _mine_muted(me["notification_muted"])
    return {"items": _mine_items(me, muted), "hasEmail": _has_email(me["email"]), "version": _mine_version(muted),
            "categories": mt.CATEGORIES}


@router.put("/api/mail-types/mine")
def set_my_mail_prefs(body: dict = Body(...), authorization: str = Header(None)):
    """本人改自己的通知。body：`{changes: {類型代碼: true(要收)|false(不收)}, expect?: 版本, confirm?: bool, preview?: bool}`。
    回 `{ok, preview, changed:[{key,name,receive,lowRisk}], unchanged:[key], risky:[名稱], version}`；沒有實質變動 ⇒ 不寫入、不留稽核。"""
    user = _require_user(authorization)
    body = body or {}
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise HTTPException(400, "沒有要儲存的修改。")
    if any(not isinstance(k, str) or not isinstance(v, bool) for k, v in changes.items()):
        raise HTTPException(400, "changes 的格式是 {類型代碼: true|false}。")
    preview = body.get("preview") is True
    known = {t.key: t for t in mt.all_types()}
    conn = get_db()
    done = None
    try:
        begin_write(conn)
        me = _mine_row(conn, user["id"])
        if me is None:
            raise HTTPException(404, "使用者不存在")
        muted = _mine_muted(me["notification_muted"])
        if body.get("expect") is not None and body.get("expect") != _mine_version(muted):
            raise HTTPException(409, "你的通知設定在你開啟這頁之後被改過（可能是管理員代為設定），請重新整理再改。")
        unknown = [k for k in changes if k not in known]
        if unknown:
            raise HTTPException(400, "不認得的通知類型：%s" % "、".join(unknown))
        o = _overrides()
        not_mine = [known[k].name for k in changes if not receivable(known[k], o, me["username"], me["role"])]
        if not_mine:
            raise HTTPException(400, "下列通知不會寄給你，不需要設定：%s" % "、".join(not_mine))
        new_muted = [k for k in muted if not (k in changes and changes[k] is True)]
        for k, v in changes.items():
            if v is False and k not in new_muted:
                new_muted.append(k)
        changed = [k for k in changes if (k in muted) != (k in new_muted)]
        view = {"ok": True, "preview": preview, "unchanged": [k for k in changes if k not in changed], "version": _mine_version(muted),
                "changed": [{"key": k, "name": known[k].name, "receive": changes[k], "lowRisk": known[k].category == "business"} for k in changed],
                "risky": [known[k].name for k in changed if changes[k] is False and known[k].category != "business"]}
        if changed:
            blocked = last_superadmin_blockers(conn, me["id"], new_muted)
            if blocked:
                raise HTTPException(400, "這樣改之後，下列系統技術類信件就沒有任何最高管理者收得到"
                                         "（至少要有一位；最後一位不能退訂）：%s" % "、".join(blocked))
            if view["risky"] and not preview and body.get("confirm") is not True:
                raise HTTPException(409, "不收「%s」（簽核／系統技術類）後，相關提醒或告警你會收不到、可能因此漏掉；確認請帶 confirm=true 再送一次"
                                    % "、".join(view["risky"]))
        if preview or not changed:
            conn.rollback()
            return view
        conn.execute("UPDATE users SET notification_muted=? WHERE id=?", (json.dumps(new_muted, ensure_ascii=False), me["id"]))
        conn.commit()
        view["version"] = _mine_version(new_muted)
        done = {"by": "self", "turned_off": [known[k].name for k in changed if changes[k] is False],
                "turned_on": [known[k].name for k in changed if changes[k] is True],
                "keys_off": [k for k in changed if changes[k] is False], "keys_on": [k for k in changed if changes[k] is True],
                "muted_before": len(muted), "muted_after": len(new_muted)}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    _audit(_tok(authorization), "user.notification_prefs.self", "user", user["username"], "我的 Email 通知偏好（本人修改）", done)
    return view
