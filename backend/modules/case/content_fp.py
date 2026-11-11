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


def signature(approval) -> tuple:
    """每個簽核條目的 (狀態, 是否待複查)——`reconcile_txn` 前後比對「有沒有任何簽核層被作廢」（影子模式只動 log／基準，簽名不變）。"""
    return tuple((a.get("status"), bool(a.get("reconfirm"))) for _t, a in _entries(approval))


def pending_entries(approval) -> list:
    """目前尚未簽核的條目（物件本身，不是複本）；`stamp_signed` 用它在簽核動作前後做差。"""
    return [a for _t, a in _entries(approval) if a.get("status") != "approved"]


def self_edit_sign(tiers, editor: str) -> bool:
    """H6-3「自改自簽」：整張單的簽核人（所有有效層、所有條目的 `username` 去重）**只有編輯者一個人** ⇒ 他改完自己簽，沒有第二雙眼。
    同一人連任多層（2026-09-15 cascade，條目 ≥2、人 1）也算；同層兩人、或另有他人的層 ⇒ 有第二雙眼，不標註。
    **偵測範圍之外**：舊單條目沒有 `signedFp` 不會被作廢，「沒有人被請回來複核」不在這裡——影子週的統計看得到。
    只做標註（稽核＋通知超管），不阻擋。`tiers`＝有效簽核層（呼叫端的 `_active_tiers`）；代理人編輯時條目是本人、編輯者是代理人 ⇒ 兩個人 ⇒ 不標註。"""
    names = set()
    for t in tiers or []:
        for a in ((t.get("approvers") or []) if isinstance(t, dict) else []):
            if isinstance(a, dict) and a.get("username"):
                names.add(a["username"])
    return bool(editor) and names == {editor}


def current_reasons_or_none(data: dict):
    """J1：目前內容的原因集合 `[{key,text}]`（S2 伺服器演算法）；任何失敗（設定讀不到、資料殘缺）回 None＝這次不記基準，**不可讓簽核因此失敗**。"""
    try:
        from modules.case import quote_terms as _qt
        return _qt.current_reason_entries(data)
    except Exception:                                   # noqa: BLE001
        return None


APPROVE_FLAGS = ("reconfirm", "reassigned", "delegated")


def approve_flags(entry: dict, username: str) -> list:
    """K3：這次核准是不是「簽在別人看過的、或自己沒親自接手的內容上」。回成立的旗標（固定順序）：
    - `reconfirm`：目標條目正在複查（內容在他簽過之後變動）；
    - `reassigned`：條目是轉簽而來（`reassignedFrom`）——新簽核人沒看過原本的送審內容；
    - `delegated`：操作者不是條目本人（代理代簽）。
    成立 ⇒ 核准一律要帶 `expectedFp`（且等於目前指紋）與 `choice="keep"`（`reconfirm_mode=on` 時，不受 `EXPECTED_FP_REQUIRED` 影響）。"""
    if not isinstance(entry, dict):
        return []
    out = []
    if entry.get("reconfirm"):
        out.append("reconfirm")
    if entry.get("reassignedFrom"):
        out.append("reassigned")
    if entry.get("username") and username and entry.get("username") != username:
        out.append("delegated")
    return out


FLAG_LABELS = {"reconfirm": "內容在你簽過之後有變動", "reassigned": "此單由他人轉簽給你", "delegated": "你是代理簽核"}
REVIEW_NOTE_MAX = 200                                 # confirmNote 進稽核的字數上限（approve 端點截斷用）


def approve_review(data: dict, entry: dict, *, fp: str = None) -> dict:
    """S5（H3）：簽核畫面「維持／編輯」彈窗要的資料——**與檢視者無關**的部分（`delegated` 旗標依操作者而定，由 approve 端點的 409 判定，這裡不含）。

    - `entry`：當層第一個未簽核條目（誰按核准，就是在簽它）。`flags`＝`approve_flags(entry, None)`（reconfirm／reassigned）。
    - `changedBlocks`：只有 reconfirm 才算——該條目簽核當時的區塊雜湊（`signedKeyHashes`）對目前內容的差異區塊名（不含內容；舊條目沒有雜湊 ⇒ 空）。
    - `newReasons`／`needNote`：只有 reconfirm 才算（G1／J1／J4）。基準＝條目的 `signedReasonEntries`，目前＝S2 伺服器演算法；
      判準在**類別層級**（`category_summary.needs_confirm`：新類別、低毛利品項增加／名次變差、天數／折讓變大、稅率變低），不看個別 key。
      舊單沒有基準 ⇒ 不要求（J1）；基準有、但目前的原因算不出來（設定讀不到）⇒ **要求**（算不出來不能當作沒新增）。
      `newReasons`＝新增與數值惡化的原因文字（畫面列表用，最多 10 則）；簽核人本來就看得到 `approval.reasons`，不另遮蔽。
    純讀：不改 `data`／`entry`。"""
    fp = fp or content_fingerprint(data)
    flags = approve_flags(entry, None)
    out = {"entry": (entry or {}).get("username"), "flags": flags, "flagLabels": [FLAG_LABELS[f] for f in flags],
           "changedBlocks": [], "newReasons": [], "needNote": False, "contentFp": fp}
    if "reconfirm" not in flags:
        return out
    sh = entry.get("signedKeyHashes")
    if isinstance(sh, dict) and sh:
        out["changedBlocks"] = changed_blocks(sh, key_hashes(data))
    old = entry.get("signedReasonEntries")
    if old is None:
        return out                                          # 舊單沒有歷史基準：不提示新增原因（J1）
    new = current_reasons_or_none(data)
    if new is None:
        out["needNote"] = True
        return out
    try:
        from modules.case import quote_terms as _qt
        diff, summ = _qt.diff_reason_entries(old, new), _qt.category_summary(old, new)
    except Exception:                                       # noqa: BLE001 — 比對本身出錯也不可當成「沒新增」
        out["needNote"] = True
        return out
    out["needNote"] = bool(summ.get("needs_confirm"))
    out["newReasons"] = ([e["text"] for e in diff.get("added") or []] + [e["after"] for e in diff.get("changed") or []])[:10]
    return out


_FP_CACHE: dict = {}
_FP_CACHE_MAX = 1024


def fingerprint_of_json(raw):
    """列表用（S4b）：`data_json` 字串 ⇒ 內容指紋；壞 JSON／不是物件／空 ⇒ None。**行程內快取**：鍵＝字串的雜湊（內容一變鍵就變，不會拿到舊值），
    指紋只由字串決定，所以快取天然正確；列表每次只付「讀字串＋雜湊」，不再每筆 json.loads＋正規化（W3 approval-freeze 的教訓）。"""
    if not raw or not isinstance(raw, str):
        return None
    import hashlib
    key = hashlib.blake2b(raw.encode("utf-8", "surrogatepass"), digest_size=16).digest()
    hit = _FP_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    fp = content_fingerprint(d)
    if len(_FP_CACHE) >= _FP_CACHE_MAX:
        _FP_CACHE.clear()                                   # 簡單、有上限：待審核單量小，清空重算的代價可忽略
    _FP_CACHE[key] = fp
    return fp


def stamp_signed(approval: dict, was_pending: list, data: dict, reason_entries=None) -> list:
    """把『這一次才變成 approved』的條目蓋上 `signedFp`／`signedKeyHashes`（含同人連簽的 cascade 層），並更新 `approval.contentFp`。

    只蓋這次簽的——S1 之前就簽好的舊條目不蓋（否則等於替它們背書了這之後才發生的內容變動）。回傳被蓋章的條目。"""
    fp, hashes = content_fingerprint(data), key_hashes(data)
    done = [a for a in was_pending if a.get("status") == "approved"]
    for a in done:
        a["signedFp"] = fp
        a["signedKeyHashes"] = hashes
        if reason_entries is not None:                   # J1：複查 diff 的基準（與 signedFp 同時記；舊單沒有 ⇒ 首次複查以當下補算）
            a["signedReasonEntries"] = reason_entries
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

    ⚠ **不得接到任何使用者端點**（unscoped 讀取棘輪的例外條件，K 審 2026-11-06）：它以呼叫端給的單號直接讀 quotations、沒有 row_access；
    守門題 `test_rebaseline_fingerprint_is_not_reachable_from_any_user_facing_endpoint` 會擋。

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
    _audit_in_txn(conn, "quotation.rebaseline_fp", quote_no, {"reason": reason, "fromFp": before, "toFp": fp, "entries": n}, user, now)
    return True


# ── S3a：reconcile_in_memory（K2；純函式，**沒有呼叫端**——接線是 S3b）────────────────────────────

REVIEW_ROUNDS_LIMIT = 5                 # H9-③：同一單複查輪次上限；已達上限後的內容變動不再自動作廢，改設 reconfirmSuspended 通知超管
SOURCE_REVIEW_EDIT = "review-edit"      # S4 的編輯入口傳進來的 source：編輯者「原已簽、正在複查」的條目視為簽新版（H9-①）
MODE_GROUP, MODE_FIELD = "quote_approval", "reconfirm_mode"
MODES = ("off", "shadow", "on")         # off＝完全不跑 reconcile（外層直接略過）；shadow＝只記錄（reconcile 的 enabled=False）；on＝作廢＋複查（enabled=True）
LOG_CAP = 50                            # changeLog／shadowLog 各保留最近幾筆（避免 data_json 無限長；輪次另由 reviewRounds 計）

#: 通知文字裡「系統做的」來源中文名（actor 為 None 時用）；沒列到的 source 照原字串
SOURCE_LABELS = {"put": "儲存報價單", "submit": "送審", "approve": "核准", "review-edit": "複查編輯", "review-edit-pre": "複查編輯前對帳", "material": "材料申請", "payment": "款項",
                 "settlement": "精算", "case-record": "案件記錄", "migration": "系統遷移",
                 # S3b 的呼叫點
                 "funnel": "儲存報價單", "overhead_pct": "調整管銷％", "material_change": "材料申請變更", "material_paid": "材料申請付款",
                 "material_recycle": "材料申請刪除／還原"}


_MODE_CODES = {0: "off", 1: "shadow", 2: "on"}      # 設定欄位是整數代碼（放寬管制只認數字欄位）；字串三態也收（測試／舊呼叫端）


def _read_mode(conn) -> str:
    """嚴格讀取、**讀不到就丟例外**（不快取失敗用）。"""
    from helpers.settings_strict import strict_value
    v = strict_value(conn, MODE_GROUP, MODE_FIELD)
    if isinstance(v, bool):
        raise ValueError("reconfirm_mode 不是 0／1／2：%r" % (v,))
    if isinstance(v, (int, float)) and v == int(v) and int(v) in _MODE_CODES:
        return _MODE_CODES[int(v)]
    if isinstance(v, str) and v.strip().lower() in MODES:
        return v.strip().lower()
    raise ValueError("reconfirm_mode 不是 0／1／2（off／shadow／on）：%r" % (v,))


def reconfirm_mode(conn=None) -> str:
    """三態旗標 `quote_approval.reconfirm_mode`（設定值 0／1／2 ⇒ `off`／`shadow`／`on`）。**只給外層（`reconcile_txn`）呼叫**——`reconcile_in_memory` 是純函式，不讀設定。
    外層映射：`off` ⇒ 略過 reconcile；`shadow` ⇒ `enabled=False`；`on` ⇒ `enabled=True`。
    **嚴格讀取**（`helpers.settings_strict.strict_value`）：讀不到（連線／資料庫錯、欄位尚未註冊、不是合法值）⇒ **`on`**（最嚴；與 D-K1「讀不到取最嚴格」同方向）。
    欄位預設 0（`off`，S3b 已在 `helpers/settings_groups.py` 註冊）。不快取；漏斗熱路徑請用 `_mode_cached`。"""
    try:
        own = conn is None
        if own:
            from db import get_db
            conn = get_db()
        try:
            return _read_mode(conn)
        finally:
            if own:
                conn.close()
    except Exception:                                                       # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("quote_approval.reconfirm_mode 讀不到，改取最嚴（on）", exc_info=True)
        return "on"


MODE_TTL_SECONDS = 5.0
_mode_cache = {"key": None, "at": 0.0, "mode": None}


def _reset_mode_cache() -> None:
    _mode_cache.update(key=None, at=0.0, mode=None)


def _mode_cached(conn) -> str:
    """漏斗熱路徑用：行程內快取 `MODE_TTL_SECONDS` 秒，設定發布（`settings_registry.invalidate`）或換資料庫即作廢。
    **讀失敗取 `on`（最嚴）且不快取**——下一次再讀，不會因為一次資料庫抖動把『最嚴』黏住 5 秒以上。
    快取命中時**零查詢**（`off` 的報價單寫入不多任何一句 SQL；測試用 SQL 計數證明）。"""
    import time
    from helpers import settings_registry as SR
    import db as _db
    key = (SR.generation(), str(getattr(_db, "DB_PATH", "")))
    now = time.monotonic()
    c = _mode_cache
    if c["key"] == key and c["mode"] is not None and now - c["at"] < MODE_TTL_SECONDS:
        return c["mode"]
    try:
        mode = _read_mode(conn)
    except Exception:                                                       # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("quote_approval.reconfirm_mode 讀不到，這次改取最嚴（on），不快取", exc_info=True)
        return "on"
    _mode_cache.update(key=key, at=now, mode=mode)
    return mode


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


def reconcile_in_memory(data: dict, now: str, actor, source: str, *, status: str = None, enabled: bool, reason_entries=None, chain_reset: bool = False):
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
    - `chain_reset`（只在 `source==SOURCE_REVIEW_EDIT` 生效；第 3 層（含）以後的簽核人複查編輯，2026-11-11）：整條簽核鏈回到第 1 層重跑——
      **所有**已簽條目（不論有沒有 `signedFp`、含編輯者自己）都回 pending＋`reconfirm`，**不**做編輯者自動重簽，`currentTier` 歸 0；`changeLog` 記 `chainReset=True`。
    基準永遠在處理完之後前進到目前內容，所以重複呼叫是冪等的。"""
    chain_reset = bool(chain_reset) and source == SOURCE_REVIEW_EDIT
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
    if source == SOURCE_REVIEW_EDIT and me and not chain_reset:
        for _t, a in _entries(appr):
            if a.get("username") == me and ((a.get("status") == "approved" and a.get("signedFp") and a.get("signedFp") != fp)
                                            or (a.get("status") != "approved" and a.get("reconfirm"))):
                resign_candidates.append(a)
    to_invalidate = [a for a in stale if not any(a is r for r in resign_candidates)]
    if chain_reset:                                                         # 整條重跑：每一個已簽的都作廢（含舊單沒有 signedFp 的、編輯者自己的）
        to_invalidate = [a for _t, a in _entries(appr) if a.get("status") == "approved"]

    if to_invalidate and rounds >= REVIEW_ROUNDS_LIMIT:                     # 有東西要作廢、但輪次已滿：不再自動作廢，改請超管處置（不改任何條目）
        first_time = not appr.get("reconfirmSuspended")
        appr["reconfirmSuspended"] = True
        _append_log(appr, "changeLog", dict(base_log, suspended=True, invalidated=[], resigned=[]))
        finish_baseline()
        notices = [{"type": "approval_reconfirm_suspended", "to": [{"role": "superadmin"}], "blocks": blocks, "by": by, "source": source, "rev": rev,
                    "text": f"報價單內容在簽核期間已變動超過 {REVIEW_ROUNDS_LIMIT} 輪，系統不再自動作廢已簽層，請最高管理者處置（最近一次：{who}）"}] if first_time else []
        return True, notices

    # 編輯者是「最後一個還沒簽完的人」（扣掉他，其他條目全已簽、且這次沒有任何一個被作廢）⇒ 不自動簽：自動簽會讓整單全部 approved 卻沒走核准的收尾
    # （狀態改已送出、PDF、通知核准）而卡在簽核中。改成他維持待簽（原已簽的轉 pending＋reconfirm），自己再按一次核准（綁版本＋choice）走正常收尾。
    last_one = bool(resign_candidates) and not to_invalidate and not any(
        a.get("status") != "approved" for _t, a in _entries(appr) if not any(a is r for r in resign_candidates))
    editor_pending = []
    if last_one:
        for a in resign_candidates:
            if a.get("status") == "approved":
                a["prevSignedFp"], a["prevApprovedAt"] = a.get("signedFp"), a.get("approvedAt")
                a["status"], a["reconfirm"] = "pending", True
                a.pop("approvedAt", None)
            editor_pending.append(a.get("username"))
        resign_candidates = []
        idx = _first_pending_tier(appr)
        if idx is not None:
            appr["currentTier"] = idx
    resigned = []
    for a in resign_candidates:
        a["status"], a["approvedAt"], a["signedFp"], a["signedKeyHashes"] = "approved", now, fp, hashes
        if reason_entries is not None:                                      # J1：呼叫端（reconcile_txn）算好傳進來，這裡維持純函式
            a["signedReasonEntries"] = reason_entries
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
    if chain_reset:
        appr["currentTier"] = 0                                             # 從第 1 層重新開始（即使沒有任何已簽條目可作廢）
    if invalidated:
        appr["reviewRounds"] = rounds + 1                                   # 不管這次一次作廢幾個條目、補追了幾次影子變動：只 +1
    entry_log = dict(base_log, invalidated=[a.get("username") for a in invalidated], resigned=[a.get("username") for a in resigned])
    if editor_pending:
        entry_log["editorPending"] = editor_pending
    if chain_reset:
        entry_log["chainReset"] = True
    _append_log(appr, "changeLog", entry_log)
    finish_baseline()

    notices = []
    if invalidated:                                                         # 沒有任何條目被作廢 ⇒ 沒有通知
        inv_names = [a.get("username") for a in invalidated if a.get("username") != me]
        blk = "、".join(blocks) if blocks else "（區塊未知）"
        if inv_names:
            notices.append({"type": "approval_reconfirm", "to": inv_names, "blocks": blocks, "by": by, "source": source, "rev": rev,
                            "text": (f"你已簽核的報價單內容被 {who} 修改（{blk}），整條簽核已回到第 1 層重新進行；輪到你時會再通知" if chain_reset
                                     else f"你已簽核的報價單內容被 {who} 修改（{blk}），請重新複查確認")})
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


# ── S3b：reconcile_txn（外殼；呼叫點在漏斗與 5 條直接寫入）────────────────────────────────────

NOTICE_LINK = "approval-queue.html"
_MERGE_TYPES = ("approval_reconfirm", "approval_reconfirm_info", "approval_reconfirm_suspended")


def audit_in_txn(conn, action: str, quote_no: str, detail: dict, user: dict = None, now: str = None) -> None:
    """公開別名（S4 的 review-edit 與存檔同交易寫稽核用）。"""
    _audit_in_txn(conn, action, quote_no, detail, user, now)


def _audit_in_txn(conn, action: str, quote_no: str, detail: dict, user: dict = None, now: str = None) -> None:
    """同一連線、同一交易寫一列稽核（`audit_log`）；不 commit。操作者沒給 ⇒ system。"""
    from helpers.audit import _derive_fields
    now = now or datetime.now().isoformat()
    d = _derive_fields(action, "quotation", quote_no, quote_no, detail)
    u = user or {}
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (now, u.get("id"), u.get("username", "system"), u.get("display_name") or u.get("username", "system"),
         action, "quotation", quote_no, quote_no, json.dumps(detail, ensure_ascii=False), d["module"], d["case_no"], d["ref_no"]))


def _superadmins(conn) -> list:
    return [r["username"] for r in conn.execute("SELECT username FROM users WHERE role='superadmin' AND active=1")]


def _write_notices(conn, quote_no: str, notices: list) -> int:
    """把 `reconcile_in_memory` 回的通知清單寫進 `notifications`（**同一連線、同一交易**）；回寫入的收件人數。
    `to` 的元素：帳號字串，或 `{"role": "superadmin"}`（展開成所有啟用中的超管）。同一收件人在同一份清單裡只寫一次（以先出現的為準）。
    同 `(type, ref_id, username)` 已有未讀列 ⇒ 合併成那一列（連改很多次，簽核人只看到一則）。"""
    from helpers.audit import _notify_in_txn
    n, seen = 0, set()
    for nt in notices or []:
        names = []
        for t in nt.get("to") or []:
            if isinstance(t, str):
                names.append(t)
            elif isinstance(t, dict) and t.get("role") == "superadmin":
                names.extend(_superadmins(conn))
        for u in names:
            if not u or (nt.get("type"), u) in seen:
                continue
            seen.add((nt.get("type"), u))
            _notify_in_txn(conn, u, nt["type"], quote_no, quote_no, nt.get("text") or "", NOTICE_LINK, merge_unread=nt["type"] in _MERGE_TYPES)
            n += 1
    return n


SHADOW_STATS_ROW_CAP = 20000       # 影子統計最多讀幾列稽核（一週的量遠低於此；超過 ⇒ truncated=True，讓讀的人知道數字是下限）


def shadow_stats(conn, since: str, until: str = None) -> dict:
    """影子模式（`reconfirm_mode=shadow`）統計（K2，**唯讀**）：窗內 `quotation.reconfirm_shadow` 稽核列＝「若開旗標本會作廢」的內容變動事件。
    回 `{window, events, wouldInvalidateEvents, quotes, byBlock, bySource, byUser, byDay, dealTagShare, truncated}`：
    - `events`：影子事件數（每次指紋變動一筆；基準前進 ⇒ 同一指紋不重複）；`wouldInvalidateEvents`：其中真的有人會被作廢（有已簽層過期）的事件數。
    - `byBlock`／`bySource`／`byUser`：依 `wouldInvalidate` 非空的事件分布（沒人會被作廢的變動不算打斷），皆 `[{key,count}]` 由多到少。
    - `dealTagShare`：會作廢的事件中，區塊含 `dealTag` 者的占比（0~1；規格要用它決定 dealTag 是否改列排除）。
    只讀 `audit_log`（走 action 索引＋at 範圍），不碰 `quotations`；不寫任何東西。"""
    sql = "SELECT at, username, target_id, detail FROM audit_log WHERE action='quotation.reconfirm_shadow' AND at>=?"
    params = [since]
    if until:
        sql += " AND at<?"
        params.append(until)
    rows = conn.execute(sql + " ORDER BY id LIMIT ?", params + [SHADOW_STATS_ROW_CAP + 1]).fetchall()
    truncated = len(rows) > SHADOW_STATS_ROW_CAP
    rows = rows[:SHADOW_STATS_ROW_CAP]
    by_block, by_source, by_user, by_day, quotes = {}, {}, {}, {}, set()
    would = deal = 0
    for r in rows:
        try:
            d = json.loads(r["detail"] or "{}") or {}
        except (TypeError, ValueError):
            d = {}
        quotes.add(r["target_id"])
        if not d.get("wouldInvalidate"):
            continue
        would += 1
        blocks = [x for x in (d.get("blocks") or []) if isinstance(x, str)]
        for blk in blocks:
            by_block[blk] = by_block.get(blk, 0) + 1
        if any(x == "dealTag" for x in blocks):
            deal += 1
        src = str(d.get("source") or "")
        by_source[src] = by_source.get(src, 0) + 1
        who = r["username"] or ""
        by_user[who] = by_user.get(who, 0) + 1
        day = (r["at"] or "")[:10]
        by_day[day] = by_day.get(day, 0) + 1

    def _top(m):
        return [{"key": k, "count": v} for k, v in sorted(m.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"window": {"from": since, "to": until}, "events": len(rows), "wouldInvalidateEvents": would, "quotes": len(quotes),
            "byBlock": _top(by_block), "bySource": _top(by_source), "byUser": _top(by_user),
            "byDay": [{"key": k, "count": by_day[k]} for k in sorted(by_day)],
            "dealTagShare": round(deal / would, 4) if would else 0.0, "truncated": truncated}


def _last_log(appr: dict, key: str, now: str):
    lst = appr.get(key)
    if isinstance(lst, list) and lst and isinstance(lst[-1], dict) and lst[-1].get("at") == now:
        return lst[-1]
    return None


def reconcile_txn(conn, quote_no: str, data: dict, *, source: str, actor: dict = None, status: str = None, now: str = None, chain_reset: bool = False) -> bool:
    """**外殼**（S3b）：在呼叫端**寫入 `quotations.data_json` 之前**，對已讀進記憶體、改完內容的 `data` 做一次對帳。
    讀設定 ⇒ （必要時讀資料庫真實 status）⇒ `reconcile_in_memory`（只改 `data["approval"]`）⇒ 同交易寫通知與稽核。回傳 `data["approval"]` 有沒有被改
    （True＝呼叫端寫回的 `data` 帶著新的簽核狀態，**必須用這份 `data` 寫**，不可以再用舊的）。

    - `off`（預設）⇒ **立刻回 False，零查詢**（模式讀取走 `_mode_cached`，快取命中不碰資料庫）。
    - `status`：呼叫端知道「這次寫完之後這張單的狀態」就傳（漏斗在改狀態時傳新狀態），不知道就不傳 ⇒ 這裡多讀一次 `SELECT status`（只在 mode≠off）。
      `data_json["status"]` 是排除鍵會過期，**不可當依據**。單不存在 ⇒ 不動。
    - 通知與稽核都在**呼叫端的連線與交易**裡，交易回滾 ⇒ 一起消失；不 commit、不另開連線（W3 凍結）。
    - `actor`：做這次修改的人（`{id, username, display_name}`）；沒有（系統路徑）⇒ 文字寫「系統（來源）」，且沒有人被當成「自己改的」而略過通知。
    - 讀路徑（佇列、GET）**不要**呼叫這裡——只用 `effective_approval` 純推導。"""
    mode = _mode_cached(conn)
    if mode == "off":
        return False
    if status is None:
        row = conn.execute("SELECT status FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        status = row["status"] if row else None
    now = now or datetime.now().isoformat()
    reasons = current_reasons_or_none(data) if (source == SOURCE_REVIEW_EDIT and mode == "on") else None    # J1：只有複查編輯會重簽條目，才需要基準
    changed, notices = reconcile_in_memory(data, now, actor, source, status=status, enabled=(mode == "on"), reason_entries=reasons, chain_reset=chain_reset)
    if not changed:
        return False
    appr = data.get("approval") or {}
    sh = _last_log(appr, "shadowLog", now)
    ch = _last_log(appr, "changeLog", now)
    if sh is not None:                                                      # 影子：同一指紋只會有一筆（基準已前進）⇒ 稽核天然去重
        _audit_in_txn(conn, "quotation.reconfirm_shadow", quote_no,
                      {"fp": sh.get("fp"), "blocks": sh.get("blocks"), "wouldInvalidate": sh.get("wouldInvalidate"), "source": source}, actor, now)
    if ch is not None:
        act = "quotation.reconfirm_suspended" if ch.get("suspended") else "quotation.reconfirm"
        _audit_in_txn(conn, act, quote_no, {"rev": ch.get("rev"), "blocks": ch.get("blocks"), "invalidated": ch.get("invalidated"),
                                            "resigned": ch.get("resigned"), "source": source, "rounds": appr.get("reviewRounds"),
                                            **({"chainReset": True} if ch.get("chainReset") else {})}, actor, now)
    _write_notices(conn, quote_no, notices)
    return True
