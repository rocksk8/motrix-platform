# -*- coding: utf-8 -*-
"""職責角色化 R1（設計：docs/platform/plans/DUTY-ROLES-DESIGN.md；使用者 2026-10-06 裁示 Q1–Q12、N1–N4）。

[單位] helper:duty_roles    [層] L1    [穩定度] 實作（R1；R2＝盤點／離職回收／職務分離／通知，尚未做）
[公開介面] DutyError, FINANCE_KEYS, HIGH_SENSITIVITY_KEYS, REASON_MAX, REASON_MIN, bind_role, create_role, effective_preview, has_duty_data, known_keys, list_changes, list_roles, resolve_raw_modules, set_subtract, unbind_role, unset_subtract, update_role
[契約題] tests/test_duty_roles_r1_2026_10_06.py、tests/test_duty_roles_equivalence_2026_10_06.py

## 權限算法（單一縫＝`helpers.auth.effective_modules`；本檔只提供「角色／扣項怎麼套到原始勾選上」）
  生效（原始勾選層）＝（`users.modules`〔個人加項〕 ∪ 啟用中的綁定角色的權限）− 個人扣項
  之後 `effective_modules` 再套第42班的「財務三鍵由角色決定」。
- **零行為變更的證明（上線當天）**：沒有綁定、沒有扣項的人 ⇒ `resolve_raw_modules` 原樣回傳傳入的清單（同一個物件），
  遷移也不建立任何綁定／扣項 ⇒ 每個人的生效權限逐字相同。
- **superadmin 維持原樣**（使用者 2026-10-06：R1 不改成「全部鍵」）：`effective_modules` 對 superadmin **完全不呼叫本檔**，
  角色／扣項資料不可能降低它；服務層也拒絕對 superadmin 設扣項／綁角色。
- `has_finance_access`／`has_cashier_access`／`user_has_module(財務三鍵)` **不動**（第42班原樣）；R1 不開放對財務三鍵設扣項（扣了不會生效，會造成假安全感）。
- 扣項只影響「以模組鍵判斷」的功能；admin 直通的一般管理判斷（B 階段才收斂）不受影響 ⇒ 畫面寫明「部分生效」。

## 變更原因（Q4 b）
只有高敏感變更必填（≥4 字、≤200 字，伺服器端強制）；是否高敏感由伺服器依差異計算，不信前端旗標。
高敏感清單 `HIGH_SENSITIVITY_KEYS`（N2 a，不含 `reports`）。
## 紀錄（只增不改不刪）
每次變更寫一列 `permission_changes`（DB 觸發器擋 UPDATE／DELETE）；沒有任何更新／刪除端點。
"""
import json
import sqlite3
from datetime import datetime

#: 高敏感權限鍵（DUTY-ROLES-DESIGN §2.4；N2 a：不含 `reports`）。改清單＝改使用者裁示，要先問。
HIGH_SENSITIVITY_KEYS = ("financial_view", "finance", "cashier", "settings", "audit_log", "module_versions", "payslip")
#: 財務三鍵（與 `helpers.auth.FINANCE_MODULE_KEYS` 同；守門題核對相等）。R1 不得被扣。
FINANCE_KEYS = ("cashier", "finance", "financial_view")

REASON_MIN = 4
REASON_MAX = 200


class DutyError(Exception):
    """服務層錯誤：`status` 給路由轉成 HTTPException。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _loads(v, default):
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return out if isinstance(out, type(default)) else default
    except (TypeError, ValueError):
        return default


def _now():
    return datetime.now().isoformat(timespec="seconds")


def known_keys() -> set:
    """目前可授權的模組鍵（內建＋動態來源）。"""
    from helpers import module_registry as mr
    keys = {k for k, _l, _g in mr.MODULES}
    try:
        keys |= {k for k, _l, _g in mr.dynamic_modules()}
    except Exception:                                   # noqa: BLE001
        pass
    return keys


# ── 讀：生效權限（單一縫會呼叫）──────────────────────────────────────────────

def has_duty_data(conn, user_id) -> bool:
    """這個人有綁定或扣項嗎。表不存在（migration 尚未跑）⇒ False。"""
    try:
        return bool(conn.execute(
            "SELECT 1 FROM user_duty_roles WHERE user_id=? UNION ALL SELECT 1 FROM user_perm_subtracts WHERE user_id=? LIMIT 1",
            (user_id, user_id)).fetchone())
    except sqlite3.OperationalError:
        return False


def resolve_raw_modules(conn, user_id, raw_modules):
    """把角色與扣項套到「原始勾選」上；沒有綁定也沒有扣項 ⇒ **原樣回傳傳入的物件**（零行為變更的證明點）。
    回傳 list（保持原順序，再依角色順序附加新鍵）。"""
    if user_id is None:
        return raw_modules
    try:
        roles = conn.execute(
            "SELECT r.permissions FROM user_duty_roles b JOIN duty_roles r ON r.id=b.role_id"
            " WHERE b.user_id=? AND r.active=1 ORDER BY r.id", (user_id,)).fetchall()
        subs = {r[0] for r in conn.execute("SELECT perm_key FROM user_perm_subtracts WHERE user_id=?", (user_id,)).fetchall()}
        bound_any = conn.execute("SELECT 1 FROM user_duty_roles WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
    except sqlite3.OperationalError:
        return raw_modules
    if not roles and not subs and not bound_any:
        return raw_modules
    out = list(raw_modules or [])
    seen = set(out)
    for (perms,) in roles:
        for k in _loads(perms, []):
            if isinstance(k, str) and k not in seen:
                seen.add(k)
                out.append(k)
    return [k for k in out if k not in subs]


def _raw_of(conn, user_id):
    r = conn.execute("SELECT modules FROM users WHERE id=?", (user_id,)).fetchone()
    return _loads(r[0] if r else "[]", [])


def _effective_of(conn, user_id, role):
    """某人目前的生效清單（含財務三鍵規則）——與 `helpers.auth.effective_modules(role, modules, user_id)` 同一條路。"""
    from helpers.auth import effective_modules
    r = conn.execute("SELECT modules FROM users WHERE id=?", (user_id,)).fetchone()
    return effective_modules(role, r[0] if r else "[]", user_id=user_id, conn=conn)


def effective_preview(conn, user) -> dict:
    """給畫面：某使用者的綁定、扣項、生效清單，並標出被扣掉／高敏感的鍵。`user` 需含 id、role、modules。"""
    uid = user["id"]
    roles = [{"id": r[0], "key": r[1], "name": r[2], "active": bool(r[3])} for r in conn.execute(
        "SELECT r.id, r.key, r.name, r.active FROM user_duty_roles b JOIN duty_roles r ON r.id=b.role_id WHERE b.user_id=? ORDER BY r.id", (uid,))]
    subs = [{"key": r[0], "reason": r[1], "setAt": r[2]} for r in conn.execute(
        "SELECT perm_key, reason, set_at FROM user_perm_subtracts WHERE user_id=? ORDER BY perm_key", (uid,))]
    eff = _effective_of(conn, uid, user["role"])
    return {"roles": roles, "subtracts": subs, "effective": eff,
            "highSensitive": [k for k in eff if k in HIGH_SENSITIVITY_KEYS]}


# ── 寫：服務層（每個動作＝一筆 permission_changes）──────────────────────────────

def _clean_reason(reason) -> str:
    r = (reason or "").strip() if isinstance(reason, str) else ""
    if len(r) > REASON_MAX:
        raise DutyError("原因最多 %d 字" % REASON_MAX)
    return r


def _require_reason_if_sensitive(sensitive: bool, reason: str) -> None:
    if sensitive and len(reason) < REASON_MIN:
        raise DutyError("這項變更涉及高敏感權限（%s），請填寫原因（至少 %d 字）" % ("、".join(HIGH_SENSITIVITY_KEYS), REASON_MIN))


def _record(conn, actor, kind, target_type, target_id, label, added, removed, before, after, sensitive, reason, ip):
    conn.execute(
        "INSERT INTO permission_changes (ts, actor_id, actor_username, actor_display, kind, target_type, target_id, target_label,"
        " added, removed, before_json, after_json, high_sensitivity, reason, ip) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (_now(), (actor or {}).get("id"), (actor or {}).get("username") or "", (actor or {}).get("display_name") or "", kind,
         target_type, int(target_id), label or "", json.dumps(sorted(added), ensure_ascii=False), json.dumps(sorted(removed), ensure_ascii=False),
         json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), 1 if sensitive else 0, reason, ip or ""))


def _check_perm_keys(keys):
    if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) and k for k in keys):
        raise DutyError("權限必須是鍵的清單")
    unknown = sorted(set(keys) - known_keys())
    if unknown:
        raise DutyError("不認得的權限鍵：%s" % "、".join(unknown))
    return list(dict.fromkeys(keys))


def _check_grantable(actor, keys):
    """Q6 a：操作者必須自己持有被授予的鍵（superadmin 不受限）。R1 的路由只有 superadmin 能呼叫，這是未來放寬管理者時的護欄。"""
    if (actor or {}).get("role") == "superadmin":
        return
    from helpers.auth import effective_modules
    mine = set(effective_modules(actor.get("role"), actor.get("modules"), user_id=actor.get("id")))
    missing = sorted(set(keys) - mine)
    if missing:
        raise DutyError("您沒有這些權限，不能授予他人：%s" % "、".join(missing), 403)


def _role_row(conn, role_id):
    r = conn.execute("SELECT * FROM duty_roles WHERE id=?", (role_id,)).fetchone()
    if not r:
        raise DutyError("找不到這個職責角色", 404)
    return r


def _user_row(conn, user_id):
    r = conn.execute("SELECT id, username, display_name, role, modules FROM users WHERE id=?", (user_id,)).fetchone()
    if not r:
        raise DutyError("找不到這位使用者", 404)
    return r


def list_roles(conn) -> list:
    out = []
    for r in conn.execute("SELECT * FROM duty_roles ORDER BY id").fetchall():
        n = conn.execute("SELECT COUNT(*) FROM user_duty_roles WHERE role_id=?", (r["id"],)).fetchone()[0]
        perms = _loads(r["permissions"], [])
        out.append({"id": r["id"], "key": r["key"], "name": r["name"], "description": r["description"], "permissions": perms,
                    "isSystem": bool(r["is_system"]), "active": bool(r["active"]), "version": r["version"], "members": n,
                    "highSensitive": [k for k in perms if k in HIGH_SENSITIVITY_KEYS]})
    return out


def create_role(conn, actor, key, name, description, permissions, reason, ip=""):
    key = (key or "").strip()
    name = (name or "").strip()
    if not key or not name or len(key) > 40 or not key.replace("_", "").isalnum():
        raise DutyError("角色代碼（英數與底線）與名稱必填")
    if conn.execute("SELECT 1 FROM duty_roles WHERE key=?", (key,)).fetchone():
        raise DutyError("角色代碼已存在", 409)
    perms = _check_perm_keys(permissions or [])
    _check_grantable(actor, perms)
    reason = _clean_reason(reason)
    sensitive = bool(set(perms) & set(HIGH_SENSITIVITY_KEYS))
    _require_reason_if_sensitive(sensitive, reason)
    now = _now()
    cur = conn.execute("INSERT INTO duty_roles (key, name, description, permissions, is_system, active, version, created_at, updated_at)"
                       " VALUES (?,?,?,?,0,1,1,?,?)", (key, name, (description or "").strip(), json.dumps(perms), now, now))
    _record(conn, actor, "role_def", "role", cur.lastrowid, name, perms, [], {}, {"permissions": perms, "active": True}, sensitive, reason, ip)
    conn.commit()
    return cur.lastrowid


def update_role(conn, actor, role_id, *, name=None, description=None, permissions=None, active=None, reason="", ip=""):
    r = _role_row(conn, role_id)
    old = _loads(r["permissions"], [])
    new = _check_perm_keys(permissions) if permissions is not None else old
    _check_grantable(actor, [k for k in new if k not in old])
    added, removed = set(new) - set(old), set(old) - set(new)
    new_active = r["active"] if active is None else (1 if active else 0)
    reason = _clean_reason(reason)
    touched = added | removed
    # 角色停用／啟用也會同時增減所有成員的權限 ⇒ 以「角色目前權限」判斷是否高敏感
    if new_active != r["active"]:
        touched |= set(new)
    sensitive = bool(touched & set(HIGH_SENSITIVITY_KEYS))
    _require_reason_if_sensitive(sensitive, reason)
    new_name = (name if name is not None else r["name"]).strip()
    if not new_name:
        raise DutyError("名稱不可空白")
    new_desc = (description if description is not None else r["description"]).strip()
    if (new_name, new_desc, new_active) == (r["name"], r["description"], r["active"]) and not (added or removed):
        return r["version"]
    version = r["version"] + (1 if (added or removed or new_active != r["active"]) else 0)
    conn.execute("UPDATE duty_roles SET name=?, description=?, permissions=?, active=?, version=?, updated_at=? WHERE id=?",
                 (new_name, new_desc, json.dumps(new), new_active, version, _now(), role_id))
    members = conn.execute("SELECT COUNT(*) FROM user_duty_roles WHERE role_id=?", (role_id,)).fetchone()[0]
    _record(conn, actor, "role_def", "role", role_id, new_name, added, removed,
            {"permissions": old, "active": bool(r["active"])}, {"permissions": new, "active": bool(new_active), "members": members},
            sensitive, reason, ip)
    conn.commit()
    return version


def _guard_target_user(conn, actor, user_id):
    u = _user_row(conn, user_id)
    if u["role"] == "superadmin":
        raise DutyError("最高管理者的權限不由職責角色或扣項決定（維持全功能）", 400)
    if actor and actor.get("id") == user_id and actor.get("role") != "superadmin":
        raise DutyError("不可變更自己的角色或權限", 403)
    return u


def bind_role(conn, actor, user_id, role_id, reason="", ip=""):
    u = _guard_target_user(conn, actor, user_id)
    r = _role_row(conn, role_id)
    if not r["active"]:
        raise DutyError("這個職責角色已停用", 400)
    if conn.execute("SELECT 1 FROM user_duty_roles WHERE user_id=? AND role_id=?", (user_id, role_id)).fetchone():
        raise DutyError("已綁定這個角色", 409)
    perms = _loads(r["permissions"], [])
    _check_grantable(actor, perms)
    reason = _clean_reason(reason)
    sensitive = bool(set(perms) & set(HIGH_SENSITIVITY_KEYS))
    _require_reason_if_sensitive(sensitive, reason)
    before = set(_effective_of(conn, user_id, u["role"]))
    conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)",
                 (user_id, role_id, (actor or {}).get("id"), _now(), reason))
    after = set(_effective_of(conn, user_id, u["role"]))
    _record(conn, actor, "bind", "user", user_id, u["display_name"] or u["username"], after - before, before - after,
            {"role": r["key"]}, {"role": r["key"], "bound": True}, sensitive, reason, ip)
    conn.commit()


def unbind_role(conn, actor, user_id, role_id, reason="", ip=""):
    u = _guard_target_user(conn, actor, user_id)
    r = _role_row(conn, role_id)
    if not conn.execute("SELECT 1 FROM user_duty_roles WHERE user_id=? AND role_id=?", (user_id, role_id)).fetchone():
        raise DutyError("沒有綁定這個角色", 404)
    perms = _loads(r["permissions"], [])
    reason = _clean_reason(reason)
    sensitive = bool(set(perms) & set(HIGH_SENSITIVITY_KEYS))
    _require_reason_if_sensitive(sensitive, reason)
    before = set(_effective_of(conn, user_id, u["role"]))
    conn.execute("DELETE FROM user_duty_roles WHERE user_id=? AND role_id=?", (user_id, role_id))
    after = set(_effective_of(conn, user_id, u["role"]))
    _record(conn, actor, "unbind", "user", user_id, u["display_name"] or u["username"], after - before, before - after,
            {"role": r["key"], "bound": True}, {"role": r["key"]}, sensitive, reason, ip)
    conn.commit()


def set_subtract(conn, actor, user_id, key, reason="", ip=""):
    u = _guard_target_user(conn, actor, user_id)
    if key not in known_keys():
        raise DutyError("不認得的權限鍵：%s" % key)
    if key in FINANCE_KEYS:
        raise DutyError("財務三鍵（財務金額可視、財務、出納）R1 不開放個人扣項：改由角色決定（要收回請變更基礎類別／解除財務角色）", 400)
    if key in _raw_of(conn, user_id):
        raise DutyError("這個權限目前是個人勾選（加項），請先在使用者管理取消勾選再設扣項（同一個鍵只能有一種個人狀態）", 400)
    if conn.execute("SELECT 1 FROM user_perm_subtracts WHERE user_id=? AND perm_key=?", (user_id, key)).fetchone():
        raise DutyError("已經是扣項", 409)
    reason = _clean_reason(reason)
    sensitive = key in HIGH_SENSITIVITY_KEYS
    _require_reason_if_sensitive(sensitive, reason)
    before = set(_effective_of(conn, user_id, u["role"]))
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
                 (user_id, key, (actor or {}).get("id"), _now(), reason))
    after = set(_effective_of(conn, user_id, u["role"]))
    _record(conn, actor, "subtract", "user", user_id, u["display_name"] or u["username"], after - before, before - after,
            {}, {"subtract": key}, sensitive, reason, ip)
    conn.commit()


def unset_subtract(conn, actor, user_id, key, reason="", ip=""):
    u = _guard_target_user(conn, actor, user_id)
    if not conn.execute("SELECT 1 FROM user_perm_subtracts WHERE user_id=? AND perm_key=?", (user_id, key)).fetchone():
        raise DutyError("沒有這個扣項", 404)
    reason = _clean_reason(reason)
    sensitive = key in HIGH_SENSITIVITY_KEYS
    _require_reason_if_sensitive(sensitive, reason)
    _check_grantable(actor, [key])                       # 解除扣項＝把權限還給對方
    before = set(_effective_of(conn, user_id, u["role"]))
    conn.execute("DELETE FROM user_perm_subtracts WHERE user_id=? AND perm_key=?", (user_id, key))
    after = set(_effective_of(conn, user_id, u["role"]))
    _record(conn, actor, "unsubtract", "user", user_id, u["display_name"] or u["username"], after - before, before - after,
            {"subtract": key}, {}, sensitive, reason, ip)
    conn.commit()


def list_changes(conn, target_type="", target_id=None, limit=200) -> list:
    sql, args = "SELECT * FROM permission_changes", []
    where = []
    if target_type:
        where.append("target_type=?")
        args.append(target_type)
    if target_id is not None:
        where.append("target_id=?")
        args.append(int(target_id))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 200), 1000)))
    return [{"id": r["id"], "ts": r["ts"], "actor": r["actor_display"] or r["actor_username"], "kind": r["kind"],
             "targetType": r["target_type"], "targetId": r["target_id"], "target": r["target_label"],
             "added": _loads(r["added"], []), "removed": _loads(r["removed"], []), "highSensitivity": bool(r["high_sensitivity"]),
             "reason": r["reason"], "ip": r["ip"]} for r in conn.execute(sql, args).fetchall()]
