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
import re
from datetime import date
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
    coord, err, _info = _unpack_geocode(geocode(address))
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
    params = urllib.parse.urlencode({"address": address, "key": key,
                                     "region": "tw", "language": "zh-TW"})
    req = urllib.request.Request(
        "https://maps.googleapis.com/maps/api/geocode/json?" + params,
        headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
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
