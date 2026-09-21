"""地理查詢：地址 → 座標（OSM／Nominatim），以及兩點間的直線距離。

§3l 第 1 步。**免金鑰**——底圖與定位都走 OpenStreetMap，
Google Maps 是**可選的加值**（「附近公司」），沒有金鑰時那一塊不存在。

## ⚠️ 這個模組會對外連線，所以有四道護欄

`USER_AGENT`／`FETCH_TIMEOUT_SECONDS`／`GEOCODE_INTERVAL_SECONDS`／總開關。
Nominatim 的使用政策明文要求**可識別的 User-Agent** 與**每秒最多一次**。
🔑 而這不只是禮貌：**被對方封鎖時的症狀是「地圖上沒有點」**，
而那跟「標案沒有地點」「沒有 Google 金鑰」在畫面上是同一個樣子
——三個成因、一個畫面、三種相反的處置，所以每一個都必須有自己的訊號。
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# 🔴 **出貨預設關**（它會對外連線）。
# ⚠️ 形狀比照 `tender_source.radar_on()`：**字面值留著、環境變數放在讀的那一端**。
# 反過來寫（把 `os.getenv(...)` 放進 `GEO_ENABLED` 的初始值）會讓釘住出貨預設的
# 那道守門從「永遠綠，除非有人改原始碼」變成「**取決於周圍環境**」——
# 有人 `export MOTRIX_GEO=1` 之後跑全回歸就會紅，**而那不是缺陷**。
#
# 📌 **沒有環境變數 ＝ 關，那就是出貨預設，不是「預設值忘了設」。**
GEO_ENABLED = False


def geo_on() -> bool:
    """地理查詢現在開著沒。只有 `MOTRIX_GEO=1` 才開。

    ⚠️ 判準是 `== "1"` **不是真假值**：`"0"` 是非空字串，
    用真假值判的話「我明確設成 0」會把它**打開**，
    **而錯的方向是往「會真的連出去」的那一邊。**
    """
    return GEO_ENABLED or os.getenv("MOTRIX_GEO") == "1"


# ── 對外連線的護欄 ───────────────────────────────────────────────────────────
USER_AGENT = "MOTRIX-ERP/1.0 (tender map; contact your MOTRIX administrator)"
FETCH_TIMEOUT_SECONDS = 10
#: Nominatim 政策：每秒最多一次。取 1.1 留一點餘裕給時鐘誤差。
GEOCODE_INTERVAL_SECONDS = 1.1

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_last_call_at = 0.0


def _throttle():
    """距離上一次查詢不足 `GEOCODE_INTERVAL_SECONDS` 就等到夠。

    ⚠️ 走 `time.sleep` 這個模組屬性（不是 `from time import sleep`），
    測試才 patch 得掉——這個專案今天已經踩過八次同一件事。
    """
    global _last_call_at
    wait = GEOCODE_INTERVAL_SECONDS - (time.time() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.time()


def geocode(address: str):
    """地址 → `((lat, lon), None)`；失敗回 `(None, "原因")`。

    🔴 **總開關檢查在這個函式裡面，不在呼叫端。**
    理由與 `tender_source.run_scan()` 相同：開關管的是「**這台機器會不會對外連線**」，
    而那個承諾不該取決於是哪一個呼叫端。放在呼叫端的話，
    **下一個呼叫端很可能忘記檢查，而它會安靜地連出去。**

    📌 兩個回傳值**必有一個是 `None`**，而判別依據是**第一個**：
    `coord is None` 就是失敗。（`tender_source.fetch_detail` 曾經讓第二個值
    一值兩用，結果 docstring 與行為對不上——這裡不重複那件事。）
    """
    address = (address or "").strip()
    if not address:
        return None, "沒有地址"
    if not geo_on():
        # ⚠️ 這不是錯誤，是**刻意不做**。訊息要講得出「怎麼打開」，
        # 否則實測的人只會看到「查不到」，然後去懷疑地址寫錯了。
        return None, "地理查詢未啟用（需要 MOTRIX_GEO=1）"

    params = urllib.parse.urlencode({
        "q": address, "format": "json", "limit": 1, "countrycodes": "tw",
    })
    req = urllib.request.Request(
        f"{NOMINATIM_URL}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        _throttle()
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:                      # noqa: BLE001
        # 把例外的型別帶出來。只回「查詢失敗」的話，
        # 「被封鎖」「逾時」「對方改版」會長成同一句話，而處置完全不同。
        return None, f"{type(exc).__name__}: {exc}"

    if not rows:
        return None, "查無此地址"
    try:
        return (float(rows[0]["lat"]), float(rows[0]["lon"])), None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"回應格式不認得：{type(exc).__name__}"


#: 已查過的地址 → 結果。**只快取成功的**。
#:
#: ⚠️ 失敗不可以快取：`503`／逾時是暫時的，快取起來會讓一次抖動變成永久的空白，
#: 而症狀是「地圖上少了那幾個點」——又是那個沒有人會報修的樣子。
#:
#: 📌 這是**行程內**的快取，重開機就沒了。可以接受，因為鍵的數量很小：
#: `tenders.location` 只可能是 22 個縣市之一（`tender_source._TW_PLACES`），
#: 加上辦公室地址一筆 ⇒ 重啟後最多重查 23 次。
#: ⇒ **不值得為它開一張表**（而開表就要 migration，那是另一個層級的成本）。
_CACHE: dict = {}


def geocode_cached(address: str):
    """`geocode` 加一層快取。**同一個地址第二次不再發出請求。**

    🔴 **快取必須在 `geocode` 外面**（也就是這裡），不可以寫進 `geocode` 裡面。
    測試是 monkeypatch `geo.geocode` 來數呼叫次數的——快取若在被換掉的那個
    函式裡，**patch 之後快取就一起被換掉了，而那一題會安靜地失效。**

    📌 這裡呼叫的是**模組層的 `geocode`**（全域查找，呼叫當下才解析），
    所以 monkeypatch 打得到。
    """
    address = (address or "").strip()
    if not address:
        return None, "沒有地址"
    if address in _CACHE:
        return _CACHE[address]
    coord, err = geocode(address)
    if coord is not None:
        _CACHE[address] = (coord, None)
    return coord, err


# ── 圖磚是否被封鎖 ───────────────────────────────────────────────────────────
#
# ☠️ **失敗偽裝成了成功。** OSM 封鎖一個 IP 的方式是：
#     HTTP 200 OK ＋ `x-blocked` 標頭 ＋ 一張畫著「Access blocked」的 PNG
# ⇒ 瀏覽器**不會**觸發 error 事件（狀態碼是 200），
#   而圖磚是 `<img>` 載的 ⇒ **JavaScript 讀不到回應標頭**
# ⇒ **前端沒有任何辦法自己發現這件事。**
#
# 🔑 這比「地圖上沒有點」那一族嚴重一級：那些是「**沒有東西**」，
#    這個是「**有東西，而且是錯的**」——使用者看到的是一張看起來正常運作的地圖。
# ⇒ 所以要由**後端**去探一次（後端讀得到標頭），把結果當成第七個訊號送給畫面。
TILE_PROBE_URL = "https://tile.openstreetmap.org/5/26/13.png"
#: ⚠️ 探測是在**使用者等著看畫面**的請求裡做的 ⇒ 不可以讓他等。
TILE_PROBE_TIMEOUT_SECONDS = 3
#: 探測結果快取多久。⚠️ 每開一次畫面探一次的話，**我們自己就是在濫用對方的服務**
#: ——而那正是會被封鎖的原因。
TILE_PROBE_CACHE_SECONDS = 3600

#: `(判定, 時間戳)`；`None` ＝ 還沒探過。
_TILE_PROBE_CACHE = None


def tiles_blocked():
    """**這台伺服器**拿不拿得到圖磚。三態：`True` / `False` / `None`。

    ## 🔴 它涵蓋什麼、不涵蓋什麼（2026-09-22 收窄）

    這個探測用的是**伺服器的身分與網路路徑**。
    - ✅ 抓得到：**OSM 封了這台機器**（那時 MOTRIX 的 UA 也會被擋）
    - ❌ 抓不到：**OSM 封了使用者的瀏覽器** —— 而那兩件今天被證實是**不同的事**

    ☠️ 實測（同一個 IP、同一個時間）：
    ```
    瀏覽器UA ＋ Referer   →  33,914 bytes  ✅ 真圖磚
    瀏覽器UA 無 Referer   →   6,987 bytes  ❌ 封鎖圖
    MOTRIX UA 無 Referer  →  33,923 bytes  ✅ 真圖磚
    ```
    ⇒ 使用者被擋的那一次，**這個探測會回 `False`**。

    ## ⇒ 所以 `False` **不可以被渲染成任何話**
    `True` ⇒ 紅字警告；`None` ⇒ 很輕的一行「無法確認」；**`False` ⇒ 什麼都不顯示。**
    🔑 把 `False` 講成「圖磚可以用」，就是**一個宣稱，而它的證據只涵蓋宣稱範圍的一小塊**。

    ## ⚠️ 為什麼不改成瀏覽器的 UA 去探
    OSM 條款逐字禁止：**never impersonate another app or a browser**。
    📌 而那個方向我一度要求視窗 C 釘成測試，**理由聽起來很完整而它是錯的**——
    我手上有「瀏覽器UA 被擋、MOTRIX UA 沒被擋」兩格，
    **就斷定變因是 UA，而缺的第三格（MOTRIX UA 無 Referer）就在同一張表裡。**
    🔑 **兩個變數要四格。完整矩陣不是更嚴謹，是唯一能分辨變因的東西。**

    ## 三態的意義

    🔴 **`None` 是「不知道」，不可以退化成 `False`。**
    `False` 的意思是「**我探過了，可以用**」——那是一個**宣稱**。
    探測本身失敗（逾時、連不上、DNS 壞掉）時回 `False` 的話，
    **我們會對使用者宣稱一件我們沒有查證過的事**，
    而他會在看到滿版的封鎖圖時，**完全沒有線索**。
    🔑 〈訊號數要 ≥ 你敢斷定的成因數〉：探測失敗只給了我一個訊號
    （「探不到」），它推不出「可以用」也推不出「被擋了」。

    📌 快取是必要的（見 `TILE_PROBE_CACHE_SECONDS`），而它有一個副作用：
    **它會讓測試之間互相汙染** —— 一個為了正確性而存在的機制，
    變成了測試之間的隱形耦合。所以 C 的每一題都先把它清掉。
    """
    global _TILE_PROBE_CACHE
    now = time.time()
    if _TILE_PROBE_CACHE is not None:
        verdict, at = _TILE_PROBE_CACHE
        if now - at < TILE_PROBE_CACHE_SECONDS:
            return verdict

    req = urllib.request.Request(TILE_PROBE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TILE_PROBE_TIMEOUT_SECONDS) as resp:
            # ⚠️ 標頭名稱大小寫不敏感，但不是每一種回應物件都保證如此 ⇒ 兩邊都看。
            headers = getattr(resp, "headers", None)
            blocked = bool(headers and (headers.get("x-blocked")
                                        or headers.get("X-Blocked")))
    except Exception:  # noqa: BLE001
        # 探不到 ⇒ 不知道。**不快取「不知道」**：下一次請求要重新試一次，
        # 否則一次網路抖動會讓這個訊號整整一小時說「不知道」。
        return None

    _TILE_PROBE_CACHE = (blocked, now)
    return blocked


def haversine_km(a, b) -> float:
    """兩個 `(lat, lon)` 之間的**直線**距離，單位公里。

    ⚠️ **直線不是行車距離**，畫面上要寫出來（M11）——
    使用者看到「32 公里」會以為是車程，而山路可能是它的兩倍。
    純函式：不碰網路、不碰資料庫、不看時間。
    """
    lat1, lon1 = float(a[0]), float(a[1])
    lat2, lon2 = float(b[0]), float(b[1])
    r = 6371.0088                      # 地球平均半徑（IUGG 平均半徑，km）
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))
