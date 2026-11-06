# -*- coding: utf-8 -*-
"""報價單「內容指紋」（簽核二擇一 S1；規格 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md §H1、§I）。

[單位] case:content_fp    [層] L2（M01）

**不變式**：簽核只對它簽的那一版內容有效。「那一版」＝ `data_json` 去掉**排除清單**後的正規化雜湊。
**未知鍵一律算內容**（denylist；預設從嚴）。排除清單鎖在 `tests/test_content_fp_write_paths_s0_2026_11_06.py`。

S1 只提供：指紋／鍵雜湊、簽核條目蓋章（`signedFp`）、**純推導**的 `effective_approval`、`rebaseline_fingerprint`。
**不**改任何簽核流向：`reconcile`／`invalidate_signatures`／旗標彈窗是 S3 以後（I2：讀路徑只推導、不寫入）。

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
    return done


def effective_approval(data: dict, fp: str = None):
    """**純推導**（讀路徑用；不寫入、不改傳入的資料）：回傳 `(approval 複本, 有沒有條目被視為過期)`。

    已簽條目若有 `signedFp` 且 ≠ 目前指紋 ⇒ 視為 pending＋`reconfirm=True`（保留 `prevSignedFp`／`prevApprovedAt`）；
    `currentTier` 取第一個尚有未簽條目的層。沒有 `signedFp` 的條目不判過期（舊單相容）。
    S1 **沒有任何呼叫端**把它接到畫面／端點上（旗標預設關；接線在 S3）。"""
    appr = copy.deepcopy((data or {}).get("approval") or {})
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
