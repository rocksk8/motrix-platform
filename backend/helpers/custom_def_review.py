# -*- coding: utf-8 -*-
"""自訂模組「定義」的送審流程（建構器第三輪 S4，2026-09-30；使用者：定義送審→退回→修改重送，每次 v1→v2…，退回要填原因）。

[單位] helper:custom_def_review    [層] L1    [穩定度] 契約（只增）
[公開介面] MODES, QUEUE_TYPE, REVIEWERS_KEY, ReviewError, SETTING_KEY, decide, detail, open_view, queue_items, restore_to_draft,
    review_state, set_review_settings, submit
[不變式]
  - **審核人名單**（系統設定「模組審核人」`custom_module_def_reviewers`，帳號清單）：名單裡有**申請人以外**至少一人 ⇒ 送審**自動啟用**；
    沒有（例如只有一位最高管理者）⇒ 發布維持直接發布，但稽核記「未經第二人審核」。手動覆寫 `custom_module_def_review`：
    `on`（強制送審；名單沒人可審時改用「申請人以外的最高管理者」）、`off`（強制直接發布，稽核記「審核已關閉」）、`auto`（預設，依名單）
  - 送審＝把草稿凍結成不可變快照（`submitted`，取新版號）；核可（審核人任一位、或其代理人、或申請人以外的最高管理者）＝該快照 `published`；
    退回（原因必填）＝該快照 `rejected`（保留、不可變、版號不回收）；草稿還在，改完再送 ⇒ 新版號
  - 申請人不能核可／退回自己送的；已發布版本不可變；已建單據綁的 `def_version` 不受影響
  - 簽核佇列：`approval.queue_items`（名稱 `custom_module_def`、type `custom_module_def`）＋`approval.detail`；卡片點開到審核頁
[契約題] tests/test_builder3_def_review_2026_09_30.py
"""
import json
from datetime import datetime

from core import definitions as D

QUEUE_TYPE = "custom_module_def"
SETTING_KEY = "custom_module_def_review"           # 手動覆寫：true／false／不存在（auto）
REVIEWERS_KEY = "custom_module_def_reviewers"       # 系統設定「模組審核人」：帳號清單
MODES = ("auto", "on", "off")


class ReviewError(ValueError):
    def __init__(self, message, status=400, problems=None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


def _mode() -> str:
    from helpers.settings import _get_setting
    v = _get_setting(SETTING_KEY, None)
    return "on" if v is True else ("off" if v is False else "auto")


def _user_rows(conn, usernames, exclude=""):
    """帳號清單 ⇒ `[{userId, username, displayName}]`（只留存在且啟用的；排除 exclude；保持順序、去重）。"""
    out, seen = [], set()
    for u in usernames or []:
        if not isinstance(u, str) or u in seen or u == exclude:
            continue
        r = conn.execute("SELECT id, username, display_name FROM users WHERE username=? AND active=1", (u,)).fetchone()
        if r is not None:
            seen.add(u)
            out.append({"userId": r["id"], "username": r["username"], "displayName": r["display_name"] or r["username"]})
    return out


def review_state(conn, submitter="") -> dict:
    """`{mode, active, reviewers:[{userId,username,displayName}], reason}`：這位申請人現在送審會怎樣。
    `reviewers`＝實際會被通知／可核可的人（已排除申請人）；`reason`＝沒啟用時的白話原因（畫面與稽核用）。"""
    from helpers.settings import _get_setting
    mode = _mode()
    listed = _user_rows(conn, _get_setting(REVIEWERS_KEY, []) or [], submitter)
    if mode == "off":
        return {"mode": mode, "active": False, "reviewers": listed, "reason": "審核已由最高管理者關閉：發布為直接發布"}
    if mode == "on" and not listed:
        listed = _user_rows(conn, [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE role='superadmin' AND active=1 ORDER BY id").fetchall()], submitter)
    if listed:
        return {"mode": mode, "active": True, "reviewers": listed, "reason": ""}
    return {"mode": mode, "active": False, "reviewers": [],
            "reason": "沒有申請人以外的審核人：發布為直接發布（稽核會記「未經第二人審核」）"}


def _open_submission_keys(conn) -> list:
    return [r["key"] for r in conn.execute(
        "SELECT DISTINCT key FROM ui_definitions WHERE kind='custom_module' AND scope='company' AND status='submitted' ORDER BY key").fetchall()]


def _latest_version(conn, module_key) -> int:
    return int((D.get(conn, "custom_module", module_key, "company") or {}).get("version") or 0)


def set_review_settings(conn, mode=None, reviewers=None) -> dict:
    """設定覆寫模式與審核人名單（只有最高管理者呼叫；呼叫端寫稽核）。帳號必須存在且啟用。回目前狀態。"""
    from helpers.settings import _get_setting, _set_setting
    if mode is not None and mode not in MODES:
        raise ReviewError("mode 要是 %s" % "、".join(MODES))
    rows = []
    if reviewers is not None:
        if not isinstance(reviewers, list) or any(not isinstance(x, str) for x in reviewers):
            raise ReviewError("reviewers 要是帳號清單")
        rows = _user_rows(conn, reviewers)
        missing = [x for x in dict.fromkeys(reviewers) if x not in {r["username"] for r in rows}]
        if missing:
            raise ReviewError("找不到（或已停用）的帳號：%s" % "、".join(missing))
    # 有送審中的定義時不准改審核模式／審核人：送審當下的審核人名單與模式是那一份的依據，中途換掉＝同一份送審被兩套規則審
    # （W3 #3：先送審 → 關審核 → 直接發布 → 舊送審還能核可）。⇒ 先決定（核可／退回）那一份再改。沒有實際變更（同值）不擋。
    changed = (mode is not None and mode != _mode()) or (
        reviewers is not None and [r["username"] for r in rows] != list(_get_setting(REVIEWERS_KEY, []) or []))
    if changed:
        opened = _open_submission_keys(conn)
        if opened:
            raise ReviewError("有送審中的定義（%s），請先審核（核可或退回）再變更審核模式或審核人" % "、".join(opened), 409)
    if mode is not None:
        _set_setting(SETTING_KEY, True if mode == "on" else (False if mode == "off" else None))
    if reviewers is not None:
        _set_setting(REVIEWERS_KEY, [r["username"] for r in rows])
    return review_state(conn)


def _display(conn, username):
    r = conn.execute("SELECT display_name FROM users WHERE username=?", (username,)).fetchone()
    return (r["display_name"] if r and r["display_name"] else username)


def _dec(row):
    try:
        d = json.loads(row.get("decision_json") or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def submit(conn, module_key, user, note="", base_etag=None):
    """送審（審核沒啟用 ⇒ 直接發布）。回 `{published, pending, version, definition, unreviewed?, reason?}`；
    `unreviewed`＝直接發布而沒有第二人審核（呼叫端據此寫稽核「未經第二人審核」）。"""
    if user.get("role") != "superadmin":
        raise ReviewError("只有最高管理者可以編輯自訂模組定義", 403)
    st = review_state(conn, user["username"])
    try:
        if not st["active"]:
            d = D.publish(conn, "custom_module", module_key, "company", note, user["username"], base_etag=base_etag)       # 有送審中的 ⇒ DefinitionConflict（409）
            return {"published": True, "pending": False, "version": d["version"], "definition": d, "unreviewed": True, "reason": st["reason"]}
        appr = {"requestedBy": user["username"], "requestedByDisplay": _display(conn, user["username"]),
                "requestedAt": datetime.now().isoformat(timespec="seconds"),
                "tiers": [{"order": 0, "approvers": [dict(r, status="pending") for r in st["reviewers"]]}], "currentTier": 0}
        # 基準版本＝送審當下的現行版：核可時現行版已經不是它 ⇒ 這份送審過期（409），不能把舊內容蓋回去
        d = D.submit_draft(conn, "custom_module", module_key, "company", note, user["username"],
                           {"approval": appr, "baseVersion": _latest_version(conn, module_key)}, base_etag=base_etag)
    except D.DraftConflict:
        raise                                                    # K-2：讓路由回 409 draft_conflict（含 current），不轉成 ReviewError
    except D.DefinitionError as e:
        raise ReviewError(str(e), 409 if isinstance(e, D.DefinitionConflict) else (422 if e.problems else 400), e.problems)
    _notify(conn, [r["username"] for r in st["reviewers"]], module_key, d["version"],
            "自訂模組「%s」的定義（第 %d 版）待您審核" % (module_key, d["version"]))
    _mail(lambda: _email().notify_custom_def_submitted(module_key, d["version"], user["username"], [r["username"] for r in st["reviewers"]]))
    return {"published": False, "pending": True, "version": d["version"], "definition": d}


def _mail(send):
    """信件：與站內通知同一原則——寄不出去不可以讓送審／決定失敗（email_notify 內部已是非同步寄送並記 WARNING）。
    `send`＝呼叫 email_notify 某支函式的無參數函式（以名稱明寫，不用動態 getattr——test_wording_guards）。"""
    try:
        send()
    except Exception:                                                           # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("自訂模組定義送審信件失敗")


def _email():
    from helpers import email_notify
    return email_notify


def _with_superadmins(conn, tiers, submitter):
    """佇列／詳情用：審核人名單＋申請人以外的最高管理者（`_can_decide` 本來就放行他們，佇列卻沒列 ⇒ 「等我簽核」看不到）。
    只改給佇列看的副本，不動存進 decision_json 的簽核鏈。每層 approvers 是「任一位都可以決定」（見 `decide`），不是依序。"""
    tiers = json.loads(json.dumps(tiers or []))
    if not tiers:
        tiers = [{"order": 0, "approvers": []}]
    have = {a.get("username") for t in tiers for a in t.get("approvers", [])}
    for r in conn.execute("SELECT username, display_name FROM users WHERE role='superadmin' AND active=1 ORDER BY id").fetchall():
        if r["username"] != submitter and r["username"] not in have:
            tiers[0].setdefault("approvers", []).append({"username": r["username"], "displayName": r["display_name"] or r["username"], "status": "pending"})
    return tiers


def _notify(conn, usernames, module_key, version, message):
    try:
        from helpers.audit import _notify as _n
        for u in usernames:
            # ref_id＝`customdef:<模組 key>:<版號>`：notif.js 認得它 ⇒ 點鈴鐺開審核頁（原本 `key:ver` 沒人解析、點了只標已讀）
            _n(u, "custom_module_def", "customdef:%s:%d" % (module_key, version), module_key, message)
    except Exception:                                                           # noqa: BLE001 — 通知失敗不擋送審
        pass


def _approver_names(row):
    return [a.get("username") for t in ((_dec(row).get("approval") or {}).get("tiers") or []) for a in t.get("approvers", [])]


def _can_decide(conn, row, user):
    """⇒ (ok, status, msg)：申請人以外，且是名單上的審核人、其有效代理人、或最高管理者。"""
    from helpers.tiered_approval import active_delegators_for
    appr = _dec(row).get("approval") or {}
    if (appr.get("requestedBy") or row.get("submitted_by") or "") == user["username"]:
        return False, 403, "不能審核自己送出的定義"
    names = set(_approver_names(row))
    if user.get("role") == "superadmin" or user["username"] in names or (names & set(active_delegators_for(conn, user["username"]))):
        return True, 200, ""
    return False, 403, "你不是這份定義的審核人"


def decide(conn, module_key, version, user, approve, note=""):
    """核可（發布）／退回（原因必填）。回 `{status, version, published}`。"""
    row = D.get(conn, "custom_module", module_key, "company", int(version))
    if row is None or row["status"] != "submitted":
        raise ReviewError("這一版不是送審中", 409)
    ok, code, msg = _can_decide(conn, row, user)
    if not ok:
        raise ReviewError(msg, code)
    note = (note or "").strip()
    if not approve and not note:
        raise ReviewError("退回要填原因", 400)
    base = _dec(row).get("baseVersion")
    if approve and base is not None and _latest_version(conn, module_key) != int(base):
        raise ReviewError("這份送審（第 %d 版）是依據第 %s 版送的，而現行版已是第 %d 版，送審已過期：請退回這一版，從最新版重新送審"
                          % (row["version"], base, _latest_version(conn, module_key)), 409)
    appr = _dec(row).get("approval") or {}
    try:
        out = D.decide_submitted(conn, "custom_module", module_key, "company", version, bool(approve), user["username"], note,
                                 {"approval": appr} if approve else {"approval": appr, "reason": note})
    except D.DefinitionError as e:
        raise ReviewError(str(e), 422 if e.problems else 400, e.problems)
    _notify(conn, [row.get("submitted_by") or ""], module_key, row["version"],
            "自訂模組「%s」的定義（第 %d 版）已%s%s" % (module_key, row["version"], "核可並發布" if approve else "退回", "：" + note if note else ""))
    if approve:
        _mail(lambda: _email().notify_custom_def_approved(module_key, row["version"], user["username"], row.get("submitted_by") or ""))
    else:
        _mail(lambda: _email().notify_custom_def_returned(module_key, row["version"], note, row.get("submitted_by") or ""))
    return {"status": out["status"], "version": out["version"], "published": bool(approve)}


def _was_involved(conn, module_key, user) -> bool:
    """這個人是不是這個模組任何一次送審的申請人或審核人（決定完之後仍讀得到「目前沒有送審中」與歷史，不是 404）。"""
    from helpers.settings import _get_setting
    if user["username"] in (_get_setting(REVIEWERS_KEY, []) or []):
        return True
    for v in D.versions(conn, "custom_module", module_key, "company"):
        if v["status"] in ("submitted", "rejected", "published") and user["username"] in (
                [v.get("submitted_by")] + [a.get("username") for t in ((v.get("decision") or {}).get("approval") or {}).get("tiers", []) for a in t.get("approvers", [])]):
            return True
    return False


def _can_read(conn, row, user) -> bool:
    from helpers.tiered_approval import active_delegators_for
    if user.get("role") == "superadmin" or (row.get("submitted_by") or "") == user["username"]:
        return True
    names = set(_approver_names(row))
    return bool(user["username"] in names or (names & set(active_delegators_for(conn, user["username"]))))


def open_view(conn, module_key, user) -> dict:
    """審核頁用：送審中的那一版（審核人、與現行版的差異、能不能決定）＋被退回的歷史。
    最高管理者、審核人（含代理）、申請人可讀；其他人 403。差異＝`core.definitions.diff`（現行版 → 送審版）。"""
    row = D.open_submission(conn, "custom_module", module_key, "company")
    if row is not None and not _can_read(conn, row, user):
        raise ReviewError("沒有審核這份定義的權限", 403)
    if row is None and user.get("role") != "superadmin" and not _was_involved(conn, module_key, user):
        raise ReviewError("沒有送審中的定義", 404)
    latest = D.get(conn, "custom_module", module_key, "company")
    hist = [{"version": v["version"], "status": v["status"], "submittedBy": v.get("submitted_by") or "", "submittedAt": v.get("submitted_at") or "",
             "note": v.get("note") or "", "reason": (v.get("decision") or {}).get("reason", ""),
             "decidedBy": (v.get("decision") or {}).get("decidedBy", "")} for v in D.versions(conn, "custom_module", module_key, "company")
            if v["status"] in ("submitted", "rejected")]
    if row is None:
        return {"open": None, "history": hist}
    ok, _c, why = _can_decide(conn, row, user)
    return {"open": {"version": row["version"], "submittedBy": row.get("submitted_by") or "", "submittedAt": row.get("submitted_at") or "",
                     "note": row.get("note") or "", "approval": _dec(row).get("approval") or {}, "canDecide": bool(ok), "whyNot": "" if ok else why,
                     "changes": D.diff((latest or {}).get("body") or {}, row["body"])},
            "history": hist}


def queue_items(conn) -> list:
    """IP-10 `approval.queue_items`：送審中的模組定義（`type`＝`custom_module_def`；`quoteNo`＝「模組key:版號」）。"""
    from helpers import approval_queue as _aq
    items = []
    for r in conn.execute("SELECT key, version, note, submitted_by, submitted_at, decision_json FROM ui_definitions "
                          "WHERE kind='custom_module' AND scope='company' AND status='submitted' ORDER BY version DESC").fetchall():
        doc_no = "%s:%d" % (r["key"], r["version"])
        # 簽核鏈在 decision_json.approval：讀不出來的那一筆跳過並記 ERROR（寫單號不寫內容）——不可以當成「沒有簽核層」列出（c-queue-json）
        raw = _aq.approval_json_of(r["decision_json"] or "{}", QUEUE_TYPE, doc_no)
        if raw is None:
            continue
        try:
            _a = json.loads(raw)
            _a["tiers"] = _with_superadmins(conn, _a.get("tiers"), r["submitted_by"] or "")
            raw = json.dumps(_a, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
        fld = _aq.tier_fields(raw)
        items.append(_aq.base_item(QUEUE_TYPE, doc_no, fld,
                                   projectName="自訂模組定義「%s」第 %d 版" % (r["key"], r["version"]),
                                   quoteDate=(r["submitted_at"] or "")[:10], moduleKey=r["key"], definitionVersion=r["version"],
                                   note=r["note"] or ""))
    return items


def detail(conn, doc_id):
    """IP-93 `approval.detail`：id＝「模組key:版號」；內容＝送審資訊與異動處數（完整差異在審核頁）。"""
    key, _, ver = str(doc_id).rpartition(":")
    try:
        # 直接讀列（不經 core.definitions.get：它會驗 key 形狀，佇列項目的 id 是我們自己組的「模組key:版號」）
        r = conn.execute("SELECT * FROM ui_definitions WHERE kind='custom_module' AND scope='company' AND key=? AND version=? AND status='submitted'",
                         (key, int(ver))).fetchone()
        row = dict(r) if r is not None else None
        if row is not None:
            row["body"] = json.loads(row.get("body_json") or "{}")
    except (ValueError, TypeError):
        return None
    if row is None:
        return None
    dec = _dec(row)
    try:
        latest = (D.get(conn, "custom_module", key, "company") or {}).get("body") or {}
    except D.DefinitionError:
        latest = {}
    changes = D.diff(latest, row["body"])
    return {"quoteNo": "", "title": "自訂模組定義送審（%s）" % doc_id,          # 沒有掛案件 ⇒ quoteNo 空（與佇列項目的 linkedQuoteNo 一致）
            "approvalRaw": json.dumps({"tiers": _with_superadmins(conn, (dec.get("approval") or {}).get("tiers"), row.get("submitted_by") or ""),
                                       "requestedBy": row.get("submitted_by") or ""}, ensure_ascii=False),
            "fields": [{"label": "模組", "value": key}, {"label": "版本", "value": "第 %s 版" % ver},
                       {"label": "申請人", "value": row.get("submitted_by") or "—"},
                       {"label": "送審說明", "value": row.get("note") or "—"},
                       {"label": "異動處數", "value": str(len(changes))}],
            "items": [], "files": []}


def restore_to_draft(conn, module_key, version, user):
    """還原舊版：**審核啟用時**＝把舊版內容放回草稿（再走送審），不直接發布；未啟用時呼叫端沿用原本的直接還原。
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
