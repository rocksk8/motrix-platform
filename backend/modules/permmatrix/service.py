# -*- coding: utf-8 -*-
"""permmatrix 模組的服務層：矩陣覆寫、個人覆寫、代理、24 小時待生效、版本與回溯（設計稿 §2、§4、§8）。

交易約定：每個寫入函式自己 `begin_write` ＋ `commit`（呼叫端給連線）；稽核（`audit_log`）與資料變更**同一個交易**；通知在 commit 之後送。
所有寫入只有最高管理者（呼叫端傳 actor dict）；本檔再檢查一次（縱深）。矩陣的讀取方（`helpers.perm`）經提供者 `perm.matrix_source` 呼叫 `load_matrix`。
"""
import json
import logging
from datetime import datetime, timedelta

from core import capabilities as CAP
from core.txn import begin_write
from helpers import auth as A
from helpers import perm as P

logger = logging.getLogger(__name__)

PENDING_HOURS = 24                                  # 使用者裁示：高風險授予 24 小時後生效、期間可撤銷
POLICY_KEY = "perm_delegation_policy"               # 之後由設定中心的群組 `delegation_policy` 接手（預設值不變）
POLICY_DEFAULT = {"selfDelegateNonRisky": True,     # 今天任何登入者都能替自己建簽核代理
                  "delegationAdditive": True,       # 代理是「額外給代理人」，不是轉移
                  "concurrentRoleExpiry": "optional"}


class PermError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now()


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _name(actor):
    return (actor or {}).get("username") or ""


def _need_super(actor):
    if (actor or {}).get("role") != "superadmin":
        raise PermError("只有最高管理者可以調整權限", 403)


def delegation_policy():
    try:
        from helpers.settings import _get_setting
        v = _get_setting(POLICY_KEY, {}) or {}
    except Exception:                                # noqa: BLE001
        v = {}
    return {**POLICY_DEFAULT, **(v if isinstance(v, dict) else {})}


def _cap_or_err(key):
    c = CAP.get(key)
    if c is None:
        raise PermError("沒有這個能力：%s" % key)
    return c


def _require_reason(reason):
    chars = {ch for ch in (reason or "") if ch.isalnum()}
    if len(chars) < 4:
        raise PermError("高風險授予必須填寫原因（至少 4 個不同的字）")


def _audit_tx(conn, actor, action, target_type, target_id, label, detail):
    """稽核與資料變更同一個交易（寫不進去 ⇒ 整筆回滾）。module＝動作第一段（與 helpers.audit 的推導一致）。"""
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,'','','ok','',0)",
        (_iso(_now()), (actor or {}).get("id"), _name(actor), (actor or {}).get("display_name") or "", action, target_type, str(target_id), label,
         json.dumps(detail, ensure_ascii=False), action.split(".", 1)[0]))


def _superadmins(conn):
    return [r[0] for r in conn.execute("SELECT username FROM users WHERE role='superadmin' AND active=1 ORDER BY id").fetchall()]


def _send(notices):
    """commit 之後送通知：[(username, type, ref, label, message)]；失敗只記 log。"""
    from helpers import _notify
    for u, t, ref, label, msg in notices:
        try:
            _notify(u, t, str(ref), label, msg)
        except Exception:                            # noqa: BLE001
            logger.exception("permmatrix notify %s failed", t)


def _roles():
    return [r for r in A.VALID_ROLES if r != "superadmin"]


# ── 讀：矩陣（提供者）────────────────────────────────────────────────────────────────
def load_matrix(seed):
    """provider `perm.matrix_source`：種子 ⊕ 覆寫列，加個人覆寫與有效代理。先把到期的待生效轉為生效（讀取時判斷，不靠排程）。"""
    from db import get_db
    conn = get_db()
    try:
        activate_due(conn)
        return _build_matrix(conn, seed)
    finally:
        conn.close()


def _build_matrix(conn, seed):
    grants = {r: set(v) for r, v in seed.role_grants.items()}
    for r in conn.execute("SELECT role, cap, granted FROM perm_role_caps").fetchall():
        bucket = grants.setdefault(r["role"], set())
        bucket.add(r["cap"]) if r["granted"] else bucket.discard(r["cap"])
    allow, deny = {}, {}
    for r in conn.execute("SELECT user_id, cap, effect FROM perm_user_overrides").fetchall():
        (allow if r["effect"] == "allow" else deny).setdefault(r["user_id"], set()).add(r["cap"])
    deleg = {}
    for r in conn.execute("SELECT * FROM perm_delegations WHERE state='active' AND scope_kind IN ('caps','doc_types') ORDER BY id").fetchall():
        try:
            sc = json.loads(r["scope_json"] or "{}")
        except ValueError:
            continue
        deleg.setdefault(r["delegate"], []).append(P.Delegation(
            id=r["id"], delegator=r["delegator"], delegate=r["delegate"], scope_kind=r["scope_kind"],
            caps=frozenset(sc.get("caps") or ()), doc_types=frozenset(sc.get("doc_types") or ()),
            valid_from=r["valid_from"] or "", valid_to=r["valid_to"] or ""))
    return P.Matrix(role_grants={k: frozenset(v) for k, v in grants.items()},
                    allow={k: frozenset(v) for k, v in allow.items()}, deny={k: frozenset(v) for k, v in deny.items()},
                    delegations={k: tuple(v) for k, v in deleg.items()})


# ── 版本 ──────────────────────────────────────────────────────────────────────────
def _snapshot(conn):
    return {"role_caps": [dict(r) for r in conn.execute("SELECT role, cap, granted FROM perm_role_caps ORDER BY role, cap").fetchall()],
            "user_overrides": [dict(r) for r in conn.execute("SELECT user_id, cap, effect FROM perm_user_overrides ORDER BY user_id, cap").fetchall()]}


def _version(conn, actor, action, reason):
    cur = conn.execute("INSERT INTO perm_versions (created_at, created_by, action, reason, snapshot_json) VALUES (?,?,?,?,?)",
                       (_iso(_now()), _name(actor), action, reason or "", json.dumps(_snapshot(conn), ensure_ascii=False)))
    return cur.lastrowid


def list_versions(conn, limit=50):
    return [dict(r) for r in conn.execute("SELECT id, created_at, created_by, action, reason FROM perm_versions ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]


# ── 待生效 ────────────────────────────────────────────────────────────────────────
def _request_pending(conn, actor, kind, payload, risk_caps, reason, label):
    now = _now()
    eff = _iso(now + timedelta(hours=PENDING_HOURS))
    cur = conn.execute("INSERT INTO perm_pending (kind, payload_json, risk_caps_json, reason, requested_by, requested_at, effective_at, state)"
                       " VALUES (?,?,?,?,?,?,?, 'pending')",
                       (kind, json.dumps(payload, ensure_ascii=False), json.dumps(sorted(risk_caps)), reason, _name(actor), _iso(now), eff))
    pid = cur.lastrowid
    _audit_tx(conn, actor, "permmatrix.pending.request", "perm_pending", pid, label,
              {"kind": kind, "payload": payload, "riskCaps": sorted(risk_caps), "reason": reason, "effectiveAt": eff})
    notices = [(u, "perm_grant_pending", pid, label, "%s 申請高風險授權：%s（%s 後生效，期間可撤銷）" % (_name(actor), label, eff[:16].replace("T", " ")))
               for u in _superadmins(conn) if u != _name(actor)]
    return {"pending": True, "id": pid, "effectiveAt": eff}, notices


def list_pending(conn, states=("pending",)):
    ph = ",".join("?" * len(states))
    out = []
    for r in conn.execute("SELECT * FROM perm_pending WHERE state IN (%s) ORDER BY id DESC" % ph, tuple(states)).fetchall():
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
        d["riskCaps"] = json.loads(d.pop("risk_caps_json") or "[]")
        out.append(d)
    return out


def cancel_pending(conn, actor, pid, reason):
    _need_super(actor)
    if len((reason or "").strip()) < 2:
        raise PermError("撤銷請填寫原因")
    begin_write(conn)
    try:
        r = conn.execute("SELECT * FROM perm_pending WHERE id=?", (int(pid),)).fetchone()
        if r is None:
            raise PermError("找不到這筆待生效項目", 404)
        cur = conn.execute("UPDATE perm_pending SET state='cancelled', resolved_by=?, resolved_at=?, resolve_note=? WHERE id=? AND state='pending'",
                           (_name(actor), _iso(_now()), reason, int(pid)))
        if cur.rowcount != 1:
            raise PermError("這筆已不是待生效狀態（%s）" % r["state"], 409)
        _audit_tx(conn, actor, "permmatrix.pending.cancel", "perm_pending", pid, "撤銷待生效 #%s" % pid, {"reason": reason, "kind": r["kind"]})
        notices = [(r["requested_by"], "perm_grant_cancelled", pid, "待生效授權已撤銷", "%s 撤銷了你申請的高風險授權 #%s：%s" % (_name(actor), pid, reason))] if r["requested_by"] != _name(actor) else []
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _send(notices)
    P.invalidate()
    return {"ok": True}


def activate_due(conn, now=None):
    """把 `effective_at <= now` 的待生效項目轉為生效。冪等；任何一筆失敗只記 log 不影響其他筆與讀取。回轉了幾筆。"""
    now_iso = _iso(now or _now())
    due = conn.execute("SELECT id FROM perm_pending WHERE state='pending' AND effective_at<=? ORDER BY id", (now_iso,)).fetchall()
    n = 0
    for row in due:
        try:
            begin_write(conn)
            r = conn.execute("SELECT * FROM perm_pending WHERE id=? AND state='pending'", (row["id"],)).fetchone()
            if r is None:
                conn.rollback()
                continue
            payload = json.loads(r["payload_json"] or "{}")
            actor = {"username": r["requested_by"], "role": "superadmin"}
            note = _apply_pending(conn, r["kind"], payload, r["reason"], actor)
            state = "active" if note == "" else "superseded"
            conn.execute("UPDATE perm_pending SET state=?, resolved_by='system', resolved_at=?, resolve_note=? WHERE id=?", (state, now_iso, note, r["id"]))
            _audit_tx(conn, {"username": "system"}, "permmatrix.pending." + ("activate" if state == "active" else "supersede"), "perm_pending", r["id"],
                      "待生效 #%s" % r["id"], {"kind": r["kind"], "payload": payload, "note": note})
            notices = [(u, "perm_grant_activated", r["id"], "高風險授權已生效", "待生效授權 #%s 已生效（%s）" % (r["id"], r["kind"]))
                       for u in set([r["requested_by"]] + _superadmins(conn)) if u] if state == "active" else []
            conn.commit()
            _send(notices)
            n += 1
        except Exception:                             # noqa: BLE001
            conn.rollback()
            logger.exception("permmatrix activate_due #%s failed", row["id"])
    if n:
        P.invalidate()
    return n


def _apply_pending(conn, kind, p, reason, actor):
    """套用一筆到期的待生效；回 '' ＝成功，否則是『被取代／失效』的說明。"""
    now = _iso(_now())
    if kind == "role_cap":
        conn.execute("INSERT INTO perm_role_caps (role, cap, granted, set_by, set_at, reason) VALUES (?,?,?,?,?,?)"
                     " ON CONFLICT(role, cap) DO UPDATE SET granted=excluded.granted, set_by=excluded.set_by, set_at=excluded.set_at, reason=excluded.reason",
                     (p["role"], p["cap"], 1 if p["granted"] else 0, _name(actor), now, reason))
        _version(conn, actor, "role_cap.activate", reason)
        return ""
    if kind == "user_override":
        if conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (p["user_id"],)).fetchone() is None:
            return "對象帳號已不存在或停用"
        conn.execute("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)"
                     " ON CONFLICT(user_id, cap) DO UPDATE SET effect=excluded.effect, set_by=excluded.set_by, set_at=excluded.set_at, reason=excluded.reason",
                     (p["user_id"], p["cap"], p["effect"], _name(actor), now, reason))
        _version(conn, actor, "user_override.activate", reason)
        return ""
    if kind == "delegation":
        if _live_scope(p, _build_matrix(conn, P.seed_from_legacy(CAP.all_caps()))) is None:
            return "委派人已不再擁有範圍內的任何能力"
        _insert_delegation(conn, actor, p, reason, "active")
        return ""
    return "不認得的種類：%s" % kind


# ── 角色格 ────────────────────────────────────────────────────────────────────────
def set_role_cap(conn, actor, role, cap, granted, reason=""):
    """把某角色的某能力改成勾／不勾。回到種子預設＝刪覆寫列（立即）；新增高風險授予＝24 小時待生效。"""
    _need_super(actor)
    c = _cap_or_err(cap)
    if role not in _roles():
        raise PermError("角色不存在或不可調整：%s" % role)
    granted = bool(granted)
    seeded = cap in P.seed_from_legacy(CAP.all_caps()).role_grants.get(role, ())
    if granted and not seeded and not c.delegable:
        raise PermError("「%s」不可委派（僅最高管理者）" % c.label)
    begin_write(conn)
    try:
        cur = conn.execute("SELECT granted FROM perm_role_caps WHERE role=? AND cap=?", (role, cap)).fetchone()
        effective_now = (seeded if cur is None else bool(cur["granted"]))
        if effective_now == granted:
            conn.rollback()
            return {"ok": True, "changed": False}
        label = "%s 角色：%s %s" % (role, c.label, "勾選" if granted else "取消")
        if granted and not seeded and c.risk == "high":
            _require_reason(reason)
            res, notices = _request_pending(conn, actor, "role_cap", {"role": role, "cap": cap, "granted": True}, [cap], reason, label)
            conn.commit()
            _send(notices)
            return res
        if granted == seeded:                          # 回到種子預設 ⇒ 刪覆寫列
            conn.execute("DELETE FROM perm_role_caps WHERE role=? AND cap=?", (role, cap))
        else:
            conn.execute("INSERT INTO perm_role_caps (role, cap, granted, set_by, set_at, reason) VALUES (?,?,?,?,?,?)"
                         " ON CONFLICT(role, cap) DO UPDATE SET granted=excluded.granted, set_by=excluded.set_by, set_at=excluded.set_at, reason=excluded.reason",
                         (role, cap, 1 if granted else 0, _name(actor), _iso(_now()), reason))
        vid = _version(conn, actor, "role_cap.set", reason)
        _audit_tx(conn, actor, "permmatrix.role_cap.set", "perm_role_cap", "%s:%s" % (role, cap), label,
                  {"role": role, "cap": cap, "old": effective_now, "new": granted, "reason": reason, "version": vid})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    P.invalidate()
    return {"ok": True, "changed": True, "version": vid}


# ── 個人覆寫 ───────────────────────────────────────────────────────────────────────
def _target_user(conn, user_id):
    r = conn.execute("SELECT id, username, role FROM users WHERE id=? AND active=1", (int(user_id),)).fetchone()
    if r is None:
        raise PermError("找不到該使用者或帳號已停用", 404)
    if r["role"] == "superadmin":
        raise PermError("最高管理者不受個人覆寫影響", 400)
    return r


def set_user_override(conn, actor, user_id, cap, effect, reason=""):
    _need_super(actor)
    c = _cap_or_err(cap)
    if effect not in ("allow", "deny"):
        raise PermError("effect 只能是 allow 或 deny")
    u = _target_user(conn, user_id)
    if effect == "allow" and not c.delegable:
        raise PermError("「%s」不可委派（僅最高管理者）" % c.label)
    begin_write(conn)
    try:
        cur = conn.execute("SELECT effect FROM perm_user_overrides WHERE user_id=? AND cap=?", (u["id"], cap)).fetchone()
        if cur is not None and cur["effect"] == effect:
            conn.rollback()
            return {"ok": True, "changed": False}
        label = "%s：%s %s" % (u["username"], c.label, "個人允許" if effect == "allow" else "個人禁止")
        if effect == "allow" and c.risk == "high":
            _require_reason(reason)
            res, notices = _request_pending(conn, actor, "user_override", {"user_id": u["id"], "username": u["username"], "cap": cap, "effect": "allow"}, [cap], reason, label)
            conn.commit()
            _send(notices)
            return res
        conn.execute("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)"
                     " ON CONFLICT(user_id, cap) DO UPDATE SET effect=excluded.effect, set_by=excluded.set_by, set_at=excluded.set_at, reason=excluded.reason",
                     (u["id"], cap, effect, _name(actor), _iso(_now()), reason))
        vid = _version(conn, actor, "user_override.set", reason)
        _audit_tx(conn, actor, "permmatrix.user_override.set", "perm_user_override", "%s:%s" % (u["id"], cap), label,
                  {"user": u["username"], "cap": cap, "old": cur["effect"] if cur else "", "new": effect, "reason": reason, "version": vid})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    P.invalidate()
    return {"ok": True, "changed": True, "version": vid}


def clear_user_override(conn, actor, user_id, cap, reason=""):
    """移除個人覆寫（回到角色／模組的結果）。立即生效。"""
    _need_super(actor)
    c = _cap_or_err(cap)
    u = _target_user(conn, user_id)
    begin_write(conn)
    try:
        cur = conn.execute("SELECT effect FROM perm_user_overrides WHERE user_id=? AND cap=?", (u["id"], cap)).fetchone()
        if cur is None:
            conn.rollback()
            return {"ok": True, "changed": False}
        conn.execute("DELETE FROM perm_user_overrides WHERE user_id=? AND cap=?", (u["id"], cap))
        vid = _version(conn, actor, "user_override.clear", reason)
        _audit_tx(conn, actor, "permmatrix.user_override.clear", "perm_user_override", "%s:%s" % (u["id"], cap), "%s：%s 取消個人%s" % (u["username"], c.label, cur["effect"]),
                  {"user": u["username"], "cap": cap, "old": cur["effect"], "new": "", "reason": reason, "version": vid})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    P.invalidate()
    return {"ok": True, "changed": True, "version": vid}


# ── 版本回溯 ───────────────────────────────────────────────────────────────────────
def restore_version(conn, actor, version_id, reason):
    """回到某個舊版本：算出與現況的差異，**逐項走一般寫入路徑**（降權立即；新增高風險授予仍要 24 小時待生效）。歷史不改，每一步都產生新版本。"""
    _need_super(actor)
    if len((reason or "").strip()) < 2:
        raise PermError("回溯請填寫原因")
    row = conn.execute("SELECT snapshot_json FROM perm_versions WHERE id=?", (int(version_id),)).fetchone()
    if row is None:
        raise PermError("找不到這個版本", 404)
    target = json.loads(row["snapshot_json"] or "{}")
    cur = _snapshot(conn)
    tr = {(r["role"], r["cap"]): bool(r["granted"]) for r in target.get("role_caps", [])}
    cr = {(r["role"], r["cap"]): bool(r["granted"]) for r in cur["role_caps"]}
    tu = {(r["user_id"], r["cap"]): r["effect"] for r in target.get("user_overrides", [])}
    cu = {(r["user_id"], r["cap"]): r["effect"] for r in cur["user_overrides"]}
    seed = P.seed_from_legacy(CAP.all_caps())
    done, pending = 0, 0
    for (role, cap) in sorted(set(tr) | set(cr)):
        want = tr.get((role, cap), cap in seed.role_grants.get(role, ()))
        have = cr.get((role, cap), cap in seed.role_grants.get(role, ()))
        if want != have:
            res = set_role_cap(conn, actor, role, cap, want, reason)
            pending += 1 if res.get("pending") else 0
            done += 0 if res.get("pending") else 1
    for (uid, cap) in sorted(set(tu) | set(cu)):
        if tu.get((uid, cap)) != cu.get((uid, cap)):
            if (uid, cap) in tu:
                res = set_user_override(conn, actor, uid, cap, tu[(uid, cap)], reason)
            else:
                res = clear_user_override(conn, actor, uid, cap, reason)
            pending += 1 if res.get("pending") else 0
            done += 0 if res.get("pending") else 1
    begin_write(conn)
    _audit_tx(conn, actor, "permmatrix.version.restore", "perm_version", version_id, "回溯到版本 #%s" % version_id, {"applied": done, "pending": pending, "reason": reason})
    conn.commit()
    return {"ok": True, "applied": done, "pending": pending}


# ── 代理 ──────────────────────────────────────────────────────────────────────────
def _live_scope(p, m=None):
    """範圍內『可委派且委派人目前就有』的能力鍵集合；空 ⇒ None。`m` 省略＝目前的矩陣（啟用待生效時傳入不經提供者的矩陣，避免遞迴）。"""
    caps = CAP.all_caps()
    delegator = P.load_user(p["delegator"])
    if delegator is None:
        return None
    m = m or P.matrix()
    keys = set(p.get("caps") or ())
    for dt in p.get("doc_types") or ():
        keys |= {k for k, c in caps.items() if "%s.%s" % (c.unit, c.obj) == dt}
    live = {k for k in keys if k in caps and caps[k].delegable and P.base_can(delegator, caps[k], m)}
    return live or None


def _insert_delegation(conn, actor, p, reason, state):
    now = _iso(_now())
    scope = {"caps": sorted(p.get("caps") or ()), "doc_types": sorted(p.get("doc_types") or ())}
    cur = conn.execute("INSERT INTO perm_delegations (delegator, delegate, scope_kind, scope_json, valid_from, valid_to, reason, state, requested_by, requested_at, effective_at)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (p["delegator"], p["delegate"], p["scope_kind"], json.dumps(scope, ensure_ascii=False), p.get("valid_from") or "", p.get("valid_to") or "",
                        reason or "", state, _name(actor), now, now))
    _audit_tx(conn, actor, "permmatrix.delegation.create", "perm_delegation", cur.lastrowid, "%s → %s" % (p["delegator"], p["delegate"]),
              {**p, "reason": reason, "state": state})
    return cur.lastrowid


def _date(s, what):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat() if s else ""
    except ValueError:
        raise PermError("%s 格式應為 YYYY-MM-DD" % what)


def create_delegation(conn, actor, delegator, delegate, scope_kind, caps=(), doc_types=(), valid_from="", valid_to="", reason=""):
    """建立代理（範圍＝能力清單或單據類型）。範圍內有高風險能力 ⇒ 只有最高管理者能建、24 小時待生效；
    非風險範圍 ⇒ 委派人本人（政策 selfDelegateNonRisky，預設＝今天的行為）或最高管理者，立即生效。"""
    if scope_kind not in ("caps", "doc_types"):
        raise PermError("scope_kind 只能是 caps 或 doc_types（approval_slot 由簽核代理人既有機制處理，之後併入）")
    if not delegator or not delegate or delegator == delegate:
        raise PermError("委派人與代理人必須是不同的兩個人")
    vf, vt = _date(valid_from, "起日"), _date(valid_to, "迄日")
    if vf and vt and vt < vf:
        raise PermError("迄日不得早於起日")
    p = {"delegator": delegator, "delegate": delegate, "scope_kind": scope_kind, "caps": sorted(set(caps or ())), "doc_types": sorted(set(doc_types or ())),
         "valid_from": vf, "valid_to": vt}
    if scope_kind == "caps" and not p["caps"] or scope_kind == "doc_types" and not p["doc_types"]:
        raise PermError("請指定代理範圍")
    for k in p["caps"]:
        c = _cap_or_err(k)
        if not c.delegable:
            raise PermError("「%s」不可委派" % c.label)
    allc = CAP.all_caps()
    for dt in p["doc_types"]:
        if not any("%s.%s" % (c.unit, c.obj) == dt for c in allc.values()):
            raise PermError("沒有這個單據類型的能力：%s" % dt)
    for u in (delegator, delegate):
        if conn.execute("SELECT 1 FROM users WHERE username=? AND active=1", (u,)).fetchone() is None:
            raise PermError("找不到帳號或已停用：%s" % u, 404)
    live = _live_scope(p)
    if live is None:
        raise PermError("委派人目前沒有範圍內的任何能力——不能憑代理升權")
    risky = sorted(k for k in live if allc[k].risk == "high")
    is_super = (actor or {}).get("role") == "superadmin"
    if risky:
        if not is_super:
            raise PermError("範圍含高風險能力，只有最高管理者可以建立代理", 403)
        _require_reason(reason)
    elif not is_super:
        if _name(actor) != delegator or not delegation_policy().get("selfDelegateNonRisky", True):
            raise PermError("僅能設定自己的代理，如需代替他人設定請聯絡最高管理員", 403)
    begin_write(conn)
    try:
        if risky:
            res, notices = _request_pending(conn, actor, "delegation", p, risky, reason, "代理 %s → %s（%s）" % (delegator, delegate, "、".join(risky[:3])))
            notices += [(delegator, "perm_delegation_pending", res["id"], "代理待生效", "你被設定為 %s 的委派人（%s 後生效）" % (delegate, res["effectiveAt"][:16].replace("T", " ")))]
            conn.commit()
            _send(notices)
            return res
        did = _insert_delegation(conn, actor, p, reason, "active")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    P.invalidate()
    return {"ok": True, "id": did}


def revoke_delegation(conn, actor, delegation_id, reason=""):
    """撤銷代理：委派人本人或最高管理者；立即生效。"""
    begin_write(conn)
    try:
        r = conn.execute("SELECT * FROM perm_delegations WHERE id=?", (int(delegation_id),)).fetchone()
        if r is None:
            raise PermError("找不到這筆代理", 404)
        if (actor or {}).get("role") != "superadmin" and _name(actor) != r["delegator"]:
            raise PermError("僅委派人本人或最高管理者可撤銷", 403)
        if r["state"] != "active":
            raise PermError("這筆代理已不是有效狀態（%s）" % r["state"], 409)
        conn.execute("UPDATE perm_delegations SET state='revoked', revoked_by=?, revoked_at=?, revoke_reason=? WHERE id=?",
                     (_name(actor), _iso(_now()), reason or "", r["id"]))
        _audit_tx(conn, actor, "permmatrix.delegation.revoke", "perm_delegation", r["id"], "%s → %s" % (r["delegator"], r["delegate"]), {"reason": reason})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    P.invalidate()
    return {"ok": True}


def list_delegations(conn, state=None):
    q = "SELECT * FROM perm_delegations" + (" WHERE state=?" if state else "") + " ORDER BY id DESC"
    out = []
    for r in conn.execute(q, (state,) if state else ()).fetchall():
        d = dict(r)
        d["scope"] = json.loads(d.pop("scope_json") or "{}")
        out.append(d)
    return out
