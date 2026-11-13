# -*- coding: utf-8 -*-
"""使用者權限頁的批次授予／取消與範本套用（設定矩陣 S3a；SPEC §4.9、§12）。

[單位] helper:user_perm_batch    [層] L1    [穩定度] 實作（S3a）
[公開介面] BATCH_GRANT_REFUSED, MAX_USERS, UNDO_DEFAULT_REASON, list_catalog, parse_request, preview, apply, undo
[契約題] tests/test_user_perm_batch_2026_11_14.py

## 規則（SPEC §12；守門題逐條驗）
1. **共用檢查點**：原因規則一律走 `helpers.duty_roles.gate_reason`（與 `PUT／POST /api/users`、職責角色各動作同一支）；寫入走
   `duty_roles.record_user_modules_change`（`permission_changes`＋同交易 `audit_log`）。本檔不自帶第二份原因規則。
2. **授予／取消不對稱**：高敏感鍵（`HIGH_SENSITIVITY_KEYS`）與批次拒絕清單（`BATCH_GRANT_REFUSED`，使用者裁示 C4）——
   **授予一律略過**（要逐人填原因）；**取消可以批次**，但要填原因（≥4 個不同字）並寫變更紀錄。
3. **財務三鍵**（`FINANCE_KEYS`）由角色決定：批次永遠不動（授予、取消都略過並說明）。
4. **最高管理者不納入**：維持全功能，批次與範本都略過。
5. **範本**：伺服器在預覽時就把範本展開成「每人明確的授予／取消清單」；套用時**重算同一份**，與預覽的 `planHash` 不同就 409（不照過期預覽寫入）。
   範本只動「個人勾選」：個人扣項與職責角色綁定不動（**範本模式絕不新增個人扣項**；角色本來就給的鍵留著，確認視窗的
   「實際生效」差異裡不會出現「少了」該鍵）；**復原也絕不新增個人扣項**（只還原這一批寫過的格）；被個人扣項扣掉的鍵不授予（回報略過）。範本套用**必須帶 planHash**（沒帶 ⇒ 400）：不盲目重新展開。
6. **取消職責角色給的權限**：該權限不在個人勾選裡 ⇒ 改設「個人扣項」（與 `duty_roles.set_subtract` 同表同規則），不是假裝取消了。
7. **整批同一個寫入交易**（`core.txn.begin_write`）：任何例外 ⇒ 全部不寫；被略過的項目不是錯誤，照實回報。
"""
import hashlib
import json
import sqlite3
from datetime import datetime

from helpers import duty_roles as dr

#: 使用者裁示 C4（SPEC §4.9）：禁止批次授予、批次取消可以。清單由 API 回傳（`list_catalog`），前端不寫死。
BATCH_GRANT_REFUSED = ("project_approve_eng", "project_approve_biz", "quotation", "expense_forms", "file_center", "contractor_list")

#: 一次最多處理幾個人（防誤送整份名冊；公司規模遠小於此）
MAX_USERS = 200


def list_catalog() -> dict:
    """給畫面：高敏感清單、批次拒絕清單、財務三鍵（前端不寫死任何一份）。"""
    return {"highSensitiveKeys": list(dr.HIGH_SENSITIVITY_KEYS), "batchGrantRefused": list(BATCH_GRANT_REFUSED),
            "financeKeys": list(dr.FINANCE_KEYS)}


def _gated_keys() -> set:
    return set(dr.HIGH_SENSITIVITY_KEYS) | set(BATCH_GRANT_REFUSED)


def _json_list(v) -> list:
    try:
        out = json.loads(v) if isinstance(v, str) else v
        return [k for k in out if isinstance(k, str)] if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def _int_list(v, label) -> list:
    if v in (None, ""):
        return []
    if not isinstance(v, (list, tuple)):
        raise dr.DutyError("%s必須是清單" % label)
    try:
        return sorted({int(i) for i in v if not isinstance(i, bool)})
    except (TypeError, ValueError):
        raise dr.DutyError("%s必須是整數清單" % label)


def _check_revoke_keys(keys):
    """取消可以點名任何「目前持有」的鍵（含已下架的舊鍵，與 PUT 一樣只擋新增未知鍵）；形狀仍要檢查，持有與否在計畫階段判斷。"""
    if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) and k for k in keys):
        raise dr.DutyError("權限必須是鍵的清單")
    return list(dict.fromkeys(keys))


def parse_request(body) -> dict:
    """驗證請求。{userIds, grant[], revoke[], bindRoleIds[], unbindRoleIds[], template, reason, planHash} ⇒ 正規化後的 dict。"""
    if not isinstance(body, dict):
        raise dr.DutyError("請求內容必須是物件")
    ids = _int_list(body.get("userIds"), "userIds")
    if not ids:
        raise dr.DutyError("請至少選一位使用者")
    if len(ids) > MAX_USERS:
        raise dr.DutyError("一次最多 %d 位" % MAX_USERS)
    grant = dr._check_perm_keys(body.get("grant") or [])
    revoke = _check_revoke_keys(body.get("revoke") or [])
    both = sorted(set(grant) & set(revoke))
    if both:
        raise dr.DutyError("同一個權限不能同時授予與取消：%s" % "、".join(both))
    bind_ids, unbind_ids = _int_list(body.get("bindRoleIds"), "bindRoleIds"), _int_list(body.get("unbindRoleIds"), "unbindRoleIds")
    if set(bind_ids) & set(unbind_ids):
        raise dr.DutyError("同一個職責角色不能同時綁定與解除")
    template = body.get("template") or ""
    if template:
        from helpers import module_registry as mr
        if not isinstance(template, str) or template not in mr.ROLE_TEMPLATES:
            raise dr.DutyError("不認得的範本：%s" % template)
        if grant or revoke or bind_ids or unbind_ids:
            raise dr.DutyError("套用範本時不能同時送個別的授予／取消／綁定")
    if not (grant or revoke or bind_ids or unbind_ids or template):
        raise dr.DutyError("沒有要變更的內容")
    plan_hash = body.get("planHash") or ""
    if not isinstance(plan_hash, str):
        raise dr.DutyError("planHash 必須是字串")
    reason = body.get("reason")
    return {"userIds": ids, "grant": grant, "revoke": revoke, "bindRoleIds": bind_ids, "unbindRoleIds": unbind_ids,
            "template": template, "reason": reason if isinstance(reason, str) else "", "planHash": plan_hash}


# ── 讀：目前狀態 ─────────────────────────────────────────────────────────────

def _load_state(conn, ids) -> dict:
    marks = ",".join("?" * len(ids))
    users = {r["id"]: r for r in conn.execute(
        "SELECT id, username, display_name, role, modules FROM users WHERE id IN (%s)" % marks, ids).fetchall()}
    roles, bound, subs = {}, {}, {}
    try:
        for r in conn.execute("SELECT id, key, name, active, permissions FROM duty_roles").fetchall():
            roles[r["id"]] = {"id": r["id"], "key": r["key"], "name": r["name"], "active": bool(r["active"]),
                              "permissions": _json_list(r["permissions"])}
        for r in conn.execute("SELECT user_id, role_id FROM user_duty_roles WHERE user_id IN (%s)" % marks, ids).fetchall():
            bound.setdefault(r["user_id"], set()).add(r["role_id"])
        for r in conn.execute("SELECT user_id, perm_key FROM user_perm_subtracts WHERE user_id IN (%s)" % marks, ids).fetchall():
            subs.setdefault(r["user_id"], set()).add(r["perm_key"])
    except sqlite3.OperationalError:                      # migration 尚未跑：沒有職責角色資料
        pass
    return {"users": users, "roles": roles, "bound": bound, "subs": subs}


def _effective(role, raw, role_ids, roles, subs) -> set:
    """與真實路徑同一條：`apply_duty`（啟用中的綁定角色權限＋個人扣項）再套 `effective_modules` 的財務規則。"""
    from helpers.auth import effective_modules
    lists = [roles[i]["permissions"] for i in sorted(role_ids) if i in roles and roles[i]["active"]]
    return set(effective_modules(role, dr.apply_duty(list(raw), lists, set(subs), bool(role_ids))))


def _refusal_for_grant(key) -> str:
    if key in dr.FINANCE_KEYS:
        return "財務三鍵由角色決定，批次不動"
    if key in dr.HIGH_SENSITIVITY_KEYS:
        return "高敏感權限：授予要逐人填原因，不能批次"
    if key in BATCH_GRANT_REFUSED:
        return "影響較大的權限：授予要逐人確認，不能批次"
    return ""


def _plan_person(uid, req, st, known, template_keys) -> dict:
    u = st["users"].get(uid)
    p = {"userId": uid, "username": "", "name": "", "role": "", "status": "nochange", "note": "", "adds": [], "removes": [],
         "bind": [], "unbind": [], "subtractAdds": [], "subtractRemoves": [], "skipped": [], "effectiveAdded": [], "effectiveRemoved": [], "gated": []}
    if u is None:
        p.update(status="skipped", note="找不到這位使用者")
        return p
    p.update(username=u["username"], name=u["display_name"] or u["username"], role=u["role"])
    if u["role"] == "superadmin":
        p.update(status="skipped", note="最高管理者不納入批次（維持全功能）")
        return p
    raw = _json_list(u["modules"])
    rawset = set(raw)
    roles, bound, subs = st["roles"], set(st["bound"].get(uid, ())), set(st["subs"].get(uid, ()))
    role_keys, held_role_keys = set(), set()              # role_keys＝套用後仍綁著的啟用角色所給的鍵（同一請求解除的角色不算）
    for rid in bound:
        if rid in roles and roles[rid]["active"]:
            held_role_keys |= set(roles[rid]["permissions"])
            if rid not in req["unbindRoleIds"]:
                role_keys |= set(roles[rid]["permissions"])
    if template_keys is not None:
        tset = set(template_keys)
        want_grant = [k for k in template_keys if k not in rawset]
        want_revoke = [k for k in raw if k in known and k not in tset and k not in dr.FINANCE_KEYS]
    else:
        want_grant, want_revoke = list(req["grant"]), list(req["revoke"])

    def skip(kind, key, why):
        p["skipped"].append({"kind": kind, "key": key, "reason": why})

    for k in req.get("unsubtract") or ():                 # 只給「復原」用：還回個人扣項＝把權限還給對方，與授予同一條不對稱規則
        if k not in subs:
            continue
        why = _refusal_for_grant(k)
        if why:
            skip("grant", k, why)
        else:
            p["subtractRemoves"].append(k)
    for k in want_grant:
        if k in rawset:
            continue
        why = _refusal_for_grant(k)
        if why:
            skip("grant", k, why)
        elif k in subs and k not in p["subtractRemoves"]:
            skip("grant", k, "目前被個人扣項扣掉，請先到「職責角色」頁解除扣項")
        else:
            p["adds"].append(k)
    new_subs = set()
    for k in want_revoke:
        if k in dr.FINANCE_KEYS:
            skip("revoke", k, "財務三鍵由角色決定，批次不動")
            continue
        in_raw = k in rawset
        from_role = template_keys is None and k in role_keys and k not in subs and not req.get("undoing")   # 復原只還原這一批寫過的東西，不另外造個人扣項（否則角色給的權限會被悄悄扣掉）
        if in_raw:
            p["removes"].append(k)
        elif k not in held_role_keys and template_keys is None:
            skip("revoke", k, "對方目前沒有這個權限")
        if from_role:
            new_subs.add(k)                               # 角色給的權限：改設個人扣項才算真的取消（範本模式不做）
    p["subtractAdds"] = sorted(new_subs)
    for rid in req["bindRoleIds"]:
        r = roles.get(rid)
        if r is None:
            skip("bind", rid, "找不到這個職責角色")
        elif not r["active"]:
            skip("bind", rid, "這個職責角色已停用")
        elif rid in bound:
            continue
        elif set(r["permissions"]) & _gated_keys():
            skip("bind", rid, "這個角色含高敏感或影響較大的權限：綁定要逐人填原因，不能批次")
        else:
            p["bind"].append(rid)
    for rid in req["unbindRoleIds"]:
        if rid in bound and rid in roles:
            p["unbind"].append(rid)
    raw_after = [k for k in raw if k not in set(p["removes"])] + [k for k in p["adds"] if k not in rawset]
    bound_after = (bound | set(p["bind"])) - set(p["unbind"])
    subs_after = (subs | set(p["subtractAdds"])) - set(p["subtractRemoves"])
    before = _effective(u["role"], raw, bound, roles, subs)
    after = _effective(u["role"], raw_after, bound_after, roles, subs_after)
    p["effectiveAdded"], p["effectiveRemoved"] = sorted(after - before), sorted(before - after)
    touched = (before ^ after) | set(p["adds"]) | set(p["removes"])
    p["gated"] = sorted(touched & _gated_keys())
    changed = bool(p["adds"] or p["removes"] or p["bind"] or p["unbind"] or p["subtractAdds"] or p["subtractRemoves"])
    p["status"] = "change" if changed else "nochange"
    p["_rawAfter"], p["_before"], p["_after"] = raw_after, sorted(before), sorted(after)
    p["_rawChanged"] = bool(p["adds"] or p["removes"])
    return p


def _template_keys(template, known):
    if not template:
        return None
    from helpers import module_registry as mr
    return [k for k in mr.ROLE_TEMPLATES[template] if k in known and k not in dr.FINANCE_KEYS]


def _plan(conn, req, per_person=None) -> dict:
    """`per_person`＝{userId: 該人專屬的請求}（只給「復原」用：每人要還原的內容不同）；沒給 ⇒ 全員同一份 `req`。"""
    st = _load_state(conn, req["userIds"])
    known = dr.known_keys()
    tkeys = _template_keys(req["template"], known)
    template_skipped = []
    if tkeys is not None:
        from helpers import module_registry as mr
        template_skipped = [k for k in mr.ROLE_TEMPLATES[req["template"]] if k in dr.FINANCE_KEYS]
    people = [_plan_person(uid, (per_person or {}).get(uid, req), st, known, tkeys) for uid in req["userIds"]]
    gated = sorted({k for p in people for k in p["gated"]})
    digest = hashlib.sha256(json.dumps(
        [[p["userId"], p["adds"], p["removes"], p["bind"], p["unbind"], p["subtractAdds"], p["subtractRemoves"]] for p in sorted(people, key=lambda x: x["userId"])],
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    return {"people": people, "gatedKeys": gated, "needsReason": bool(gated), "planHash": digest, "templateFinanceKeysLeftAlone": template_skipped}


def _public(plan) -> dict:
    people = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plan["people"]]
    return {"people": people, "gatedKeys": plan["gatedKeys"], "needsReason": plan["needsReason"], "planHash": plan["planHash"],
            "templateFinanceKeysLeftAlone": plan["templateFinanceKeysLeftAlone"],
            "summary": {"requested": len(people), "changed": sum(1 for p in people if p["status"] == "change"),
                        "unchanged": sum(1 for p in people if p["status"] == "nochange"),
                        "skippedPeople": sum(1 for p in people if p["status"] == "skipped"),
                        "skippedItems": sum(len(p["skipped"]) for p in people)},
            "lists": list_catalog()}


def preview(conn, actor, body) -> dict:
    """唯讀：算出每個人實際會變什麼、略過什麼與原因、需不需要原因。不寫任何東西。"""
    return _public(_plan(conn, parse_request(body)))


def _write_people(conn, actor, plan, reason, ip) -> list:
    """把計畫逐人寫進去（呼叫端已在寫入交易內、已過原因檢查點）。⇒ 實際寫入的 userId 清單。"""
    now = datetime.now().isoformat(timespec="seconds")
    applied = []
    for p in plan["people"]:
        if p["status"] != "change":
            continue
        uid = p["userId"]
        if p["_rawChanged"]:
            conn.execute("UPDATE users SET modules=? WHERE id=?", (json.dumps(p["_rawAfter"], ensure_ascii=False), uid))
        for rid in p["bind"]:
            conn.execute("INSERT INTO user_duty_roles (user_id, role_id, granted_by, granted_at, reason) VALUES (?,?,?,?,?)",
                         (uid, rid, (actor or {}).get("id"), now, reason))
        for rid in p["unbind"]:
            conn.execute("DELETE FROM user_duty_roles WHERE user_id=? AND role_id=?", (uid, rid))
        for k in p["subtractAdds"]:
            conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
                         (uid, k, (actor or {}).get("id"), now, reason))
        for k in p["subtractRemoves"]:
            conn.execute("DELETE FROM user_perm_subtracts WHERE user_id=? AND perm_key=?", (uid, k))
        dr.record_user_modules_change(conn, actor, uid, p["username"], p["_before"], p["_after"], reason, ip, sensitive=bool(p["gated"]))
        applied.append(uid)
    return applied


def _notify(actor, plan, applied, reason, undo=False) -> None:
    """commit **之後**通知（共用元件 `settings_notify`，SPEC §13-7／§12.10）：一批＝**一則**合併通知（`batch()`）；
    動到高敏感／批次拒絕鍵的人 ⇒ 該項 `risk="security"`＋`sensitive`（非最高管理者看不到值與原因；另發 LINE 給最高管理者）。
    只放「誰、幾項」不放權限鍵名清單。永不丟例外、不影響已 commit 的寫入。"""
    try:
        from helpers import settings_notify as sn
        done = set(applied or ())
        who = (actor or {}).get("username") or ""
        with sn.batch(verb="復原" if undo else "", header="復原一批權限調整" if undo else "批次調整權限"):
            for p in plan["people"]:
                if p["userId"] not in done:
                    continue
                bits = []
                if p["effectiveAdded"] or p["effectiveRemoved"]:
                    bits.append("實際生效多%d項、少%d項" % (len(p["effectiveAdded"]), len(p["effectiveRemoved"])))
                if p["bind"] or p["unbind"]:
                    bits.append("角色綁定+%d／-%d" % (len(p["bind"]), len(p["unbind"])))
                gated = bool(p["gated"])
                sn.emit([sn.make_item("permission", "%s的權限" % (p["name"] or p["username"]), "調整前", "，".join(bits) or "已調整", "updated",
                                      actor=who, reason=reason, risk="security" if gated else "none", sensitive=gated, link="users.html")])
    except Exception:                                    # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("user_perm_batch._notify 失敗（不影響已 commit 的寫入）", exc_info=True)


def apply(conn, actor, body, ip="") -> dict:
    """套用：同一個寫入交易重算計畫（與預覽同一支函式）、過共用檢查點、逐人寫入並記 `permission_changes`＋`audit_log`。
    `planHash` 有帶且與重算結果不同 ⇒ 409。任何例外 ⇒ rollback（全部不寫）。回應的 `people[*]` 就是「復原這一批」要送回的內容。"""
    from core.txn import begin_write
    req = parse_request(body)
    if req["template"] and not req["planHash"]:
        raise dr.DutyError("套用範本要帶預覽的 planHash（請先預覽再套用）")
    begin_write(conn)
    try:
        plan = _plan(conn, req)
        if req["planHash"] and req["planHash"] != plan["planHash"]:
            raise dr.DutyError("名單或權限在預覽之後有變動，請重新預覽再套用", 409)
        _sens, reason = dr.gate_reason(plan["gatedKeys"], req["reason"], extra_keys=BATCH_GRANT_REFUSED)
        applied = _write_people(conn, actor, plan, reason, ip)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _notify(actor, plan, applied, reason)
    out = _public(plan)
    out["ok"] = True
    out["applied"] = applied
    return out


# ── 復原這一批（SPEC §5-3：逐人 compare-and-set，不覆蓋別人的修改）────────────────────

#: 復原時沒填原因的預設文字（只在沒動到高敏感／批次拒絕鍵時才允許留空；寫進變更紀錄用）
UNDO_DEFAULT_REASON = "復原批次"


def _undo_request(change, st, uid):
    """某人的「復原內容」＝套用時那一筆的反向；⇒ (請求 or None, 衝突說明 or "")。
    CAS：套用時這個人**這一批自己改到的格**，目前必須仍是套用後的樣子（加的仍在、拿掉的仍沒有、綁定／扣項同理）；否則整個人拒絕復原。"""
    u = st["users"].get(uid)
    if u is None:
        return None, "找不到這位使用者"
    if u["role"] == "superadmin":
        return None, "最高管理者不納入批次"
    raw = set(_json_list(u["modules"]))
    bound, subs = set(st["bound"].get(uid, ())), set(st["subs"].get(uid, ()))
    adds, removes = [k for k in change.get("adds") or [] if isinstance(k, str)], [k for k in change.get("removes") or [] if isinstance(k, str)]
    bind, unbind = _int_list(change.get("bind"), "bind"), _int_list(change.get("unbind"), "unbind")
    sub_adds, sub_removes = [k for k in change.get("subtractAdds") or [] if isinstance(k, str)], [k for k in change.get("subtractRemoves") or [] if isinstance(k, str)]
    drift = []
    drift += ["個人勾選「%s」已被改過" % k for k in adds if k not in raw] + ["個人勾選「%s」已被改過" % k for k in removes if k in raw]
    drift += ["職責角色綁定 #%s 已被改過" % r for r in bind if r not in bound] + ["職責角色綁定 #%s 已被改過" % r for r in unbind if r in bound]
    drift += ["個人扣項「%s」已被改過" % k for k in sub_adds if k not in subs] + ["個人扣項「%s」已被改過" % k for k in sub_removes if k in subs]
    if drift:
        return None, "；".join(drift)
    return {"userIds": [uid], "grant": removes, "revoke": adds, "bindRoleIds": unbind, "unbindRoleIds": bind, "template": "",
            "unsubtract": sub_adds, "reason": "", "undoing": True}, ""


def undo(conn, actor, body, ip="") -> dict:
    """復原一批：`body.changes`＝套用回應 `people[*]` 中有變更的那幾筆（只讀它們的 userId／adds／removes／bind／unbind／subtractAdds／subtractRemoves）。
    逐人 CAS，有人被別人改過 ⇒ 只拒絕那個人並說明（`conflicts`），其餘照復原；反向動作走同一支規劃與同一個檢查點
    （還回高敏感／批次拒絕鍵＝授予 ⇒ 略過，要逐人處理；取消它們要原因）。整批同一個交易。"""
    from core.txn import begin_write
    changes = body.get("changes") if isinstance(body, dict) else None
    if not isinstance(changes, list) or not changes:
        raise dr.DutyError("沒有可復原的內容")
    if len(changes) > MAX_USERS:
        raise dr.DutyError("一次最多 %d 位" % MAX_USERS)
    reason_in = body.get("reason") if isinstance(body.get("reason"), str) else ""
    by_user = {}
    for c in changes:
        if not isinstance(c, dict):
            raise dr.DutyError("changes 的每一筆必須是物件")
        try:
            by_user[int(c.get("userId"))] = c
        except (TypeError, ValueError):
            raise dr.DutyError("userId 必須是整數")
    begin_write(conn)
    try:
        ids = sorted(by_user)
        st = _load_state(conn, ids)
        per, conflicts = {}, []
        for uid in ids:
            req, why = _undo_request(by_user[uid], st, uid)
            if req is None:
                name = st["users"][uid]["display_name"] or st["users"][uid]["username"] if uid in st["users"] else str(uid)
                conflicts.append({"userId": uid, "name": name, "reason": why})
            else:
                per[uid] = req
        if not per:
            conn.rollback()
            return {"ok": True, "applied": [], "conflicts": conflicts, "people": [], "summary": {"restored": 0, "conflicts": len(conflicts)}}
        req_all = {"userIds": sorted(per), "grant": [], "revoke": [], "bindRoleIds": [], "unbindRoleIds": [], "template": "", "reason": "", "planHash": ""}
        plan = _plan(conn, req_all, per)
        _sens, reason = dr.gate_reason(plan["gatedKeys"], reason_in, extra_keys=BATCH_GRANT_REFUSED)
        reason = reason or UNDO_DEFAULT_REASON
        applied = _write_people(conn, actor, plan, reason, ip)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _notify(actor, plan, applied, reason, undo=True)
    out = _public(plan)
    out.update({"ok": True, "applied": applied, "conflicts": conflicts})
    out["summary"].update({"restored": len(applied), "conflicts": len(conflicts)})
    return out
