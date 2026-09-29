# -*- coding: utf-8 -*-
"""標案清單快取（2026-09-29 使用者：「標案雷達載入慢七秒，先在伺服器端先有運算好，不要等使用者點選進模組才做運算」；
「先下載分類好資訊，最後一次回傳給使用者」「只有定期更新標案的時候才計算」）。

[單位] tender_radar:listing   [層] L2（只 import db）   [穩定度] 內部
[不變式] ①請求端**只有「從來沒算過」才同步分類**；有舊結果就先回舊的（stale-while-revalidate）
         ②回傳的清單內容與「當下重算一次」逐字相同（順序、標籤、標註、`matchedEmptyReason`）
         ③重算只發生在：啟動預算一次、定期抓取寫入標案後（背景）、使用者改條件／標註時（寫入端自己算完才回）；**沒有 TTL、沒有定時重算**
         ④快取只在記憶體，重啟即空；不寫檔、不進備份；快取的是**序列化後的 JSON 位元組**

## 為什麼要快取
`GET /api/tender-radar/tenders` 原本每次都 SELECT 全表，再逐筆 × 逐條件比對（O(N×W)）；標籤即時算是刻意設計
（見 api.list_tenders docstring：顯示不掛在 `tender_hits` 通知帳本上），所以**不改成讀帳本**，只把「算」的結果留著。

## 什麼時候重算（`bump()`）
- 抓取寫入後（`source.run_scan`）：`bump(background=True)`——背景重算，這段時間請求先拿舊的。
- 使用者新增／修改／刪除條件、標註／取消標註：`bump()`——**寫入端同步重算完才回應**，使用者接著重讀就是新的
  （否則按完標註立刻重讀會看到舊的）；請求端不承擔。
- 讀時發現資料庫簽章（筆數、最大 id、最新抓取／標註／條件更新時間…）變了而**沒人 bump**（人手改庫、別條寫入路徑）：
  同步重算——這是「不明寫入者」，寧可慢一次也不回錯的。
- 背景預算未啟用（`enable_warm()` 沒呼叫：測試、單機腳本）：bump 後的第一個讀取同步重算。
⚠️ 已知取捨：沒有 TTL ⇒ 就地改 tenders 的非簽章欄位、使用者顯示名稱（標註人）改名，要等下一次抓取／條件／標註異動才反映。
"""
import json
import logging
import threading

from db import get_db
from modules.tender_radar import match as tender_match

logger = logging.getLogger(__name__)

_WARM_DELAY_SECONDS = 1.0
_STARTUP_WARM_DELAY_SECONDS = 20
_RESP_CACHE_MAX = 64

_LOCK = threading.Lock()        # 建構用（可能持有數秒）
_META = threading.Lock()        # 只護 gen／pending，短暫持有：寫入端 bump() 不可以被建構卡住
_STATE = {"gen": 0, "built_gen": -1, "sig": None, "data": None}
_WARM = {"enabled": False, "pending": False}


def bump(background=False):
    """資料變了：作廢快取。

    `background=True`（抓取寫入後）：背景重算，請求先拿舊的。
    預設（使用者改條件／標註）：**在呼叫的寫入端就地重算完**再回，使用者接著重讀就是新的。
    重算失敗只記錄（請求端會在讀時補算），不丟例外給寫入端。
    """
    with _META:
        _STATE["gen"] += 1
    if background:
        _schedule_warm(_WARM_DELAY_SECONDS)
        return
    try:
        conn = get_db()
        try:
            _rebuild(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("tender listing rebuild after write failed")


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
            _rebuild(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 —— 預算失敗只影響速度：請求端仍有舊結果，或「從來沒算過」時同步算
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


def _rebuild(conn):
    """重算一份並換上去。單一建構者；已經是最新的（gen 與簽章都對）就直接回現成的。"""
    with _LOCK:
        gen = _STATE["gen"]
        sig = _signature(conn)
        data = _STATE["data"]
        if data is not None and _STATE["built_gen"] == gen and _STATE["sig"] == sig:
            return data
        data = _build(conn)
        data["resp"] = {}
        _STATE.update(built_gen=gen, sig=sig, data=data)
        return data


def _snapshot(conn):
    """請求端取快取。**只有「從來沒算過」才同步分類**（另見模組 docstring 的兩個保守例外）。"""
    data = _STATE["data"]
    if data is None:
        return _rebuild(conn)
    if _STATE["built_gen"] != _STATE["gen"]:
        if _WARM["enabled"]:
            _schedule_warm(0)        # 已知有新資料、背景重算中（或漏排了就補排）：先回舊的
            return data
        return _rebuild(conn)        # 沒有背景預算可等
    if _signature(conn) == _STATE["sig"]:
        return data
    return _rebuild(conn)            # 不明寫入者（沒人 bump 而資料變了）：寧可慢一次


def respond(conn, watch=None, q=None):
    """`GET /tenders` 的回應本體（UTF-8 JSON 位元組）。同一份快取、同一組 (watch, q) 直接回現成的位元組。"""
    data = _snapshot(conn)
    needle = tender_match.normalize((q or "").strip())
    key = (watch, needle)
    body = data["resp"].get(key)
    if body is None:
        items, hay = data["items"], data["hay"]
        if watch is not None:
            keep = [(it, h) for it, h in zip(items, hay)
                    if any(w["id"] == watch for w in it["matchedWatches"])]
            items, hay = [p[0] for p in keep], [p[1] for p in keep]
        if needle:
            items = [it for it, h in zip(items, hay) if needle in h]
        # ⚠️ `matchedEmptyReason` 是「搜尋條件有沒有命中東西」，不受 watch／q 篩選影響
        body = json.dumps({"items": items, "source": "資料來源：政府電子採購網",
                           "matchedEmptyReason": data["reason"]},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data["resp"]) < _RESP_CACHE_MAX:
            data["resp"][key] = body
    return body


def reset():
    """測試用：清空。"""
    with _META:
        _STATE["gen"] += 1
    with _LOCK:
        _STATE.update(built_gen=-1, sig=None, data=None)
