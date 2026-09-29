# -*- coding: utf-8 -*-
"""標案清單快取（2026-09-29 使用者：「標案雷達載入慢七秒，先在伺服器端算好，不要等使用者點進模組才算」）。

[單位] tender_radar:listing   [層] L2（只 import db）   [穩定度] 內部
[不變式] ①回傳的清單與「當下重算一次」逐字相同（順序、標籤、標註、`matchedEmptyReason`）
         ②任何寫入 tenders／tender_watches 的地方都呼叫 `bump()`；漏掉時由資料庫簽章與 TTL 兜底，不會永遠過期
         ③快取只存在記憶體，重啟即空；不寫檔、不進備份

## 為什麼要快取
`GET /api/tender-radar/tenders` 每次都 SELECT 全表，再逐筆 × 逐條件比對（O(N×W)）；標籤即時算是刻意設計
（見 api.list_tenders docstring：顯示不掛在 `tender_hits` 通知帳本上），所以**不改成讀帳本**，只把「算」的結果留著。

## 失效（三道）
1. `bump()`：抓取寫入、補詳情、條件新增／修改／刪除、標註／取消標註之後呼叫；同時排一個背景預算（有開才排）。
2. 資料庫簽章：筆數、最大 id、最新抓取時間、標註數與最新標註時間、條件的筆數／最大 id／最新更新時間／啟用數——
   別條路徑（測試直接寫 SQL、人手改庫）動到這些也會失效。
3. TTL（`TTL_SECONDS`）：兜住簽章看不到的（例如使用者顯示名稱改了、就地改標案欄位）。
⚠️ 已知代價：就地改 tenders 的非簽章欄位而沒呼叫 `bump()`，最久 `TTL_SECONDS` 才看得到。
"""
import logging
import threading
import time

from db import get_db
from modules.tender_radar import match as tender_match

logger = logging.getLogger(__name__)

TTL_SECONDS = 300
_WARM_DELAY_SECONDS = 1.0
_STARTUP_WARM_DELAY_SECONDS = 20

_LOCK = threading.Lock()        # 建構用（可能持有數秒）
_META = threading.Lock()        # 只護 gen／pending，短暫持有：寫入端 bump() 不可以被建構卡住
_STATE = {"gen": 0, "key": None, "built_at": 0.0, "data": None}
_WARM = {"enabled": False, "pending": False}


def bump():
    """資料變了：作廢快取，並（若已啟用）在背景預先重算。可從任何執行緒呼叫，不丟例外。"""
    with _META:
        _STATE["gen"] += 1
    _schedule_warm(_WARM_DELAY_SECONDS)


def enable_warm():
    """啟動時呼叫一次（排程器）：開啟背景預算，並在啟動後稍晚先算第一份，使用者第一次點進來就是熱的。"""
    _WARM["enabled"] = True
    _schedule_warm(_STARTUP_WARM_DELAY_SECONDS)


def _schedule_warm(delay):
    if not _WARM["enabled"]:
        return
    with _META:
        if _WARM["pending"]:
            return
        _WARM["pending"] = True
    t = threading.Timer(delay, _warm_once)   # ⚠️ 走模組屬性，測試才 patch 得到
    t.daemon = True
    t.start()


def _warm_once():
    with _META:
        _WARM["pending"] = False
    try:
        conn = get_db()
        try:
            get_listing(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 —— 預算失敗只影響速度，使用者請求仍會即時算
        logger.exception("tender listing warm failed")


def _signature(conn):
    t = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(fetched_at),''), "
        "COUNT(marked_at), COALESCE(MAX(marked_at),''), COALESCE(SUM(marked_by),0) FROM tenders").fetchone()
    w = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(updated_at),''), "
        "COALESCE(SUM(enabled),0) FROM tender_watches").fetchone()
    db_file = ""
    for r in conn.execute("PRAGMA database_list").fetchall():
        if r[1] == "main":
            db_file = r[2]
    return (db_file, tuple(t), tuple(w))


def _clean_url(raw):
    text = str(raw or "").strip()
    return text or None


def _build(conn):
    import json

    rows = conn.execute("""
        SELECT * FROM tenders
        ORDER BY (deadline IS NULL), deadline ASC, id DESC
    """).fetchall()
    watches = []
    for r in conn.execute("SELECT * FROM tender_watches WHERE enabled=1").fetchall():
        w = dict(r)
        # ⚠️ keywords／excludes 在庫裡是 JSON 字串；不解析會被當成「一個關鍵字」而永遠比不到
        for key in ("keywords", "excludes"):
            try:
                w[key] = json.loads(w[key] or "[]")
            except (ValueError, TypeError):
                w[key] = []
        watches.append(w)

    marker_ids = sorted({r["marked_by"] for r in rows if r["marked_by"] is not None})
    marker_names = {}
    if marker_ids:
        qs = ",".join("?" * len(marker_ids))
        for u in conn.execute(
                f"SELECT id, display_name, username FROM users WHERE id IN ({qs})",
                marker_ids).fetchall():
            marker_names[u["id"]] = (u["display_name"] or "").strip() or u["username"]

    labels = {}
    for t in rows:
        tender = {"name": t["name"], "org": t["org"], "budget": t["budget"]}
        hit = [{"id": w["id"], "name": w["name"]}
               for w in watches if tender_match.matches(tender, w)]
        if hit:
            labels[t["id"]] = hit

    items = [{
        "id": r["id"], "caseNo": r["case_no"], "org": r["org"], "name": r["name"],
        "publishedAt": r["published_at"], "deadline": r["deadline"],
        "budget": r["budget"], "url": _clean_url(r["url"]),
        "location": r["location"], "procurementType": r["procurement_type"],
        "tenderMethod": r["tender_method"],
        "matchedWatches": labels.get(r["id"], []),
        "marked": r["marked_at"] is not None,
        "markedAt": r["marked_at"],
        "markedBy": r["marked_by"],
        "markedByName": marker_names.get(r["marked_by"], ""),
    } for r in rows]

    # 兩次穩定排序：命中的整段在前，再把標註的整批提前（規則與理由見 api.list_tenders）
    items.sort(key=lambda it: not it["matchedWatches"])
    items.sort(key=lambda it: not it["marked"])

    if not watches:
        reason = "no_watches"
    elif not labels:
        reason = "no_hits"
    else:
        reason = None

    # q 搜尋用的正規化字串一次算好（異體字表在 tender_match，後端才有同一套規則）
    hay = [tender_match.normalize(
        " ".join(str(it.get(k) or "") for k in ("name", "org", "caseNo"))) for it in items]
    return {"items": items, "hay": hay, "reason": reason}


def get_listing(conn):
    """回 `{items, hay, reason}`；命中快取就不碰 tenders 全表。**回傳的結構唯讀，呼叫端不可改。**"""
    now = time.monotonic()
    gen = _STATE["gen"]
    key = (gen, _signature(conn))
    with _LOCK:
        data = _STATE["data"]
        if data is not None and _STATE["key"] == key and now - _STATE["built_at"] < TTL_SECONDS:
            return data
    with _LOCK:   # 單一建構者：同時進來的請求排隊後直接吃新的
        data = _STATE["data"]
        if data is not None and _STATE["key"] == key and time.monotonic() - _STATE["built_at"] < TTL_SECONDS:
            return data
        data = _build(conn)
        _STATE.update(key=key, built_at=time.monotonic(), data=data)
        return data


def reset():
    """測試用：清空。"""
    with _META:
        _STATE["gen"] += 1
    with _LOCK:
        _STATE.update(key=None, built_at=0.0, data=None)
