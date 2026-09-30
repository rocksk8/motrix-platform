# -*- coding: utf-8 -*-
"""自訂模組「定義」的送審流程（建構器第三輪 S4，2026-09-30；使用者：定義送審→退回→修改重送，每次 v1→v2…，退回要填原因）。

[單位] plat:custom-def-review    [層] L1    [穩定度] 契約（只增）
[公開介面] DOC_TYPE, QUEUE_TYPE, ReviewError, SETTING_KEY, decide, detail, open_view, queue_items, restore_to_draft, review_enabled, submit
[不變式]
  - **預設關閉**（系統設定 `custom_module_def_review`＝false）：關閉時「發布」與過去完全一樣（直接發布）。開啟後：
    送審＝把草稿凍結成不可變快照（`submitted`，取新版號）；簽核鏈＝文件類型 `custom_module_def` 的流程設定（預設走統一流程）；
    申請人是最高管理者且沒有簽核層（或部門主管解析不出來）⇒ 直接發布；其他情形 ⇒ 由簽核層／最高管理者核可
  - 核可＝該快照 `published`（成為現行版本）；退回（原因必填）＝該快照 `rejected`（保留、不可變、版號不回收）；草稿還在，改完再送 ⇒ 新版號
  - 申請人不能核可／退回自己送的；已發布版本不可變；已建單據綁的 `def_version` 不受影響
  - 簽核佇列：`approval.queue_items`（名稱 `custom_module_def`、type `custom_module_def`）＋`approval.detail`；卡片點開到建構器的審核畫面
[契約題] tests/test_builder3_def_review_2026_09_30.py
"""
import json
from datetime import datetime

from core import definitions as D

DOC_TYPE = "custom_module_def"
QUEUE_TYPE = "custom_module_def"
SETTING_KEY = "custom_module_def_review"


class ReviewError(ValueError):
    def __init__(self, message, status=400, problems=None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


def review_enabled() -> bool:
    from helpers.settings import _get_setting
    return bool(_get_setting(SETTING_KEY, False))


def _tiers_for(conn, username):
    """申請人的簽核層（文件類型 custom_module_def 的流程設定）；設定沒有層、或部門主管解析不出來 ⇒ []。"""
    from helpers.settings import _get_setting
    from helpers.tiered_approval import UnresolvedManagerError, approval_flow_setting_key, setting_to_active_tiers
    scope = dict(_get_setting("approval_flow_scope", {}) or {})
    scope.setdefault(DOC_TYPE, True)                   # 預設走統一流程（不動共用的 DEFAULT_UNIFIED_DOC_TYPES）；scope 明設 false ⇒ 用自己那把 key
    flow = _get_setting(approval_flow_setting_key(DOC_TYPE, scope), {"tiers": []}) or {}
    try:
        return setting_to_active_tiers(flow, conn, username)
    except UnresolvedManagerError:
        return []


def _display(conn, username):
    r = conn.execute("SELECT display_name FROM users WHERE username=?", (username,)).fetchone()
    return (r["display_name"] if r and r["display_name"] else username)


def _dec(row):
    try:
        d = json.loads(row.get("decision_json") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def submit(conn, module_key, user, note=""):
    """送審（或流程關閉／無簽核層的最高管理者 ⇒ 直接發布）。回 `{published, pending, version, definition}`。"""
    if user.get("role") != "superadmin":
        raise ReviewError("只有最高管理者可以編輯自訂模組定義", 403)
    try:
        if not review_enabled():
            d = D.publish(conn, "custom_module", module_key, "company", note, user["username"])
            return {"published": True, "pending": False, "version": d["version"], "definition": d}
        tiers = _tiers_for(conn, user["username"])
        if not tiers:
            # 沒有簽核層：最高管理者自己送 ⇒ 直接發布（＝關閉時的行為）；不需要另外的核可人
            d = D.publish(conn, "custom_module", module_key, "company", note, user["username"])
            return {"published": True, "pending": False, "version": d["version"], "definition": d}
        appr = {"requestedBy": user["username"], "requestedByDisplay": _display(conn, user["username"]),
                "requestedAt": datetime.now().isoformat(timespec="seconds"), "tiers": tiers, "currentTier": 0}
        d = D.submit_draft(conn, "custom_module", module_key, "company", note, user["username"], {"approval": appr})
    except D.DefinitionError as e:
        raise ReviewError(str(e), 422 if e.problems else 400, e.problems)
    _notify_first_tier(conn, module_key, d["version"], tiers, user)
    return {"published": False, "pending": True, "version": d["version"], "definition": d}


def _notify_first_tier(conn, module_key, version, tiers, user):
    try:
        from helpers.audit import _notify
        for a in (tiers[0].get("approvers") or []) if tiers else []:
            _notify(a["username"], "custom_module_def", "%s:%d" % (module_key, version), module_key,
                    "自訂模組「%s」的定義（第 %d 版）待您審核" % (module_key, version))
    except Exception:                                                           # noqa: BLE001 — 通知失敗不擋送審
        pass


def _can_decide(row, user):
    """⇒ (ok, status, msg)。有簽核層：當層排序最前的未簽人（或其有效代理人）；沒有簽核層：只有最高管理者。申請人不能審自己送的。"""
    from helpers import tiered_approval as ta
    dec = _dec(row)
    appr = dec.get("approval") or {}
    if (appr.get("requestedBy") or row.get("submitted_by") or "") == user["username"]:
        return False, 403, "不能審核自己送出的定義"
    tiers = ta.active_tiers(appr)
    if tiers:
        return True, 200, ""                                                    # 細節（輪到誰）由 check_approve_permission 判
    return (user.get("role") == "superadmin"), 403, "沒有簽核層：只有最高管理者可以審核"


def decide(conn, module_key, version, user, approve, note=""):
    """核可／退回。退回原因必填。全部簽核層簽完的核可才發布。回 `{status, version, published}`。"""
    from helpers import tiered_approval as ta
    row = D.get(conn, "custom_module", module_key, "company", int(version))
    if row is None or row["status"] != "submitted":
        raise ReviewError("這一版不是送審中", 409)
    ok, code, msg = _can_decide(row, user)
    if not ok:
        raise ReviewError(msg, code)
    note = (note or "").strip()
    dec = _dec(row)
    appr = dec.get("approval") or {}
    tiers, idx = ta.active_tiers(appr), ta.current_tier_idx(appr)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        if not approve:
            if not note:
                raise ReviewError("退回要填原因", 400)
            if tiers:
                ok2, code2, msg2 = ta.check_reject_permission(tiers, idx, user, conn)
                if not ok2:
                    raise ReviewError(msg2, code2)
            out = D.decide_submitted(conn, "custom_module", module_key, "company", version, False, user["username"], note,
                                     {"approval": appr, "reason": note})
            _notify_requester(conn, row, "退回", note)
            return {"status": out["status"], "version": out["version"], "published": False}
        if tiers:
            ok2, code2, msg2 = ta.check_approve_permission(tiers, idx, user["username"], conn)
            if not ok2:
                raise ReviewError(msg2, code2)
            if ta.sign_first_pending(tiers[idx], user, now, conn):
                appr["currentTier"] = idx + 1
            if appr["currentTier"] < len(tiers):
                dec["approval"] = appr
                D.save_decision(conn, "custom_module", module_key, "company", version, dec)
                _notify_first_tier(conn, module_key, int(version), [tiers[appr["currentTier"]]], user)
                return {"status": "submitted", "version": int(version), "published": False}
        out = D.decide_submitted(conn, "custom_module", module_key, "company", version, True, user["username"], note, {"approval": appr})
        _notify_requester(conn, row, "核可並發布", note)
        return {"status": out["status"], "version": out["version"], "published": True}
    except D.DefinitionError as e:
        raise ReviewError(str(e), 422 if e.problems else 400, e.problems)


def _notify_requester(conn, row, what, note):
    try:
        from helpers.audit import _notify
        _notify(row.get("submitted_by") or "", "custom_module_def", "%s:%d" % (row["key"], row["version"]), row["key"],
                "自訂模組「%s」的定義（第 %d 版）已%s%s" % (row["key"], row["version"], what, "：" + note if note else ""))
    except Exception:                                                           # noqa: BLE001
        pass


def _is_reviewer(conn, row, user) -> bool:
    """最高管理者，或這次送審簽核鏈上的人（含目前有效的代理人），或申請人本人。"""
    from helpers.tiered_approval import active_delegators_for
    if user.get("role") == "superadmin" or (row.get("submitted_by") or "") == user["username"]:
        return True
    names = {a.get("username") for t in ((_dec(row).get("approval") or {}).get("tiers") or []) for a in t.get("approvers", [])}
    return bool(user["username"] in names or (names & set(active_delegators_for(conn, user["username"]))))


def open_view(conn, module_key, user) -> dict:
    """建構器審核畫面用：送審中的那一版（簽核進度、與現行版的差異）；沒有 ⇒ `{open: None, history: […]}`。
    最高管理者、簽核鏈上的人（含代理）、申請人可讀；其他人 403。差異＝`core.definitions.diff`（現行版 → 送審版）。"""
    row = D.open_submission(conn, "custom_module", module_key, "company")
    if row is not None and not _is_reviewer(conn, row, user):
        raise ReviewError("沒有審核這份定義的權限", 403)
    if row is None and user.get("role") != "superadmin":
        raise ReviewError("沒有送審中的定義", 404)
    latest = D.get(conn, "custom_module", module_key, "company")
    hist = [{"version": v["version"], "status": v["status"], "submittedBy": v.get("submitted_by") or "", "submittedAt": v.get("submitted_at") or "",
             "note": v.get("note") or "", "reason": (v.get("decision") or {}).get("reason", ""),
             "decidedBy": (v.get("decision") or {}).get("decidedBy", "")} for v in D.versions(conn, "custom_module", module_key, "company")
            if v["status"] in ("submitted", "rejected")]
    if row is None:
        return {"open": None, "history": hist}
    dec = _dec(row)
    ok, _c, why = _can_decide(row, user)
    return {"open": {"version": row["version"], "submittedBy": row.get("submitted_by") or "", "submittedAt": row.get("submitted_at") or "",
                     "note": row.get("note") or "", "approval": dec.get("approval") or {},
                     "canDecide": bool(ok) and _turn_ok(dec, user, conn), "whyNot": "" if ok else why,
                     "changes": D.diff((latest or {}).get("body") or {}, row["body"])},
            "history": hist}


def _turn_ok(dec, user, conn) -> bool:
    """有簽核層時：輪到這個人（當層未簽、或其代理）。沒有簽核層 ⇒ True（最高管理者已由 _can_decide 判）。"""
    from helpers import tiered_approval as ta
    appr = dec.get("approval") or {}
    tiers = ta.active_tiers(appr)
    if not tiers:
        return True
    ok, _c, _m = ta.check_approve_permission(tiers, ta.current_tier_idx(appr), user["username"], conn)
    return bool(ok)


def queue_items(conn) -> list:
    """IP-10 `approval.queue_items`：送審中的模組定義（`type`＝`custom_module_def`；`quoteNo`＝「模組key:版號」）。"""
    from helpers import approval_queue as _aq
    items = []
    for r in conn.execute("SELECT key, version, note, submitted_by, submitted_at, decision_json FROM ui_definitions "
                          "WHERE kind='custom_module' AND scope='company' AND status='submitted' ORDER BY version DESC").fetchall():
        dec = _dec(dict(r))
        raw = _aq.approval_raw_of(json.dumps(dec.get("approval") or {}, ensure_ascii=False), QUEUE_TYPE, "%s:%d" % (r["key"], r["version"]))
        if raw is None:
            continue
        fld = _aq.tier_fields(raw)
        items.append(_aq.base_item(QUEUE_TYPE, "%s:%d" % (r["key"], r["version"]), fld,
                                   projectName="自訂模組定義「%s」第 %d 版" % (r["key"], r["version"]),
                                   quoteDate=(r["submitted_at"] or "")[:10], moduleKey=r["key"], definitionVersion=r["version"],
                                   note=r["note"] or ""))
    return items


def detail(conn, doc_id):
    """IP-93 `approval.detail`：id＝「模組key:版號」；內容＝送審資訊與異動摘要（完整差異在建構器審核畫面）。"""
    key, _, ver = str(doc_id).rpartition(":")
    try:
        row = D.get(conn, "custom_module", key, "company", int(ver))
    except (D.DefinitionError, ValueError):
        return None
    if row is None or row["status"] != "submitted":
        return None
    dec = _dec(row)
    changes = D.diff((D.get(conn, "custom_module", key, "company") or {}).get("body") or {}, row["body"])
    return {"quoteNo": str(doc_id), "title": "自訂模組定義送審",
            "approvalRaw": json.dumps({"tiers": (dec.get("approval") or {}).get("tiers") or [], "requestedBy": row.get("submitted_by") or ""},
                                      ensure_ascii=False),
            "fields": [{"label": "模組", "value": key}, {"label": "版本", "value": "第 %s 版" % ver},
                       {"label": "申請人", "value": row.get("submitted_by") or "—"},
                       {"label": "送審說明", "value": row.get("note") or "—"},
                       {"label": "異動處數", "value": str(len(changes))}],
            "items": [], "files": []}


def restore_to_draft(conn, module_key, version, user):
    """還原舊版：**審核開啟時**＝把舊版內容放回草稿（再走送審），不直接發布；關閉時呼叫端沿用原本的直接還原。
    舊版必須是已發布、且在目前環境驗證得過。回 `{restoredToDraft, fromVersion}`。"""
    if user.get("role") != "superadmin":
        raise ReviewError("只有最高管理者可以編輯自訂模組定義", 403)
    old = D.get(conn, "custom_module", module_key, "company", int(version))
    if old is None or old["status"] != "published":
        raise ReviewError("找不到第 %s 版（已發布）" % version, 404)
    problems = D.validate("custom_module", module_key, old["body"])
    if problems:
        raise ReviewError("第 %s 版在目前的環境驗證不通過，無法還原" % version, 422, problems)
    D.save_draft(conn, "custom_module", module_key, "company", old["body"], user["username"])
    return {"restoredToDraft": True, "fromVersion": int(version)}
