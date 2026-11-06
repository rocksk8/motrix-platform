# -*- coding: utf-8 -*-
"""報價單「內容指紋」（簽核二擇一 S1；規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §H1、§I）。

[單位] case:content_fp    [層] L2（M01）

**不變式**：簽核只對它簽的那一版內容有效。「那一版」＝ `data_json` 去掉**排除清單**後的正規化雜湊。
**未知鍵一律算內容**（denylist；預設從嚴）。排除清單鎖在 `tests/test_content_fp_write_paths_s0_2026_11_06.py`。

S1 只提供：指紋／鍵雜湊、簽核條目蓋章（`signedFp`）、**純推導**的 `effective_approval`、`rebaseline_fingerprint`。
S3a（本檔尾）加 `reconcile_in_memory`／`reconfirm_mode`：**純函式，沒有任何呼叫端**（接線是 S3b；I2：讀路徑只推導、不寫入）。

相容：條目沒有 `signedFp`（S1 上線前簽的）＝**視為與目前相同**（不判過期）；第一次有人蓋章或 `rebaseline_fingerprint` 之後才開始計。
"""
import copy
import hashlib
import json
from datetime import datetime

#: 指紋格式版本。正規化規則變動時加一——所有已存的指紋都會失配，**必須**同時對簽核中的單呼叫 `rebaseline_fingerprint`
FP_VERSION = "1"

#: 排除清單（I4 定案）：純伺服器簿記、簽核人不需審視的頂層鍵。`dealTag`／`rejection` 維持從嚴算內容（影子模式一週後再議）
EXCLUDED_KEYS = frozenset({
    "approval", "statusLog", "editHistory", "returnInfo", "clauseTitles", "locationIdentity", "status",
    "updatedAt", "docVersions", "googleCalendarEventId", "altPickedAt", "altPickedBy", "dealWonAt",
})

#: `POST /approve` 的 `expectedFp` 是否必填。H3 寫「必填」；S1 先設 False——舊前端沒帶就照舊放行、帶了且不符才 409。
#: 前端（quotation-form）已改為帶；確認所有入口都帶了之後翻成 True（翻轉要比照放寬簽核門檻的管控，見 H4）
EXPECTED_FP_REQUIRED = False

PENDING_STATES = ("待審核", "簽核中")


def _canon(v):
    """正規形：None 與缺鍵相同（dict 內丟掉 None 值）；整數值的浮點數視為整數（Python 的 30000.0 經瀏覽器 JSON 來回變 30000）。
    與 `quotations._canon_segment` 同一組規則（那邊只在比對時處理 None，這裡要產生雜湊，所以直接丟掉）。"""
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_canon(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _digest(obj) -> str:
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()


def content_fingerprint(data: dict) -> str:
    """`<版本>:<32 hex>`。只看頂層鍵不在排除清單內的部分。"""
    if not isinstance(data, dict):
        raise TypeError("content_fingerprint：data 必須是 dict")
    body = {k: v for k, v in data.items() if k not in EXCLUDED_KEYS}
    return FP_VERSION + ":" + _digest(_canon(body))[:32]


def key_hashes(data: dict) -> dict:
    """各區塊的短雜湊（8 hex）：頂層鍵，外加 `caseRecord` 的第二層鍵（`caseRecord.<k>`）。供「哪些區塊變了」顯示，不存內容。"""
    out = {}
    for k, v in (data or {}).items():
        if k in EXCLUDED_KEYS:
            continue
        cv = _canon(v)
        if k == "caseRecord" and isinstance(cv, dict):
            for k2, v2 in cv.items():
                out["caseRecord." + k2] = _digest(v2)[:8]
        else:
            out[k] = _digest(cv)[:8]
    return out


def changed_blocks(old: dict, new: dict) -> list:
    """兩份 `key_hashes` 的差異區塊名（排序；新增／刪除／變更都算）。只回名稱，不含內容。"""
    old, new = old or {}, new or {}
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


def _entries(approval):
    for t in (approval or {}).get("tiers") or []:
        for a in (t.get("approvers") or []) if isinstance(t, dict) else []:
            if isinstance(a, dict):
                yield t, a


def pending_entries(approval) -> list:
    """目前尚未簽核的條目（物件本身，不是複本）；`stamp_signed` 用它在簽核動作前後做差。"""
    return [a for _t, a in _entries(approval) if a.get("status") != "approved"]


def stamp_signed(approval: dict, was_pending: list, data: dict) -> list:
    """把『這一次才變成 approved』的條目蓋上 `signedFp`／`signedKeyHashes`（含同人連簽的 cascade 層），並更新 `approval.contentFp`。

    只蓋這次簽的——S1 之前就簽好的舊條目不蓋（否則等於替它們背書了這之後才發生的內容變動）。回傳被蓋章的條目。"""
    fp, hashes = content_fingerprint(data), key_hashes(data)
    done = [a for a in was_pending if a.get("status") == "approved"]
    for a in done:
        a["signedFp"] = fp
        a["signedKeyHashes"] = hashes
    approval["contentFp"] = fp
    approval["keyHashes"] = hashes                       # 最近一次基準的區塊雜湊（`reconcile_in_memory` 比對「哪些區塊變了」用；否則會退回取某個舊條目的 signedKeyHashes ⇒ 重複報舊變動）
    return done


def effective_approval(data: dict, fp: str = None, *, enabled: bool, suspended: bool = None):
    """**純推導**（讀路徑用；不寫入、不改傳入的資料）：回傳 `(approval 複本, 有沒有條目被視為過期)`。

    只在 **旗標＝開**（`enabled=True`）且**沒有暫停**時才推導複查：影子模式（`enabled=False`）或 `approval.reconfirmSuspended`（輪次已達上限，
    系統不再自動作廢）時**不推導**——畫面不能顯示「需複查」而伺服器實際不會作廢，兩邊必須一致。`enabled` 必傳（由外層讀 `reconfirm_mode`）；
    `suspended` 沒給就看 `approval.reconfirmSuspended`。

    已簽條目若有 `signedFp` 且 ≠ 目前指紋 ⇒ 視為 pending＋`reconfirm=True`（保留 `prevSignedFp`／`prevApprovedAt`）；
    `currentTier` 取第一個尚有未簽條目的層。沒有 `signedFp` 的條目不判過期（舊單相容）。
    S1 **沒有任何呼叫端**把它接到畫面／端點上（接線在 S3b）。"""
    appr = copy.deepcopy((data or {}).get("approval") or {})
    if suspended is None:
        suspended = bool(appr.get("reconfirmSuspended"))
    if not enabled or suspended:
        return appr, False
    fp = fp or content_fingerprint(data)
    stale = False
    for _t, a in _entries(appr):
        sf = a.get("signedFp")
        if a.get("status") == "approved" and sf and sf != fp:
            a["prevSignedFp"], a["prevApprovedAt"] = sf, a.get("approvedAt")
            a["status"], a["reconfirm"] = "pending", True
            a.pop("approvedAt", None)
            stale = True
    if stale:
        tiers = appr.get("tiers") or []
        for i, t in enumerate(tiers):
            if any(isinstance(a, dict) and a.get("status") != "approved" for a in (t.get("approvers") or [])):
                appr["currentTier"] = i
                break
    return appr, stale


def rebaseline_fingerprint(conn, quote_no: str, user: dict = None, reason: str = "遷移重設基準", now: str = None) -> bool:
    """把簽核中單的基準重設為**目前**內容：`approval.contentFp` 與所有已簽條目的 `signedFp` 都改成現在的指紋。

    用在：會改 `quotations.data_json` 內容鍵、又可能碰到待審核／簽核中單的**開機遷移**（例：`db.py::_m116`）——
    否則遷移會讓已簽的簽核一次性失配。之後新增這類遷移必須呼叫它（S0 守門的 MIGRATION_ONCE 備註要寫明）。

    前置：呼叫端已在寫交易內（沿用 `save_quotation_json` 的 lost-update 守門）。**不動 `updated_at`**（它是 PUT 樂觀鎖的版本戳）。
    回傳 True＝有重設；單不存在／不在待審核簽核中／沒有簽核資料 ⇒ False（什麼都不寫）。稽核與資料同一交易。"""
    from modules.case.quotations import save_quotation_json
    row = conn.execute("SELECT data_json, status, updated_at FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row or row["status"] not in PENDING_STATES:
        return False
    try:
        data = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        return False
    appr = data.get("approval") if isinstance(data, dict) else None
    if not isinstance(appr, dict) or not appr.get("tiers"):
        return False
    fp, hashes = content_fingerprint(data), key_hashes(data)
    before = appr.get("contentFp")
    n = 0
    for _t, a in _entries(appr):
        if a.get("status") == "approved":
            a["signedFp"], a["signedKeyHashes"] = fp, hashes
            n += 1
    appr["contentFp"] = fp
    data["approval"] = appr
    save_quotation_json(conn, quote_no, data, updated_at=row["updated_at"])
    now = now or datetime.now().isoformat()
    from helpers.audit import _derive_fields
    detail = {"reason": reason, "fromFp": before, "toFp": fp, "entries": n}
    d = _derive_fields("quotation.rebaseline_fp", "quotation", quote_no, quote_no, detail)
    u = user or {}
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (now, u.get("id"), u.get("username", "system"), u.get("display_name") or u.get("username", "system"),
         "quotation.rebaseline_fp", "quotation", quote_no, quote_no, json.dumps(detail, ensure_ascii=False),
         d["module"], d["case_no"], d["ref_no"]))
    return True


# ── S3a：reconcile_in_memory（K2；純函式，**沒有呼叫端**——接線是 S3b）────────────────────────────

REVIEW_ROUNDS_LIMIT = 5                 # H9-③：同一單複查輪次上限；已達上限後的內容變動不再自動作廢，改設 reconfirmSuspended 通知超管
SOURCE_REVIEW_EDIT = "review-edit"      # S4 的編輯入口傳進來的 source：編輯者「原已簽、正在複查」的條目視為簽新版（H9-①）
MODE_GROUP, MODE_FIELD = "quote_approval", "reconfirm_mode"
MODES = ("off", "shadow", "on")         # off＝完全不跑 reconcile（外層直接略過）；shadow＝只記錄（reconcile 的 enabled=False）；on＝作廢＋複查（enabled=True）
LOG_CAP = 50                            # changeLog／shadowLog 各保留最近幾筆（避免 data_json 無限長；輪次另由 reviewRounds 計）

#: 通知文字裡「系統做的」來源中文名（actor 為 None 時用）；沒列到的 source 照原字串
SOURCE_LABELS = {"put": "儲存報價單", "submit": "送審", "approve": "核准", "review-edit": "複查編輯", "material": "叫料", "payment": "款項",
                 "settlement": "精算", "case-record": "案件記錄", "migration": "系統遷移"}


def reconfirm_mode(conn=None) -> str:
    """三態旗標 `quote_approval.reconfirm_mode`（`off`／`shadow`／`on`）。**只給外層（S3b 的 reconcile_txn）呼叫**——`reconcile_in_memory` 是純函式，不讀設定。
    外層映射：`off` ⇒ 略過 reconcile；`shadow` ⇒ `enabled=False`；`on` ⇒ `enabled=True`。
    **嚴格讀取**（`helpers.settings_strict.strict_value`）：讀不到（連線／資料庫錯、欄位尚未註冊、不是這三個值）⇒ **`on`**（最嚴；與 D-K1「讀不到取最嚴格」同方向）。
    欄位的預設值（未儲存過時）由設定註冊表決定——S3a 尚未註冊該欄位（註冊了設定中心會多一個沒接線的開關），所以現在永遠回 `on`；S3b 註冊時預設 `off`。"""
    try:
        from helpers.settings_strict import strict_value
        own = conn is None
        if own:
            from db import get_db
            conn = get_db()
        try:
            v = strict_value(conn, MODE_GROUP, MODE_FIELD)
        finally:
            if own:
                conn.close()
        if isinstance(v, str) and v.strip().lower() in MODES:
            return v.strip().lower()
        raise ValueError("reconfirm_mode 不是 off／shadow／on：%r" % (v,))
    except Exception:                                                       # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("quote_approval.reconfirm_mode 讀不到，改取最嚴（on）", exc_info=True)
        return "on"


def _actor_name(actor) -> str:
    if isinstance(actor, dict):
        return actor.get("display_name") or actor.get("username") or "system"
    return str(actor) if actor else "system"


def _actor_text(actor, source) -> str:
    """通知文字裡的操作者：有人 ⇒ 顯示名；沒有（系統）⇒ 「系統（<來源中文名>）」。"""
    if actor:
        return _actor_name(actor)
    return "系統（%s）" % SOURCE_LABELS.get(source, source)


def _actor_username(actor):
    return actor.get("username") if isinstance(actor, dict) else (actor if isinstance(actor, str) else None)


def _append_log(appr: dict, key: str, entry: dict) -> None:
    lst = appr.get(key)
    lst = lst if isinstance(lst, list) else []
    lst.append(entry)
    appr[key] = lst[-LOG_CAP:]


def _first_pending_tier(appr: dict):
    for i, t in enumerate(appr.get("tiers") or []):
        if isinstance(t, dict) and any(isinstance(a, dict) and a.get("status") != "approved" for a in (t.get("approvers") or [])):
            return i
    return None


def _old_key_hashes(appr: dict) -> dict:
    kh = appr.get("keyHashes")
    if isinstance(kh, dict) and kh:
        return kh
    for _t, a in _entries(appr):
        h = a.get("signedKeyHashes")
        if isinstance(h, dict) and h:
            return h
    return {}


def reconcile_in_memory(data: dict, now: str, actor, source: str, *, status: str = None, enabled: bool):
    """**純函式**：只改記憶體中的 `data["approval"]`，不寫資料庫、不讀設定、不呼叫任何 API。回 `(changed, notices)`：
    `changed`＝approval 有被改、呼叫端要寫回；`notices`＝要發的通知清單（見下）。

    - `status`＝資料庫列的狀態，**呼叫端必傳**（`data_json` 的 `status` 是排除鍵、會過期）。**fail-closed**：沒傳（None）、或不在
      `PENDING_STATES`（待審核／簽核中）⇒ 不動；`approval.status` 是 approved／rejected ⇒ 一律不動（雙保險，不管 `status` 傳什麼）。沒有 `tiers` ⇒ 不動。
    - `enabled`（**必傳關鍵字**）：True＝旗標開（作廢＋複查）、False＝影子模式。外層讀 `reconfirm_mode()` 映射（off ⇒ 根本不呼叫）。
    - `approval.contentFp` 缺（舊單／剛送審）⇒ **靜默設基準**（`contentFp`／`keyHashes`／`baselineSetBy=source`），不作廢。
    - 指紋與 `contentFp` 相同，且（影子，或沒有「已簽且 signedFp≠目前」的條目）⇒ `(False, [])`（冪等）。
    - 內容不同、影子：只追加 `shadowLog`（`{at, blocks, by, source, fp, wouldInvalidate}`），不改條目、不加 `contentRev`；基準仍前進（不重複記）。
    - 開：
        · 已簽且 `signedFp`≠目前者 ⇒ pending＋`reconfirm`＋`prevSignedFp／prevApprovedAt`；`currentTier` 退到第一個未簽層；`contentRev+1`；
          `changeLog` 加一筆 `{at, rev, blocks, by, source, invalidated, resigned}`；`reviewRounds+1`（一次作廢幾層都只算 1 輪）。沒有 `signedFp` 的舊條目**永不作廢**。
        · **補追**：影子期間改了 N 次、之後旗標開 ⇒ 下一次 reconcile（即使指紋與基準相同）一次作廢所有過期條目，只算 1 輪，`changeLog.catchUp=True`。
        · `source==SOURCE_REVIEW_EDIT`：編輯者本人「已簽但過期」或「pending＋reconfirm」的條目改 approved＋新 `signedFp`（H9-①）；首次待簽的不自動簽。
        · **沒有可作廢條目**（扣掉編輯者自己重簽的之後，沒有過期條目；例：還沒人簽、或全是無 signedFp 的舊條目）：基準仍前進，`contentRev+1`＋`changeLog` 照記，
          但**不**加輪、**不**通知、**不**暫停——不管 `reviewRounds` 已經多少。
        · **有可作廢條目**而 `reviewRounds>=REVIEW_ROUNDS_LIMIT` ⇒ 不作廢、不改任何條目（連編輯者的重簽也不做），設 `reconfirmSuspended=True`，通知超管（只在第一次設旗標時發）。
    通知元素：`{type, to, text, blocks, by, source, rev}`；`to` 一律是**清單**：元素是帳號字串，或 `{"role": "superadmin"}`（超管）。
    基準永遠在處理完之後前進到目前內容，所以重複呼叫是冪等的。"""
    if not isinstance(data, dict) or status not in PENDING_STATES:
        return False, []
    appr = data.get("approval")
    if not isinstance(appr, dict) or not isinstance(appr.get("tiers"), list) or not appr["tiers"]:
        return False, []
    if appr.get("status") in ("approved", "rejected"):
        return False, []

    fp, hashes = content_fingerprint(data), key_hashes(data)
    cur = appr.get("contentFp")
    if not cur:
        appr["contentFp"], appr["keyHashes"], appr["baselineSetBy"] = fp, hashes, source
        return True, []
    stale = [a for _t, a in _entries(appr) if a.get("status") == "approved" and a.get("signedFp") and a.get("signedFp") != fp]
    if cur == fp and (not stale or not enabled):
        return False, []

    catch_up = cur == fp                                                    # 指紋與基準相同卻有過期條目 ⇒ 影子期間累積的變動，旗標剛開
    if catch_up:
        bl = set()
        for a in stale:
            sh = a.get("signedKeyHashes")
            if isinstance(sh, dict) and sh:
                bl.update(changed_blocks(sh, hashes))
        blocks, known = sorted(bl), bool(bl)
    else:
        old_hashes = _old_key_hashes(appr)
        blocks, known = (changed_blocks(old_hashes, hashes) if old_hashes else []), bool(old_hashes)
    by = _actor_name(actor)
    who = _actor_text(actor, source)
    me = _actor_username(actor)

    def finish_baseline():
        appr["contentFp"], appr["keyHashes"] = fp, hashes

    if not enabled:                                                         # 影子模式：只記錄
        _append_log(appr, "shadowLog", {"at": now, "blocks": blocks, "by": by, "source": source, "fp": fp,
                                        "wouldInvalidate": [a.get("username") for a in stale], **({} if known else {"blocksUnknown": True})})
        finish_baseline()
        return True, []

    rev = int(appr.get("contentRev") or 0) + 1
    rounds = int(appr.get("reviewRounds") or 0)
    base_log = {"at": now, "rev": rev, "blocks": blocks, "by": by, "source": source,
                **({} if known else {"blocksUnknown": True}), **({"catchUp": True} if catch_up else {})}
    appr["contentRev"] = rev

    resign_candidates = []                                                  # 編輯者自己的條目（先只挑出來，確定要不要作廢之後才動）
    if source == SOURCE_REVIEW_EDIT and me:
        for _t, a in _entries(appr):
            if a.get("username") == me and ((a.get("status") == "approved" and a.get("signedFp") and a.get("signedFp") != fp)
                                            or (a.get("status") != "approved" and a.get("reconfirm"))):
                resign_candidates.append(a)
    to_invalidate = [a for a in stale if not any(a is r for r in resign_candidates)]

    if to_invalidate and rounds >= REVIEW_ROUNDS_LIMIT:                     # 有東西要作廢、但輪次已滿：不再自動作廢，改請超管處置（不改任何條目）
        first_time = not appr.get("reconfirmSuspended")
        appr["reconfirmSuspended"] = True
        _append_log(appr, "changeLog", dict(base_log, suspended=True, invalidated=[], resigned=[]))
        finish_baseline()
        notices = [{"type": "approval_reconfirm_suspended", "to": [{"role": "superadmin"}], "blocks": blocks, "by": by, "source": source, "rev": rev,
                    "text": f"報價單內容在簽核期間已變動超過 {REVIEW_ROUNDS_LIMIT} 輪，系統不再自動作廢已簽層，請最高管理者處置（最近一次：{who}）"}] if first_time else []
        return True, notices

    resigned = []
    for a in resign_candidates:
        a["status"], a["approvedAt"], a["signedFp"], a["signedKeyHashes"] = "approved", now, fp, hashes
        for k in ("reconfirm", "prevSignedFp", "prevApprovedAt"):
            a.pop(k, None)
        resigned.append(a)
    invalidated = []
    for a in to_invalidate:
        a["prevSignedFp"], a["prevApprovedAt"] = a.get("signedFp"), a.get("approvedAt")
        a["status"], a["reconfirm"] = "pending", True
        a.pop("approvedAt", None)
        invalidated.append(a)
    if invalidated or resigned:
        idx = _first_pending_tier(appr)
        if idx is not None:
            appr["currentTier"] = idx
    if invalidated:
        appr["reviewRounds"] = rounds + 1                                   # 不管這次一次作廢幾個條目、補追了幾次影子變動：只 +1
    _append_log(appr, "changeLog", dict(base_log, invalidated=[a.get("username") for a in invalidated], resigned=[a.get("username") for a in resigned]))
    finish_baseline()

    notices = []
    if invalidated:                                                         # 沒有任何條目被作廢 ⇒ 沒有通知
        inv_names = [a.get("username") for a in invalidated if a.get("username") != me]
        blk = "、".join(blocks) if blocks else "（區塊未知）"
        if inv_names:
            notices.append({"type": "approval_reconfirm", "to": inv_names, "blocks": blocks, "by": by, "source": source, "rev": rev,
                            "text": f"你已簽核的報價單內容被 {who} 修改（{blk}），請重新複查確認"})
        others = [a.get("username") for _t, a in _entries(appr)
                  if a.get("status") != "approved" and not a.get("reconfirm") and a.get("username") not in (me, None)]
        if others:
            notices.append({"type": "approval_reconfirm_info", "to": others, "blocks": blocks, "by": by, "source": source, "rev": rev,
                            "text": f"報價單內容被 {who} 修改（{blk}），前面已簽的層需重新複查"})
        req = appr.get("requestedBy")
        if req and req != me and req not in inv_names:
            notices.append({"type": "approval_reconfirm_info", "to": [req], "blocks": blocks, "by": by, "source": source, "rev": rev,
                            "text": f"你送審的報價單內容被 {who} 修改（{blk}），已簽核的層需重新複查"})
    return True, notices
