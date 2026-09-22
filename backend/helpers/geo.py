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
import logging
import re
import threading
from datetime import date, datetime
import math
import os
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

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


def _unpack_geocode(got):
    """把 `geocode()` 的回傳拆成 `(coord, err, info)`，**兩種長度都收**。

    ## ⚠️ 為什麼要容忍兩種長度
    `geocode` 現在回三個（多了 `info`：Nominatim 的 `class`／`type`／
    `addresstype`），🔴 **而既有測試裡的假 `geocode` 回的是兩個**
    （`test_geo_2026_09_21.py` 的 `_geocode_spy`，M4／M5 都用它）。
    ☠️ 嚴格解包的話那些題會紅，而**紅的樣子會像是我們的 bug**，
    不是「假物件過期了」——而測試不是我能改的檔。

    📌 沒有 `info` ⇒ `None` ⇒ `classify_precision` 維持 `street`，
    **退回舊行為，不會往樂觀那一側跑。**
    """
    if not isinstance(got, (tuple, list)):
        return None, "geocode 回傳的形狀不認得", None
    coord = got[0] if len(got) > 0 else None
    err = got[1] if len(got) > 1 else None
    info = got[2] if len(got) > 2 else None
    return coord, err, info


def geocode(address: str):
    """地址 → `((lat, lon), None, info)`；失敗回 `(None, "原因", None)`。

    ⚠️ **第三個值 `info` 是 Nominatim 的分類**（`class`／`type`／`addresstype`），
    給 `classify_precision()` 用。這裡原本**把整筆回應丟掉只留座標**，
    ⇒ 命中建物與命中路段在回傳上沒有任何差別，
    而 `_locate_nominatim` 只好一律回 `street`（R9 的根源）。
    📌 呼叫端請用 `_unpack_geocode()` 拆，不要直接解包兩個。

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
        return None, "沒有地址", None
    if not geo_on():
        # ⚠️ 這不是錯誤，是**刻意不做**。訊息要講得出「怎麼打開」，
        # 否則實測的人只會看到「查不到」，然後去懷疑地址寫錯了。
        return None, "地理查詢未啟用（需要 MOTRIX_GEO=1）", None

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
        return None, f"{type(exc).__name__}: {exc}", None

    if not rows:
        return None, "查無此地址", None
    try:
        row = rows[0]
        return (float(row["lat"]), float(row["lon"])), None, row
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"回應格式不認得：{type(exc).__name__}", None


#: 已查過的地址 → 結果。**只快取成功的**。
#:
#: ⚠️ 失敗不可以快取：`503`／逾時是暫時的，快取起來會讓一次抖動變成永久的空白，
#: 而症狀是「地圖上少了那幾個點」——又是那個沒有人會報修的樣子。
#:
#: 📌 **這是第一層（行程內）。第二層是資料庫的 `geocode_cache` 表**（migration v89）。
#:
#: ⚠️ 這裡原本寫著「行程內就夠了，**不值得為它開一張表**」——
#: 🔴 **那句話現在是反的**，而它比一般的過期註解糟一級：
#: **過期的註解只是沒有用，主張相反方向的註解會讓下一個人照它做決定。**
#:
#: 推翻它的是一個當時沒算進去的量：正式機的 `autostart.bat` 是**無限迴圈**
#: （uvicorn 一退出就重拉）⇒ **查詢次數由「重啟幾次」決定，不是由使用者決定**，
#: 而 Google 那一階要收費。
#: 🔑 **原本的估算沒有錯，是它漏了一個變數** ——
#: 「27 個地址」乘上一個我沒去看的次數。
_CACHE: dict = {}


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
#: **「不知道」也要快取，但很短。**
#:
#: 🔴 原本探測失敗時完全不快取，理由是
#: 「一次網路抖動不該讓這個訊號整整一小時說『不知道』」——**而那只看了一端**：
#: ☠️ 如果對方持續不可達，**每一次開地圖都會重探、每一次都等 3 秒**。
#: 🔑 「為了一個附加訊號讓主要功能變慢」最糟的組合就是這個：**壞掉的時候最慢。**
#: ⇒ 60 秒同時滿足兩端：抖動 60 秒後就重試，而持續壞掉也不會每次都罰 3 秒。
#: ⚠️ **必須短於 `TILE_PROBE_CACHE_SECONDS`** ——
#: 兩個都設 3600 的話就退回「抖動被記一小時」，也就是這個修正的反面。
TILE_PROBE_UNKNOWN_CACHE_SECONDS = 60

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
        # 📌 **「不知道」有自己的（短）有效期。** 用同一個秒數的話，
        # 一次抖動會讓這個訊號整整一小時說「不知道」。
        ttl = (TILE_PROBE_UNKNOWN_CACHE_SECONDS if verdict is None
               else TILE_PROBE_CACHE_SECONDS)
        if now - at < ttl:
            return verdict

    req = urllib.request.Request(TILE_PROBE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TILE_PROBE_TIMEOUT_SECONDS) as resp:
            # ⚠️ 標頭名稱大小寫不敏感，但不是每一種回應物件都保證如此 ⇒ 兩邊都看。
            headers = getattr(resp, "headers", None)
            blocked = bool(headers and (headers.get("x-blocked")
                                        or headers.get("X-Blocked")))
    except Exception:  # noqa: BLE001
        # 探不到 ⇒ 不知道。**快取，但只快取 60 秒**（見常數的說明）。
        _TILE_PROBE_CACHE = (None, now)
        return None

    _TILE_PROBE_CACHE = (blocked, now)
    return blocked


# 地址 -> 座標：**三個來源都保留，有序退階**（3o）
#
# 起因是實測：**不是地址寫錯，是圖資認不得台灣的路名與門牌。**
#     台中市梧棲區八德路一段66號12樓之11   查不到
#     台中市梧棲區八德路一段66號           查不到
#     台中市梧棲區                        OK
# 而現行缺陷是「查不到就整個回報定位不到」，**連退一階都沒做**。
#
# **座標一定要帶著它的精度與來源一起回來。**
# 門牌精度與行政區精度**在畫面上都是一個圖釘**，而距離可能差好幾公里。
# 一個數字不帶它的可信度，就會被當成事實。

PRECISION_EXACT = "exact"          # 人工填的座標
PRECISION_ROOFTOP = "rooftop"      # 門牌
PRECISION_POI = "poi"              # 具名地物（機關、建物、場所）
PRECISION_STREET = "street"        # 路段
PRECISION_DISTRICT = "district"    # 縣市＋區（退階的結果）

#: Nominatim 回應裡代表「**一個具體地物**」的 `class`／`addresstype` 值。
#:
#: 🔴 **這是一張白名單，不是黑名單。** 判準是「我查到了什麼」，
#: 不是「我沒查到什麼」——黑名單漏掉一種，那一種就會被標成 `poi`，
#: 而**錯的方向是往樂觀那一側**：把很粗的座標標成細的
#: ⇒ 前端不警告 ⇒ **使用者按著一個差好幾公里的圖釘出門。**
#:
#: 📌 `place`（city／town／suburb）與 `boundary`（administrative）**刻意不在裡面**：
#: 它們是行政範圍的中心點，不是地物。
POI_CLASSES = frozenset({
    "office", "amenity", "building", "shop", "tourism", "leisure",
    "man_made", "healthcare", "historic", "craft", "emergency",
    "military", "aeroway", "railway", "club", "industrial",
})


def classify_precision(info) -> str:
    """Nominatim 的一筆回應 → 精度。**讀不出來就維持 `street`。**

    ## 🔴 判準是「我查到了什麼」，不是「我用什麼字串查的」
    A 的限制值得逐字留著：
    > **不要因為「是用名稱查的」就假設它是地物** ——
    > 那會讓 `poi` 變成「我用什麼字串查的」而不是「我查到了什麼」。

    ☠️ 用「是不是用名稱查的」來判斷的話，一個查到路口的機關名稱
    也會被標成建物級，而**畫面上完全看不出來**（只是那個圖釘差幾公里）。
    """
    if not isinstance(info, dict):
        return PRECISION_STREET
    cls = str(info.get("class") or "").strip().lower()
    addrtype = str(info.get("addresstype") or "").strip().lower()
    if cls in POI_CLASSES or addrtype in POI_CLASSES:
        return PRECISION_POI
    return PRECISION_STREET


#: 被截斷的名稱長什麼樣子。**只看明確標記，不看長度。**
#:
#: ⚠️ 「長度超過某個上限就當成被截斷」那一半已經拿掉（A 2026-09-22 裁定）：
#: 資料裡沒有那個上限（200 筆／158 個相異 `org`，以 `…` 結尾的 **0 個**，
#: 最長 19 字而長度分布連續、尖峰在 12 不在最大值）
#: ⇒ 那個常數只能用猜的，而**猜高了它永遠不觸發，猜低了它砍掉合法名稱**。
TRUNCATION_MARKERS = ("…", "...")


def looks_truncated(name) -> bool:
    """這個名稱看起來是被截斷的嗎。**回真正的 `True`／`False`。**

    ## 它防的不是「查不到」，是「查到錯的」
    🔑 **查不到會退階（安全），查到錯的不會。**
    「交通部民用航空局飛航」如果剛好命中某個不相關的地點，
    我們會得到一個**看起來合理而完全錯誤**的座標——
    而地圖上那個圖釘**看起來跟正確的一模一樣**。

    📌 資料庫裡現在**一個被截斷的名稱都沒有**，所以這道守門今天不會觸發。
    〈計數器要有落點〉：一道現在不會觸發的守門必須有一題證明它活著。
    """
    text = str(name or "").strip()
    if not text:
        return False
    return any(text.endswith(m) for m in TRUNCATION_MARKERS)

#: 精度由**精確到粗略**的有序序列。**這是單一來源。**
#:
#: 🔴 兩個地方各抄一份的話，改階梯時**會有一邊安靜地過期** ——
#: 那一邊的測試不會紅，**它只是在驗一個舊的階梯**。
#: 📌 之後要在 street 與 district 之間插入「機關所在地」那一級時，
#: 只改這一行。
PRECISION_ORDER = (PRECISION_EXACT, PRECISION_ROOFTOP, PRECISION_POI,
                   PRECISION_STREET, PRECISION_DISTRICT)

SOURCE_MANUAL = "manual"
SOURCE_GOOGLE = "google"
SOURCE_TGOS = "tgos"
SOURCE_NOMINATIM = "nominatim"
SOURCE_NOMINATIM_DISTRICT = "nominatim_district"

GOOGLE_KEY_SETTING = "google_maps_api_key"
TGOS_APPID_SETTING = "tgos_app_id"

#: 快取多久之後要重新查一次。
#: **TTL 不是為了省用量，是為了讓錯誤有機會自己修好。**
#: 地址與座標的對應會變（門牌改編、行政區調整、圖資被修正），
#: 而存進資料庫 = 一輩子不再查 => 那個錯誤會**永遠留著**，
#: 症狀是「地圖上那個點一直在錯的位置」——**沒有人會報修。**
#: 記憶體版沒有這個問題，是因為**它會自己忘記**；
#: 進資料庫之後那個保護就消失了，所以要自己把它加回來。
#: 具名常數，不可以埋進 SQL 字面值——埋進去就沒有人驗得到它變了。
GEOCODE_CACHE_TTL_DAYS = 180

_DISTRICT_RE = re.compile(r"^(.{2,3}[縣市])(.{1,4}?[區鄉鎮市])")


class GeoResult:
    """定位的結果。**具名結構，不是 tuple。**

    tuple 可以被 `coord, *_ = locate(...)` 拆掉，
    **而具名結構逼呼叫端講出它要的是哪一個。**
    （同一個理由用過一次：`tender_source.fetch_detail` 的第二個回傳值一值兩用。）
    """

    __slots__ = ("coord", "precision", "source", "error", "address")

    def __init__(self, coord=None, precision=None, source=None, error=None,
                 address=None):
        self.coord = coord
        self.precision = precision
        self.source = source
        self.error = error
        self.address = address

    def __repr__(self):
        return (f"GeoResult(coord={self.coord!r}, precision={self.precision!r}, "
                f"source={self.source!r}, error={self.error!r})")


def district_of(address):
    """從完整地址切出「縣市＋區」。切不出來回 `None`。

    切不出來時**必須回 `None`**，不可以回原地址——
    回原地址的話退階會拿同一串字再查一次，
    **而那是一個不會結束的迴圈的第一步**（A4c）。
    """
    m = _DISTRICT_RE.match((address or "").strip())
    return m.group(0) if m else None


# ==========================================================================
# 16 GB - Google 額度治理（真實計算器 + 自動降回免費）
# ==========================================================================
#
# 使用者 2026-09-22：「你做一個真實計算器，並讓超級管理員可以依據現在 google 的
# 免費額度去調整，當準備到達上限額度自動寄信並將附近客戶跟查找功能先回歸免費，
# 待月週期結束開放」
#
# 這一整節的預設是「關著」（GB13）：沒有金鑰、或沒填額度 => 行為跟現在完全一樣。
# 「關著」要能被證明，不是靠沒有人去踩到它。

#: 額度設定存在 `system_settings` 的這個鍵底下。
QUOTA_SETTING = "google_quota"

#: 計數的「來源」。
#:
#: 這個值是 **SKU 粒度**，不是 provider 粒度（A-2 2026-09-22）：
#: Google 2025-03-01 起廢掉了每月 $200 共用 credit，改成**每個 SKU 各自**
#: 一組免費月額度而且**不共用**。所以「google 用了幾次」這個問題沒有意義，
#: 有意義的是「Geocoding 這個 SKU 用了幾次」。
#: 17 NB 若之後接 Places，它是**另一個 SKU、另一組額度** =>
#: 要用另一個值（例如 `google:places-text-search`），不可以跟這個加在一起。
#: 值是 `"google:geocoding"`，**不是** `"google"`。
#: Places Text Search / Place Details 各自是另一個 SKU、另一組額度，
#: 要用另一個值，**不可以跟這個加在一起去對同一個門檻**——那會兩邊都算錯。
USAGE_SKU_GEOCODING = "google:geocoding"
USAGE_SKU_PLACES_TEXT = "google:places-text-search"
USAGE_SKU_PLACE_DETAILS = "google:place-details"

#: 預設值。`monthly_free_quota` **留空（None）= 不管制**，不是 0（GB7）。
#:
#: 免費額度**不寫死在程式裡**（GB5/GB6）：它是超級管理員填的欄位。
#: Google 改過不止一次，而寫死的數字不會報錯，只會算錯。
QUOTA_DEFAULTS = {
    # 一個 SKU 一格：{"google:geocoding": 10000, ...}。**留空的 SKU = 不管制。**
    # 預設**不填任何數字**：A-2 2026-09-22 明說「台灣適用哪一組數字我沒查」，
    # 而寫死一個沒查證的額度，錯的方向若偏晚就是真的花錢。
    "sku_quotas": {},
    # Geocoding 那一格的舊名。今天只有這一個 SKU 在用，保留它讓既有的
    # curl / 腳本還能用；`quota_for()` 會把兩者解析成同一件事。
    "monthly_free_quota": None,
    "price_per_1000": None,       # 只影響畫面上的金額換算，不影響管制
    "warn_pct": 80,
    "hard_pct": 100,
    "cycle_start_day": 1,
}


def quota_settings() -> dict:
    """超級管理員填的額度設定。"""
    from helpers.settings import _get_setting
    stored = _get_setting(QUOTA_SETTING, {}) or {}
    return {**QUOTA_DEFAULTS, **stored}


def quota_for(sku: str = None):
    """某個 SKU 的免費額度。**沒填回 `None`（= 不管制），不是 0**（GB7）。

    額度是 **per-SKU 而且不 pool**（Google 2025-03-01 起廢掉共用的
    $200 credit）=> 「Google 還剩多少」這個問題沒有意義，
    有意義的是「**這個 SKU** 還剩多少」。
    """
    sku = sku or USAGE_SKU_GEOCODING
    settings = quota_settings()
    quotas = settings.get("sku_quotas") or {}
    if sku in quotas:
        return quotas[sku]
    if sku == USAGE_SKU_GEOCODING:
        return settings.get("monthly_free_quota")
    return None


def current_billing_period(start_day: int = 1, today=None) -> str:
    """當下所在帳單週期的**起日**（`YYYY-MM-DD`）。

    回起日而不是 `"2026-09"` 這種標籤，理由是 A-2 問的那個問題：
    使用者把起算日從 1 號改成 15 號的那一刻，舊標籤已經累計了 N 次，
    而 09-01~09-14 的那 N 次該算在哪一期？
    => 存**實際的週期起日**就沒有這個問題：改設定會開出一個新的週期，
    舊的那一段原封不動留在原本的起日底下，看得到也對得上。

    Google 的帳單週期**不一定是自然月**（GB4）——
    寫死 1 號的話，跨週期那幾天的管制會完全錯位：
    我們以為歸零了，而帳單還在累積。

    週期是**算出來的**，不是存下來的（GB11）：
    一個「下次恢復日」欄位在排程漏跑一次之後就永遠不會觸發，
    而症狀是「額度早就重置了，而系統還在省錢模式」。
    """
    today = today or date.today()
    try:
        start_day = int(start_day)
    except (TypeError, ValueError):
        start_day = 1
    # 28：每個月都有的最後一天。29~31 在二月會不存在，
    # 而那種設定會讓某些月份**整個月沒有起算日**。
    start_day = min(max(start_day, 1), 28)
    year, month = today.year, today.month
    if today.day < start_day:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return "%04d-%02d-%02d" % (year, month, start_day)


def record_geocode_call(source: str) -> None:
    """記一次**真的發出去而且收到回應**的請求。

    計數點在 `_locate_google()` 內部、發出之後解析之前（GB2/GB3）：

        快取命中、預算用完、提前返回、沒有金鑰   不計
        收到回應（含 ZERO_RESULTS、配額用完）    計
        連線失敗（timeout / DNS）                不計

    判準是「**有沒有收到回應**」，不是「有沒有拿到座標」（A 2026-09-22 裁定）。
    只看有沒有拿到座標的話，這兩種會被歸成同一類。

    把計數加在「決定要查」的地方，算出來的數字會**大於**帳單
    => 我們會提前降級，**使用者拿到的精度比他付的錢低**。
    只計成功的話，一個查不到的地址可以無限重試而不進計數器。

    未查證：ZERO_RESULTS 與錯誤回應**在帳單上算不算一次**，
    A-2 2026-09-22 讀過官方頁面，**沒有找到明文**。
    所以這個計數器數的是「我們發出去幾次」，那與帳單的關係目前是未確認的。
    不要把「查不到也計費」當成已知的事寫進任何地方。

    寫進 `geocode_usage` 表，不是行程內變數：
    記憶體計數器一重啟就歸零，而「永遠沒觸發」跟「運作良好」長得一模一樣。
    """
    from db import get_db
    settings = quota_settings()
    period = current_billing_period(settings.get("cycle_start_day", 1))
    conn = get_db()
    try:
        # **原子 upsert，不要讀出來 +1 再寫回去**（A-2）：
        # 兩個請求同時進來會少算一次，而**少算的方向是危險的那一側** ——
        # 計數器偏低 => 自動降回免費太晚觸發 => 真的花到錢。
        # 偏高只會讓功能提早變差，看得見、會被報修；偏低不會。
        #
        # 也不要用 `INSERT OR IGNORE` 當 upsert：AUTOINCREMENT 下它撞 UNIQUE
        # 時照樣把 `sqlite_sequence` 往前推，`max(id)` 會漲到幾十萬，
        # 而下一個人看 `max(id)` 會以為這裡有大量資料
        # （`module_versions` 就是這樣騙了我們大半天）。
        # `ON CONFLICT ... DO UPDATE` 走 UPDATE 路徑，不分配 rowid。
        conn.execute(
            "INSERT INTO geocode_usage "
            "(period_start, month, source, count, updated_at) "
            "VALUES (?,?,?,1,?) "
            "ON CONFLICT(period_start, source) DO UPDATE SET "
            "count = count + 1, updated_at = excluded.updated_at",
            (period, period[:7], source, datetime.now().isoformat()))
        conn.commit()
    except Exception:   # noqa: BLE001
        # 計數失敗**不可以打斷查詢** —— 使用者要的是地圖，不是計數器。
        # 而它也不可以安靜：留一行 log，否則「沒有用量」與「計數壞了」一樣。
        logger.exception("record_geocode_call failed (source=%s)", source)
    finally:
        conn.close()


def usage_this_period(source: str = None) -> int:
    """這個帳單週期已經發出去幾次。"""
    from db import get_db
    source = source or USAGE_SKU_GEOCODING
    period = current_billing_period(quota_settings().get("cycle_start_day", 1))
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT count FROM geocode_usage WHERE period_start=? AND source=?",
            (period, source)).fetchone()
    except Exception:   # noqa: BLE001
        logger.exception("usage_this_period failed")
        return 0
    finally:
        conn.close()
    return int(row["count"]) if row else 0


def quota_exceeded(used=None, quota=None, pct=None) -> bool:
    """到硬上限了嗎。

    **`quota is None` = 不管制**（GB7），不是 = 0。
    用 `is None`，不要用真假值。寫成真假值的話：
    沒填額度 = 額度 0 = **第一次請求就鎖死**，
    而那看起來很像「金鑰有問題」—— 使用者會去查金鑰，查不出東西。

    `quota` 明著填 0 => 「一次都不准查」。**那與留空是兩件事。**
    """
    settings = quota_settings()
    if quota is None and used is None:
        quota = quota_for()
        used = usage_this_period()
    if quota is None:
        return False
    if pct is None:
        pct = settings.get("hard_pct") or 100
    try:
        limit = float(quota) * float(pct) / 100.0
    except (TypeError, ValueError):
        return False
    return float(used or 0) >= limit


def quota_status() -> dict:
    """現在是不是省錢模式，以及這個週期到哪天。給畫面用（GB9）。"""
    settings = quota_settings()
    used = usage_this_period()
    quota = quota_for()
    period = current_billing_period(settings.get("cycle_start_day", 1))
    return {
        "sku": USAGE_SKU_GEOCODING,
        "managed": quota is not None,
        "used": used,
        "quota": quota,
        "periodStart": period,
        "degraded": quota_exceeded(used=used, quota=quota),
        "warnPct": settings.get("warn_pct"),
        "hardPct": settings.get("hard_pct"),
        "cycleStartDay": settings.get("cycle_start_day"),
    }


def quota_calculator() -> dict:
    """**真實**計算器 —— 每一個數字都從實際資料算，一個都不是估的（GB5）。

    單價與免費額度**不寫死在程式裡**，它們是超級管理員填的欄位（GB6）。
    Google 改過不止一次，而寫死的價格不會報錯，只會算錯。

    `cost_this_period` 的前提是「一次請求 = 一個計費單位」，
    而那一點**尚未查證**（A-2 讀過官方頁面沒有找到明文）=>
    沒填單價就回 `None`，不要用 0 冒充：0 元會被讀成「不用錢」。
    """
    from db import get_db
    settings = quota_settings()
    cached = uncached = 0
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT address) AS c FROM geocode_cache").fetchone()
        cached = int(row["c"] or 0) if row else 0
    except Exception:   # noqa: BLE001
        logger.exception("quota_calculator: geocode_cache 讀不到")
    finally:
        conn.close()

    # 還沒快取的相異地址：問「誰會被畫在地圖上」的那些來源。
    # 用 `cached_only()` 判斷，不自己再寫一次「算不算已知」——
    # 兩份判準會分岔，而分岔之後計算器說的跟實際查的就不是同一件事。
    try:
        addresses = set()
        for fn in list(_WARM_SOURCES):
            try:
                addresses.update(a for a in (fn() or []) if a)
            except Exception:   # noqa: BLE001
                logger.exception("quota_calculator: 一個待暖來源壞了")
        uncached = sum(1 for a in addresses if cached_only(a) is None)
    except Exception:   # noqa: BLE001
        logger.exception("quota_calculator: 待暖清單算不出來")

    used = usage_this_period()
    quota = quota_for()
    price = settings.get("price_per_1000")
    out = {
        "cached_addresses": cached,
        "uncached_addresses": uncached,
        "used_this_period": used,
        "quota": quota,
        "remaining": None if quota is None else max(int(quota) - used, 0),
        "period_start": current_billing_period(
            settings.get("cycle_start_day", 1)),
        # TTL 到期攤提：相異地址 / TTL 天數 * 30 = **每月經常性**用量。
        "monthly_recurring_estimate": (
            round(cached / float(GEOCODE_CACHE_TTL_DAYS) * 30, 1)
            if cached else 0.0),
        "price_per_1000": price,
        "ttl_days": GEOCODE_CACHE_TTL_DAYS,
    }
    out["cost_this_period"] = (None if price is None
                               else round(used * float(price) / 1000.0, 2))
    return out


#: 一個週期只寄一次警戒信，記在這個設定鍵底下。
QUOTA_WARNED_SETTING = "google_quota_warned_period"


def notify_quota_warning(used=None, quota=None) -> bool:
    """達警戒線 => 寄信給超級管理員。**一個週期只寄一次。**

    告警必須有速率上限：設計時就要想「失控時怎麼關掉」。
    走 `_send_raising` **不要走 `_async_send`** ——
    射後不理會讓「已通知」被標起來而信沒出去（同 3s 的標案雷達）。

    回傳「這一次有沒有真的寄出去」。
    """
    settings = quota_settings()
    if quota is None:
        quota = quota_for()
    if quota is None:
        # ⚠️ 這個早退**排在 import 之前**是刻意的（D 2026-09-22 指出的測試成本）：
        # 🔑 想測「額度留空時什麼都不做」，就不應該先備好一個寄信模組才跑得到分支。
        # 📌 一個需要先架好周邊才驗得到的短路，很容易被寫成「反正它會回 False」。
        return False            # 不管制 => 沒有警戒線可言
    from helpers import email_notify
    from helpers.settings import _get_setting, _set_setting

    if used is None:
        used = usage_this_period()
    warn_pct = settings.get("warn_pct") or 80
    try:
        if float(used) < float(quota) * float(warn_pct) / 100.0:
            return False
    except (TypeError, ValueError):
        return False

    period = current_billing_period(settings.get("cycle_start_day", 1))
    if (_get_setting(QUOTA_WARNED_SETTING, "") or "") == period:
        return False

    subject = "Google 地圖額度已達警戒線（週期 %s 起）" % period
    body = (
        "本週期（%s 起）Google 地理編碼已送出 %s 次請求，設定的免費額度 %s 次，"
        "已達警戒線 %s%%。\n\n"
        "達到硬上限之後，系統會自動退回免費的定位來源（精度較低），"
        "功能不會關閉；下一個週期開始會自動恢復，不需要有人去按。"
        % (period, used, quota, warn_pct))
    # 先寄再記：先記的話寄失敗就永遠不會再寄。
    result = email_notify._send_raising(subject, body)
    if result == email_notify.SEND_SENT:
        _set_setting(QUOTA_WARNED_SETTING, period)
        return True
    return False


def _locate_google(address, **_kw):
    """Google Geocoding。**沒有金鑰就不發請求**（A6）。

    「沒有金鑰時不要送出去」不只是省錢：
    **一個帶空金鑰的請求會被記在對方那裡**，而我們拿不到任何有用的東西。
    """
    from helpers.settings import _get_setting
    profile = _get_setting("company_profile", {}) or {}
    key = (profile.get(GOOGLE_KEY_SETTING) or "").strip()
    if not key:
        return None
    # 🔴 GB8 第二道：到硬上限就**不要發出去**。
    # ⚠️ 第一道在退階迴圈裡（`_stage_allowed()`）—— 這一道是給直接呼叫者的。
    # 🔑 兩道都要：少了迴圈那道，我們會付錢；少了這一道，
    #    任何一個繞過迴圈的新呼叫端都會默默把額度用完。
    if quota_exceeded():
        return None
    params = urllib.parse.urlencode({"address": address, "key": key,
                                     "region": "tw", "language": "zh-TW"})
    req = urllib.request.Request(
        "https://maps.googleapis.com/maps/api/geocode/json?" + params,
        headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except Exception:  # noqa: BLE001
        # 🔑 **連線失敗不計數**（GB3）：請求沒有到達對方，或沒有收到回應。
        # ⚠️ 判準是「有沒有收到回應」，不是「有沒有拿到座標」——
        # ☠️ 只看有沒有座標的話，「查不到」與「連不上」會被歸成同一類。
        return None
    # 🔴 **計數點在這裡**：收到回應之後、解析之前（GB2／GB3）。
    # ☠️ 放在解析之後的話，`ZERO_RESULTS` 這種「送出去了、對方回了、
    #    而我們沒拿到座標」的請求就不會被計到 ——
    #    而那種地址可以被無限重試。
    record_geocode_call(USAGE_SKU_GEOCODING)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    results = data.get("results") or []
    if not results:
        return None
    geometry = results[0].get("geometry") or {}
    loc = geometry.get("location") or {}
    if "lat" not in loc or "lng" not in loc:
        return None
    # Google 自己會講精度（location_type）。ROOFTOP 才算門牌。
    precision = (PRECISION_ROOFTOP if geometry.get("location_type") == "ROOFTOP"
                 else PRECISION_STREET)
    return (float(loc["lat"]), float(loc["lng"])), precision


def _locate_tgos(address, **_kw):
    """TGOS（政府圖資）。**沒有 AppID 就不發請求**（A7）。

    **條款尚未查證的部分**：TGOS 的**底圖**已逐字查證為免註冊、免費、可商用
    （政府資料開放授權條款第 1 版，但顯名標示是硬性的）；
    **而「地址定位」在不在免申請的 Lite 版裡，目前仍然未知。**
    => 所以這一階預設沒有 AppID => 不做任何事，等條款讀完再接。
    「我記得它是免費的」跟「我查過它是免費的」在單子上長得一樣。
    """
    from helpers.settings import _get_setting
    app_id = _get_setting(TGOS_APPID_SETTING) or ""
    if not str(app_id).strip():
        return None
    # 尚未接上：有 AppID 也先不查，等條款與端點確認。
    return None


def _locate_nominatim(address, **_kw):
    """OSM／Nominatim。回 `((lat, lon), precision)` 或 `None`。

    🔴 精度由**回應的分類**決定（`classify_precision`），不是一律 `street`。
    ⚠️ 這裡原本不管命中什麼都回 `PRECISION_STREET`
    ⇒ `交通部航港局`（建物）與 `台中市西屯區台灣大道三段`（路段中心）
    **在畫面上是同一種準度**，而誤差差了兩個數量級。
    """
    coord, _err, info = _unpack_geocode(geocode(address))
    if coord is None:
        return None
    return coord, classify_precision(info)


#: 有序退階。**每一階都是模組層屬性**，否則測試沒辦法讓前 N 階失敗，
#: 而那一題會退化成「只驗最後有沒有座標」。
_STAGES = (("_locate_google", SOURCE_GOOGLE),
           ("_locate_tgos", SOURCE_TGOS),
           ("_locate_nominatim", SOURCE_NOMINATIM))


def _stage_allowed(source) -> bool:
    """這一階現在可不可以走。

    🔴 GB8：達硬上限 ⇒ **google 那一階直接跳過**，退到 TGOS／Nominatim／行政區。
    ⭐ 使用者要的是「附近客戶跟查找功能**先回歸免費**」——
       **功能照用，只是精度降級**，不是把功能關掉。

    ⚠️ 只擋 Google。免費那幾階沒有額度可言，擋它們等於把地圖關掉，
    ☠️ 而「鎖死了所以地圖是空的」會讓「沒有超支」這個斷言變綠（GB15）——
       那是把一個成本問題換成一個功能故障。
    """
    if source != SOURCE_GOOGLE:
        return True
    # 🔑 具名呼叫模組層函式，不要抓住參考：抓住的話測試 patch 打不到，
    #    而那一題會安靜地失效。
    return not quota_exceeded()


def _run_stage(name, address):
    """呼叫某一階。**從模組全域取，不要抓住函式參考。**

    抓住參考的話，測試 patch 模組屬性就打不到那個舊參考,
    而那一題會安靜地失效——今晚已經踩過這一族很多次。
    """
    return globals()[name](address)


def locate(address, manual_coord=None):
    """地址 -> `GeoResult`。手動 -> Google -> TGOS -> Nominatim -> 退到行政區。"""
    if manual_coord is not None:
        # **人工填的座標跳過每一階，而且不對外連線**（A2）。
        # 使用者親手指定的位置，沒有任何理由再去問別人一次。
        return GeoResult(coord=tuple(manual_coord), precision=PRECISION_EXACT,
                         source=SOURCE_MANUAL, address=address)

    address = (address or "").strip()
    if not address:
        return GeoResult(error="沒有地址")
    if not geo_on():
        return GeoResult(error="地理查詢未啟用（需要 MOTRIX_GEO=1）")

    for name, source in _STAGES:
        if not _stage_allowed(source):
            continue
        found = _run_stage(name, address)
        if found:
            coord, precision = found
            return GeoResult(coord=coord, precision=precision, source=source,
                             address=address)

    return _locate_district(address)


def _locate_district(address):
    """整個地址查不到時，退到「縣市＋區」再查一次。

    🔴 **抽出來是為了消掉一次重複查詢**（A16）：
    原本 `locate_cached()` 自己跑完整個梯子、全 miss 之後呼叫 `locate()`，
    而 `locate()` **又從第一階把梯子重跑一遍**才退到行政區
    ⇒ 同一個地址被問了**三次**，其中一次是純粹浪費的。
    ☠️ 而那是**常態路徑**：沒有 Google 金鑰的機器上，每一個門牌地址都查不到。
    而重複查詢正是 Nominatim 封 IP 的理由——被封之後的樣子是
    「**地圖上沒有點，而 `geoEnabled` 仍然是 true**」，看起來像使用者地址填錯。

    ⚠️ **兩個入口都要能退階**（A16d）：`locate()` 與 `locate_cached()` 各自呼叫它。
    抽出來之後很容易變成「只剩快取那條路會退階」，
    而那是〈兩個都對而路不存在〉的新斷點。
    """
    district = district_of(address)
    if not district or district == address:
        # 切不出行政區、或切出來跟原地址一樣 => **不要再查一次**（A4c）。
        return GeoResult(error="查無此地址", address=address)
    found = _run_stage("_locate_nominatim", district)
    if not found:
        return GeoResult(error="查無此地址", address=address)
    coord, _precision = found
    # **精度由「我們實際問了什麼」決定，不是由回應說什麼決定。**
    # 我們問的是行政區 => 拿到的就是行政區中心點，不管對方怎麼標。
    return GeoResult(coord=coord, precision=PRECISION_DISTRICT,
                     source=SOURCE_NOMINATIM_DISTRICT, address=address)


def _cache_get(address, source):
    """讀資料庫快取。**過期的當成沒有。**"""
    from db import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT lat, lon, precision, created_at FROM geocode_cache "
            "WHERE address=? AND source=?", (address, source)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    created = (row["created_at"] or "")[:10]
    if created:
        try:
            age = (date.today() - date.fromisoformat(created)).days
        except ValueError:
            age = 0
        if age >= GEOCODE_CACHE_TTL_DAYS:
            return None
    return GeoResult(coord=(row["lat"], row["lon"]), precision=row["precision"],
                     source=source, address=address)


def _cache_put(result):
    """寫資料庫快取。**只寫成功的**——失敗不進永久快取（A14）。

    `503`／逾時是暫時的，寫進資料庫會讓一次抖動變成**永久的空白**。
    記憶體會自己忘記，資料庫不會。
    """
    if not result or not result.coord or result.source == SOURCE_MANUAL:
        return
    from db import get_db
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO geocode_cache "
            "(address, source, lat, lon, precision, created_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(address, source) DO UPDATE SET "
            "lat=excluded.lat, lon=excluded.lon, "
            "precision=excluded.precision, created_at=excluded.created_at",
            (result.address, result.source, result.coord[0], result.coord[1],
             result.precision, date.today().isoformat()))
        conn.commit()
    finally:
        conn.close()


def _remember(address, result):
    result.address = address
    _CACHE[(address, result.source)] = result
    _cache_put(result)


def _cached_stage(address, source):
    """記憶體 -> 資料庫，兩層都找。"""
    key = (address, source)
    if key in _CACHE:
        return _CACHE[key]
    hit = _cache_get(address, source)
    if hit:
        _CACHE[key] = hit
        return hit
    return None


def cached_only(address):
    """**只問快取，絕不對外連線。** 找不到回 `None`。

    ## 🔴 為什麼需要一個「不會連出去」的入口
    `locate_cached()` 的名字讀起來像「用快取」，**而它在 miss 的時候會連出去**。
    ⇒ 呼叫端想問「這個地址我已經知道了嗎」時，沒有辦法只問而不查。

    📌 `/api/map/points` 用它來實作**每次請求的查詢預算**：
    已經知道的一律免費，不知道的才算進預算。
    """
    address = (address or "").strip()
    if not address:
        return None
    for _name, source in _STAGES:
        hit = _cached_stage(address, source)
        if hit:
            return hit
    # 退階那一階也有自己的快取鍵（見 `locate_cached`）。
    return _cached_stage(address, SOURCE_NOMINATIM_DISTRICT)


def locate_cached(address, manual_coord=None):
    """`locate` 加兩層快取：記憶體 -> 資料庫。

    **快取以「地址＋來源」為鍵，逐階檢查。**
    只用地址當鍵的話：Nominatim 先查到行政區中心點並寫進快取
    => 使用者後來填了 Google 金鑰 => **快取命中，永遠拿不到門牌精度**（A9）。
    而症狀是**沒有症狀**：地圖上有點、距離有數字，只是一直差幾公里。
    """
    if manual_coord is not None:
        return locate(address, manual_coord)
    address = (address or "").strip()
    if not address:
        return GeoResult(error="沒有地址")

    for name, source in _STAGES:
        hit = _cached_stage(address, source)
        if hit:
            return hit
        if not _stage_allowed(source):
            # 🔴 GB10／GB16：**跳過，而不是用免費階的結果去填 google 的快取鍵。**
            # ☠️ 填進去的話，額度恢復之後 `cached_only()` 會在 google 階命中
            #    ⇒ **永遠不會再問 Google** —— 就是 A9／GC1 那個坑。
            # 🔑 而「永遠不再問」與「問了而答案一樣」在畫面上完全相同：
            #    症狀是**沒有症狀**，金鑰、額度、設定全都正常。
            # 📌 下面每一階各自用自己的 `source` 當快取鍵，所以降級期間拿到的
            #    行政區中心點會被記在 `nominatim` 底下，不會污染 google 那一格。
            continue
        found = _run_stage(name, address)
        if found:
            coord, precision = found
            result = GeoResult(coord=coord, precision=precision, source=source)
            _remember(address, result)
            return result

    # 退階那一階也要有自己的快取鍵。
    hit = _cached_stage(address, SOURCE_NOMINATIM_DISTRICT)
    if hit:
        return hit
    # ⚠️ 直接呼叫退階，**不要再走一次 `locate()`** ——
    # 上面那個迴圈已經把三階都問過了，`locate()` 會從第一階重跑（A16）。
    result = _locate_district(address)
    if result.coord:
        _remember(address, result)
    return result


# ══════════════════════════════════════════════════════════════════════════
# 背景自動暖快取（§3v）
# ══════════════════════════════════════════════════════════════════════════
#
# ☠️ **一個會自己跑的背景迴圈，失控的樣子就是被 Nominatim 封 IP。**
# 🔑 而 2026-09-22 圖磚那件已經演過一次：
# **對方回 HTTP 200 而內容是拒絕，我們的錯誤處理完全沒觸發。**
#
# ⇒ 五道防線，每一道都不是可選的：
#   ① 沿用現有的 `_throttle()`，**不另開不受限的路**
#   ② 每日上限**跨呼叫累計並存 DB**（行程內變數 ＝「每次呼叫最多 N」）
#   ③ 受 `geo_on()` 管，關著時**一次都不發**
#   ④ **連續**失敗就停，而「失敗」**不可以只認例外**
#   ⑤ 查完就停，而「沒有待辦」與「上限用完」**要分得開**
# 而第六道是「怎麼知道它在跑」：
#   ⑥ `warm_status()` —— **「沒有在跑」與「跑了什麼都沒做」在畫面上一模一樣**

#: 一天最多查幾個新地址。
#:
#: 📌 199 個相異字串 ÷ 120 ≈ 兩天補完，而每天只佔 Nominatim 約兩分鐘。
#: ⚠️ 這個數字**不是拍腦袋**：它要小於「一天內不會被當成 bulk geocoding」
#: 的量，又要大到兩三天能收斂。改它之前先想「失控時誰會發現」。
GEOCODE_WARM_DAILY_LIMIT = 120

#: 連續失敗幾次就停。**連續，不是累計。**
#:
#: ☠️ 累計判準會在**正常運作**時停住：待辦裡本來就有查不到的地址
#: （實測：門牌一律查不到）⇒ 跑三筆就永久停，
#: 🔑 而症狀是「背景好像沒在跑」，**跟「它根本沒被排程」一模一樣**。
WARM_MAX_CONSECUTIVE_FAILURES = 3

#: 兩次背景暖快取之間隔多久。
GEOCODE_WARM_INTERVAL_SECONDS = 6 * 60 * 60

#: 狀態與每日計數存在哪。**存 DB 不存記憶體。**
#: ⚠️ 存記憶體的話，uvicorn 一重啟（`autostart.bat` 是無限迴圈）
#: 每日上限就歸零 ⇒ **上限實際上變成「每次重啟最多 N」**。
WARM_STATE_SETTING = "geocode_warm_state"

#: 待辦的來源。**由呼叫端註冊，`geo` 不認識任何一張業務表。**
#:
#: 🔑 〈模組化〉：`geo` 是共用能力，它不可以知道 `tenders`／`customers`
#: 這些表的存在——那會讓「地理編碼」這個模組**賣不動**（它綁死了 ERP 的 schema）。
#: ⇒ `routers/map_points.py` 在匯入時把自己的待辦清單註冊進來。
_WARM_SOURCES = []


def register_warm_source(fn):
    """註冊一個「待辦地址清單」的來源。`fn()` 回一串字串。

    ⚠️ **重複註冊要擋掉**：模組被重新匯入時（測試、reload）會再跑一次，
    而一個被註冊兩次的來源會讓待辦**看起來多一倍**。
    """
    if fn not in _WARM_SOURCES:
        _WARM_SOURCES.append(fn)
    return fn


def _warm_state():
    from helpers.settings import _get_setting
    state = _get_setting(WARM_STATE_SETTING, {}) or {}
    return dict(state) if isinstance(state, dict) else {}


def _save_warm_state(state):
    from helpers.settings import _set_setting
    _set_setting(WARM_STATE_SETTING, state)


def warm_status() -> dict:
    """背景暖快取的狀態。**四個欄位各自回答一個問題。**

    | 欄位 | 回答的問題 |
    |---|---|
    | `lastRunAt` | **有沒有跑** |
    | `processed` | **做了多少** |
    | `succeeded` | **有沒有用** |
    | `stoppedBecause` | **為什麼停** |

    ☠️ 少任何一個，都有一種沉默分不出來。
    📌 最容易漏的是 `succeeded`：跑了 100 筆而成功 0 筆，
    `processed` 那個數字**看起來非常健康**。
    """
    state = _warm_state()
    return {
        "lastRunAt": state.get("last_run_at"),
        "processed": state.get("processed", 0),
        "succeeded": state.get("succeeded", 0),
        "stoppedBecause": state.get("stopped_because"),
        "usedToday": state.get("used", 0),
        "dailyLimit": GEOCODE_WARM_DAILY_LIMIT,
    }


def _warm_backlog():
    """所有註冊來源的待辦地址，**去重、且排除已經查過的**。

    ⚠️ 一個來源壞掉不可以拖垮其他來源：那會讓「背景沒在跑」變成
    一個**跟資料無關**的原因，而 log 裡只有一行堆疊。
    """
    seen, out = set(), []
    for source in _WARM_SOURCES:
        try:
            items = source() or []
        except Exception:                     # noqa: BLE001
            logger.exception("暖快取的待辦來源失敗：%r", source)
            continue
        for raw in items:
            address = str(raw or "").strip()
            if not address or address in seen:
                continue
            seen.add(address)
            if cached_only(address) is not None:
                continue                      # 已經知道了，不算待辦
            out.append(address)
    return out


def _check_quota_warning():
    """順手看一下要不要寄警戒信（`GB12`）。

    🔑 **掛在背景這一輪，不掛在 `record_geocode_call()` 裡**：
    ☠️ `_send_raising()` 是同步的 —— 掛在計數那一行等於把一次 SMTP
       塞進使用者開地圖的請求路徑上，而 SMTP 慢起來是以秒計的。
    📌 警戒線講的是「快到了」，不是「已經超了」⇒ 六小時的解析度夠用；
       而真正的硬上限是**每一次呼叫都會檢查**的（`_stage_allowed()`）。
    ⚠️ 寄信失敗不可以打斷背景暖快取 —— 它的工作是補快取，不是寄信。
    """
    try:
        notify_quota_warning()
    except Exception:   # noqa: BLE001
        logger.exception("_check_quota_warning failed")


def warm_geocode_cache() -> dict:
    """跑一趟背景暖快取。回 `warm_status()`。

    **可以單獨呼叫** —— 排程與測試共用同一支，
    🔑 那讓「排程呼叫的東西」與「測試驗過的東西」**不可能是兩份**。
    """
    state = _warm_state()
    today = date.today().isoformat()
    if state.get("date") != today:
        # 跨日 ⇒ 計數歸零。⚠️ **只歸零計數，不清掉上一次的狀態**：
        # 那些數字是「上一次跑的結果」，昨天跑的仍然是有效的答案。
        state["date"] = today
        state["used"] = 0

    def _finish(reason, processed=0, succeeded=0):
        # 🔴 **每一趟都寫，包含什麼都沒做的那些。**
        # ☠️ 只在有做事時才更新的話，畫面會永遠寫著「上次處理 3 筆」，
        # 而那個迴圈可能已經停了三天 —— **一個看起來很健康的畫面。**
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        state["processed"] = processed
        state["succeeded"] = succeeded
        state["stopped_because"] = reason
        _save_warm_state(state)
        return warm_status()

    # ── 防線③：總開關 ────────────────────────────────────────────────
    # ⚠️ 「發了失敗」與「沒發」在畫面上一樣（都沒有新座標），
    # 而代價差一個逾時 × 每一筆待辦。**壞掉的時候最慢。**
    if not geo_on():
        return _finish("geo_off")

    # ── 防線⑤：沒有待辦就不要空轉 ────────────────────────────────────
    # 🔑 「沒有待辦」是**好消息**，「上限用完」是欠帳 —— 合成一個
    # 「已停止」的話，那兩件在畫面上會長得一樣。
    backlog = _warm_backlog()
    if not backlog:
        return _finish("no_backlog")

    # ── 防線②：每日上限，跨呼叫累計 ──────────────────────────────────
    remaining = GEOCODE_WARM_DAILY_LIMIT - int(state.get("used", 0) or 0)
    if remaining <= 0:
        return _finish("daily_limit")

    processed = succeeded = streak = 0
    reason = "no_backlog"                 # 全部查完 ⇒ 待辦空了
    for address in backlog:
        if processed >= remaining:
            reason = "daily_limit"
            break
        # ── 防線①：沿用現有節流 ──────────────────────────────────────
        # ☠️ 另開一條不受節流的路 ＝ 用最快的速度連打對方，
        # 而那正是被封 IP 的標準做法。
        _throttle()
        try:
            result = locate_cached(address)
        except Exception:                 # noqa: BLE001
            logger.exception("暖快取查詢失敗：%s", address)
            result = None
        processed += 1
        state["used"] = int(state.get("used", 0) or 0) + 1
        # ── 防線④：連續失敗就停，**而失敗不只認例外** ────────────────
        # ☠️ 對方回 HTTP 200 而內容是拒絕時，`except` 完全不會觸發
        # ⇒ 只在 `except` 裡累計的實作會**若無其事地繼續打**。
        # ⇒ 判準是「**這一筆有沒有拿到座標**」，不是「有沒有丟例外」。
        if result is not None and getattr(result, "coord", None):
            succeeded += 1
            streak = 0
        else:
            streak += 1
            if streak >= WARM_MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "暖快取連續失敗 %d 次，停下來。"
                    "（對方可能拒絕了我們——請看上面的錯誤訊息）", streak)
                reason = "failures"
                break
    # 📌 每一輪結束時看一次警戒線（`GB12`）——
    #    這裡是**唯一**會定期醒來而且不在請求路徑上的地方。
    _check_quota_warning()
    return _finish(reason, processed, succeeded)


def schedule_geocode_warm():
    """啟動時呼叫一次：跑一輪，然後排下一次。

    ⚠️ 工作包在 `try` 裡、**重排放在 `finally`** —— 形狀照
    `tender_source.schedule_tender_scan()`。
    把重排放在工作之後而沒包 try 的話，丟一次例外就**永遠不會再排**，
    而「排程死了」跟「今天沒事做」長得一模一樣。

    ⚠️ `threading.Timer` 走模組屬性，`from threading import Timer`
    會讓 monkeypatch 打不到。
    """
    try:
        warm_geocode_cache()
    except Exception:                     # noqa: BLE001
        logger.exception("warm_geocode_cache failed")
    finally:
        t = threading.Timer(GEOCODE_WARM_INTERVAL_SECONDS,
                            schedule_geocode_warm)
        t.daemon = True
        t.start()


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
