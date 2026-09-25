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
from helpers.settings import  _set_setting
from helpers import _audit, _require_user, _tok, require_any_module
# ⚠️ 走模組不是 `from ... import run_scan`：那會複製走副本，
# 測試換不掉，而「換不掉」的症狀是計數器永遠 0、那一題永遠綠。
from modules.tender_radar import match as tender_match
from modules.tender_radar import source as tender_source
# ⚠️ 同理走模組：`geo.geocode` 要 patch 得到（M8b）。

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

# ⚠️ **這個函式要放在 `@router.get` 之上。**
# 🔴 今天第二次踩：把新函式插在一支**被裝飾的**函式正上方，
# 那個 `@router.get` 就會落到新函式頭上 ⇒ **路由指向錯的人**。
# ☠️ 而症狀完全不像成因：這次是 `GET /tenders` 回 422 說
# 「query 參數 `raw` 是必填」——上一次（`_check_office_coord`）是
# PUT 回 200 而什麼都沒存。
# 🔑 `sub()` 的 assert 守的是「字串有沒有對上」，**守不到「插在哪裡」**。
def _clean_url(raw):
    """空網址回 `None`，**不是 `""`**。

    ☠️ 回 `""` 的話，前端最自然的寫法 `if (t.url !== undefined)`
    會把空字串當成「有網址」⇒ 渲染出一個 `href=""` 的死連結。
    🔑 **一個看起來可以點的東西點了沒反應，比一開始就不可點更糟** ——
    前者讓使用者以為是網路壞了，然後再點五次。
    📌 前後空白也要去掉：`" "` 不是空字串，而它一樣是死連結。
    """
    text = str(raw or "").strip()
    return text or None


@router.get("/api/tender-radar/tenders")
def list_tenders(watch: int = None, q: str = None,
                 authorization: str = Header(None)):
    """**所有**標案，命中的帶上標籤。最近截止的排前面。

    ## 使用者原話
    > 「200 筆改成都顯示，我可以打入關鍵字讓他分類，但分類剩的我一樣看得到」

    🔴 **關鍵字從「門檻」變成「標籤」。**
    原本這裡是 `JOIN tender_hits` => **沒有命中任何條件的標案根本不在清單裡**,
    而實測是：資料庫 200 筆、命中 0 筆 => **畫面上什麼都沒有**。
    ☠️ 而那跟「今天沒有新標案」長得一模一樣。

    ⚠️ **通知那一側不跟著改**（P4）：信裡仍然只有命中的。
    🔑 「顯示」與「通知」共用一個「命中」概念，**那正是它們會一起被改掉的原因**——
    而改錯的話使用者每天收到 200 筆，**那封信會讓他關掉整個功能**。

    沒有截止日的排最後而不是最前面——`NULL` 在 SQLite 的排序裡最小，
    不處理的話「沒寫截止日」會插到最急的位置。

    ## 🔴 `?q=` 手動搜尋**在後端**，不在前端
    前端一個 `Array.filter` 是最自然的做法，⚠️ **而異體字表在 Python 裡**
    （`tender_match.VARIANT_MAP`）。
    ☠️ 使用者手打「台中」查不到 `臺中市政府`，**而他剛剛才看到
    搜尋條件「台中」命中了那一筆** —— 🔑 **同一個字，兩個地方兩種結果。**
    ⇒ 手動搜尋必須套**同一套**正規化，所以它必須在後端。

    ⚠️ **手動搜尋不可以被存成一筆 watch**：
    使用者隨手打三個字就會在設定裡長出三個搜尋條件，
    **然後他每天會收到那三個條件的通知信。**

    ## 📌 `matchedEmptyReason`：三態
    | 值 | 意思 | 使用者要做的事 |
    |---|---|---|
    | `no_watches` | 一個搜尋條件都沒有 | 去**新增**條件 |
    | `no_hits` | 有條件但沒命中 | 去**改**條件 |
    | `null` | 有命中 | —— |

    ☠️ 前兩個在畫面上都是一塊空白，**而處置相反**。
    前端分辨不了：它得再打一支 `watches` API，那是兩次往返加一個競態
    （中間有人刪掉條件就會講錯話）⇒ 這個訊號必須跟清單同一個回應出來。
    """
    _require_radar(authorization)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM tenders
            ORDER BY (deadline IS NULL), deadline ASC, id DESC
        """).fetchall()
        watches = []
        for r in conn.execute(
                "SELECT * FROM tender_watches WHERE enabled=1").fetchall():
            w = dict(r)
            # ⚠️ `keywords`／`excludes` 在資料庫裡是 **JSON 字串**，不是 list。
            # 不解析的話 `_as_list` 會把整串 `'["監視"]'` 當成**一個關鍵字**
            # ⇒ 永遠比不到，**而畫面上看起來像「這個條件沒有命中任何標案」**。
            # 📌 形狀照 `tender_source._store()`（同一份資料的同一種解析）。
            for key in ("keywords", "excludes"):
                try:
                    w[key] = json.loads(w[key] or "[]")
                except (ValueError, TypeError):
                    w[key] = []
            watches.append(w)
    finally:
        conn.close()

    # 🔴 **標籤是即時算出來的，不是從 `tender_hits` 讀的。**
    #
    # 兩個理由，而第二個才是重點：
    # ① 新增一個條件就立刻看得到它的標籤（P5），不必等下一次抓取。
    # ② ☠️ **`tender_hits` 是「通知的帳本」**——每一列代表「這一筆要寄給使用者」。
    #    把顯示也掛在它上面的話，**「讓畫面看得到」就會變成「寄一封信」**：
    #    使用者新增一個條件 ⇒ 回溯比對寫進 200 列未通知的命中
    #    ⇒ 下一個寄信時段**一次寄出 200 筆**，而那封信會讓他關掉整個功能。
    # 🔑 P4 擔心的是「顯示與通知共用一個命中概念」——
    #    **而真正的解不是小心一點，是讓它們不再共用。**
    # ── 標註人的名字：一次查完，不要每一列各打一次 ──────────────
    # 🔴 `SELECT *` 已經把 `marked_at`／`marked_by` 帶回來了（v92 加的兩欄），
    # 缺的只有「那個 id 是誰」。
    # ⚠️ 不用 JOIN：`SELECT *` 加 JOIN 之後欄位名會相撞（`tenders.id` 與
    # `users.id`），而 sqlite3 的 Row 取名字時**後面的會蓋掉前面的** ——
    # ☠️ 那會讓 `r["id"]` 安靜地變成使用者的 id，而清單看起來完全正常。
    marker_ids = sorted({r["marked_by"] for r in rows
                         if r["marked_by"] is not None})
    marker_names = {}
    if marker_ids:
        conn2 = get_db()
        try:
            qs = ",".join("?" * len(marker_ids))
            for u in conn2.execute(
                    f"SELECT id, display_name, username FROM users"
                    f" WHERE id IN ({qs})", marker_ids).fetchall():
                marker_names[u["id"]] = (u["display_name"] or "").strip() \
                    or u["username"]
        finally:
            conn2.close()

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
        # ⚠️ 沒命中是**空陣列**不是缺這個鍵（P2）——
        # 缺鍵的話前端每個用到它的地方都要防 undefined，
        # 而漏防的那一處會是「畫面整塊消失」。
        "matchedWatches": labels.get(r["id"], []),
        # 🔑 判定一律 `is not None`，**不可以用真假值** ——
        # `marked_at` 是字串，空字串是假的而它代表「有標註」。
        # 📌 〈null 不等於 0〉：「沒有值」與「值是空的」是兩件事。
        "marked": r["marked_at"] is not None,
        "markedAt": r["marked_at"],
        "markedBy": r["marked_by"],
        # ⚠️ 讀不到對應的人時給「未知」，**不是把那一列藏起來**，
        # 也不是回 `null` 讓前端自己想辦法 ——
        # ☠️ 使用者被刪掉之後標註仍然要在，而畫面要說得出「不知道是誰」。
        "markedByName": marker_names.get(r["marked_by"], ""),
    } for r in rows]

    # 🔴 **命中的整段排在前面**，兩段各自再依截止日排。
    # ⚠️ **不是「整份排完再分段」**：資料庫已經照截止日排好了，
    # 而 Python 的 sort 是**穩定**的 ⇒ 只用「有沒有命中」當鍵，
    # 段內的截止日順序自然保留。
    # 📌 只看截止日的話，一筆沒命中但截止日很近的會被推到最前面，
    # 而使用者第一眼看到的就會是他不做的那一類。
    items.sort(key=lambda it: not it["matchedWatches"])

    # 🔴 **標註的整批提到最前面**（TD5／TD8）。
    #
    # > 使用者原話：「當這個標案被標誌，**則顯示於標案的最上方**」
    #
    # ⚠️ 這是**第二次** `sort`，不是把兩個鍵併成一個 tuple ——
    # 🔑 Python 的 sort 是**穩定**的 ⇒ 後排的鍵是主鍵，而前一次排好的順序
    #    在每一組內部原封不動保留下來。
    # ⇒ TD8 要的「整批提前，**內部照既有排序**（不另外排）」就是這個意思：
    #    標註那一批內部仍然是「命中的在前、再依截止日」，**沒有被重排過**。
    # ☠️ 若照**標註時間**排，先標晚的再標早的會得到相反的順序 ——
    #    而那兩種實作在「只標一筆」的測試下完全無法分辨。
    #
    # 🔴 而它擺在這裡（**篩選之前**）是刻意的：
    #    下面的 `watch` 與 `q` 是在這個順序上做**過濾**，過濾不會改變順序。
    # ☠️ 反過來把標註的「UNION 上去」的話，一筆**不符合搜尋條件**的標案
    #    會因為被標註而冒出來 —— 而使用者會以為搜尋壞了。
    items.sort(key=lambda it: not it["marked"])

    # ⚠️ **在 `q` 篩選之前算**：這個訊號問的是「搜尋條件有沒有命中東西」，
    # 不是「這次的搜尋結果有幾筆」。兩者混在一起的話，
    # 使用者打一個查無結果的字，畫面會告訴他「你的搜尋條件都沒命中」——
    # **而那是另一件事，會害他跑去改條件。**
    if not watches:
        matched_empty_reason = "no_watches"
    elif not labels:
        matched_empty_reason = "no_hits"
    else:
        matched_empty_reason = None

    if watch is not None:
        # 📌 篩選是**可選的**：不帶參數就是全部（P3）。
        items = [it for it in items
                 if any(w["id"] == watch for w in it["matchedWatches"])]

    # 🔴 `q` 是**篩選**不是查詢：清空就回到全部，什麼都不留下。
    # ⚠️ 空字串與沒給參數是同一件事（`?q=` 也是「不篩選」）——
    # 把空字串當成「查一個空關鍵字」的話會篩掉全部，而畫面上那是「沒有標案」。
    needle = tender_match.normalize((q or "").strip())
    if needle:
        items = [it for it in items
                 if needle in tender_match.normalize(
                     " ".join(str(it.get(k) or "")
                              for k in ("name", "org", "caseNo")))]

    return {"items": items, "source": "資料來源：政府電子採購網",
            "matchedEmptyReason": matched_empty_reason}


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
    """抓取與寄信的時段設定。**兩份獨立的設定。**

    ⚠️ 這裡**不再回「每日一次為硬上限，不可調整」**。
    那句話是 2026-09-21 稍早寫的，而使用者在畫面上讀到它之後裁示「我要可調整」。
    🔑 **寫在畫面上的字串沒有「待辦」狀態——它一上線就在對使用者說話**，
    在它被改掉之前都還在說。
    """
    _require_radar(authorization)
    return {
        "scanHours": ",".join(str(h) for h in tender_source.scan_hours()),
        "notifyHours": ",".join(str(h) for h in tender_source.notify_hours()),
        "defaultScanHours": ",".join(str(h) for h in tender_source.SCAN_HOURS),
        "defaultNotifyHours": ",".join(str(h) for h in tender_source.NOTIFY_HOURS),
        # 門檻只有這一份，前端從這裡取。兩邊各寫一份 ⇒ 前端不跳、後端擋，
        # 而使用者存不了又看不出為什麼。
        "highFrequencyThreshold": tender_source.HIGH_FREQUENCY_SLOT_THRESHOLD,
    }


def _hours_field(body, key, setting_key, label, confirmed, changes):
    """解析一份時段設定。不合法 → 422；超過門檻而未確認 → 409。

    🔑 **422 與 409 是兩件不同的事**：
    422 ＝「這個值不合法」（擋下來，使用者要改）
    409 ＝「這個值合法但頻繁」（**要確認，不是要拒絕**）——
    使用者明確裁示**不設硬上限**，所以按了確認就一定要存得進去。
    """
    if key not in body:
        return
    try:
        hours = tender_source.parse_hours_strict(body[key])
    except ValueError as exc:
        raise HTTPException(422, f"{label}：{exc}")
    threshold = tender_source.HIGH_FREQUENCY_SLOT_THRESHOLD
    if len(hours) > threshold and not confirmed:
        current = len(tender_source.scan_hours())
        # ⚠️ 警告要講出**代價**，不是只講數字。
        # 「你設了 18 個時段，確定嗎？」使用者只會學會一路按確定；
        # 要講「對誰、多少次、跟現在比」。
        raise HTTPException(409, (
            f"{label}設了 {len(hours)} 個時段，這會在每個工作日對政府採購網"
            f"發出 {len(hours)} 次請求（目前 {current} 次）。"
            f"超過 {threshold} 個時段需要確認。"))
    changes.append((setting_key, ",".join(str(h) for h in hours), label, hours))


@router.put("/api/tender-radar/schedule")
def set_schedule(body: dict = Body(...), authorization: str = Header(None)):
    """設定抓取與寄信的時段。**兩份可以分別設，也可以設成空。**

    🔴 **空字串是合法值**：抓取設空＝不抓，寄信設空＝不寄。
    「可調整」包含「調成不要」，而那是最容易被實作漏掉的值——**它看起來像「還沒設」**。

    ⚠️ **驗證與寫入分兩段**：兩份設定都通過之後才開始寫。
    一邊驗一邊寫的話，第二份不合法時**第一份已經生效了**，
    而使用者看到的是一個錯誤訊息 ⇒ 他會以為什麼都沒變。
    """
    _require_radar(authorization)
    confirmed = bool(body.get("confirmHighFrequency"))
    changes = []
    _hours_field(body, "scanHours", tender_source.SCAN_HOURS_SETTING,
                 "抓取時段", confirmed, changes)
    _hours_field(body, "notifyHours", tender_source.NOTIFY_HOURS_SETTING,
                 "寄信時段", confirmed, changes)
    if not changes:
        raise HTTPException(422, "沒有要變更的設定（scanHours／notifyHours）")
    for setting_key, text, _label, _hours in changes:
        _set_setting(setting_key, text)
    _audit(_tok(authorization), "tender_radar.schedule", "tender_radar", "",
           "；".join(f"{label}改為 {text or '（不執行）'}"
                     for _k, text, label, _h in changes))
    return {
        "scanHours": ",".join(str(h) for h in tender_source.scan_hours()),
        "notifyHours": ",".join(str(h) for h in tender_source.notify_hours()),
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


# ── 標註 ─────────────────────────────────────────────────────────────────────
#
# > 使用者 2026-09-22 凌晨：「增加一個標註的功能，
# > **當這個標案被標誌，則顯示於標案的最上方**」
# > 使用者裁示：**共用的** —— 一個人標，全部的人看得到。
#
# ⚠️ 權限走 `_require_radar`（與本檔其他九條同一個），**不另外發明一個** ——
# 🔑 另設一個權限的話，第一個想標的人會被擋住，**而他不知道要找誰開**。

def _mark_target(conn, case_no):
    """找出那一筆，找不到就 404。**用 `case_no` 不用 `id`。**

    🔑 `case_no` 是政府電子採購網那一側的識別碼 ⇒ 它在重新抓取之後仍然一樣，
    而 `id` 是我們這邊的流水號。
    ⚠️ 端點用 `case_no` 是規格定的，而它同時也是比較穩的那一個。
    """
    row = conn.execute(
        "SELECT id, case_no, name, marked_at, marked_by FROM tenders"
        " WHERE case_no=?", (case_no,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到這個標案")
    return row


@router.post("/api/tender-radar/tenders/{case_no}/mark")
def mark_tender(case_no: str, authorization: str = Header(None)):
    """標註一筆標案。記**誰標的**與**什麼時候標的**。

    ## 🔑 已經標註過的，**原封不動**

    ⚠️ 不是「最後一個按的人獲勝」：畫面上標註是一顆切換鈕，
    要重新標一次得先取消 ⇒ 會走到 `DELETE` 那一條。
    ☠️ 而覆寫的話，一次誤按（或一次連點）會把**原本是誰標的**換掉，
    🔑 而那個資訊沒有別的地方留著 —— 取消是清掉，不留歷史。
    ⇒ 重複 POST 是 no-op，回 200 而不是 409：呼叫端要的狀態已經達成了。
    """
    user = _require_radar(authorization)
    conn = get_db()
    try:
        row = _mark_target(conn, case_no)
        # 📌 判定用 `is None`，不是 `not row["marked_at"]` ——
        # 空字串是假的，而它代表「有標註但時間戳是空的」，不是「沒標註」。
        if row["marked_at"] is None:
            conn.execute(
                "UPDATE tenders SET marked_at=?, marked_by=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"),
                 user["id"], row["id"]))
            conn.commit()
            row = _mark_target(conn, case_no)
    finally:
        conn.close()
    _audit(_tok(authorization), "tender.mark", "tender", case_no, row["name"])
    return {"caseNo": case_no, "marked": True,
            "markedAt": row["marked_at"], "markedBy": row["marked_by"]}


@router.delete("/api/tender-radar/tenders/{case_no}/mark", status_code=204)
def unmark_tender(case_no: str, authorization: str = Header(None)):
    """取消標註。**兩欄都回 `NULL`。**

    ## ⚠️ 兩欄一起清，不可以只清一半

    ☠️ 「只清 `marked_at`、留著 `marked_by`」是最容易發生的半套 ——
    🔑 那會讓「誰標的」指向一個**已經不存在的標註**，
    而 `marked_at IS NOT NULL` 那個判定仍然會說它沒標註
    ⇒ **兩欄講的話不一樣了，而沒有任何東西會紅。**

    ## 🔑 **任何有這個模組的人都可以取消別人的標註**

    使用者裁示「共用的」⇒ 它是這一筆標案的屬性，不是誰的私有物。
    ☠️ 「只有標的人可以取消」是一個看起來很合理的錯誤實作 ——
    **那個人請假的那一天，那一筆就沒有人能動它。**
    📌 而畫面要看得到是誰標的，那是靠 `markedByName`，不是靠限制權限。
    """
    _require_radar(authorization)
    conn = get_db()
    try:
        row = _mark_target(conn, case_no)
        conn.execute(
            "UPDATE tenders SET marked_at=NULL, marked_by=NULL WHERE id=?",
            (row["id"],))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "tender.unmark", "tender", case_no,
           row["name"])
