# -*- coding: utf-8 -*-
"""設定變更通知（2026-11-13，新票 feat/settings-change-notify；使用者：「變更後要有通知……點選後沒人知道變動了」）。

設定中心有任何變更（儲存、還原、重置、套用預設組、待生效項核准／到期生效／撤銷）⇒ **commit 之後**發站內通知：
  ① 全部在職最高管理者（含操作者本人，讓他看到「確實存了」）；② 該欄位 `impact_scope.roles` 列出的角色（對照見 `_ROLE_USERS`；對不上的說法忽略）。
  內容：誰改的、群組／欄位（繁中名稱）、舊值 → 新值（繁中選項名稱）、原因、「立即生效」或「待核准／確認期間後生效」。
  風險 security／money／legal 的欄位另發 LINE（事件 `settings_changed`，LINE-only、只發給最高管理者；LINE 內容不放自由文字與數值，只放名稱與選項）。
  一次操作改很多欄位（儲存多欄、還原、預設組、每日到期生效）⇒ **合併成一則**（預設組跨多個群組：`batch()` 把各群組的 `publish()` 收攏後只發一則）。

[單位] helper:settings_notify    [層] L1    [穩定度] 實作
[公開介面] EVENT_KEY, LINE_RISKS, LINK, NOTIF_TYPE, batch, compose, emit, item, item_from_ledger
[契約題] backend/tests/test_settings_change_notify_2026_11_13.py
不變式：① 永不丟例外、永不影響設定寫入（呼叫端都是 commit 之後才呼叫；內部全部 try/except）；② 不在 `settings_registry._lock` 或任何寫鎖內發（`publish()` 已 commit、鎖已放）；
  ③ 站內通知用一條自己的連線、一個短交易；LINE 走 `line_notify.notify_event`（背景執行緒，LINE 未啟用或事件沒勾選 ⇒ 什麼都不做）。
"""
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

EVENT_KEY = "settings_changed"
NOTIF_TYPE = "settings_changed"
LINK = "settings-center.html"
LINE_RISKS = ("security", "money", "legal")
_MAX_LINES = 8
_MAX_MSG = 900

#: `impact_scope.roles` 的白話說法 ⇒ users.role；None＝所有在職使用者。不在表內的說法（例如「簽核人」「開立勞報單的人」：不是角色）一律忽略。
_ROLE_USERS = {"最高管理者": ("superadmin",), "管理員": ("admin",), "業務": ("sales",), "財務": ("finance",), "出納": ("finance",), "所有使用者": None}

_tl = threading.local()


# ── 項目（一個欄位的一次變動）───────────────────────────────────────────

def _clip(s, n=40):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def item(group, field, old, new, phase, *, actor="", reason="", effective_at="", approvals=0, required=0):
    """組一個通知項目；群組／欄位不認得 ⇒ None（略過）。`phase`：updated｜pending｜pending_approval｜approved｜activated｜cancelled。"""
    try:
        from helpers import settings_registry as sr
        g = sr.groups().get(group)
        f = sr.field_defs(group).get(field)
        if g is None or f is None:
            return None
        return {"group": group, "groupLabel": g["label"], "field": field, "fieldLabel": f.label or field,
                "oldText": _clip(sr.show_value(f, old)), "newText": _clip(sr.show_value(f, new)),
                "plain": bool(f.choices) or f.type == "bool",         # 選項／開關型：值本身就是白話（LINE 可以帶）；數字與文字不帶
                "phase": phase, "actor": actor or "", "reason": (reason or "").strip(), "effectiveAt": effective_at or "",
                "approvals": int(approvals or 0), "required": int(required or 0), "risk": f.risk,
                "roles": list((f.impact_scope or {}).get("roles") or [])}
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.item 失敗：%s", exc)
        return None


def item_from_ledger(row, phase, *, actor="", reason="", approvals=0, required=0):
    """從 `config_changes` 的一列（`sqlite3.Row`／dict；欄位 key／field／old_json／new_json／effective_at）組項目。"""
    import json
    try:
        d = dict(row)
        return item(d["key"], d["field"], json.loads(d.get("old_json") or "null"), json.loads(d.get("new_json") or "null"), phase,
                    actor=actor, reason=reason or d.get("reason") or "", effective_at=d.get("effective_at") or "",
                    approvals=approvals, required=required)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.item_from_ledger 失敗：%s", exc)
        return None


# ── 合併（預設組）───────────────────────────────────────────────────────

class batch:
    """`with batch(): …` 期間所有 `emit()` 只收集，離開時（含例外：已 commit 的變更照樣要通知）合併成**一則**發出。可巢狀（只有最外層發）。"""

    def __enter__(self):
        self._outer = getattr(_tl, "items", None)
        if self._outer is None:
            _tl.items = []
        return self

    def __exit__(self, et, ev, tb):
        if self._outer is None:
            items, _tl.items = _tl.items, None
            _send_safely(items)
        return False


def emit(items):
    """commit **之後**呼叫。在 `batch()` 內 ⇒ 只收集；否則立即發。永不丟例外。"""
    items = [i for i in (items or []) if i]
    if not items:
        return
    buf = getattr(_tl, "items", None)
    if buf is not None:
        buf.extend(items)
        return
    _send_safely(items)


def _send_safely(items):
    if not items:
        return
    try:
        _send(items)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify：發送失敗（不影響設定）：%s", exc)


# ── 文字 ────────────────────────────────────────────────────────────

def _day(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except Exception:                                           # noqa: BLE001
        return (iso or "")[:10]


def _status(it, *, short=False):
    p = it["phase"]
    d = _day(it["effectiveAt"])
    if p == "updated":
        return "已立即生效"
    if p == "pending":
        return "已列入待生效，預計 %s 生效" % d if d else "已列入待生效"
    if p == "pending_approval":
        return "待第二位最高管理者核准，核准後預計 %s 生效" % d if d else "待第二位最高管理者核准"
    if p == "approved":
        return "已核准 %d／%d，預計 %s 生效" % (it["approvals"], it["required"], d) if d else "已核准 %d／%d" % (it["approvals"], it["required"])
    if p == "activated":
        return "已生效"
    if p == "cancelled":
        return "已撤銷，維持原設定"
    return ""


def _who(names, it):
    return names.get(it["actor"]) or it["actor"] or "系統"


def _sentence(it, names):
    base = "「%s／%s」" % (it["groupLabel"], it["fieldLabel"])
    chg = "%s → %s" % (it["oldText"], it["newText"])
    a = _who(names, it)
    p = it["phase"]
    if p == "activated":
        return "%s的待生效變更已生效：%s" % (base, chg)
    if p == "cancelled":
        return "%s撤銷了%s的待生效變更：%s（維持原設定）" % (a, base, chg)
    if p == "approved":
        return "%s核准了%s的變更：%s（%s）" % (a, base, chg, _status(it))
    return "%s修改了%s：%s（%s）" % (a, base, chg, _status(it))


def compose(items, names=None):
    """⇒ (ref_label, message)。單一項目一句話；多項目＝一行摘要＋逐項條列（最多 8 行）；原因（去重後最多兩個）接在最後。"""
    names = names or {}
    if len(items) == 1:
        it = items[0]
        label = "設定變更：%s／%s" % (it["groupLabel"], it["fieldLabel"])
        body = _sentence(it, names)
    else:
        label = "設定變更（%d 項）" % len(items)
        lines = ["• " + _sentence(i, names) for i in items[:_MAX_LINES]]
        if len(items) > _MAX_LINES:
            lines.append("…另 %d 項，請到設定中心的「版本與變更紀錄」查看" % (len(items) - _MAX_LINES))
        body = "共 %d 項設定變更：\n%s" % (len(items), "\n".join(lines))
    reasons = list(dict.fromkeys(i["reason"] for i in items if i["reason"]))[:2]
    if reasons:
        body += "\n原因：" + "；".join(_clip(r, 80) for r in reasons)
    return label, body[:_MAX_MSG]


# ── 發送 ────────────────────────────────────────────────────────────

def _recipients(conn, items):
    """⇒ (最高管理者帳號清單, {帳號: [項目…]})。最高管理者拿全部；其他角色只拿 `impact_scope.roles` 對得上的項目。"""
    sa = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' ORDER BY id").fetchall()]
    per = {u: list(items) for u in sa}
    for it in items:
        roles, everyone = set(), False
        for name in it["roles"]:
            if name not in _ROLE_USERS:
                continue
            if _ROLE_USERS[name] is None:
                everyone = True
            else:
                roles.update(_ROLE_USERS[name])
        if everyone:
            users = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1").fetchall()]
        elif roles:
            users = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role IN (%s)" % ",".join("?" * len(roles)), sorted(roles)).fetchall()]
        else:
            users = []
        for u in users:
            if u not in sa:
                per.setdefault(u, []).append(it)
    return sa, per


def _send(items):
    from db import get_db
    from helpers import audit
    conn = get_db()
    try:
        sa, per = _recipients(conn, items)
        names = {r[0]: (r[1] or r[0]) for r in conn.execute("SELECT username, display_name FROM users").fetchall()}
        for user, its in per.items():
            label, msg = compose(its, names)
            ref = its[0]["group"] if len({i["group"] for i in its}) == 1 else "batch"
            audit._notify_in_txn(conn, user, NOTIF_TYPE, ref, label, msg, LINK)
        conn.commit()
    finally:
        conn.close()
    high = [i for i in items if i["risk"] in LINE_RISKS]
    if high and sa:
        _line(high, sa, names)


def _line(items, superadmins, names):
    """LINE（LINE-only 事件 `settings_changed`）：只發給最高管理者。內容不放自由文字（原因）與數值，只放名稱與選項（`email_notify._line_event` 的內容守則）。"""
    try:
        from helpers import line_notify as _ln
        rows = []
        for i, it in enumerate(items[:5], 1):
            rows.append(("項目" if len(items) == 1 else "項目%d" % i, "%s／%s" % (it["groupLabel"], it["fieldLabel"])))
            if it["plain"]:
                rows.append(("變更", "%s → %s" % (it["oldText"], it["newText"])))
            rows.append(("狀態", _status(it)))
        if len(items) > 5:
            rows.append(("其他", "另 %d 項，請登入系統查看" % (len(items) - 5)))
        rows.append(("操作", ("、".join(dict.fromkeys(_who(names, i) for i in items)))[:40]))
        _ln.notify_event("settings_changed", usernames=list(superadmins), title="設定變更（高風險）", rows=rows, link=LINK)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify：LINE 失敗（站內通知已發）：%s", exc)
