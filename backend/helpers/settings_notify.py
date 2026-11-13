# -*- coding: utf-8 -*-
"""變更通知元件（2026-11-13，feat/settings-change-notify；使用者：「變更後要有通知，或是儲存選項；點選後沒人知道變動了」）。
**所有頁共用同一個通知元件**（設定中心、LINE 矩陣、權限頁、信件頁、簽核流程、獎金預設、營運目標、報價條款…；SPEC §13-7）：呼叫端只需要把「改了什麼」整理成通用項目 `make_item(...)`，
commit **之後**呼叫 `emit()`；收件人解析、合併成一則、LINE（高風險）、收件人預覽都在這裡。設定中心的欄位用 `setting_item(...)`（從登錄表取白話名稱、選項、風險、影響角色）。

[單位] helper:settings_notify    [層] L1    [穩定度] 實作
[公開介面] EVENT_KEY, KIND_LABELS, LINE_RISKS, LINK, NOTIF_TYPE, batch, compose, emit, make_item, notify_change, preview_recipients, setting_item, setting_item_from_ledger
[契約題] backend/tests/test_settings_change_notify_2026_11_13.py
[不變式]
  ① 永不丟例外、永不影響被通知的寫入：呼叫端都在 commit 之後呼叫；內部全部 try/except（失敗只記 warning）。
  ② 不在任何鎖內發：`settings_registry.publish()` 已 commit、`_lock` 已放；站內通知用自己的連線、一個短交易；LINE 走 `line_notify.notify_event`（背景執行緒；LINE 未啟用或事件沒勾選 ⇒ 什麼都不做）。
  ③ 一則合併：同一次伺服器呼叫內的多個項目（多欄、多群組）＝一則；跨呼叫（預設組／批次端點／每日到期生效）用 `with batch():` 收攏，離開時才發（含例外：已 commit 的變更照樣通知）。
  ④ 收件人（`_recipients`）：全部在職最高管理者（含操作者本人）＋項目 `roles` 片語對得上的角色（`_ROLE_USERS`）＋項目 `recipients` 明列的帳號。
     **支援的只有這三種**；角色片語以外的收件人（簽核人、受影響同仁的主管、單據的申請人…）**目前不支援**：片語不在 `_ROLE_USERS` ⇒ 忽略，並在 `preview_recipients()` 的 `ignoredRoles` 列出（畫面據此誠實顯示「另有 X 不在通知對象內」）。
  ⑤ LINE：任一項目 risk 屬 security／money／legal（含呼叫端指定 `risk`）⇒ 另發 LINE `settings_changed` 給最高管理者（LINE-only 事件、預設全關由管理者勾選）；LINE 內容不放原因（自由文字）與數值，只放名稱與選項（`email_notify._line_event` 的內容守則）。
  ⑥ 站內通知超過 8 行 ⇒ 最後一行寫「完整明細：變更紀錄」，通知連結指到設定中心的「版本與變更紀錄」頁籤（單一群組時帶群組）。
  ⑦ 復原：`batch(verb="復原", header="已復原到第 N 版")` 把一次復原（單群組或多群組）發成**一則**「復原了…」，不是每群組一則。
"""
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

EVENT_KEY = "settings_changed"
NOTIF_TYPE = "settings_changed"
LINK = "settings-center.html"
LINE_RISKS = ("security", "money", "legal")
_RISK_ORDER = ("none", "ops", "money", "legal", "security")
_MAX_LINES = 8
_MAX_MSG = 900

#: 項目種類（kind）⇒ 通知標題的前綴。不在表內的種類一律用「設定變更」。新頁接上時在這裡加一行即可。
KIND_LABELS = {"setting": "設定變更", "permission": "權限變更", "mail": "信件設定變更", "line": "LINE 通知設定變更", "approval_flow": "簽核流程變更",
               "bonus_default": "獎金預設變更", "ops_target": "營運目標變更", "quote_terms": "報價條款變更", "personal_pref": "個人偏好變更"}

#: 角色片語 ⇒ users.role；None＝所有在職使用者。不在表內的片語（例如「簽核人」「開立勞報單的人」：不是角色）一律忽略（見不變式 ④）。
_ROLE_USERS = {"最高管理者": ("superadmin",), "管理員": ("admin",), "業務": ("sales",), "財務": ("finance",), "出納": ("finance",), "所有使用者": None}

_tl = threading.local()


def _clip(s, n=40):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


# ── 項目 ────────────────────────────────────────────────────────────────

def make_item(kind, label, old, new, phase="updated", *, actor="", reason="", effective_at="", approvals=0, required=0,
              risk="none", roles=(), recipients=(), plain=False, ref="", link=""):
    """通用項目（所有頁共用）。`label`＝這一項是什麼（例：「報價送審門檻／單項毛利率送審門檻」「王經理的權限：案件管理」）；`old`／`new`＝**已是白話**的值文字。
    `phase`：updated｜pending｜pending_approval｜approved｜activated｜cancelled。`roles`＝受影響的角色片語（見 `_ROLE_USERS`）；`recipients`＝額外明列的帳號。
    `plain`＝值本身是白話選項（LINE 才可以帶；數字、文字、金額不帶）。`ref`＝分組鍵（通知的 ref_id，同一則裡全部相同才寫入，否則 `batch`）。`link`＝點通知要開的頁面（同站檔名＋選填查詢字串）。"""
    return {"kind": kind if kind in KIND_LABELS else "setting", "label": _clip(label, 80), "oldText": _clip(old), "newText": _clip(new), "plain": bool(plain),
            "phase": phase, "actor": actor or "", "reason": (reason or "").strip(), "effectiveAt": effective_at or "",
            "approvals": int(approvals or 0), "required": int(required or 0),
            "risk": risk if risk in _RISK_ORDER else "none", "roles": [str(r) for r in (roles or ())],
            "recipients": [str(u) for u in (recipients or ()) if u], "ref": ref or "", "link": link or "", "verb": ""}


def setting_item(group, field, old, new, phase, *, actor="", reason="", effective_at="", approvals=0, required=0):
    """設定中心欄位的項目：群組／欄位的繁中名稱、選項白話值、風險、影響角色都從登錄表取。群組／欄位不認得 ⇒ None（略過）。"""
    try:
        from helpers import settings_registry as sr
        g = sr.groups().get(group)
        f = sr.field_defs(group).get(field)
        if g is None or f is None:
            return None
        return make_item("setting", "%s／%s" % (g["label"], f.label or field), sr.show_value(f, old), sr.show_value(f, new), phase,
                         actor=actor, reason=reason, effective_at=effective_at, approvals=approvals, required=required, risk=f.risk,
                         roles=(f.impact_scope or {}).get("roles") or (), plain=bool(f.choices) or f.type == "bool", ref=group)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.setting_item 失敗：%s", exc)
        return None


def setting_item_from_ledger(row, phase, *, actor="", reason="", approvals=0, required=0):
    """從 `config_changes` 的一列（欄位 key／field／old_json／new_json／reason／effective_at）組設定項目（核准／撤銷待生效項用）。"""
    import json
    try:
        d = dict(row)
        return setting_item(d["key"], d["field"], json.loads(d.get("old_json") or "null"), json.loads(d.get("new_json") or "null"), phase,
                            actor=actor, reason=reason or d.get("reason") or "", effective_at=d.get("effective_at") or "",
                            approvals=approvals, required=required)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.setting_item_from_ledger 失敗：%s", exc)
        return None


def notify_change(kind, label, old, new, *, actor="", reason="", risk="none", roles=(), recipients=(), plain=False, ref="", link="",
                  phase="updated", effective_at="", approvals=0, required=0):
    """給設定中心以外的頁面（權限、信件、LINE、簽核流程、獎金預設、營運目標、報價條款…）：commit 之後一行呼叫。永不丟例外。
    高敏感權限變更（`kind="permission"`、`risk="security"`）⇒ 站內通知最高管理者＋受影響角色／帳號，並發 LINE 給最高管理者。
    一次操作有很多項目 ⇒ 外面包一層 `with batch():`，只發一則。"""
    try:
        emit([make_item(kind, label, old, new, phase, actor=actor, reason=reason, effective_at=effective_at, approvals=approvals, required=required,
                        risk=risk, roles=roles, recipients=recipients, plain=plain, ref=ref, link=link)])
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.notify_change 失敗：%s", exc)


# ── 合併 ────────────────────────────────────────────────────────────────

class batch:
    """`with batch(): …` 期間所有 `emit()` 只收集，離開時（含例外：已 commit 的變更照樣要通知）合併成**一則**發出。可巢狀（只有最外層發）。
    `verb`（例：「復原」）⇒ 句子用「復原了」；`header` ⇒ 多項目時放在摘要行最前面（例：「已復原到第 3 版」）。"""

    def __init__(self, verb="", header=""):
        self.verb, self.header = verb, header

    def __enter__(self):
        self._outer = getattr(_tl, "buf", None)
        if self._outer is None:
            _tl.buf = {"items": [], "verb": self.verb, "header": self.header}
        return self

    def __exit__(self, et, ev, tb):
        if self._outer is None:
            buf, _tl.buf = _tl.buf, None
            _send_safely(buf["items"], verb=buf["verb"], header=buf["header"])
        return False


def emit(items):
    """commit **之後**呼叫。在 `batch()` 內 ⇒ 只收集；否則立即發。永不丟例外。"""
    items = [i for i in (items or []) if i]
    if not items:
        return
    buf = getattr(_tl, "buf", None)
    if buf is not None:
        buf["items"].extend(items)
        return
    _send_safely(items)


def _send_safely(items, verb="", header=""):
    if not items:
        return
    try:
        _send(items, verb=verb, header=header)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify：發送失敗（不影響被通知的寫入）：%s", exc)


# ── 文字 ────────────────────────────────────────────────────────────────

def _day(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except Exception:                                           # noqa: BLE001
        return (iso or "")[:10]


def _status(it):
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
    base = "「%s」" % it["label"]
    chg = "%s → %s" % (it["oldText"], it["newText"])
    a = _who(names, it)
    p = it["phase"]
    if p == "activated":
        return "%s的待生效變更已生效：%s" % (base, chg)
    if p == "cancelled":
        return "%s撤銷了%s的待生效變更：%s（維持原設定）" % (a, base, chg)
    if p == "approved":
        return "%s核准了%s的變更：%s（%s）" % (a, base, chg, _status(it))
    return "%s%s了%s：%s（%s）" % (a, it["verb"] or "修改", base, chg, _status(it))


def _title_prefix(items):
    kinds = {i["kind"] for i in items}
    return KIND_LABELS[kinds.pop()] if len(kinds) == 1 else KIND_LABELS["setting"]


def _link_for(items):
    """通知連結：同一個頁面連結 ⇒ 用它；超過 8 行（要看完整明細）⇒ 設定中心的「版本與變更紀錄」頁籤（單一群組時帶群組）。"""
    links = {i["link"] for i in items if i["link"]}
    if len(items) > _MAX_LINES:
        refs = {i["ref"] for i in items if i["kind"] == "setting" and i["ref"]}
        return "settings-center.html?tab=versions" + ("&group=%s" % next(iter(refs)) if len(refs) == 1 else "")
    return next(iter(links)) if len(links) == 1 else LINK


def compose(items, names=None, header=""):
    """⇒ (ref_label, message)。單一項目一句話；多項目＝一行摘要＋逐項條列（最多 8 行；超過 ⇒ 最後一行「完整明細：變更紀錄」）；原因（去重後最多兩個）接在最後。"""
    names = names or {}
    prefix = _title_prefix(items)
    if len(items) == 1:
        label = "%s：%s" % (prefix, items[0]["label"])
        body = _sentence(items[0], names)
        if header:
            body = header + "。" + body
    else:
        label = "%s（%d 項）" % (prefix, len(items))
        lines = ["• " + _sentence(i, names) for i in items[:_MAX_LINES]]
        if len(items) > _MAX_LINES:
            lines.append("…另 %d 項。完整明細：變更紀錄（點此開啟）" % (len(items) - _MAX_LINES))
        body = (header + "，" if header else "") + "共 %d 項變更：\n%s" % (len(items), "\n".join(lines))
    reasons = list(dict.fromkeys(i["reason"] for i in items if i["reason"]))[:2]
    if reasons:
        body += "\n原因：" + "；".join(_clip(r, 80) for r in reasons)
    return label, body[:_MAX_MSG]


# ── 收件人（發送與預覽共用）──────────────────────────────────────────────

def _recipients(conn, items):
    """⇒ (最高管理者帳號清單, {帳號: [項目…]}, 被忽略的角色片語清單)。最高管理者拿全部；其他人只拿對得上的項目（角色片語或明列帳號）。"""
    sa = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' ORDER BY id").fetchall()]
    active = None
    per = {u: list(items) for u in sa}
    ignored = []
    for it in items:
        roles, everyone, users = set(), False, []
        for name in it["roles"]:
            if name not in _ROLE_USERS:
                if name not in ignored:
                    ignored.append(name)
                continue
            if _ROLE_USERS[name] is None:
                everyone = True
            else:
                roles.update(_ROLE_USERS[name])
        if everyone:
            users = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1").fetchall()]
        elif roles:
            users = [r[0] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role IN (%s)" % ",".join("?" * len(roles)), sorted(roles)).fetchall()]
        if it["recipients"]:
            if active is None:
                active = {r[0] for r in conn.execute("SELECT username FROM users WHERE active=1").fetchall()}
            users += [u for u in it["recipients"] if u in active]
        for u in dict.fromkeys(users):
            if u not in sa:
                per.setdefault(u, []).append(it)
    return sa, per, ignored


def preview_recipients(items, conn=None):
    """收件人預覽（dry-run，**不寫入、不發送**）：確認視窗顯示「誰會收到」。`items`＝`make_item`／`setting_item` 組出的假想項目（`phase` 用變更之後會是的狀態）。
    ⇒ `{"superadmins": [顯示名稱], "others": [{"username", "display", "count"}], "ignoredRoles": [不支援的片語], "line": {"willSend": bool, "reason": 說明}}`。
    `line.willSend`＝有高風險項目、而且 LINE 啟用且 `settings_changed` 事件已勾選。永不丟例外（出錯 ⇒ 空名單）。"""
    items = [i for i in (items or []) if i]
    out = {"superadmins": [], "others": [], "ignoredRoles": [], "line": {"willSend": False, "reason": "沒有高風險項目，不發 LINE"}}
    if not items:
        return out
    own = conn is None
    try:
        from db import get_db
        c = conn if conn is not None else get_db()
        try:
            sa, per, ignored = _recipients(c, items)
            names = {r[0]: (r[1] or r[0]) for r in c.execute("SELECT username, display_name FROM users").fetchall()}
        finally:
            if own:
                c.close()
        out["superadmins"] = [names.get(u, u) for u in sa]
        out["others"] = [{"username": u, "display": names.get(u, u), "count": len(v)} for u, v in per.items() if u not in sa]
        out["ignoredRoles"] = ignored
        if any(i["risk"] in LINE_RISKS for i in items):
            try:
                from helpers import line_notify as _ln
                on = _ln.event_enabled(EVENT_KEY)
            except Exception:                                   # noqa: BLE001
                on = False
            out["line"] = {"willSend": bool(on and sa), "reason": ("會發 LINE 給最高管理者" if on else "有高風險項目，但 LINE 通知未啟用或「設定變更」事件未勾選，不會發 LINE")}
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify.preview_recipients 失敗：%s", exc)
    return out


# ── 發送 ────────────────────────────────────────────────────────────────

def _send(items, verb="", header=""):
    from db import get_db
    from helpers import audit
    if verb:
        for it in items:
            if it["phase"] in ("updated", "pending", "pending_approval") and not it["verb"]:
                it["verb"] = verb
    conn = get_db()
    try:
        sa, per, _ignored = _recipients(conn, items)
        names = {r[0]: (r[1] or r[0]) for r in conn.execute("SELECT username, display_name FROM users").fetchall()}
        for user, its in per.items():
            label, msg = compose(its, names, header)
            refs = {i["ref"] for i in its}
            audit._notify_in_txn(conn, user, NOTIF_TYPE, next(iter(refs)) if len(refs) == 1 and next(iter(refs)) else "batch", label, msg, _link_for(its))
        conn.commit()
    finally:
        conn.close()
    high = [i for i in items if i["risk"] in LINE_RISKS]
    if high and sa:
        _line(high, sa, names)


def _line(items, superadmins, names):
    """LINE（LINE-only 事件 `settings_changed`）：只發給最高管理者。內容不放自由文字（原因）與數值，只放名稱與選項。"""
    try:
        from helpers import line_notify as _ln
        rows = []
        for i, it in enumerate(items[:5], 1):
            rows.append(("項目" if len(items) == 1 else "項目%d" % i, it["label"]))
            if it["plain"]:
                rows.append(("變更", "%s → %s" % (it["oldText"], it["newText"])))
            rows.append(("狀態", _status(it)))
        if len(items) > 5:
            rows.append(("其他", "另 %d 項，請登入系統查看" % (len(items) - 5)))
        rows.append(("操作", ("、".join(dict.fromkeys(_who(names, i) for i in items)))[:40]))
        _ln.notify_event("settings_changed", usernames=list(superadmins), title="%s（高風險）" % _title_prefix(items), rows=rows, link=LINK)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("settings_notify：LINE 失敗（站內通知已發）：%s", exc)
