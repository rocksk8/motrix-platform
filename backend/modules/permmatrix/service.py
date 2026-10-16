# -*- coding: utf-8 -*-
"""permmatrix 模組的服務層：矩陣覆寫、個人覆寫、代理、待生效（設定帳本＋確認期間＋放寬需第二位最高管理者核准）、版本與回溯（設計稿 §2、§4、§8；T67 PM-S0）。

交易約定：每個寫入函式自己 `begin_write` ＋ `commit`（呼叫端給連線）；稽核（`audit_log`）與資料變更**同一個交易**；通知在 commit 之後送。
所有寫入只有最高管理者（呼叫端傳 actor dict）；本檔再檢查一次（縱深）。矩陣的讀取方（`helpers.perm`）經提供者 `perm.matrix_source` 呼叫 `load_matrix`。
"""
import json
import logging
import threading
from datetime import datetime, timedelta

from core import capabilities as CAP
from core.txn import begin_write
from helpers import auth as A
from helpers import config_ledger as L
from helpers import perm as P

logger = logging.getLogger(__name__)

PENDING_DOMAIN = "perm"                             # 設定帳本的 domain 前綴；實際 domain＝`perm:<kind>`（kind＝role_cap／user_override／user_override_clear／delegation）
PENDING_RISK = "security"                           # 權限變更在帳本的風險等級（屬 HIGH_RISK ⇒ 帳本同交易通知其他最高管理者）
PENDING_LINK = "permission-matrix.html"
DEFAULT_CONFIRM_DAYS = 7                            # 讀不到設定中心的確認期間時的預設（與 settings_registry.DEFAULT_CONFIRM_DAYS 同值）
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
    """provider `perm.matrix_source`：種子 ⊕ 覆寫列，加個人覆寫與有效代理。**純讀取**——權限檢查的讀取路徑不寫資料庫、不等寫鎖
    （05 稽核 B）。到期的待生效由 `kick_activation()` 在背景執行緒（單一飛行、拿不到鎖就略過）轉為生效；轉完會 `invalidate()`，下一次讀取就看到。"""
    from db import get_db
    conn = get_db()
    try:
        m = _build_matrix(conn, seed)
        due = bool(_due_rows(conn, _iso(_now())))
    finally:
        conn.close()
    if due:
        kick_activation()
    return m


_act_lock = threading.Lock()


def kick_activation(wait=False):
    """到期待生效的背景轉態：單一飛行（已有一條在跑 ⇒ 直接返回 None），不阻塞呼叫端。`wait=True`（測試／排程）等它跑完。回執行緒或 None。"""
    if not _act_lock.acquire(blocking=False):
        return None

    def _run():
        try:
            from db import get_db
            c = get_db()
            try:
                activate_due(c)
            finally:
                c.close()
        except Exception:                                           # noqa: BLE001
            logger.exception("permmatrix background activation failed")
        finally:
            _act_lock.release()

    t = threading.Thread(target=_run, name="permmatrix-activate", daemon=True)
    try:
        t.start()
    except Exception:                                               # noqa: BLE001 — 起不了執行緒：放鎖，下次讀取再試（不讓鎖永遠卡住）
        _act_lock.release()
        logger.exception("permmatrix activation thread failed to start")
        return None
    if wait:
        t.join()
    return t


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
def _write_role_cell(conn, actor, role, cap, granted, seeded, reason):
    """寫一個角色格：回到種子預設＝刪覆寫列，否則 upsert。立即路徑與到期套用共用這一份。"""
    if granted == seeded:
        conn.execute("DELETE FROM perm_role_caps WHERE role=? AND cap=?", (role, cap))
    else:
        conn.execute("INSERT INTO perm_role_caps (role, cap, granted, set_by, set_at, reason) VALUES (?,?,?,?,?,?)"
                     " ON CONFLICT(role, cap) DO UPDATE SET granted=excluded.granted, set_by=excluded.set_by, set_at=excluded.set_at, reason=excluded.reason",
                     (role, cap, 1 if granted else 0, _name(actor), _iso(_now()), reason))


def _delete_override(conn, user_id, cap):
    conn.execute("DELETE FROM perm_user_overrides WHERE user_id=? AND cap=?", (user_id, cap))


def _confirm_days(conn):
    """確認期間（天）：與設定中心同一把（`change_control.confirm_period_days`，預設 7、下限 1）；讀不到 ⇒ 預設。永不丟例外。"""
    try:
        from helpers import settings_registry as SR
        return max(1, int(SR.confirm_period_days(conn)))
    except Exception:                                # noqa: BLE001
        return DEFAULT_CONFIRM_DAYS


def _due_rows(conn, now_iso):
    """到期且已集滿核准票數的待生效變更（帳本 `in_effect` 判斷；純讀取）。先用一句 SQL 篩掉沒有到期項的常見情況。"""
    if conn.execute("SELECT 1 FROM config_changes WHERE domain LIKE 'perm:%' AND effective_at<>'' AND effective_at<=? LIMIT 1", (now_iso,)).fetchone() is None:
        return []
    return [r for r in L.pending(conn, PENDING_DOMAIN) if r["domain"].startswith("perm:") and L.in_effect(r, now_iso)]


def _request_pending(conn, actor, kind, key, old, payload, reason, label):
    """放寬類變更：寫帳本待生效明細（確認期間後生效，期間可撤銷）；有其他在職最高管理者 ⇒ 還要其中一位核准（雙人核准，D-K1 同一條規則）。
    只有申請人一位最高管理者 ⇒ 改為『原因＋確認期間＋警告』。同一目標更早的待生效項標為被取代。回 (結果, commit 之後才送的通知)。"""
    days = _confirm_days(conn)
    eff = _iso(_now() + timedelta(days=days))
    domain = "%s:%s" % (PENDING_DOMAIN, kind)
    need = 1 if [u for u in _superadmins(conn) if u != _name(actor)] else 0
    for r in L.pending(conn, domain):
        if r["domain"] == domain and r["key"] == key:
            L.supersede(conn, r["id"], actor, "被較新的申請取代")
    rec = L.record(conn, domain, key, [{"field": kind, "old": old, "new": payload}], reason, actor, risk=PENDING_RISK, effective_at=eff,
                   audit_action="permmatrix.pending.request", target_label=label, link=PENDING_LINK, approvals_required=need)
    res = {"pending": True, "id": rec["ids"][0], "effectiveAt": eff, "confirmDays": days, "approvalsRequired": need, "warnings": []}
    if not need:
        res["warnings"].append("目前只有一位最高管理者，沒有第二人可以核准：這項放寬改為「填寫原因、等 %d 天確認期間後生效」，並已留下紀錄。" % days)
    return res, []


def list_pending(conn, states=("pending",)):
    """待生效清單（帳本資料）。每列：id、kind、key、payload、reason、requested_by、requested_at、effective_at、state、approvals、approvalsRequired、riskCaps。"""
    out = []
    for r in L.history(conn, PENDING_DOMAIN, None, limit=1000):
        if not r["domain"].startswith("perm:") or r["state"] not in states:
            continue
        pl = r["new"] if isinstance(r["new"], dict) else {}
        out.append({"id": r["id"], "kind": r["domain"].split(":", 1)[1], "key": r["key"], "payload": pl, "reason": r["reason"],
                    "requested_by": r["actor"], "requested_at": r["at"], "effective_at": r["effective_at"], "state": r["state"],
                    "approvals": list(r.get("approvals") or []), "approvalsRequired": int(r.get("approvals_required") or 0),
                    "riskCaps": [pl["cap"]] if pl.get("cap") else sorted(pl.get("caps") or ())})
    return out


def _pending_requester(conn, pid):
    r = conn.execute("SELECT domain, actor FROM config_changes WHERE id=?", (int(pid),)).fetchone()
    if r is None or not r["domain"].startswith("perm:"):
        raise PermError("找不到這筆待生效項目", 404)
    return r["actor"]


def cancel_pending(conn, actor, pid, reason):
    """撤銷待生效項：任一最高管理者（含申請人本人）皆可，需原因；已非待生效 ⇒ 409。"""
    _need_super(actor)
    if len((reason or "").strip()) < 2:
        raise PermError("撤銷請填寫原因")
    begin_write(conn)
    try:
        req = _pending_requester(conn, pid)
        st = L.state_of(conn, int(pid))
        if not L.cancel(conn, int(pid), actor, reason):
            raise PermError("這筆已不是待生效狀態（%s）" % st, 409)
        L.audit_event(conn, actor, "permmatrix.pending.cancel", pid, {"reason": reason, "id": int(pid)}, target_label="撤銷待生效 #%s" % pid)
        notices = [(req, "perm_grant_cancelled", pid, "待生效授權已撤銷", "%s 撤銷了你申請的授權變更 #%s：%s" % (_name(actor), pid, reason))] if req != _name(actor) else []
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _send(notices)
    P.invalidate()
    return {"ok": True}


def approve_pending(conn, actor, pid, reason=""):
    """雙人核准的一票：另一位最高管理者核准放寬（申請人不能核准自己的、同一人不能重複投票——帳本把關）。核准不會讓它立刻生效：仍要等確認期間。"""
    _need_super(actor)
    begin_write(conn)
    try:
        _pending_requester(conn, pid)
        res = L.approve(conn, int(pid), actor, reason)
        if not res["ok"]:
            raise PermError(res["why"], 409)
        L.audit_event(conn, actor, "permmatrix.pending.approve", pid, {"id": int(pid), "approvals": res["approvals"], "required": res["required"], "reason": reason},
                      target_label="核准待生效 #%s" % pid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"ok": True, "approvals": res["approvals"], "required": res["required"]}


def activate_due(conn, now=None):
    """把到期且核准票數足夠的待生效項目轉為生效。冪等；任何一筆失敗只記 log、該筆撤銷並稽核，不影響其他筆與讀取（逐筆 SAVEPOINT）。回處理了幾筆（含被取代者）。"""
    now_iso = _iso(now or _now())
    n, applied, notices = 0, False, []
    try:
        begin_write(conn)
        for r in sorted(_due_rows(conn, now_iso), key=lambda x: x["id"]):
            conn.execute("SAVEPOINT pm_row")
            try:
                kind = r["domain"].split(":", 1)[1]
                payload = r["new"] if isinstance(r["new"], dict) else {}
                if conn.execute("SELECT 1 FROM users WHERE username=? AND active=1 AND role='superadmin'", (r["actor"],)).fetchone() is None:
                    note = "申請人已不是在職的最高管理者，未套用"          # 05 稽核 C：申請後被降級／停用 ⇒ 不以他的名義套用
                else:
                    note = _apply_pending(conn, kind, payload, r["reason"], {"username": r["actor"], "role": "superadmin"})
                if note:
                    L.supersede(conn, r["id"], "system", note)
                else:
                    applied = True
                    notices += [(u, "perm_grant_activated", r["id"], "授權變更已生效", "待生效授權 #%s 已生效（%s）" % (r["id"], kind))
                                for u in set([r["actor"]] + _superadmins(conn)) if u]
                L.audit_event(conn, "system", "permmatrix.pending." + ("supersede" if note else "activate"), r["id"],
                              {"kind": kind, "payload": payload, "note": note}, target_label="待生效 #%s" % r["id"])
                conn.execute("RELEASE pm_row")
                n += 1
            except Exception:                         # noqa: BLE001
                conn.execute("ROLLBACK TO pm_row")
                conn.execute("RELEASE pm_row")
                logger.exception("permmatrix activate_due #%s failed", r["id"])
                L.cancel(conn, r["id"], "system", "套用時發生錯誤，已自動撤銷（詳見伺服器紀錄）")
        L.promote_due(conn, now_iso, domain=PENDING_DOMAIN)       # 套用成功的（仍是 pending 且已生效者）轉 activated；被取代／撤銷的已不是 pending
        conn.commit()
    except Exception:                                 # noqa: BLE001
        if conn.in_transaction:
            conn.rollback()
        logger.exception("permmatrix activate_due failed")
        return 0
    _send(notices)
    if applied:
        P.invalidate()
    return n


def _apply_pending(conn, kind, p, reason, actor):
    """套用一筆到期的待生效；回 '' ＝成功，否則是『被取代／失效』的說明。"""
    now = _iso(_now())
    if kind == "role_cap":
        seeded = p["cap"] in P.seed_from_legacy(CAP.all_caps()).role_grants.get(p["role"], ())
        _write_role_cell(conn, actor, p["role"], p["cap"], bool(p["granted"]), seeded, reason)      # 回到種子預設 ⇒ 刪覆寫列（與立即路徑一致）
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
    if kind == "user_override_clear":
        cur = conn.execute("SELECT effect FROM perm_user_overrides WHERE user_id=? AND cap=?", (p["user_id"], p["cap"])).fetchone()
        if cur is None or cur["effect"] != "deny":
            return "個人禁止已不存在或已改變"
        _delete_override(conn, p["user_id"], p["cap"])
        _version(conn, actor, "user_override.clear_activate", reason)
        return ""
    if kind == "delegation":
        if _live_scope(p, _build_matrix(conn, P.seed_from_legacy(CAP.all_caps()))) is None:
            return "委派人已不再擁有範圍內的任何能力"
        _insert_delegation(conn, actor, p, reason, "active")
        return ""
    return "不認得的種類：%s" % kind


# ── 角色格 ────────────────────────────────────────────────────────────────────────
def set_role_cap(conn, actor, role, cap, granted, reason=""):
    """把某角色的某能力改成勾／不勾。收緊與低風險放寬立即；**任何放寬高風險能力**（含把種子本來就有、後來被取消的格子勾回來）＝24 小時待生效（過渡實作，見 SPEC PMX13）。"""
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
        if granted and c.risk == "high":                # 此時 effective_now 必為 False ⇒ 一定是放寬（含種子預設被取消後勾回）
            _require_reason(reason)
            res, notices = _request_pending(conn, actor, "role_cap", "%s:%s" % (role, cap), {"granted": effective_now}, {"role": role, "cap": cap, "granted": True}, reason, label)
            conn.commit()
            _send(notices)
            return res
        _write_role_cell(conn, actor, role, cap, granted, seeded, reason)
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
            res, notices = _request_pending(conn, actor, "user_override", "%s:%s" % (u["id"], cap), {"effect": cur["effect"] if cur else ""},
                                           {"user_id": u["id"], "username": u["username"], "cap": cap, "effect": "allow"}, reason, label)
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
    """移除個人覆寫（回到角色／模組的結果）。移除個人允許＝收緊，立即；**移除高風險能力的個人禁止＝放寬**，走 24 小時待生效（需原因；過渡實作，見 SPEC PMX13）。"""
    _need_super(actor)
    c = _cap_or_err(cap)
    u = _target_user(conn, user_id)
    begin_write(conn)
    try:
        cur = conn.execute("SELECT effect FROM perm_user_overrides WHERE user_id=? AND cap=?", (u["id"], cap)).fetchone()
        if cur is None:
            conn.rollback()
            return {"ok": True, "changed": False}
        if cur["effect"] == "deny" and c.risk == "high":
            _require_reason(reason)
            label = "%s：%s 取消個人禁止" % (u["username"], c.label)
            res, notices = _request_pending(conn, actor, "user_override_clear", "%s:%s" % (u["id"], cap), {"effect": "deny"},
                                           {"user_id": u["id"], "username": u["username"], "cap": cap}, reason, label)
            conn.commit()
            _send(notices)
            return res
        _delete_override(conn, u["id"], cap)
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
    return _restore_snapshot(conn, actor, json.loads(row["snapshot_json"] or "{}"), reason, "版本 #%s" % version_id)


def _restore_snapshot(conn, actor, target, reason, label):
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
    _audit_tx(conn, actor, "permmatrix.version.restore", "perm_version", label, "回溯到" + label, {"applied": done, "pending": pending, "reason": reason})
    conn.commit()
    return {"ok": True, "applied": done, "pending": pending}


UNDO_REASON = "一鍵復原"


def undo_last_change(conn, actor):
    """一鍵復原：回到『上一個狀態』。每按一次往回一步（復原本身產生的版本不算一步，所以不會來回跳）；
    走一般寫入規則（新增高風險授予仍要 24 小時）。已經是最早的狀態 ⇒ 錯誤。"""
    _need_super(actor)
    cur = _snapshot(conn)
    vers = [(r["id"], json.loads(r["snapshot_json"] or "{}")) for r in conn.execute(
        "SELECT id, snapshot_json FROM perm_versions WHERE reason<>? ORDER BY id", (UNDO_REASON,)).fetchall()]
    empty = {"role_caps": [], "user_overrides": []}
    idx = None
    for i in range(len(vers) - 1, -1, -1):
        if vers[i][1] == cur:
            idx = i
            break
    if idx is None:
        idx = len(vers)                       # 現況不在歷史裡（例如待生效剛生效）⇒ 回到最近一個版本
    if idx == 0 and cur == empty:
        raise PermError("沒有可以復原的變更")
    target = vers[idx - 1][1] if idx >= 1 else empty
    if target == cur:
        raise PermError("沒有可以復原的變更")
    return _restore_snapshot(conn, actor, target, UNDO_REASON, "上一個狀態")


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
            res, notices = _request_pending(conn, actor, "delegation", "%s>%s" % (delegator, delegate), None, dict(p, riskCaps=risky), reason, "代理 %s → %s（%s）" % (delegator, delegate, "、".join(risky[:3])))
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


# ── 白話預覽（存檔前的「影響面板」）與一鍵復原 ─────────────────────────────────────────────
def _risk_hint(conn, key):
    """L1 `perm_text.risk_hint` 的句子寫的是舊的『24 小時後才會生效』；這裡換成目前的規則（確認期間＋第二位最高管理者核准）。低風險仍回空字串。"""
    from helpers import perm_text as T
    h = T.risk_hint(key)
    return h.replace("24 小時後才會生效，這段時間內隨時可以撤銷。", "要等 %d 天確認期間後才會生效，需要另一位最高管理者核准，這段時間內隨時可以撤銷。" % _confirm_days(conn)) if h else h


def _preview(conn, cap, sentence, users, delay, extra=None):
    """共用的預覽內容：句子、勾選後會影響什麼、影響幾位使用者／幾份單據、適用範圍、可否復原、何時生效、風險提示。畫面只顯示這些中文。"""
    from helpers import perm_text as T
    out = {
        "sentence": sentence,
        "impact": cap.impact,                                             # 宣告時寫的白話影響說明
        "users": users,
        "usersText": "約影響 %d 位使用者" % users,
        "appliesTo": "之後的操作會依新設定；已經送出或完成的單據與簽核紀錄不受影響",
        "reversible": True,
        "reversibleText": "隨時可以一鍵復原",
        "effective": ("%d 天確認期間後生效（這段時間內可以撤銷；需要另一位最高管理者核准）" % _confirm_days(conn)) if delay else "儲存後立即生效",
        "pending": bool(delay),
        "risk": _risk_hint(conn, cap.key),
    }
    # 影響計算（單據筆數等）：能力宣告的 `impact_calc` 已預留；提供者機制 `perm.impact` 等第一個單位真的需要時再登記（P1），目前只顯示白話影響說明與人數。
    return out


def preview_role_cap(conn, role, cap_key, granted):
    from helpers import perm_text as T
    c = _cap_or_err(cap_key)
    if role not in _roles():
        raise PermError("角色不存在或不可調整")
    seeded = cap_key in P.seed_from_legacy(CAP.all_caps()).role_grants.get(role, ())
    cur = conn.execute("SELECT granted FROM perm_role_caps WHERE role=? AND cap=?", (role, cap_key)).fetchone()
    now_has = seeded if cur is None else bool(cur["granted"])
    n = conn.execute("SELECT COUNT(*) FROM users WHERE role=? AND active=1", (role,)).fetchone()[0]
    delay = bool(granted) and not seeded and c.risk == "high" and now_has != bool(granted)
    out = _preview(conn, c, T.sentence_role_cap(role, cap_key, bool(granted)), n if now_has != bool(granted) else 0, delay, {"role": role, "granted": bool(granted)})
    out["changed"] = now_has != bool(granted)
    out["question"] = T.question(cap_key, T.role_label(role))
    out["recommended"] = role in c.recommended
    return out


def preview_user_override(conn, user_id, cap_key, effect):
    from helpers import perm_text as T
    c = _cap_or_err(cap_key)
    u = _target_user(conn, user_id)
    name = conn.execute("SELECT display_name, username FROM users WHERE id=?", (u["id"],)).fetchone()
    label = name["display_name"] or name["username"]
    delay = effect == "allow" and c.risk == "high"
    return _preview(conn, c, T.sentence_user_override(label, cap_key, effect == "allow"), 1, delay, {"user_id": u["id"], "effect": effect})


def preview_delegation(conn, delegator, delegate, keys, valid_to=""):
    from helpers import perm_text as T
    allc = CAP.all_caps()
    caps = [allc[k] for k in keys if k in allc]
    if not caps:
        raise PermError("請指定代理範圍")
    names = {}
    for u in (delegator, delegate):
        r = conn.execute("SELECT display_name, username FROM users WHERE username=? AND active=1", (u,)).fetchone()
        if r is None:
            raise PermError("找不到帳號或已停用：%s" % u, 404)
        names[u] = r["display_name"] or r["username"]
    risky = any(c.risk == "high" for c in caps)
    out = _preview(conn, caps[0], T.sentence_delegation(names[delegator], names[delegate], [c.key for c in caps], valid_to, 0), 1, risky)
    if risky:
        out["sentence"] = out["sentence"].replace("儲存後立即生效", "%d 天確認期間後生效，並需要另一位最高管理者核准" % _confirm_days(conn))
    out["impact"] = "；".join(c.impact for c in caps)
    out["risk"] = "；".join(h for h in (_risk_hint(conn, c.key) for c in caps) if h)
    out["appliesTo"] = "代理期間內，%s可以以自己的帳號做這些事，並會註明是代理%s；%s本人的權限不變" % (names[delegate], names[delegator], names[delegator])
    return out
