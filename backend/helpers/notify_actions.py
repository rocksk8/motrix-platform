# -*- coding: utf-8 -*-
"""額外通知動作（BP-4 S4；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §4）：管理者宣告「當事件 E 發生，額外通知 R，內容 T」。

[單位] helper:notify_actions    [層] L1    [穩定度] 實驗（旗標關＝完全沒有這個功能）
[公開介面] CAPS, CHANNELS, EVENTS, GROUP, KIND, MAIL_KEY, NOTIF_TYPE, OFF_REASON, PREVIEW_ROLES, SUBSCRIBER, compare, definition_problems, dispatch, emit, enabled, ensure_kind, event_catalog, preview, resolve_actions
[不變式] ①沿用 S-X3 的設定群組 `builder_notify.enabled`，且必須同時開啟 `builder_governance.enabled`（`helpers.notify_templates.enabled`，同一個函式）；
    旗標關著、沒有已發布動作、動作不合法或任何錯誤 ⇒ `dispatch()` 什麼都不做（不寫 `notifications`、不寄信、不拋例外）。
    ②這裡新增的是**額外**通知：不能關掉或改寫任何內建信件、系統技術類或稽核類通知（內建收件人仍用「信件與通知收件設定」）。
    ③事件只能挑 `EVENTS` 已登記的；金額／內部欄位的占位符對沒有權限的收件人一律顯示「（略）」，**遮蔽以收件人為準，不以動作作者為準**；
    條件（`when`）與範本只能用事件宣告的非金額欄位。收件人只收固定目錄（角色、群組、現有啟用帳號、事件裡的申請人／負責人），不收 email 位址、不收網址。
    ④逐人過濾：收件人必須讀得到那張單據（事件登記的 `readable`），讀不到的丟棄並計數（稽核只記人數）。
    ⑤上限（`CAPS`，寫死）：每動作每次觸發 ≤ 25 位收件人、每動作每小時 ≤ 200 封信、整次派發 ≤ 2 秒；超過降級並寫稽核，**絕不影響原交易**（事件在 commit 之後才送達）。
    ⑥通知不再觸發事件（派發中收到的事件一律略過）。信件類型固定為 `user_notice`（主旨前綴與分類由 `mail_types.subject` 決定），按鈕只回首頁。
    ⑦任何放寬（新增動作、擴大收件人、加信件通道、放寬節流、範本新增占位符、`when` 放寬）都走治理（第二位最高管理者核准）；`compare()` 看不懂的一律算放寬。
[契約題] tests/platform/test_notify_actions_t63.py
[注意] 新增一個 kind `notify_action`（key＝動作代號，scope＝company），惰性登記（旗標關 ⇒ 不登記）。S4 只有後端（kind、派發器、事件宣告）；編輯器與試跑預覽是 S5。
    事件宣告在這裡（`events.declare`），**發佈那一行屬各模組的小改**（flag-off、獨立 commit）；沒有發佈者的事件只是目錄，不會有任何通知。
"""
import logging
import re
import string
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from core import definitions as D
from core import events as _events
from helpers import notify_templates as NT

_log = logging.getLogger(__name__)

GROUP = NT.GROUP                    # builder_notify（與 S-X3 通知用語同一個旗標群組）
KIND = "notify_action"
MAIL_KEY = "user_notice"
NOTIF_TYPE = "notify_action"
SUBSCRIBER = "notify_actions"
OFF_REASON = "額外通知尚未開放（設定中心：自訂通知）"

CAPS = {"recipients": 25, "mailsPerHour": 200, "seconds": 2.0, "recipientsDefined": 8, "conditions": 3, "title": 60, "body": 400, "label": 30}
CHANNELS = ("in_app", "email")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
_USER_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,40}$")
_TOP = {"version", "label", "enabled", "event", "when", "channels", "recipients", "template", "throttle"}
_MASK = "（略）"

# ── 事件登記 ──────────────────────────────────────────────────────────────────────────────────
#: 事件代號 ⇒ 說明。`ph`＝占位符名稱 ⇒ payload 欄位；`money`／`internal`＝占位符名稱（沒有權限的收件人看到「（略）」）；
#: `filterable`＝`when` 可用的欄位（占位符名稱，不含金額／內部）；`people`＝收件人類別 ⇒ 取人的方式（payload 欄位名，或 "case_owner"＝案件業務）；
#: `case_key`＝payload 裡的案件單號欄位（逐人讀取權限用）；`module_key`＝payload 裡的模組代號（沒有案件時用模組權限）；`link`＝站內通知連結範本（同站頁面）。
#: `declare`＝這支檔案要不要宣告事件（`custom_module.transitioned` 由 `helpers.custom_modules` 自己宣告）。
EVENTS = {
    "completion_note.attachment_added": {
        "label": "完工單上傳了附件", "owner": "case", "declare": True, "version": 1,
        "fields": ("noteNo", "quoteNo", "slot", "by"),
        "ph": {"完工單號": "noteNo", "單號": "quoteNo", "附件種類": "slot", "操作人": "by"},
        "money": (), "internal": (), "filterable": ("附件種類",),
        "people": {"requester": "by", "owner": "case_owner"}, "case_key": "quoteNo",
        "link": "case-management.html?q={quoteNo}", "ref": ("noteNo",),
        "sample": {"noteNo": "CN-202610-001", "quoteNo": "MQ-202610-001", "slot": "signed", "by": "王小明"},
        "desc": "完工單的附件上傳成功（payload 的 slot 是附件種類代號）",
    },
    "completion_note.state_changed": {
        "label": "完工單狀態改變", "owner": "case", "declare": True, "version": 1,
        "fields": ("noteNo", "quoteNo", "from", "to", "by"),
        "ph": {"完工單號": "noteNo", "單號": "quoteNo", "原狀態": "from", "新狀態": "to", "操作人": "by"},
        "money": (), "internal": (), "filterable": ("原狀態", "新狀態"),
        "people": {"requester": "by", "owner": "case_owner"}, "case_key": "quoteNo",
        "link": "case-management.html?q={quoteNo}", "ref": ("noteNo", "to"),
        "sample": {"noteNo": "CN-202610-001", "quoteNo": "MQ-202610-001", "from": "草稿", "to": "已送出", "by": "王小明"},
        "desc": "完工單的狀態改變（草稿、送出、核准、退回…）",
    },
    "custom_module.transitioned": {
        "label": "自訂模組的單據狀態改變", "owner": "L1:custom_modules", "declare": False, "version": 1,
        "fields": ("module", "recordNo", "from", "to", "action", "by"),
        "ph": {"模組": "module", "單據號": "recordNo", "原狀態": "from", "新狀態": "to", "動作": "action", "操作人": "by"},
        "money": (), "internal": (), "filterable": ("模組", "原狀態", "新狀態", "動作"),
        "people": {"requester": "by"}, "module_key": "module", "link": "", "ref": ("recordNo", "to"),
        "sample": {"module": "demo", "recordNo": "DEMO-001", "from": "草稿", "to": "已送出", "action": "submit", "by": "王小明"},
        "desc": "自訂模組的單據狀態轉換（既有事件，已有發佈者）",
    },
    "case.deadline_near": {
        "label": "案件階段即將到期", "owner": "case", "declare": True, "version": 1,
        "fields": ("quoteNo", "stage", "dueDate", "daysLeft", "assignee"),
        "ph": {"單號": "quoteNo", "階段": "stage", "到期日": "dueDate", "剩餘天數": "daysLeft"},
        "money": (), "internal": (), "filterable": ("階段",),
        "people": {"owner": "case_owner", "requester": "assignee"}, "case_key": "quoteNo",
        "link": "case-management.html?q={quoteNo}", "ref": ("quoteNo", "stage"),
        "sample": {"quoteNo": "MQ-202610-001", "stage": "施工", "dueDate": "2026-10-20", "daysLeft": "3", "assignee": "王小明"},
        "desc": "案件階段離到期日只剩幾天（重用 case_deadlines 的掃描）",
    },
}


def _declare_events():
    """宣告事件（契約進能力目錄）。只宣告、不發佈：沒有發佈者的事件不會產生任何通知。"""
    for name, ev in EVENTS.items():
        if ev["declare"]:
            _events.declare(name, ev["owner"], ev["version"], ev["fields"], ev["desc"])


_declare_events()


def event_catalog() -> list:
    """給編輯器（S5）與測試用：每個事件的說明、占位符、可篩選欄位、可用收件人類別。"""
    return [{"event": k, "label": v["label"], "placeholders": list(v["ph"]), "money": list(v["money"]), "internal": list(v["internal"]),
             "filterable": list(v["filterable"]), "people": sorted(v["people"]), "sample": dict(v["sample"])} for k, v in EVENTS.items()]


def enabled(conn=None) -> bool:
    """fail-closed：與 S-X3 同一個條件（`builder_notify.enabled` 且 `builder_governance.enabled`）。"""
    return NT.enabled(conn)


# ── 驗證 ──────────────────────────────────────────────────────────────────────────────────────
def _text_spec(limit, placeholders, need=()):
    return {"default": None, "limit": limit, "placeholders": tuple(placeholders), "need": tuple(need), "allow_status": False}


def _user_exists(username) -> bool:
    try:
        from db import get_db
        conn = get_db()
        try:
            return conn.execute("SELECT 1 FROM users WHERE username=? AND active=1", (username,)).fetchone() is not None
        finally:
            conn.close()
    except Exception:                                        # noqa: BLE001  查不到 ⇒ 當作不存在（fail closed）
        return False


def definition_problems(key, body):
    """發布前驗證 ⇒ `[{path, message}]`（空＝通過）。"""
    out = []
    add = lambda path, msg: out.append({"path": path, "message": msg})        # noqa: E731
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return [{"path": "", "message": "動作代號只能用小寫英文、數字與底線（3～31 字，英文開頭）"}]
    if not isinstance(body, dict):
        return [{"path": "", "message": "動作必須是物件"}]
    if body.get("version") != 1:
        add("version", "版本必須是 1")
    for k in body:
        if k not in _TOP:
            add(k, "不認得的設定：%s" % k)
    p = NT._text_problems(body.get("label"), _text_spec(CAPS["label"], ()))
    if p:
        add("label", "動作名稱：" + p)
    if not isinstance(body.get("enabled"), bool):
        add("enabled", "必須是 true／false")
    ev = EVENTS.get(body.get("event"))
    if ev is None:
        add("event", "不認得的事件：%s" % (body.get("event"),))
        return out
    allowed_ph = tuple(n for n in ev["ph"] if n not in ev["internal"])
    # when：欄位 ∈ 值集合，最多 3 條 AND，欄位限事件宣告為可篩選的非金額欄位
    when = body.get("when", [])
    if not isinstance(when, list) or len(when) > CAPS["conditions"]:
        add("when", "條件最多 %d 條" % CAPS["conditions"])
    else:
        seen = set()
        for i, c in enumerate(when):
            path = "when[%d]" % i
            if not isinstance(c, dict) or set(c) != {"field", "in"}:
                add(path, "每條條件只能有 field 與 in")
                continue
            if c["field"] not in ev["filterable"] or c["field"] in ev["money"] or c["field"] in ev["internal"]:
                add(path + ".field", "這個事件不能用「%s」當條件（可用：%s）" % (c["field"], "、".join(ev["filterable"]) or "無"))
            if c["field"] in seen:
                add(path + ".field", "同一個欄位只能出現一次")
            seen.add(c["field"])
            vals = c["in"]
            if not isinstance(vals, list) or not (1 <= len(vals) <= 10) or not all(isinstance(v, str) and 1 <= len(v) <= 40 for v in vals):
                add(path + ".in", "必須是 1～10 個文字（每個最多 40 字）")
    ch = body.get("channels")
    if not isinstance(ch, list) or not ch or any(c not in CHANNELS for c in ch) or len(set(ch)) != len(ch) or "in_app" not in ch:
        add("channels", "通道必須包含站內通知，可再加信件（in_app、email）")
    rec = body.get("recipients")
    if not isinstance(rec, list) or not (1 <= len(rec) <= CAPS["recipientsDefined"]):
        add("recipients", "收件人 1～%d 項" % CAPS["recipientsDefined"])
    else:
        from helpers import mail_types as MT
        for i, r in enumerate(rec):
            path = "recipients[%d]" % i
            if not isinstance(r, dict) or not (set(r) <= {"kind", "value"}):
                add(path, "每項收件人只能有 kind 與 value")
                continue
            kind, val = r.get("kind"), r.get("value")
            if kind in ("requester", "owner"):
                if kind not in ev["people"]:
                    add(path + ".kind", "這個事件沒有「%s」可以通知" % {"requester": "操作人／申請人", "owner": "案件負責業務"}[kind])
                if val is not None:
                    add(path + ".value", "這種收件人不用填值")
            elif kind == "role":
                if val not in MT.ROLES:
                    add(path + ".value", "角色必須是：%s" % "、".join(MT.ROLES))
            elif kind == "group":
                if val not in MT.GROUPS or val == "none":
                    add(path + ".value", "群組必須是：%s" % "、".join(g for g in MT.GROUPS if g != "none"))
            elif kind == "user":
                if not isinstance(val, str) or not _USER_RE.match(val) or not _user_exists(val):
                    add(path + ".value", "必須是現有的啟用帳號（只存帳號，不收 email）")
            else:
                add(path + ".kind", "收件人類別必須是 requester、owner、role、group、user 其中之一")
    tpl = body.get("template")
    if not isinstance(tpl, dict) or set(tpl) != {"title", "body"}:
        add("template", "範本必須有 title 與 body")
    else:
        for f, lim in (("title", CAPS["title"]), ("body", CAPS["body"])):
            p = NT._text_problems(tpl.get(f), _text_spec(lim, allowed_ph))
            if p:
                add("template." + f, ("標題：" if f == "title" else "內文：") + p)
    th = body.get("throttle")
    if not isinstance(th, dict) or set(th) != {"dedupeMinutes", "maxPerRecipientPerDay"}:
        add("throttle", "節流必須有 dedupeMinutes 與 maxPerRecipientPerDay")
    else:
        for f, lo, hi in (("dedupeMinutes", 1, 1440), ("maxPerRecipientPerDay", 1, 20)):
            v = th.get(f)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                add("throttle." + f, "必須是 %d～%d 的整數" % (lo, hi))
    return out


def _kind_validator(body, key):
    return definition_problems(key, body)


def _gate(key):
    """通用定義路由的功能狀態閘門：旗標或治理關閉 ⇒ hidden（404）；開著 ⇒ 順手登記 kind（編輯器／定義路由先於任何派發）。"""
    if not enabled():
        return "hidden"
    ensure_kind()
    return "open"


from core import spine as _spine  # noqa: E402

_spine.register_kind_gate(KIND, _gate)


def ensure_kind():
    """惰性登記 kind（旗標關＝不登記，`/api/definition-kinds` 與今天相同）。"""
    if KIND not in D.kinds() and enabled():
        try:
            D.register_kind(KIND, label="額外通知", validator=_kind_validator)
        except ValueError:                                   # 並行登記 ⇒ 已存在
            pass
    return KIND in D.kinds()


try:                                                         # 啟動時旗標若已開 ⇒ 先登記一次；讀不到資料庫 ⇒ 當關（第一次進 `_gate` 時再補）
    ensure_kind()
except Exception:                                            # noqa: BLE001
    pass


# ── 寬嚴比較（`routers/def_pipeline.COMPARATORS` 使用）────────────────────────────────────────
_PH = NT._PH


def _norm(b):
    b = b if isinstance(b, dict) else {}
    tpl = b.get("template") if isinstance(b.get("template"), dict) else {}
    th = b.get("throttle") if isinstance(b.get("throttle"), dict) else {}
    when = {}
    for c in b.get("when") or []:
        if isinstance(c, dict):
            when[c.get("field")] = set(c.get("in") or [])
    return {"enabled": bool(b.get("enabled")), "event": b.get("event"), "when": when, "ch": set(b.get("channels") or []),
            "rec": {(r.get("kind"), r.get("value")) for r in (b.get("recipients") or []) if isinstance(r, dict)},
            "ph": set(_PH.findall((tpl.get("title") or "") + (tpl.get("body") or ""))),
            "dedupe": th.get("dedupeMinutes") or 0, "perDay": th.get("maxPerRecipientPerDay") or 0}


def compare(old, new):
    """old_body → new_body ⇒ (`loosen`｜`tighten`｜`neutral`, reasons)。無法判斷 ⇒ 放寬。
    放寬＝讓更多人在更多情況收到更多東西；改文字（不新增占位符）、縮小、停用＝收緊或中性。"""
    try:
        a, b = _norm(old), _norm(new)
        if not isinstance(new, dict):
            return "loosen", ["無法解析，視為放寬"]
    except Exception:                                        # noqa: BLE001
        return "loosen", ["無法解析，視為放寬"]
    loosen, tighten = [], []
    if not old:                                              # 第一次發布
        if b["enabled"]:
            loosen.append("新增通知動作（有人會開始收到額外通知）")
        return ("loosen", loosen) if loosen else ("neutral", [])
    if b["enabled"] and not a["enabled"]:
        loosen.append("重新啟用")
    if a["enabled"] and not b["enabled"]:
        tighten.append("停用")
    if a["event"] != b["event"]:
        loosen.append("改了觸發事件")
    for r in sorted(b["rec"] - a["rec"], key=str):
        loosen.append("新增收件人：%s%s" % (r[0], "（%s）" % r[1] if r[1] else ""))
    if a["rec"] - b["rec"]:
        tighten.append("縮小收件人")
    if b["ch"] - a["ch"]:
        loosen.append("新增通道：%s" % "、".join(sorted(b["ch"] - a["ch"])))
    if a["ch"] - b["ch"]:
        tighten.append("拿掉通道")
    if b["ph"] - a["ph"]:
        loosen.append("範本新增占位符：%s" % "、".join("{%s}" % x for x in sorted(b["ph"] - a["ph"])))
    for f in a["when"]:                                      # 條件放寬：拿掉條件、或同一欄位的值變多
        if f not in b["when"]:
            loosen.append("拿掉條件「%s」" % f)
        elif b["when"][f] - a["when"][f]:
            loosen.append("條件「%s」多了值：%s" % (f, "、".join(sorted(b["when"][f] - a["when"][f]))))
        elif a["when"][f] - b["when"][f]:
            tighten.append("條件「%s」縮小" % f)
    if set(b["when"]) - set(a["when"]):
        tighten.append("新增條件")
    if b["dedupe"] < a["dedupe"] or b["perDay"] > a["perDay"]:
        loosen.append("放寬節流")
    if b["dedupe"] > a["dedupe"] or b["perDay"] < a["perDay"]:
        tighten.append("加嚴節流")
    unknown = {x for x in set(old) | set(new) if old.get(x) != new.get(x)} - _TOP
    if unknown:
        loosen.append("%s 變了（無法判斷寬嚴，視為放寬）" % "、".join(sorted(unknown)))
    if loosen:
        return "loosen", loosen + tighten
    return ("tighten", tighten) if tighten else ("neutral", [])


# ── 執行期 ────────────────────────────────────────────────────────────────────────────────────
def resolve_actions(conn, event) -> list:
    """已發布、仍合法、已啟用、屬於這個事件的動作 ⇒ `[(key, body)]`。旗標關／任何錯誤 ⇒ []。"""
    if event not in EVENTS or not enabled(conn):
        return []
    ensure_kind()
    out = []
    try:
        for row in D.list_definitions(conn, KIND):
            if row["scope"] != "company" or row["latestVersion"] is None:
                continue
            r = D.get(conn, KIND, row["key"], "company")
            body = (r or {}).get("body")
            if isinstance(body, dict) and body.get("enabled") is True and body.get("event") == event and not definition_problems(row["key"], body):
                out.append((row["key"], body))
    except Exception:                                        # noqa: BLE001
        _log.warning("notify_actions: 讀取已發布動作失敗", exc_info=True)
        return []
    return out


def _matches(body, ev, payload) -> bool:
    for c in body.get("when") or []:
        if str(payload.get(ev["ph"][c["field"]], "")) not in c["in"]:
            return False
    return True


def _case_owner(conn, quote_no):
    try:
        from helpers.case_access import case_owner_username
        return case_owner_username(conn, quote_no)
    except Exception:                                        # noqa: BLE001
        return None


def _people(conn, ev, payload, rec) -> list:
    """一項收件人定義 ⇒ 帳號清單（只含啟用中的帳號）。"""
    from helpers import mail_types as MT
    kind, val = rec.get("kind"), rec.get("value")
    if kind in ("requester", "owner"):
        src = ev["people"].get(kind)
        name = _case_owner(conn, payload.get(ev.get("case_key", ""), "")) if src == "case_owner" else payload.get(src or "")
        names = [name] if name else []
    elif kind == "user":
        names = [val]
    else:
        roles = (val,) if kind == "role" else {"admins": ("admin", "superadmin"), "superadmins": ("superadmin",), "finance": ("finance", "superadmin")}.get(val, ())
        if not roles:
            return []
        ph = ",".join("?" * len(roles))
        return [r["username"] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role IN (%s) ORDER BY username" % ph, list(roles))]
    out = []
    for n in names:
        r = conn.execute("SELECT username FROM users WHERE username=? AND active=1", (n,)).fetchone()
        if r:
            out.append(r["username"])
    return out


def _user_row(conn, username):
    r = conn.execute("SELECT id, username, role, modules, display_name, email, notification_muted FROM users WHERE username=? AND active=1", (username,)).fetchone()
    return dict(r) if r else None


def _readable(conn, ev, payload, user) -> bool:
    """收件人讀得到那張單據嗎？案件類事件 ⇒ 案件存取規則（`helpers.case_access.case_access_allowed`）；模組類事件 ⇒ admin 以上或具備該模組。"""
    try:
        ck = ev.get("case_key")
        if ck:
            from helpers.case_access import case_access_allowed, case_row_for_access
            q = case_row_for_access(conn, payload.get(ck))
            return bool(q) and bool(case_access_allowed(conn, q, user))
        mk = ev.get("module_key")
        if mk:
            from helpers.auth import user_has_module
            return user.get("role") in ("superadmin", "admin") or user_has_module(user, str(payload.get(mk))) is True
    except Exception:                                        # noqa: BLE001  驗權限出錯 ⇒ 不通知
        return False
    return False


def _render(text, ev, payload, user) -> str:
    """逐收件人展開：金額／內部占位符，沒有權限的收件人看到「（略）」。"""
    from helpers.auth import has_finance_access
    ok_money = has_finance_access(user)

    def sub(m):
        name = m.group(1)
        key = ev["ph"].get(name)
        if key is None:
            return ""
        if name in ev["internal"] or (name in ev["money"] and not ok_money):
            return _MASK
        return str(payload.get(key, ""))
    return _PH.sub(sub, text)


def _link(ev, payload) -> str:
    try:
        return string.Formatter().vformat(ev["link"], (), {k: payload.get(k, "") for k in ev["fields"]}) if ev.get("link") else ""
    except Exception:                                        # noqa: BLE001
        return ""


_mail_times: dict = {}
_mail_lock = threading.Lock()
_busy = threading.local()


def _mail_budget(action_id) -> bool:
    """每動作每小時 ≤ 200 封（程序內計數；重啟歸零，是上限不是帳）。"""
    now = time.monotonic()
    with _mail_lock:
        q = _mail_times.setdefault(action_id, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= CAPS["mailsPerHour"]:
            return False
        q.append(now)
        return True


def _throttled(conn, username, action_id, ref, th) -> bool:
    """同一人同一事件 `dedupeMinutes` 分鐘內已收過 ⇒ True；今天收滿 `maxPerRecipientPerDay` 則 ⇒ True（以 notifications 為準）。"""
    since = (datetime.now() - timedelta(minutes=th["dedupeMinutes"])).isoformat()
    if conn.execute("SELECT 1 FROM notifications WHERE username=? AND type=? AND ref_id=? AND created_at>=?", (username, NOTIF_TYPE, ref, since)).fetchone():
        return True
    day = datetime.now().strftime("%Y-%m-%d")
    prefix = action_id + ":"                                 # 精確前綴比對（動作代號含底線，LIKE 會把它當萬用字元）
    n = conn.execute("SELECT COUNT(*) c FROM notifications WHERE username=? AND type=? AND substr(ref_id, 1, ?) = ? AND created_at>=?",
                     (username, NOTIF_TYPE, len(prefix), prefix, day)).fetchone()["c"]
    return n >= th["maxPerRecipientPerDay"]


def _send_mail(user, action_id, title, text) -> str:
    from helpers import email_notify as EN
    from helpers import mail_types as MT
    from helpers import notification_prefs as NP
    if not user.get("email") or EN._mail_off(MAIL_KEY):
        return "skipped"
    if not (NP.is_enabled(user.get("notification_muted"), MAIL_KEY) and NP.is_enabled(user.get("notification_muted"), "na:" + action_id)):
        return "muted"
    if not _mail_budget(action_id):
        return "over_budget"                                 # 呼叫端計數並寫稽核（站內通知照樣送出）
    html = EN._build_html("user_notice", title, "額外通知", "#1D4ED8", [], None, EN._base_url(), intro=text, button_text="前往系統")
    EN._async_send([user["email"]], MT.subject("user_notice", title), html)
    return "sent"


def dispatch(event, payload, conn=None) -> int:
    """事件匯流排的訂閱者：對每個啟用且符合條件的動作寫站內通知（與選填的信件）。⇒ 通知則數；絕不丟例外。"""
    if getattr(_busy, "on", False) or event not in EVENTS:
        return 0
    _busy.on = True
    own = conn is None
    try:
        from db import get_db
        conn = conn if conn is not None else get_db()
        actions = resolve_actions(conn, event)
        if not actions:
            return 0
        return _dispatch(conn, event, EVENTS[event], payload or {}, actions)
    except Exception:                                        # noqa: BLE001  通知壞了不可以影響業務（交易早已 commit）
        _log.error("notify_actions: 派發 %s 失敗", event, exc_info=True)
        return 0
    finally:
        _busy.on = False
        if own and conn is not None:
            try:
                conn.close()
            except Exception:                                # noqa: BLE001
                pass


def _dispatch(conn, event, ev, payload, actions) -> int:
    from helpers.audit import _audit, _notify
    t0, sent = time.monotonic(), 0
    for aid, body in actions:
        if time.monotonic() - t0 > CAPS["seconds"]:
            _audit("", "notify_action.degraded", "notify_action", aid, body.get("label", ""), {"event": event, "reason": "超過時間預算，後面的動作略過"})
            break
        if not _matches(body, ev, payload):
            continue
        names = []
        for rec in body["recipients"]:
            for n in _people(conn, ev, payload, rec):
                if n not in names:
                    names.append(n)
        capped = max(0, len(names) - CAPS["recipients"])
        names = names[:CAPS["recipients"]]
        dropped = n_sent = mail_over = 0
        degraded = False
        ref = aid + ":" + ":".join(str(payload.get(k, "")) for k in ev["ref"])         # 去重鍵＝動作＋這件事的識別（事件登記的 ref 欄位；階段到期含階段、狀態改變含新狀態）
        for n in names:
            if time.monotonic() - t0 > CAPS["seconds"]:             # 時間預算也要在收件人迴圈裡檢查（一個動作 25 人也可能超時）
                degraded = True
                break
            user = _user_row(conn, n)
            if user is None or not _readable(conn, ev, payload, user):
                dropped += 1
                continue
            if _throttled(conn, n, aid, ref, body["throttle"]):
                continue
            title = _render(body["template"]["title"], ev, payload, user)
            text = _render(body["template"]["body"], ev, payload, user)
            _notify(n, NOTIF_TYPE, ref, title, text, _link(ev, payload) or None)
            n_sent += 1
            if "email" in body["channels"]:
                try:
                    if _send_mail(user, aid, title, text) == "over_budget":
                        mail_over += 1
                except Exception:                            # noqa: BLE001  信件失敗不影響站內通知與其他人
                    _log.warning("notify_actions: 寄信失敗（%s）", aid, exc_info=True)
        sent += n_sent
        _audit("", "notify_action.dispatch", "notify_action", aid, body.get("label", ""),
               {"event": event, "recipients": n_sent, "droppedNoAccess": dropped, "overCap": capped, "channels": body["channels"]})
        if mail_over or degraded:                            # 降級一律留稽核（只記人數與原因，不記姓名）
            _audit("", "notify_action.degraded", "notify_action", aid, body.get("label", ""),
                   {"event": event, "mailOverHourlyCap": mail_over, "timeBudgetExceeded": degraded, "notNotified": max(0, len(names) - n_sent - dropped) if degraded else 0})
        if degraded:
            break
    return sent


# ── 試跑預覽（S5 的後端：唯讀；不寄信、不寫 notifications、不發事件）──────────────────────────
PREVIEW_ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")
_ROLE_NAMES = {"superadmin": "最高管理者", "admin": "管理員", "sales": "業務", "engineer": "工程師", "viewer": "檢視者", "finance": "財務"}


def _sample_payload(ev, payload):
    """試跑用的事件內容：沒給 ⇒ 範例；給了 ⇒ 只收事件宣告的欄位、值必須是文字或數字（其餘欄位用範例補）。"""
    out = dict(ev["sample"])
    for k, v in (payload or {}).items():
        if k not in ev["fields"]:
            raise ValueError("事件沒有「%s」這個欄位" % k)
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            raise ValueError("欄位「%s」必須是文字或數字" % k)
        out[k] = v
    return out


def preview(conn, caller, key, body, payload=None) -> dict:
    """試跑：「這個動作（草稿）對這筆事件會發生什麼事」。**唯讀**：不寄信、不寫 `notifications`、不發事件、不計入任何節流。
    ⇒ `{event, label, sample, usesSample, matches, conditions, recipients, readable, renders, estimate, classification, warnings}`。
    只有最高管理者呼叫得到（路由把關）；收件人只回人數與類別，不回姓名。草稿不合法 ⇒ ValueError(problems)；找不到事件 ⇒ LookupError。"""
    problems = definition_problems(key, body)
    if problems:
        raise ValueError(problems)
    ev = EVENTS[body["event"]]
    pay = _sample_payload(ev, payload)
    conds = []
    for c in body.get("when") or []:
        got = str(pay.get(ev["ph"][c["field"]], ""))
        conds.append({"field": c["field"], "value": got, "in": list(c["in"]), "ok": got in c["in"]})
    matches = all(c["ok"] for c in conds)
    recs, total, unknown = [], 0, 0
    names = []
    for r in body["recipients"]:
        who = _people(conn, ev, pay, r) if r["kind"] in ("role", "group", "user") else None
        if who is None:
            unknown += 1                                       # requester／owner：要看實際事件才知道是誰
            recs.append({"kind": r["kind"], "value": r.get("value"), "count": None})
        else:
            recs.append({"kind": r["kind"], "value": r.get("value"), "count": len(who)})
            names += [n for n in who if n not in names]
    total = len(names)
    shown_over = max(0, total - CAPS["recipients"])
    # 逐角色渲染：看看沒有權限的人會看到什麼（金額／內部占位符 ⇒「（略）」）
    renders = []
    for role in PREVIEW_ROLES:
        u = {"role": role, "modules": "[]", "username": "", "id": 0}
        renders.append({"role": role, "roleName": _ROLE_NAMES[role], "title": _render(body["template"]["title"], ev, pay, u),
                        "body": _render(body["template"]["body"], ev, pay, u)})
    # 最近 30 天這個動作實際寄出的則數 ⇒ 每日大約幾則（新動作 ⇒ 0）
    since = (datetime.now() - timedelta(days=30)).isoformat()
    try:
        n30 = conn.execute("SELECT COUNT(*) c FROM notifications WHERE type=? AND substr(ref_id, 1, ?) = ? AND created_at>=?",
                           (NOTIF_TYPE, len(key) + 1, key + ":", since)).fetchone()["c"]
    except Exception:                                          # noqa: BLE001
        n30 = 0
    published = None
    try:
        r0 = D.get(conn, KIND, key, "company") if ensure_kind() else None
        published = (r0 or {}).get("body")
    except Exception:                                          # noqa: BLE001
        published = None
    from routers.def_pipeline import classify
    cls, reasons = classify(KIND, published or {}, body)
    warnings = ["試跑不寄信、不寫通知、不發事件。", "收件人只顯示人數與類別；實際收到的人還要通過『讀得到那張單據』的檢查。"]
    if "email" in body["channels"]:
        warnings.append("信件通道：每動作每小時最多 %d 封，主旨前綴【MOTRIX 系統通知】與分類固定。" % CAPS["mailsPerHour"])
    if shown_over:
        warnings.append("預計收件人 %d 人，超過每次上限 %d 人，多的不會收到。" % (total, CAPS["recipients"]))
    return {"user": caller.get("username"), "role": caller.get("role"), "event": body["event"], "label": ev["label"], "sample": pay,
            "usesSample": not payload, "matches": matches, "conditions": conds, "recipients": recs, "knownRecipientCount": total,
            "eventDependentRecipients": unknown, "overCap": shown_over,
            "readable": "未檢查：試跑用的不是真實單據，實際派發時每位收件人都要讀得到那張單據才會收到" if not payload else "未檢查：試跑只看人數與文字",
            "renders": renders, "estimate": {"last30DaysSent": n30, "perDay": round(n30 / 30.0, 1)},
            "classification": {"class": cls, "reasons": reasons}, "warnings": warnings}


def emit(name, payload) -> int:
    """發佈方的一行：在**自己的 commit 之後**呼叫。照事件匯流排的語意一律發佈（別的訂閱者也聽得到）；任何錯誤只記 log、絕不外拋（通知壞了不可以影響業務）。
    旗標關 ⇒ 本檔的訂閱者什麼都不做（沒有訂閱者也是正常情況）。⇒ 送達的訂閱者數。"""
    try:
        return _events.publish(name, payload)
    except Exception:                                        # noqa: BLE001
        _log.error("notify_actions: 發佈 %s 失敗", name, exc_info=True)
        return 0


def _on_event(name):
    def handler(payload):
        dispatch(name, payload)
    handler.__name__ = "notify_actions_" + name.replace(".", "_")
    return handler


for _name in EVENTS:
    _events.subscribe(_name, _on_event(_name), SUBSCRIBER)
