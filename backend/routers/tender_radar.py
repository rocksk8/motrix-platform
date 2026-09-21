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
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers.settings import _get_setting, _set_setting
from helpers import _audit, _require_user, _tok, require_any_module
# ⚠️ 走模組不是 `from ... import run_scan`：那會複製走副本，
# 測試換不掉，而「換不掉」的症狀是計數器永遠 0、那一題永遠綠。
from helpers import tender_source
# ⚠️ 同理走模組：`geo.geocode` 要 patch 得到（M8b）。
from helpers import geo

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
    """部分更新：**body 裡沒有的欄位一律保留現值。**

    🔴 這裡原本是「整筆覆蓋」，而呼叫端（含畫面上的啟用／停用鈕）當它是部分更新。
    兩邊各自都講得通，合起來的結果是：只送 `enabled` 一個欄位 → `name` 變空 → 422，
    而前端的 `catch` 是空的 ⇒ **使用者按了停用，畫面沒有任何反應，也沒有任何錯誤訊息。**

    ⚠️ 我第一次修這裡時**只把 `enabled` 一個欄位改成保留現值**，另外六個原封不動。
    當時的註解還把那個失敗形狀完整描述了一遍——**我修掉了那個案例，沒有修那個形狀。**
    判準應該是「這個修法會不會讓第七個欄位不可能出事」，而不是「這個欄位好了沒」。

    ⚠️ 判準是 `key in body` **不是** `body.get(key)`：後者會把「明確送了空值」
    （清空機關、清空預算上限）當成「沒有送」，於是使用者清不掉任何欄位。
    """
    _require_radar(authorization)
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, keywords, excludes, org, budget_min, budget_max, "
            "enabled FROM tender_watches WHERE id=?", (watch_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到這個搜尋條件")

        name = row["name"]
        if "name" in body:
            name = (body["name"] or "").strip()
            if not name:
                raise HTTPException(422, "請填寫條件名稱")

        keywords = row["keywords"]
        if "keywords" in body:
            keywords = _json_list(body["keywords"], "keywords")
            # 與 `create_watch` 逐字相同的一道。
            # ⚠️ 它原本**只掛在 POST 上**，PUT 沒有 ⇒ 先建一個合法的、再 PUT 清空，
            # 就得到一個命中所有標案的條件。**驗證要掛在每一個寫入點上，
            # 不是掛在第一個寫入點上**——放寬 422 去讓按鈕能動會直接打開這個洞。
            if keywords == "[]":
                raise HTTPException(
                    422, "至少要有一個關鍵字，否則這個條件會命中所有標案")

        excludes = row["excludes"]
        if "excludes" in body:
            excludes = _json_list(body["excludes"], "excludes")

        org = row["org"]
        if "org" in body:
            org = (body["org"] or "").strip() or None   # 空 = 不篩機關

        budget_min = row["budget_min"]
        if "budgetMin" in body:
            budget_min = _opt_int(body["budgetMin"], "budgetMin")

        budget_max = row["budget_max"]
        if "budgetMax" in body:
            budget_max = _opt_int(body["budgetMax"], "budgetMax")

        # D22：收不到 `enabled` 就維持原值，不要預設 `True`。
        # `body.get("enabled", True)` 是**靜默的資料改寫**：使用者去改一個關鍵字，
        # 順手把一個停用的條件打開了，而沒有任何訊息。
        # 🔑 這是〈降級之後它還是會動〉的寫入版本：
        # **操作成功了，而它做的不只是你要的那件事。**
        enabled = row["enabled"]
        if "enabled" in body:
            enabled = 1 if body["enabled"] else 0

        conn.execute(
            "UPDATE tender_watches SET name=?, keywords=?, excludes=?, org=?, "
            "budget_min=?, budget_max=?, enabled=?, updated_at=? WHERE id=?",
            (name, keywords, excludes, org, budget_min, budget_max,
             enabled, now, watch_id),
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
        # 🔴 讀 `radar_on()` 不是讀 `TENDER_RADAR_ENABLED`。
        # 讀字面值的話：測試機上雷達實際是開的、畫面顯示「關」——
        # **使用者看到的狀態與實際相反，比完全不顯示還難發現。**
        "enabled": tender_source.radar_on(),
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


@router.get("/api/tender-radar/schedule")
def get_schedule(authorization: str = Header(None)):
    """每天幾點掃。**只有「幾點」可設定，「幾次」不行。**"""
    _require_radar(authorization)
    return {
        "scanHour": tender_source.scan_hour(),
        "defaultScanHour": tender_source.SCAN_HOUR,
        "dailyLimitNote": "每日一次為硬上限，不可調整",
    }


@router.put("/api/tender-radar/schedule")
def set_schedule(body: dict = Body(...), authorization: str = Header(None)):
    """設定每天幾點掃。

    ⚠️ **只收「幾點」，刻意不提供「一天幾次」。**
    每日一次是對政府網站的節制（SPEC §T.5 #4），**不是我們自己的偏好**，
    所以它不該出現在設定畫面上——**能調的東西遲早會被調**。
    📌 改了之後下一次 Timer 才會用新時間（排程是自我重排的）。
    """
    _require_radar(authorization)
    raw = body.get("scanHour")
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, "掃描時間必須是 0-23 的整數")
    if not 0 <= hour <= 23:
        raise HTTPException(422, "掃描時間必須是 0-23 的整數")
    _set_setting(tender_source.SCAN_HOUR_SETTING, hour)
    _audit(_tok(authorization), "tender_radar.schedule", "tender_radar", "",
           f"每日掃描時間改為 {hour}:00")
    return {"scanHour": hour}


@router.get("/api/tender-radar/map")
def tender_map(authorization: str = Header(None)):
    """地圖資料：辦公室、有地點的標案、以及**沒有地點的有幾筆**。

    ## ☠️ 這個畫面有三個成因會長成同一個樣子

    | 成因 | 畫面 | 處置 |
    |---|---|---|
    | 標案 `location` 是 NULL | 地圖上少幾個點 | 回報 `withoutLocation` |
    | 辦公室地址沒填 | 沒有距離 | 回報 `officeMissing` |
    | 沒有 Google 金鑰 | 「附近公司」是空的 | 回報 `googleMapsConfigured=False` |

    三個都是「一張乾淨、看起來完全正常的地圖」，**而處置完全相反**。
    ⇒ **每一個都必須有自己的訊號**，不能靠使用者看圖分辨——
    少幾個點跟「那些標案不存在」長得一樣，**而且沒有人會報修**。

    📌 距離是**直線**距離（`haversine_km`），不是行車距離。
    """
    _require_radar(authorization)
    profile = {**(_get_setting("company_profile", {}) or {})}
    office_address = (profile.get("address") or "").strip()
    api_key = (profile.get("google_maps_api_key") or "").strip()

    office = None
    if office_address:
        coord, _err = geo.geocode_cached(office_address)
        if coord:
            office = {"address": office_address, "lat": coord[0], "lon": coord[1]}

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT case_no, name, org, location, budget, deadline, url "
            "FROM tenders ORDER BY id DESC").fetchall()
    finally:
        conn.close()

    points, without_location = [], 0
    for r in rows:
        place = (r["location"] or "").strip()
        if not place:
            # 🔴 **數出來，不要丟掉。** 丟掉的話這幾筆會從畫面上消失，
            # 而「消失」跟「不存在」長得一模一樣。
            without_location += 1
            continue
        coord, _err = geo.geocode_cached(place)
        if not coord:
            # ⚠️ **一筆失敗不可以拖垮其他筆**（M5）。整張地圖空白的症狀
            # 又是「一張乾淨的空地圖」——第三個會長成那個樣子的成因。
            # 這一筆歸到「沒有地點」那一欄，使用者至少看得到它存在。
            without_location += 1
            continue
        points.append({
            "caseNo": r["case_no"], "name": r["name"], "org": r["org"],
            "location": place, "lat": coord[0], "lon": coord[1],
            "budget": r["budget"], "deadline": r["deadline"], "url": r["url"],
            "distanceKm": (round(geo.haversine_km((office["lat"], office["lon"]),
                                                  coord), 1)
                           if office else None),
        })

    return {
        "office": office,
        # 空地址要**說出來**。安靜的話使用者會以為功能壞了，而不是他還沒填——
        # 兩者的下一步完全不同：一個是報修，一個是去設定頁填一行字。
        "officeMissing": not office_address,
        "points": points,
        "withoutLocation": without_location,
        # ⚠️ 只回「有沒有設定」，**金鑰本身不在這個端點回傳**——
        # 這個端點的回應會被放進前端的除錯輸出，那不是放金鑰的地方。
        "googleMapsConfigured": bool(api_key),
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


# ── 測試模式專用：清掉今天的抓取紀錄 ────────────────────────────────────
#
# 🔴 **這個端點在正式出貨的機器上不是「被關掉」，是「沒有」。**
# 註冊發生在 import 時，所以沒有環境變數時 FastAPI 根本沒有這條路由 ⇒ **404**，
# 不是 403。403 會告訴外面的人「這裡有東西，只是你不能用」，而 404 什麼都不說。
#
# ⚠️ **閘門刻意綁環境變數，不是綁 `radar_on()`。**
# `radar_on()` 在「出貨開關被打開」時也是 True——那是一台正常營運的客戶機器，
# **它不該得到一個能重設每日上限的端點**。
# 「雷達開著」與「這台機器是測試機」是兩件事，壓成一件就會靜默出貨。
#
# ⚠️ 這裡清掉的是**抓取紀錄**，`_already_fetched_today` 本身一個字都沒動。
# 每日一次是對政府網站的承諾，它不會因為有人想多試一次而放寬——
# 放寬的是「這台測試機今天算不算抓過」，不是那條規則。
if os.getenv("MOTRIX_TENDER_RADAR") == "1":

    @router.post("/api/tender-radar/reset-today")
    def reset_today(authorization: str = Header(None)):
        """【測試模式】刪掉今天的 `tender_fetch_log`，讓 `_already_fetched_today` 回 False。"""
        _require_radar(authorization)
        conn = get_db()
        try:
            cur = conn.execute(
                "DELETE FROM tender_fetch_log WHERE substr(fetched_at,1,10)=?",
                (tender_source.today().isoformat(),),
            )
            removed = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        # 稽核一定要留：這是一個**放寬了節流**的動作，即使只在測試機上也要看得見。
        _audit(_tok(authorization), "tender_radar.reset_today", "tender_radar",
               "", f"清掉今天的抓取紀錄 {removed} 筆（測試模式）")
        return {"removed": removed}
