# -*- coding: utf-8 -*-
"""設定與權限共用的「變更明細＋待生效」層（L1；第 54 班設定中心 S0；與 1d 的權限矩陣設計 §7 共同定案）。

[單位] helper:config_ledger    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] HIGH_RISK, RISKS, activate_due, cancel, cancel_pending_for, domains, history, in_effect, pending, record, register_domain,
    restore_version, snapshot_version, state_of, supersede
[不變式] ①`config_changes` 與 `config_change_events` 只增不改不刪（資料庫觸發器擋）；②狀態**不是欄位**：目前狀態＝該變更最後一個事件
    （`pending`／`activated`／`cancelled`／`superseded`），沒有事件＝立即生效；③`record()` 在**呼叫端的交易內**寫變更明細、稽核與
    （高風險時）站內通知——不 commit，也不另開連線（另開連線會撞呼叫端的寫鎖）；④版本快照與還原**不在這裡**：各 domain 用自己的儲存，
    以 `register_domain()` 登記 adapter（權限＝perm_versions、設定＝ui_definitions）；⑤`in_effect()` 是純函式，讀取端（`perm.can()`、
    `settings.get()`）在**讀取時**判斷待生效項，不靠排程。
[契約題] backend/tests/platform/test_config_ledger_t54.py
domain 命名：`<前綴>` 或 `<前綴>:<key>`；前綴＝`setting`（設定群組，key＝群組代號）、`perm`（權限矩陣）、`duty`（R1/R2 的 permission_changes 歷史，不搬資料）。
"""
import json
import re
import uuid
from datetime import datetime

RISKS = ("none", "ops", "money", "legal", "security")
HIGH_RISK = ("money", "legal", "security")          # 通知其他最高管理者、原因必填由呼叫端把關
EVENTS = ("pending", "activated", "cancelled", "superseded")
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{0,19}(:[A-Za-z0-9_.\-]{1,60})?$")
_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
_VALUE_MAX = 20000                                   # 單一值序列化後的長度上限（過長只留摘要，明細層不是資料倉庫）

_DOMAINS = {}                                        # 前綴 -> {"label", "snapshot", "restore", "diff"}


def register_domain(prefix, snapshot_fn=None, restore_fn=None, diff_fn=None, label=""):
    """登記一種 domain 的版本 adapter。`snapshot_fn(conn, key, version=None)`、`restore_fn(conn, key, version, actor, reason)`、
    `diff_fn(conn, key, a, b)`；任一可省略。同前綴重複登記且內容不同 ⇒ ValueError（兩個登記者在搶）。"""
    if not _PREFIX_RE.match(prefix or ""):
        raise ValueError("domain 前綴不合法：%r" % (prefix,))
    entry = {"label": label or prefix, "snapshot": snapshot_fn, "restore": restore_fn, "diff": diff_fn}
    cur = _DOMAINS.get(prefix)
    if cur is not None and cur != entry:
        raise ValueError("domain 已登記：%r" % prefix)
    _DOMAINS[prefix] = entry


def domains():
    return {k: v["label"] for k, v in _DOMAINS.items()}


def _prefix(domain):
    return (domain or "").split(":", 1)[0]


def _dump(v):
    s = json.dumps(v, ensure_ascii=False, default=str)
    if len(s) > _VALUE_MAX:
        s = json.dumps({"_truncated": True, "originalLength": len(s), "preview": s[:_VALUE_MAX // 4]}, ensure_ascii=False)
    return s


def _actor(actor):
    if isinstance(actor, dict):
        return actor.get("username") or "", actor.get("display_name") or "", actor.get("id")
    return str(actor or ""), "", None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def record(conn, domain, key, changes, reason, actor, *, ip="", risk="none", ref_version=None, effective_at=None,
           audit_action=None, target_label="", link="settings-center.html"):
    """在呼叫端交易內寫一批變更。`changes`＝`[{field, old, new}]`（舊＝新的略過）；回 `{"batch", "ids", "audit_id"}`（沒有實質變更 ⇒ ids＝[]）。
    - `effective_at`（ISO 字串）給了 ⇒ 每列加一個 `pending` 事件（待生效）；不給＝立即生效（沒有事件）。
    - 同交易寫 `audit_log`（動作＝`audit_action` 或 `<前綴>.change`；明細含逐欄舊→新與原因）。
    - `risk` 屬 HIGH_RISK ⇒ 站內通知**其他**在職最高管理者（同交易 INSERT；操作者本人不通知）。
    不 commit。"""
    if not _DOMAIN_RE.match(domain or ""):
        raise ValueError("domain 不合法：%r" % (domain,))
    if risk not in RISKS:
        raise ValueError("risk 不合法：%r" % (risk,))
    real = [c for c in (changes or []) if isinstance(c, dict) and c.get("field") is not None and c.get("old") != c.get("new")]
    if not real:
        return {"batch": "", "ids": [], "audit_id": None}
    username, display, uid = _actor(actor)
    now = _now()
    batch = uuid.uuid4().hex
    ids = []
    for c in real:
        cur = conn.execute(
            "INSERT INTO config_changes (at, domain, key, field, old_json, new_json, reason, actor, actor_display, ip, risk, ref_version, effective_at, batch)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, domain, str(key), str(c["field"]), _dump(c.get("old")), _dump(c.get("new")), reason or "", username, display, ip or "", risk,
             ref_version, effective_at or "", batch))
        ids.append(cur.lastrowid)
        if effective_at:
            conn.execute("INSERT INTO config_change_events (change_id, event, actor, reason, at) VALUES (?,?,?,?,?)", (cur.lastrowid, "pending", username, reason or "", now))
    action = audit_action or "%s.change" % _prefix(domain)
    detail = {"domain": domain, "batch": batch, "risk": risk, "reason": reason or "", "ref_version": ref_version,
              "changes": [{"field": c["field"], "old": c.get("old"), "new": c.get("new")} for c in real]}
    if effective_at:
        detail["effective_at"] = effective_at
    payload = _dump(detail)
    cur = conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (now, uid, username, display, action, "config", str(key), target_label or ("%s %s" % (domain, key)), payload, action.split(".", 1)[0], "", ""))
    audit_id = cur.lastrowid
    if risk in HIGH_RISK:
        _notify_others(conn, username, domain, key, risk, link, now,
                       "%s 變更了高風險設定「%s」：%s" % (display or username or "系統", target_label or key, "、".join(str(c["field"]) for c in real)[:80]))
    return {"batch": batch, "ids": ids, "audit_id": audit_id}


def _notify_others(conn, actor_username, domain, key, risk, link, now, message):
    """同交易 INSERT 站內通知（不呼叫 helpers.audit._notify：它自己開連線，會撞呼叫端的寫鎖）。"""
    rows = conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' AND username<>? ORDER BY id", (actor_username or "",)).fetchall()
    for r in rows:
        try:
            conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at, link) VALUES (?,?,?,?,?,0,?,?)",
                         (r[0], "config_change", str(key), str(domain), message, now, link or ""))
        except Exception:                                    # noqa: BLE001 — 舊庫沒有 link 欄：只寫舊欄位
            conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES (?,?,?,?,?,0,?)",
                         (r[0], "config_change", str(key), str(domain), message, now))


def _row(r, last_event):
    d = dict(r)
    d["old"], d["new"] = json.loads(d.pop("old_json") or "null"), json.loads(d.pop("new_json") or "null")
    d["state"] = last_event or ("immediate" if not d.get("effective_at") else "activated")
    return d


def _last_events(conn, ids):
    if not ids:
        return {}
    out = {}
    q = "SELECT change_id, event FROM config_change_events WHERE change_id IN (%s) ORDER BY id" % ",".join("?" * len(ids))
    for cid, ev in conn.execute(q, list(ids)).fetchall():
        out[cid] = ev                                        # 依 id 排序，最後一個覆蓋＝最新事件
    return out


def history(conn, domain=None, key=None, limit=100, offset=0):
    """變更明細（新→舊）。`domain` 給前綴（`setting`）＝該前綴全部；給完整（`setting:retention`）＝只那一個。每列帶目前 `state`。"""
    where, args = [], []
    if domain:
        if ":" in domain:
            where.append("domain=?")
            args.append(domain)
        else:
            where.append("(domain=? OR domain LIKE ?)")
            args += [domain, domain + ":%"]
    if key is not None:
        where.append("key=?")
        args.append(str(key))
    sql = "SELECT * FROM config_changes" + ((" WHERE " + " AND ".join(where)) if where else "") + " ORDER BY id DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, args + [max(1, min(int(limit), 1000)), max(0, int(offset))]).fetchall()
    ev = _last_events(conn, [r["id"] for r in rows])
    return [_row(r, ev.get(r["id"])) for r in rows]


def state_of(conn, change_id):
    r = conn.execute("SELECT effective_at FROM config_changes WHERE id=?", (change_id,)).fetchone()
    if r is None:
        return None
    ev = _last_events(conn, [change_id]).get(change_id)
    return ev or ("immediate" if not r["effective_at"] else "activated")


def pending(conn, domain=None):
    """目前狀態＝pending 的變更（待生效清單）。"""
    rows = history(conn, domain, None, limit=1000)
    return [r for r in rows if r["state"] == "pending"]


def _append(conn, change_id, event, actor, reason):
    if event not in EVENTS:
        raise ValueError("事件不合法：%r" % (event,))
    username, _d, _i = _actor(actor)
    conn.execute("INSERT INTO config_change_events (change_id, event, actor, reason, at) VALUES (?,?,?,?,?)", (change_id, event, username, reason or "", _now()))


def cancel(conn, change_id, actor, reason=""):
    """撤銷一筆**待生效**的變更（已生效／已撤銷的回 False）。不 commit。"""
    if state_of(conn, change_id) != "pending":
        return False
    _append(conn, change_id, "cancelled", actor, reason)
    return True


def supersede(conn, change_id, actor, reason=""):
    """同一目標同一欄位再次申請 ⇒ 舊的待生效項標為 superseded。不 commit。"""
    if state_of(conn, change_id) != "pending":
        return False
    _append(conn, change_id, "superseded", actor, reason)
    return True


def cancel_pending_for(conn, domain, key, actor, reason=""):
    """還原到舊版本時，該 domain 的 restore 呼叫它：這個 key 底下所有待生效項一併撤銷。回撤銷筆數。不 commit。"""
    n = 0
    for r in pending(conn, domain):
        if r["domain"] == domain and r["key"] == str(key) and cancel(conn, r["id"], actor, reason or "還原舊版本時一併撤銷"):
            n += 1
    return n


def activate_due(conn, now=None, domain=None):
    """把已到時的 pending 轉成 activated（定時工作呼叫；漏跑也不改變誰有效，因為 `in_effect()` 在讀取時判斷）。回轉態的 id 清單。不 commit。"""
    now = now or _now()
    done = []
    for r in pending(conn, domain):
        if r["effective_at"] and r["effective_at"] <= now:
            _append(conn, r["id"], "activated", "system", "")
            done.append(r["id"])
    return done


def in_effect(row, now=None):
    """純函式：這一列變更現在算不算有效。`row` 需有 `state`、`effective_at`（`history()` 回傳的就是）。
    cancelled／superseded ⇒ 否；pending ⇒ 只看 `effective_at <= now`（讀取時判斷）；activated／immediate ⇒ 是。"""
    st = row.get("state") or "immediate"
    if st in ("cancelled", "superseded"):
        return False
    if st == "pending":
        return bool(row.get("effective_at")) and row["effective_at"] <= (now or _now())
    return True


def snapshot_version(conn, domain, key, version=None):
    fn = (_DOMAINS.get(_prefix(domain)) or {}).get("snapshot")
    if fn is None:
        raise ValueError("domain %r 沒有登記 snapshot adapter" % domain)
    return fn(conn, key, version)


def restore_version(conn, domain, key, version, actor, reason=""):
    """呼叫該 domain 的 restore adapter（歷史不改，產生新版本），並撤銷這個 key 的待生效項。回 adapter 的結果。不 commit（adapter 可自行 commit）。"""
    fn = (_DOMAINS.get(_prefix(domain)) or {}).get("restore")
    if fn is None:
        raise ValueError("domain %r 沒有登記 restore adapter" % domain)
    out = fn(conn, key, version, actor, reason)
    cancel_pending_for(conn, domain, key, actor, reason)
    return out
