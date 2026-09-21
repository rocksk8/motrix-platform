"""標案雷達（2026-09-21，細線 6 第 1～3 步）。

搜尋條件的 CRUD、抓回來的標案清單、以及**雷達健康狀態**。

⚠️ **模組 key 是 `tender_radar`，不沿用 `dev_crm`**（A 第二十七次裁決）。
細線 1 第 4 步已把它定為第 9 個套餐 `tender`——沿用別人的 key 會讓
**套餐名與模組 key 對不上，而那會長出一張對照表，對照表最會腐爛**。
⚠️ 新增 key 要**三處一起補**（`users.html` 目錄／`sidebar.js`／這裡），
少一處 `test_module_keys_consistency_2026_09_13.py` 就會紅。

⚠️ **本輪不做通知**（第 5 步）。`suspect_redesign` 只回旗標、只顯示在畫面上。
先確認抓回來的東西是對的，再談要不要寄信——
**一個會發假警報的雷達，比沒有雷達更快被關掉。**
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
# ⚠️ 走模組不是 `from ... import run_scan`：那會複製走副本，
# 測試換不掉，而「換不掉」的症狀是計數器永遠 0、那一題永遠綠。
from helpers import tender_source

router = APIRouter()


def _require_radar(authorization: str) -> dict:
    """標案雷達的模組權限。

    ⚠️ **用自己的 key `tender_radar`，不沿用 `dev_crm`**（A 第二十七次裁決）。
    細線 1 第 4 步已把標案雷達定為第 9 個套餐 `tender`；沿用 `dev_crm` 的話
    **套餐名與模組 key 對不上，而那會長出一張對照表——對照表最會腐爛**。
    現在補是三行，等套餐上線再改是一次資料遷移。
    """
    user = _require_user(authorization)
    require_any_module(user, ("tender_radar",), "標案雷達")
    return user


def _json_list(value, field):
    """關鍵字／排除詞：收 list 或逗號分隔字串，一律存成 JSON 陣列。"""
    if value is None:
        return "[]"
    if isinstance(value, str):
        value = [v for v in value.replace("，", ",").split(",")]
    if not isinstance(value, list):
        raise HTTPException(422, f"{field} 必須是陣列或逗號分隔字串")
    return json.dumps([str(v).strip() for v in value if str(v).strip()],
                      ensure_ascii=False)


def _opt_int(value, field):
    """金額上下限：空值 → `None`（不篩）。**`None` 不是 `0`。**

    寫成 `int(value or 0)` 的話，「沒填上限」會變成「上限 0 元」——
    一筆都不會中，而且安靜。
    """
    if value is None or value == "":
        return None
    try:
        n = int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        raise HTTPException(422, f"{field} 必須是整數")
    if n < 0:
        raise HTTPException(422, f"{field} 不可為負數")
    return n


def _watch_out(row):
    d = dict(row)
    for key in ("keywords", "excludes"):
        try:
            d[key] = json.loads(d[key] or "[]")
        except (ValueError, TypeError):
            d[key] = []
    return {
        "id": d["id"], "name": d["name"], "keywords": d["keywords"],
        "excludes": d["excludes"], "org": d["org"],
        "budgetMin": d["budget_min"], "budgetMax": d["budget_max"],
        "enabled": bool(d["enabled"]),
        "createdAt": d.get("created_at", ""), "updatedAt": d.get("updated_at", ""),
    }


# ── 搜尋條件 ─────────────────────────────────────────────────────────────────

@router.get("/api/tender-radar/watches")
def list_watches(authorization: str = Header(None)):
    _require_radar(authorization)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM tender_watches ORDER BY enabled DESC, id DESC").fetchall()
    finally:
        conn.close()
    return {"items": [_watch_out(r) for r in rows]}


@router.post("/api/tender-radar/watches", status_code=201)
def create_watch(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_radar(authorization)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "請填寫條件名稱")
    keywords = _json_list(body.get("keywords"), "keywords")
    if keywords == "[]":
        raise HTTPException(422, "至少要有一個關鍵字，否則這個條件會命中所有標案")
    org = (body.get("org") or "").strip() or None   # 空 = 不篩機關
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO tender_watches (name, keywords, excludes, org, "
            "budget_min, budget_max, enabled, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, keywords, _json_list(body.get("excludes"), "excludes"), org,
             _opt_int(body.get("budgetMin"), "budgetMin"),
             _opt_int(body.get("budgetMax"), "budgetMax"),
             1 if body.get("enabled", True) else 0, now, now),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "tender_watch.create", "tender_watch",
           str(new_id), name)
    return {"id": new_id, "name": name}


@router.put("/api/tender-radar/watches/{watch_id}")
def update_watch(watch_id: int, body: dict = Body(...),
                 authorization: str = Header(None)):
    _require_radar(authorization)
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM tender_watches WHERE id=?",
                            (watch_id,)).fetchone():
            raise HTTPException(404, "找不到這個搜尋條件")
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "請填寫條件名稱")
        conn.execute(
            "UPDATE tender_watches SET name=?, keywords=?, excludes=?, org=?, "
            "budget_min=?, budget_max=?, enabled=?, updated_at=? WHERE id=?",
            (name, _json_list(body.get("keywords"), "keywords"),
             _json_list(body.get("excludes"), "excludes"),
             (body.get("org") or "").strip() or None,
             _opt_int(body.get("budgetMin"), "budgetMin"),
             _opt_int(body.get("budgetMax"), "budgetMax"),
             1 if body.get("enabled", True) else 0, now, watch_id),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "tender_watch.update", "tender_watch",
           str(watch_id), name)
    return {"ok": True}


@router.delete("/api/tender-radar/watches/{watch_id}", status_code=204)
def delete_watch(watch_id: int, authorization: str = Header(None)):
    _require_radar(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM tender_watches WHERE id=?",
                           (watch_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到這個搜尋條件")
        # 命中紀錄一起刪：它們只在這個條件的脈絡下有意義。
        conn.execute("DELETE FROM tender_hits WHERE watch_id=?", (watch_id,))
        conn.execute("DELETE FROM tender_watches WHERE id=?", (watch_id,))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "tender_watch.delete", "tender_watch",
           str(watch_id), row["name"])


# ── 標案與命中 ───────────────────────────────────────────────────────────────

@router.get("/api/tender-radar/tenders")
def list_tenders(authorization: str = Header(None)):
    """命中的標案，最近截止的排前面。**沒有截止日的排最後而不是最前面**——
    `NULL` 在 SQLite 的排序裡最小，不處理的話「沒寫截止日」會插到最急的位置。
    """
    _require_radar(authorization)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT t.*, w.id AS watch_id, w.name AS watch_name
            FROM tender_hits h
            JOIN tenders t        ON t.id = h.tender_id
            JOIN tender_watches w ON w.id = h.watch_id
            ORDER BY (t.deadline IS NULL), t.deadline ASC, t.id DESC
        """).fetchall()
    finally:
        conn.close()
    return {"items": [{
        "id": r["id"], "caseNo": r["case_no"], "org": r["org"], "name": r["name"],
        "publishedAt": r["published_at"], "deadline": r["deadline"],
        "budget": r["budget"], "url": r["url"],
        "watchId": r["watch_id"], "watchName": r["watch_name"],
    } for r in rows], "source": "資料來源：政府電子採購網"}


# ── 雷達健康狀態 ─────────────────────────────────────────────────────────────

@router.get("/api/tender-radar/status")
def radar_status(authorization: str = Header(None)):
    """雷達現在是什麼狀態。**`recognised` 的三個值不可以被合併成兩個。**

    `NULL`＝抓不到（網站掛了／逾時）／`0`＝認不得（對方改版）／`1`＝正常。
    前兩者的處置相反：掛掉只要等它好，改版要改解析器。
    """
    _require_radar(authorization)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT fetched_at, recognised, dropped, error "
            "FROM tender_fetch_log ORDER BY id DESC LIMIT 1").fetchone()
        counts = conn.execute(
            "SELECT COUNT(*) AS c FROM tenders").fetchone()
    finally:
        conn.close()

    last = dict(row) if row else None
    if last is None:
        health = "never_run"
    elif last["recognised"] is None:
        health = "unreachable"      # 抓不到
    elif not last["recognised"]:
        health = "unrecognised"     # 認不得
    else:
        health = "ok"

    return {
        "enabled": tender_source.TENDER_RADAR_ENABLED,
        "health": health,
        "lastFetchedAt": last["fetched_at"] if last else None,
        "lastRecognised": last["recognised"] if last else None,
        "lastDropped": last["dropped"] if last else None,
        "lastError": last["error"] if last else None,
        "suspectRedesign": bool(
            last and last["recognised"] and
            tender_source.suspect_redesign(counts["c"], last["dropped"])),
        "tenderCount": counts["c"],
        "source": "資料來源：政府電子採購網",
    }


@router.post("/api/tender-radar/scan")
def manual_scan(authorization: str = Header(None)):
    """手動跑一次掃描。

    ⚠️ **總開關關著時這裡也不會抓**（`run_scan` 自己判斷）——
    手動觸發不是繞過開關的後門。開關管的是「這台機器會不會對外連線」，
    而那個承諾不該因為有人按了按鈕就失效。
    """
    _require_radar(authorization)
    result = tender_source.run_scan()
    _audit(_tok(authorization), "tender_radar.scan", "tender_radar", "",
           json.dumps(result, ensure_ascii=False)[:200])
    return result
