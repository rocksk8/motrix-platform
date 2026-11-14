# -*- coding: utf-8 -*-
"""職責角色「權限矩陣」的批次授予／取消（T86；SPEC 設定矩陣 §12 的角色端；使用者端是 `helpers/user_perm_batch.py`）。

[單位] helper:duty_role_matrix    [層] L1    [穩定度] 實作（T86）
[公開介面] MAX_ROLES, UNDO_DEFAULT_REASON, parse_request, preview, apply, undo
[契約題] tests/test_duty_role_matrix_2026_11_14.py

職責角色頁（`duty-roles.html`）把「30 顆權限 chip」換成「職責 × 權限」一張表：欄＝角色、列＝權限（依群組）、群組總開關、整欄整列一次勾、篩選、
先看預覽→確認→套用→復原這一批。**鍵與值都沒變**：角色的 `permissions` 仍是同一份鍵清單，寫入仍走 `duty_roles.update_role`。

## 規則（守門題逐條驗）
1. **同一個檢查點**：原因規則走 `duty_roles.gate_reason`（高敏感鍵的授予或取消都要原因，≥4 個不同的字）；每個角色的寫入就是 `update_role`
   （`permission_changes`＋同交易 `audit_log`、版本 +1、`_check_grantable`、未知鍵 400）。本檔不自帶第二份規則、不直接寫 `duty_roles`。
2. **先預覽才能套用**：套用一定要帶預覽的 `planHash`（沒帶 ⇒ 400；與重算結果不同 ⇒ 409，不照過期預覽寫入）。`planHash` 含每個角色的版本號。
3. **整批同一個寫入交易**（`core.txn.begin_write`）：任何例外 ⇒ 全部不寫；沒有實質變更的角色（`nochange`）不寫、不留紀錄。
4. **財務三鍵**（`FINANCE_KEYS`）可以放進角色（與 PUT 一致），但持有者不會因此取得財務／出納能力；預覽照實提醒（`financeNote`），不擋。
5. **復原這一批＝逐角色 compare-and-set**：這一批自己動到的格，現在必須仍是套用後的樣子（加的仍在、拿掉的仍沒有）才還原；
   被其他人改過的角色只拒絕那一個並說明（`conflicts`），其餘照復原。還回高敏感鍵＝授予、取消它們＝取消，原因規則照樣適用。
6. **通知**（`settings_notify`）在 commit 之後、一批一則；非最高管理者看不到高敏感項目的值與原因；永不丟例外。
"""
import hashlib
import json

from helpers import duty_roles as dr

#: 一次最多處理幾個角色（防誤送；公司角色數遠小於此）
MAX_ROLES = 100

#: 復原時沒填原因、且沒動到高敏感鍵時，寫進變更紀錄的預設原因
UNDO_DEFAULT_REASON = "復原批次"

_MAX_ID = 2 ** 31 - 1                                   # SQLite INTEGER 的安全範圍（再大會 OverflowError ⇒ 500）
_MEMBER_NAMES = 8                                       # 預覽每個角色最多列幾位成員的名字（其餘只給人數）


def _one_id(v, label) -> int:
    """單一編號：整數（或純數字字串），1..2**31-1；布林、浮點數、超範圍一律 400。"""
    if isinstance(v, bool) or isinstance(v, float) or not isinstance(v, (int, str)):
        raise dr.DutyError("%s必須是整數" % label)
    if isinstance(v, str) and not (v.isascii() and v.isdigit()):
        raise dr.DutyError("%s必須是整數" % label)
    n = int(v)
    if not 1 <= n <= _MAX_ID:
        raise dr.DutyError("%s超出範圍" % label)
    return n


def _key_list(v, label) -> list:
    """權限鍵清單：缺省＝空；有給就必須是「非空字串的清單」，去重保序。"""
    if v is None:
        return []
    if not isinstance(v, (list, tuple)) or not all(isinstance(k, str) and k for k in v):
        raise dr.DutyError("%s必須是權限鍵的清單" % label)
    return list(dict.fromkeys(v))


def _reason_text(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise dr.DutyError("reason 必須是字串")
    return v


def parse_request(body) -> dict:
    """`{changes:[{roleId, grant:[鍵], revoke:[鍵]}], reason?, planHash?}` ⇒ 規格化後的請求；形狀不對一律 400。"""
    if not isinstance(body, dict):
        raise dr.DutyError("請求格式不正確")
    changes = body.get("changes")
    if not isinstance(changes, list) or not changes:
        raise dr.DutyError("沒有要調整的角色")
    if len(changes) > MAX_ROLES:
        raise dr.DutyError("一次最多 %d 個角色" % MAX_ROLES)
    per, seen = [], set()
    for c in changes:
        if not isinstance(c, dict):
            raise dr.DutyError("changes 的每一筆必須是物件")
        rid = _one_id(c.get("roleId"), "roleId")
        if rid in seen:
            raise dr.DutyError("同一個角色在 changes 裡重複出現")
        seen.add(rid)
        grant, revoke = _key_list(c.get("grant"), "grant"), _key_list(c.get("revoke"), "revoke")
        both = sorted(set(grant) & set(revoke))
        if both:
            raise dr.DutyError("同一個權限不能同時授予與取消：%s" % "、".join(both))
        per.append({"roleId": rid, "grant": grant, "revoke": revoke})
    plan_hash = body.get("planHash")
    if plan_hash is not None and not isinstance(plan_hash, str):
        raise dr.DutyError("planHash 必須是字串")
    return {"changes": sorted(per, key=lambda x: x["roleId"]), "reason": _reason_text(body.get("reason")), "planHash": plan_hash or ""}


def _members(conn, role_ids) -> dict:
    """{roleId: [顯示名稱…]}（依使用者編號）；只用來在預覽裡講「會影響哪些人」。"""
    out = {rid: [] for rid in role_ids}
    if not role_ids:
        return out
    marks = ",".join("?" * len(role_ids))
    for r in conn.execute("SELECT d.role_id AS rid, u.display_name AS dn, u.username AS un FROM user_duty_roles d JOIN users u ON u.id=d.user_id"
                          " WHERE d.role_id IN (%s) ORDER BY u.id" % marks, tuple(role_ids)).fetchall():
        out[r["rid"]].append(r["dn"] or r["un"] or "")
    return out


def _plan_role(role, req, known, members) -> dict:
    rid = role["id"] if role else req["roleId"]
    base = {"roleId": rid, "name": role["name"] if role else "", "key": role["key"] if role else "", "active": bool(role["active"]) if role else False,
            "version": role["version"] if role else 0, "adds": [], "removes": [], "after": [], "gated": [], "financeNote": [], "notes": [],
            "members": len(members), "memberNames": members[:_MEMBER_NAMES], "status": "skipped", "note": "", "_new": None}
    if role is None:
        base["note"] = "找不到此職責角色。"
        return base
    old = list(role["permissions"])
    adds = [k for k in req["grant"] if k not in old]
    removes = [k for k in req["revoke"] if k in old]
    new = [k for k in old if k not in removes] + adds
    legacy = sorted(k for k in new if k not in known)
    if legacy:                                          # 與 PUT 相同：新清單裡有已下架的鍵會被擋；先講清楚，不讓整批因為它失敗
        base["note"] = "此角色含已下架的權限鍵（%s），請先取消這些權限鍵，再調整其他項目。" % "、".join(legacy)
        return base
    base.update({"adds": adds, "removes": removes, "after": new, "_new": new})
    base["gated"] = sorted((set(adds) | set(removes)) & set(dr.HIGH_SENSITIVITY_KEYS))
    base["financeNote"] = sorted(set(adds) & set(dr.FINANCE_KEYS))
    if base["financeNote"]:
        base["notes"].append("財務三鍵可以放進角色，但持有者不會因此取得財務／出納能力（仍只由「財務」基礎角色與最高管理者決定）")
    if not role["active"] and (adds or removes):
        base["notes"].append("這個角色目前已停用，調整後不會影響成員，啟用後才生效")
    base["status"] = "change" if (adds or removes) else "nochange"
    return base


def _plan(conn, req) -> dict:
    roles = {r["id"]: r for r in dr.list_roles(conn)}
    known = dr.known_keys()
    mem = _members(conn, [c["roleId"] for c in req["changes"] if c["roleId"] in roles])
    out = [_plan_role(roles.get(c["roleId"]), c, known, mem.get(c["roleId"], [])) for c in req["changes"]]
    unknown = sorted({k for c in req["changes"] for k in c["grant"]} - known)
    if unknown:                                         # 授予不認得的鍵＝整批 400（與 PUT 同一句）；取消可以點名已下架的舊鍵
        raise dr.DutyError("不認得的權限鍵：%s" % "、".join(unknown))
    gated = sorted({k for p in out for k in p["gated"]})
    digest = hashlib.sha256(json.dumps([[p["roleId"], p["version"], p["adds"], p["removes"]] for p in out],
                                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    return {"roles": out, "gatedKeys": gated, "needsReason": bool(gated), "planHash": digest}


def _public(plan) -> dict:
    roles = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plan["roles"]]
    return {"roles": roles, "gatedKeys": plan["gatedKeys"], "needsReason": plan["needsReason"], "planHash": plan["planHash"],
            "summary": {"requested": len(roles), "changed": sum(1 for p in roles if p["status"] == "change"),
                        "unchanged": sum(1 for p in roles if p["status"] == "nochange"),
                        "skipped": sum(1 for p in roles if p["status"] == "skipped"),
                        "cellsAdded": sum(len(p["adds"]) for p in roles), "cellsRemoved": sum(len(p["removes"]) for p in roles),
                        "membersAffected": sum(p["members"] for p in roles if p["status"] == "change" and p["active"])},
            "highSensitiveKeys": list(dr.HIGH_SENSITIVITY_KEYS)}


def preview(conn, actor, body) -> dict:
    """唯讀：每個角色實際會多／少哪些權限、影響幾位成員、略過什麼與原因、要不要原因。不寫任何東西。"""
    return _public(_plan(conn, parse_request(body)))


def _write_roles(conn, actor, plan, reason, ip) -> list:
    """逐角色寫（呼叫端已在寫入交易內、已過原因檢查點）；寫入就是 `update_role`（不 commit）。⇒ 實際寫入的 roleId 清單。"""
    applied = []
    for p in plan["roles"]:
        if p["status"] != "change":
            continue
        p["version"] = dr.update_role(conn, actor, p["roleId"], permissions=p["_new"], reason=reason, ip=ip, commit=False)
        applied.append(p["roleId"])
    return applied


def _notify(actor, plan, applied, reason, undo=False) -> None:
    """commit **之後**通知：一批＝一則合併通知；動到高敏感鍵的角色 ⇒ risk=security＋sensitive。只放「哪個角色、幾項」不放鍵名清單。永不丟例外。"""
    try:
        from helpers import settings_notify as sn
        done = set(applied or ())
        who = (actor or {}).get("username") or ""
        with sn.batch(verb="復原" if undo else "", header="復原一批職責角色權限" if undo else "批次調整職責角色權限"):
            for p in plan["roles"]:
                if p["roleId"] not in done:
                    continue
                gated = bool(p["gated"])
                sn.emit([sn.make_item("permission", "職責角色「%s」的權限" % p["name"], "調整前", "多 %d 項、少 %d 項（影響 %d 位成員）" % (len(p["adds"]), len(p["removes"]), p["members"]),
                                      "updated", actor=who, reason=reason, risk="security" if gated else "none", sensitive=gated, link="duty-roles.html")])
    except Exception:                                    # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("duty_role_matrix._notify 失敗（不影響已 commit 的寫入）", exc_info=True)


def apply(conn, actor, body, ip="") -> dict:
    """套用：同一個寫入交易重算計畫（與預覽同一支）、過共用檢查點、逐角色 `update_role`。**一定要帶預覽的 `planHash`**；不同 ⇒ 409。任何例外 ⇒ rollback。
    回應的 `roles[*]`（`roleId／adds／removes／version`）就是「復原這一批」要送回的內容。"""
    from core.txn import begin_write
    req = parse_request(body)
    if not req["planHash"]:
        raise dr.DutyError("套用時必須帶有預覽的 planHash，請先預覽再套用。")
    begin_write(conn)
    try:
        plan = _plan(conn, req)
        if req["planHash"] != plan["planHash"]:
            raise dr.DutyError("角色或權限在預覽之後已有變動，請重新預覽再套用。", 409)
        _sens, reason = dr.gate_reason(plan["gatedKeys"], req["reason"])
        applied = _write_roles(conn, actor, plan, reason, ip)
    except Exception:
        conn.rollback()
        raise
    conn.commit()          # 頂層 commit：寫鎖在這裡放掉；通知（另開連線寫入）一律在它之後
    _notify(actor, plan, applied, reason)
    out = _public(plan)
    out["ok"] = True
    out["applied"] = applied
    return out


def undo(conn, actor, body, ip="") -> dict:
    """復原一批：`body.changes`＝套用回應 `roles[*]` 中有變更的那幾筆（只讀 roleId／adds／removes）。逐角色 CAS：這一批動到的格現在必須仍是套用後的樣子，
    否則只拒絕那個角色並說明（`conflicts`），其餘照復原。反向動作走同一支規劃與同一個檢查點。整批同一個交易。"""
    from core.txn import begin_write
    changes = body.get("changes") if isinstance(body, dict) else None
    if not isinstance(changes, list) or not changes:
        raise dr.DutyError("沒有可復原的內容")
    if len(changes) > MAX_ROLES:
        raise dr.DutyError("一次最多 %d 個角色" % MAX_ROLES)
    reason_in = _reason_text(body.get("reason"))
    by_role = {}
    for c in changes:
        if not isinstance(c, dict):
            raise dr.DutyError("changes 的每一筆必須是物件")
        by_role[_one_id(c.get("roleId"), "roleId")] = (_key_list(c.get("adds"), "adds"), _key_list(c.get("removes"), "removes"))
    begin_write(conn)
    try:
        roles = {r["id"]: r for r in dr.list_roles(conn)}
        per, conflicts = [], []
        for rid in sorted(by_role):
            adds, removes = by_role[rid]
            role = roles.get(rid)
            if role is None:
                conflicts.append({"roleId": rid, "name": "", "reason": "找不到此職責角色。"})
                continue
            cur = set(role["permissions"])
            drift = ["「%s」已被改過" % k for k in adds if k not in cur] + ["「%s」已被改過" % k for k in removes if k in cur]
            if drift:
                conflicts.append({"roleId": rid, "name": role["name"], "reason": "；".join(drift)})
                continue
            per.append({"roleId": rid, "grant": removes, "revoke": adds})
        if not per:
            conn.rollback()
            return {"ok": True, "applied": [], "conflicts": conflicts, "roles": [], "summary": {"restored": 0, "conflicts": len(conflicts)}}
        plan = _plan(conn, {"changes": per, "reason": "", "planHash": ""})
        _sens, reason = dr.gate_reason(plan["gatedKeys"], reason_in)
        reason = reason or UNDO_DEFAULT_REASON
        applied = _write_roles(conn, actor, plan, reason, ip)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    _notify(actor, plan, applied, reason, undo=True)
    out = _public(plan)
    out.update({"ok": True, "applied": applied, "conflicts": conflicts})
    out["summary"].update({"restored": len(applied), "conflicts": len(conflicts)})
    return out
