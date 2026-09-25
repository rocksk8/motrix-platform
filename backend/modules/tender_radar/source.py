"""標案來源：抓取與解析（2026-09-21，細線 6 第 1～2 步）。

資料來源：政府電子採購網招標查詢
`https://web.pcc.gov.tw/prkms/tender/common/basic/readTenderBasic`
授權：官網著作權聲明「得重製、公開播送或公開傳輸，**利用時請註明出處**」
（SPEC §T.2 已查證）。⚠️ 社群 API 明文禁商業用途，**不使用**。

## 抓取與解析刻意分成兩支

`fetch_raw` 只負責拿回 HTML、`parse_list` 只吃字串吐結構。
混在一起的話測試只能對著真實網站跑，**而它紅的時候分不出是我們寫錯還是對方改版**。

## 四種壞法不可以互相蓋掉

| 壞法 | 應該長什麼樣 | 為什麼容易被合併 |
|---|---|---|
| 今天真的沒標案 | `recognised=True, items=[]` | |
| 對方改版、整頁認不出 | `recognised=False` | 跟上面一樣是 `items=[]` |
| 網站掛了／403／逾時 | `fetch_raw` 回 `(None, error)`，紀錄 `recognised=NULL` | 空字串也找不到容器 → 也會變 `recognised=False` |
| **欄序對調／名稱是 JS** | 該筆丟掉或正確拆出 | ⚠️ **每個訊號都綠而資料全錯** |

前三種是「雷達安靜」，**第四種是雷達報錯的東西而且看起來很正常**——
所以有〈形狀驗證〉那一段。這條線的價值是「不會漏掉標案」，
**瞎掉與報錯正好是它唯二不能發生的事**。

## 這個網站的三個真實陷阱（都是實際樣本上量到的，不是假設）

1. **表頭字樣在原始 HTML 裡被標籤切開**：`截止<br>投標`、`&emsp;`。
   直接在原始碼找 `截止投標` 會得到 0 次 ⇒ `recognised` 永遠是 `False`。
   **必須先 strip tags → unescape → 去掉所有空白再比。**
2. **查詢表單頁也有 `<table>`，而且也含「機關名稱」「標案案號」。**
   所以 `recognised` 要求**四個字樣同時出現**，而且是**逐表**檢查——
   實作成「頁面上找得到 table」的話，表單頁也會回 `True`。
3. **標案名稱是 JavaScript 產生的**：`pageCode2Img("真正的名稱")`。
   naive strip tags 會得到一整行 JS，**而真名是那串垃圾的子字串**——
   於是關鍵字照樣命中、「非空」照樣通過，**而資料庫裡每一筆名稱都是一行 JavaScript**。

## 日期是民國年

`115/09/30` ＝ 西元 2026-09-30。⚠️ **響亮的失敗不可怕，安靜的才可怕**：
`datetime.strptime("115/09/30", "%Y/%m/%d")` 會丟例外（好事），
但 `date(115, 9, 30)` 是**合法物件**、距今約 -697,970 天，
會被「早就截止」安靜濾掉 —— 整批標案消失而每個訊號都綠。
所以除了轉換，還有**上界檢查**（`_DATE_SANITY_YEARS`）：
**那個上界是這一類錯誤的通用網子，不只接民國年**，任何把日期算歪的 bug
（時區、世紀、格式）都會掉進來。
"""
import json
import logging
import os
import re
# ⚠️ **`import threading` 走模組，不要 `from threading import Timer`。**
# 後者會把 Timer 複製進本模組的命名空間，monkeypatch 打不到 ⇒ S3 永遠綠。
# 跟 `fetch_raw`／`procurement.today` 是同一條（第 4 輪 8b 的教訓）。
import threading
# ⚠️ `import time` 走模組：`time.sleep` 要 patch 得到（D3）。
# **「patch 目標要走模組」的第七個實例**——前六個：fetch_raw／procurement.today／
# _PUBKEY_DEV／LICENSE_PATH／threading.Timer／_pref_enabled。
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from db import get_db
from helpers.settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# **預設關。它會對外連線，預設就不該是開的。**
# 關著時**連 `fetch_raw` 都不會被呼叫**——不是「呼叫了但不做事」。
# 那個差別驗得出來（條件 8 的觀測點是呼叫次數，不是有沒有產生資料），
# 而「沒產生資料 ≠ 沒被呼叫」正是 licensing middleware 那次的教訓。
TENDER_RADAR_ENABLED = False


def radar_on():
    """雷達現在開著沒。**出貨預設關；只有 `MOTRIX_TENDER_RADAR=1` 才開。**

    🔴 **為什麼環境變數放在這裡，而不是寫進 `TENDER_RADAR_ENABLED` 的初始值：**
    上面那個字面值被 `test_08c_switch_ships_off_by_default` 釘著。若寫成
    `TENDER_RADAR_ENABLED = os.getenv(...) == "1"`，那道守門就會從
    「永遠綠，除非有人改原始碼」變成「結果取決於周圍環境」——
    有人 `export MOTRIX_TENDER_RADAR=1` 之後跑全回歸，它會紅，
    **而那不是缺陷**。一個不是缺陷的紅燈，代價是一次抓錯方向的除錯。
    ⇒ **字面值留著（守門無條件綠），環境變數放在讀的那一端。**

    ⚠️ 判準是 `== "1"` **不是真假值**：`"0"` 是非空字串，用真假值判會變成開著。

    📌 這個函式讀的是**模組全域**，所以既有 18 處
    `monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)` 照樣有效。
    """
    return TENDER_RADAR_ENABLED or os.getenv("MOTRIX_TENDER_RADAR") == "1"

SITE_ROOT = "https://web.pcc.gov.tw"
TENDER_SOURCE_URL = (
    "https://web.pcc.gov.tw/prkms/tender/common/basic/readTenderBasic")
TENDER_INDEX_URL = (
    "https://web.pcc.gov.tw/prkms/tender/common/basic/indexTenderBasic")
USER_AGENT = "MOTRIX-ERP/1.0 (tender radar; contact your MOTRIX administrator)"
FETCH_TIMEOUT_SECONDS = 15

# 表頭字樣。**四個都要出現才算認得**——前兩個查詢表單也有。
_HEADER_MARKERS = ("機關名稱", "標案案號", "截止投標", "預算金額")

# 欄位位置。⚠️ 固定索引正是「欄序被對調」偵測不到的原因，所以一定要配形狀驗證。
_COL_ORG, _COL_CASE_NAME = 1, 2
# 表頭：項次｜機關名稱｜標案案號標案名稱｜傳輸次數｜招標方式｜採購性質｜…
_COL_METHOD, _COL_PROC_TYPE = 4, 5
_COL_PUBLISHED, _COL_DEADLINE, _COL_BUDGET = 6, 7, 8
_MIN_COLUMNS = 9

_DATE_SANITY_YEARS = 5

# 純記錄模式：首次成功掃描起 N 天內只抓只存、不寄信（SPEC §T.5 #3）。
# ⚠️ 起算點是「第一次成功掃描」不是「開關被打開」——常數翻開的時間無法查證，
# 而**無法查證的起算點在正式機上完全不存在**。
QUIET_PERIOD_DAYS = 7
FIRST_SCAN_SETTING = "tender_radar_first_scan_at"
# ⚠️ 存 system_settings 不是 tender_fetch_log：後者不進每日 JSON 備份，
# 還原之後是空的 ⇒ 7 天純記錄期會**靜默重新開始**。
# ── 時段設定 ─────────────────────────────────────────────────────────────────
#
# 🔑 **抓取與寄信是兩份獨立的設定**（使用者 2026-09-21：「我要可調整」「信的頻率可調」）。
# 「一天一封」從一條寫死的規則，變成**那份設定的一個值**。
SCAN_HOURS = (9, 12, 15, 18)          # 預設抓取時段
NOTIFY_HOURS = (18,)                  # 預設寄信時段
SCAN_HOURS_SETTING = "tender_radar_scan_hours"
NOTIFY_HOURS_SETTING = "tender_radar_notify_hours"
#: 「這個時段寄過沒」。**放 `system_settings` 不放 `tender_fetch_log`**：
#: 後者**不進每日 JSON 備份** ⇒ 放那裡的話**每一次災難還原都會重寄當天的彙總信**。
#: ⚠️ 反過來，抓取的標記**可以**留在 `tender_fetch_log`——
#: **重抓一次是無害的，重寄一封不是。**（同一份證據的兩個方向。）
NOTIFY_MARK_SETTING = "tender_radar_notify_last_slot"

#: 超過幾個時段要先跟使用者確認。**不是硬上限**——按了確認就一定存得進去
#: （使用者 2026-09-21 裁示）。門檻**只有這一份**，前端從後端取。
#: ⚠️ 兩邊各寫一份的失敗樣子是：**前端不跳、後端擋 ⇒ 使用者存不了而且不知道為什麼。**
HIGH_FREQUENCY_SLOT_THRESHOLD = 12

SCAN_HOUR = 8            # 舊的單值預設。具名常數才驗得到「預設值是多少」（D14）
SCAN_HOUR_SETTING = "tender_radar_scan_hour"   # 舊的單數鍵，**留著不刪**（見 scan_hours）

# 第二層（詳細頁）抓取的安全閥。三條缺一不可，而 D1 是基礎：
# **只對「命中 watch 的」抓** —— 把 N 從「當天所有公告」綁到「你真的在乎的那幾筆」。
# 沒有 D1 的話，上限與間隔都只是在拖慢一件不該做的事。
DETAIL_DAILY_LIMIT = 20
DETAIL_INTERVAL_SECONDS = 2

# 履約地點那一格的 id。⚠️ **只認這個 id，不要用「地址」字樣去找。**
# 詳細頁上「地址」出現 10 次，9 次是每一頁都一樣的樣板（六個監督機關＋頁尾）。
# 用字樣找 ⇒ 每一筆標案都得到同一個臺北市信義區的地址，**而它看起來完全像一個合法地點**。
# ⚠️ 更陰的是監督機關裡有一個也在桃園市，抽驗時「桃園市」會讓人以為抓對了。
_LOCATION_FIELD_ID = "fkPmsExecuteLocation"

#: 招標方式在詳細頁上的 id（實測 `tests/fixtures/tender_detail_20260921.html`）。
#:
#: 🔑 它與 `location` 走同一條路 ⇒ 補地點的時候順便把它補起來，**零額外請求**。
#: ⚠️ 而**採購性質不在詳細頁上** —— 「工程類／財物類／勞務類」那三個字
#: 在那一頁只出現在 JavaScript 的註解與字串裡，**不是一個被渲染出來的欄位值**。
#: ☠️ 不要寫一個「順便也抓採購性質」的解析：它會**永遠回 None**，
#:    而那與「這一筆本來就沒有」長得一模一樣。
_METHOD_FIELD_ID = "fkPmsTenderWay"

# 臺灣 22 個縣市。⚠️ **用白名單不用樣式比對**：
# 「多個縣市」用 `^..[市縣]$` 是會通過的（多個縣＋市），而它不是地名。
# 白名單是封閉集合、幾乎不變，而樣式比對的漏網之魚會**看起來像個地名**。
_TW_PLACES = frozenset((
    "臺北市", "台北市", "新北市", "桃園市", "臺中市", "台中市", "臺南市", "台南市",
    "高雄市", "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣",
    "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "台東縣",
    "澎湖縣", "金門縣", "連江縣",
))
_ROC_OFFSET = 1911

_TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_TR_RE    = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_TD_RE    = re.compile(r"<td\b.*?</td>", re.S | re.I)
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.S | re.I)
_TAG_RE   = re.compile(r"<[^>]*>")
_PAGECODE_RE = re.compile(r"pageCode2Img\(\s*[\"'](.*?)[\"']\s*\)", re.S)
_ROC_DATE_RE = re.compile(r"^(\d{2,3})/(\d{1,2})/(\d{1,2})$")
_CASE_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()\-/]*$")
_CJK_RE = re.compile(r"[一-鿿]")


def now_dt():
    """現在（含時刻）。**這是這個模組裡唯一會碰系統時鐘的地方。**

    🔴 時段判定需要「幾點」，而 `today()` 只給日期。
    ⚠️ **不可以在別處直接 `datetime.now()`**：那樣測試 patch 不到，而後果不是紅燈，
    是**偶爾紅的綠燈**——一天四個時段邊界（8:59/9:00…），全部落在上班時間，
    失敗率低、無法重現、**看起來像真的有 bug**。
    🔑 **偶爾紅的綠燈比紅燈貴**：紅燈會被修，偶爾紅的會被重跑一次然後忘掉。
    """
    return datetime.now()


def today():
    """今天。**存在的理由是讓測試換得掉**（同 `helpers/procurement.today()`）。

    各模組持有自己的接縫，而不是互相 import 一個共用的——
    跨模組共用一個 `today` 會讓「換掉採購的今天」順手改掉標案雷達的行為。
    """
    return date.today()


# ── 文字正規化 ───────────────────────────────────────────────────────────────

def _text(fragment):
    """HTML 片段 → 可讀文字。**先整段拿掉 `<script>`**，再去標籤、解實體。

    ⚠️ 拿掉 script 是必要的：這個網站的標案名稱在 `<script>` 裡，
    不拿掉的話整行 JavaScript 會混進文字，而**真名是它的子字串**，
    於是關鍵字比對照樣會命中——錯得很像對的。
    """
    if not fragment:
        return ""
    s = _SCRIPT_RE.sub(" ", fragment)
    s = _TAG_RE.sub(" ", s)
    s = _unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _unescape(s):
    import html as _html
    return _html.unescape(s)


def _squash(fragment):
    """去標籤 → 解實體 → **去掉所有空白**。給表頭字樣比對用。

    這個網站的表頭是 `截止<br>投標` 加 `&emsp;`，不做這一步永遠比不到。
    """
    s = _TAG_RE.sub("", _SCRIPT_RE.sub("", fragment or ""))
    return re.sub(r"\s+", "", _unescape(s))


# ── 民國年 ───────────────────────────────────────────────────────────────────

def roc_to_date(value):
    """`115/09/30` → `date(2026, 9, 30)`。認不得回 `None`（不丟例外）。"""
    m = _ROC_DATE_RE.match((value or "").strip())
    if not m:
        return None
    roc_year, month, day = (int(g) for g in m.groups())
    try:
        return date(roc_year + _ROC_OFFSET, month, day)
    except ValueError:
        return None


def _within_sanity_window(d):
    """距今超過 ±N 年就是算歪了。**這是這一類錯誤的通用網子。**"""
    if d is None:
        return True
    return abs((d - today()).days) <= _DATE_SANITY_YEARS * 365


# ── 解析 ─────────────────────────────────────────────────────────────────────

def _find_result_table(html):
    """找出結果表。**逐表比對四個表頭字樣**，不是「頁面上有沒有 table」。

    回 `None` 代表這一頁認不得（改版、或根本是別的頁）。
    """
    for table in _TABLE_RE.findall(html or ""):
        squashed = _squash(table)
        if all(marker in squashed for marker in _HEADER_MARKERS):
            return table
    return None


def _split_case_and_name(cell_html):
    """案號與名稱在同一格。回 `(case_no, name)`，取不到的那個是空字串。

    案號在 `<br>` 之前；名稱是 `pageCode2Img("…")` 的引數。
    ⚠️ 名稱**不能**用 strip tags 取——那會得到一整行 JavaScript。
    """
    head = re.split(r"<br\b[^>]*>", cell_html, maxsplit=1)[0]
    case_tokens = _text(head).split()
    case_no = case_tokens[0] if case_tokens else ""

    m = _PAGECODE_RE.search(cell_html or "")
    name = _unescape(m.group(1)).strip() if m else ""
    return case_no, name


def _parse_budget(raw):
    """`2,433,600` → `2433600`。空白 → `None`。**`None` 不是 `0`。**

    形狀不符（例如那一格放的是機關名）回 `False`，呼叫端據此丟掉該筆——
    用 `False` 而不是 `None` 是因為 `None` 在這裡是**合法值**（公告沒寫）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    cleaned = text.replace(",", "").replace("元", "").strip()
    if not re.fullmatch(r"\d+", cleaned):
        return False
    return int(cleaned)


def _parse_row(cells):
    """一列 → 標案 dict。**不合格回 `None`，由呼叫端計入 `dropped`。**"""
    if len(cells) < _MIN_COLUMNS:
        return None

    case_no, name = _split_case_and_name(cells[_COL_CASE_NAME])
    org = _text(cells[_COL_ORG])
    m = re.search(r'href="([^"]+)"', cells[_COL_CASE_NAME])
    detail_href = m.group(1) if m else ""

    # 必要欄位：案號／名稱／機關。**截止日不在其中**——
    # 「公告沒寫截止日」是解析成功而不是失敗，算成失敗會污染 dropped 那個訊號。
    if not case_no or not name or not org:
        return None

    # ── 形狀驗證：防「欄序被對調」那種每個訊號都綠而資料全錯的壞法 ──
    if not _CASE_NO_RE.match(case_no) or len(case_no) > 40:
        return None
    # 機關一定是中文名；那一格若放的是日期或數字，就是欄序不對了。
    if not _CJK_RE.search(org) or _ROC_DATE_RE.match(org):
        return None

    budget = _parse_budget(_text(cells[_COL_BUDGET]))
    if budget is False:
        return None

    published_raw = _text(cells[_COL_PUBLISHED])
    deadline_raw = _text(cells[_COL_DEADLINE])
    published = roc_to_date(published_raw)
    deadline = roc_to_date(deadline_raw)

    # 公告日那一格有東西卻讀不成日期 ⇒ 欄序或格式不對，不是「沒寫」。
    if published_raw and published is None:
        return None
    # 截止日可以真的沒寫（空白）；有東西卻讀不成日期同樣是形狀問題。
    if deadline_raw and deadline is None:
        return None

    # ── 上界檢查 ──
    if deadline and published and deadline < published:
        return None
    if not _within_sanity_window(published) or not _within_sanity_window(deadline):
        return None

    # ⚠️ 解析不到存 `None` 不是 `""`：「沒有這一欄」與「這一欄是空的」是兩件事。
    # （`0` vs `NULL` 那一族，今天第五次。）
    method = _text(cells[_COL_METHOD]) or None
    proc_type = _text(cells[_COL_PROC_TYPE]) or None

    return {
        "case_no":   case_no,
        "name":      name,
        "org":       org,
        "tender_method":    method,
        "procurement_type": proc_type,
        # R1（第 5 輪）：這個鍵原本叫 `published`，而 DB 欄位叫 `published_at`。
        # ⚠️ 兩者在相鄰兩行被讀寫，中間沒有轉換層 —— 同一輪裡兩種寫法，
        # 下一個人會以為那是有意義的區別。API 那一層的 `publishedAt` 才是
        # 有意義的不同（跨邊界慣例），這一層沒有。
        "published_at": published.isoformat() if published else None,
        "deadline":  deadline.isoformat() if deadline else None,
        "budget":    budget,
        # ⚠️ 這是**轉址前**的連結（`/prkms/urlSelector/...` 會 302 到
        # `/tps/QueryTender/...`）。點下去照樣到得了頁面（瀏覽器會跟隨轉址）。
        # **刻意不自己合成轉址後的網址**：我只觀察過一次轉址，
        # 據一個樣本推斷規則，錯的時候會是**每一筆的網址都錯而且看起來很合法**。
        # 真正抓過詳細頁的那些，會用**實際觀察到的最終網址**覆寫（見 _fetch_details）。
        "url":       _absolute(detail_href) or TENDER_SOURCE_URL,
    }


def parse_list(html):
    """HTML → `(items, dropped, recognised)`。**純函式，不碰網路也不碰 DB。**

    - `recognised` 看**結構**（四個表頭字樣同時出現），**不看筆數**——
      「0 筆」正是「今天沒標案」與「它瞎了」共用的那個值。
    - `dropped` 是**解析失敗**的筆數，不含「某個選填欄位是空的」。
    """
    table = _find_result_table(html)
    if table is None:
        return [], 0, False

    items, dropped = [], 0
    for row in _TR_RE.findall(table):
        cells = _TD_RE.findall(row)
        if not cells:
            continue  # 表頭列用 <th>，不是資料
        parsed = _parse_row(cells)
        if parsed is None:
            dropped += 1
        else:
            items.append(parsed)
    return items, dropped, True


def suspect_redesign(parsed_count, dropped):
    """丟掉的比解出來的還多 ⇒ 疑似對方改版。**衍生判斷，刻意不放進 `parse_list`。**

    放進去的話那支函式會同時負責「解析」與「判斷健康度」，
    而健康度的門檻是會被調的——會被調的東西要能單獨驗。
    """
    total = (parsed_count or 0) + (dropped or 0)
    if total <= 0:
        return False
    return dropped > total / 2


def _absolute(href):
    """把列表頁的相對連結補成絕對網址。空的回空字串。"""
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return SITE_ROOT + (href if href.startswith("/") else "/" + href)


def _detail_field(html, field_id):
    """詳細頁上 `id="<field_id>"` 那一格的文字。找不到回 `None`。

    兩種引號都收：fixture 用雙引號，但不保證對方永遠不改。
    """
    for q in (chr(34), chr(39)):
        m = re.search("id=" + q + field_id + q + "[^>]*>(.*?)</", html, re.S)
        if m:
            return _text(m.group(1)) or None
    return None


def parse_detail(html):
    """詳細頁 HTML → `{"location": str|None, "tender_method": str|None}`。
    **純函式，不碰網路。**

    ⚠️ **只認 `id="fkPmsExecuteLocation"`。** 不要用「地址」字樣去找——
    那一頁「地址」出現 10 次，9 次是每一頁都一樣的樣板（六個監督機關＋頁尾工程會）。
    用字樣找的話**每一筆標案都會得到同一個臺北市信義區的地址**，
    而它看起來完全像一個合法地點，畫面上不會有任何異常。
    ⚠️ 而監督機關裡有一個**也在桃園市**，抽驗時「桃園市」三個字會讓人以為抓對了。
    """
    if not html:
        return {"location": None, "tender_method": None}
    # TD3：招標方式與地點在同一頁上 ⇒ 一次請求補兩格。
    method = _detail_field(html, _METHOD_FIELD_ID)
    raw = _detail_field(html, _LOCATION_FIELD_ID)
    if not raw:
        return {"location": None, "tender_method": method}
    # 括號後綴（「桃園市(非原住民地區)」）拆掉，只留縣市。
    place = re.split(r"[（(]", raw, maxsplit=1)[0].strip()
    # ⚠️ 非地名值（「全國」「依契約規定」「多個縣市」）**留 None 不要硬存**——
    # 硬存的話，下游「依地點篩選」會篩出一個叫「依契約規定」的縣市。
    # 🔑 跟 `0` vs `NULL` 同一族：**「不知道」不是一個值。**
    return {"location": place if place in _TW_PLACES else None,
            "tender_method": method}


def fetch_detail(url):
    """拿回一筆標案的詳細頁。回 `(html, error)`，**其中一個必為 None**。

    ⚠️ 簽名比照 `fetch_raw`：字串沒有辦法表達「我沒拿到」，
    而「抓不到」與「解析不出」的處置不一樣。
    """
    if not url:
        return None, "no url"
    if not radar_on():
        # 🔴 **總開關檢查在這個函式裡面，不在呼叫端。**
        # 今天唯一的呼叫端 `_fetch_details` 在 `run_scan()` 底下（那裡有守），
        # 所以「目前安全」——但那是**呼叫端剛好都在守衛底下**，不是這個函式安全。
        # 🔑 一個由呼叫端維持的不變量，會在**下一個呼叫端出現時**失效，
        # 而那跟 `DEFAULT_SCAN_HOUR` 靠「寫入端剛好擋了範圍」活下來是同一個形狀。
        # ⚠️ 而這個不變量是「**這台機器不會在沒有人知道的情況下對外連線**」——
        # 它是整條線最外層的那個承諾，不該取決於是誰叫的。
        return None, "標案雷達未啟用（需要 MOTRIX_TENDER_RADAR=1）"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Referer": TENDER_INDEX_URL,
        })
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", "replace"), resp.geturl()
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


DETAIL_COUNT_SETTING = "tender_radar_detail_fetched"


def _details_fetched_today(conn):
    """今天已經抓了幾筆詳細頁。存 `system_settings`，值是 `"YYYY-MM-DD:N"`。

    ⚠️ **日期一起存**：只存數字的話跨日不會歸零，而那會讓上限愈收愈緊，
    直到有一天完全不抓——**而症狀是「地圖上沒有點」，跟其他三個成因長得一樣。**

    🔴 **走傳進來的 `conn`，不可以用 `helpers.settings._get_setting`。**
    那兩支各自 `get_db()` 開**另一條連線**，而這裡是在 `_fetch_details` 裡面被叫的，
    外層那條 `conn` 正握著一個還沒 commit 的寫入交易
    ⇒ 新連線要寫就得等它 ⇒ **`sqlite3.OperationalError: database is locked`**。
    ⚠️ 我就是這樣把 13 題弄紅的，而那個錯誤訊息**完全不指向成因**：
    它說「資料庫被鎖住」，而真正的問題是「**我在自己的交易裡面又開了一條連線**」。
    """
    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key=?",
        (DETAIL_COUNT_SETTING,)).fetchone()
    if not row:
        return 0
    try:
        raw = json.loads(row["value_json"])
    except (TypeError, ValueError):
        return 0
    day, _, count = str(raw).partition(":")
    if day != today().isoformat():
        return 0
    try:
        return max(int(count), 0)
    except (TypeError, ValueError):
        return 0


def _remember_details_fetched(conn, total):
    """同上：走 `conn`，而且**值的格式要與 `_set_setting` 相同**（JSON）。

    ⚠️ 格式不一致的話，這裡寫進去的東西**別人讀不出來**，
    而 `_get_setting` 讀失敗時會安靜地回預設值 ⇒ 計數永遠是 0 ⇒ 上限形同不存在。
    """
    conn.execute(
        "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
        "updated_at=excluded.updated_at",
        (DETAIL_COUNT_SETTING,
         json.dumps(f"{today().isoformat()}:{int(total)}", ensure_ascii=False),
         _now_iso()))


def _backlog_detail_ids(conn, limit=None):
    """**既有**那些命中 watch 而還沒有地點的標案 id。

    🔴 TD3：`_fetch_details()` 一直只收 `run_scan()` 這一輪**新插入的** id
    ⇒ 既有那 200 筆**從來沒有進過那支函式** ⇒ `location` 全部是 NULL。
    ☠️ 而畫面上「來源沒寫」與「我們沒去抓」長得一模一樣。

    ⚠️ 安全閥一條都沒有放寬：這裡只是把 id 撈出來交給 `_fetch_details()`，
    D1（只抓命中的）／D2（每日上限）／D3（間隔）／D6（有地點的不抓）
    **全部由那支函式維持** —— 在這裡自己再判一次的話，兩份會分岔。
    """
    rows = conn.execute(
        "SELECT DISTINCT t.id FROM tenders t "
        "JOIN tender_hits h ON h.tender_id = t.id "
        "WHERE (t.location IS NULL OR t.location='') "
        "  AND t.url IS NOT NULL AND TRIM(t.url) <> '' "
        "ORDER BY t.id DESC" + (" LIMIT %d" % int(limit) if limit else "")
    ).fetchall()
    return [r["id"] for r in rows]


def _fetch_details(conn, tender_ids):
    """對**命中 watch 且還沒有地點**的標案抓詳細頁。回實際抓了幾筆。

    三道安全閥，而 **D1 是基礎**：
      D1 只對命中的抓 —— 把 N 從「當天所有公告」綁到「你真的在乎的那幾筆」。
                        沒有它，上限與間隔都只是在拖慢一件不該做的事。
      D2 每日硬上限（`DETAIL_DAILY_LIMIT`），超過就停並記進 log
      D3 每次之間間隔（`DETAIL_INTERVAL_SECONDS`）——對別人的伺服器的禮貌
      D6 已經有 `location` 的不再抓（冪等）

    ⚠️ **抓失敗／解析不出地點 → 那一筆標案照樣留著，`location` 是 NULL。**
    不可以因為拿不到地點就整筆丟掉——這條線的承諾是「不會漏掉標案」。
    """
    if not tender_ids:
        return 0
    marks = ",".join("?" * len(tender_ids))
    rows = conn.execute(
        f"SELECT DISTINCT t.id, t.url FROM tenders t "
        f"JOIN tender_hits h ON h.tender_id = t.id "        # D1：只有命中的
        f"WHERE t.id IN ({marks}) AND (t.location IS NULL OR t.location='') "  # D6
        f"ORDER BY t.id", tuple(tender_ids)).fetchall()

    # 🔴 **額度要跨呼叫累計，不可以是區域變數。**
    # 原本 `fetched = 0` 寫在這裡 ⇒ 實際語意是「**每次呼叫**最多 20 筆」。
    # 一天呼叫一次的時候兩者恰好相等——**那是巧合不是設計**，
    # 而改成一天四個時段之後，上限會**靜默變成 80**：
    # 功能照跑、畫面正常，只是對政府網站的負載變四倍，**而沒有任何測試會紅**。
    used_today = _details_fetched_today(conn)
    fetched = 0
    for i, r in enumerate(rows):
        if used_today + fetched >= DETAIL_DAILY_LIMIT:
            logger.warning("詳細頁抓取達每日上限 %d（今日已用 %d），其餘留到明天",
                           DETAIL_DAILY_LIMIT, used_today + fetched)
            conn.execute(
                "UPDATE tender_fetch_log SET error=? WHERE id=(SELECT MAX(id) FROM tender_fetch_log)",
                (f"詳細頁達每日上限 {DETAIL_DAILY_LIMIT}，剩 {len(rows) - fetched} 筆未抓",))
            break
        if i:
            time.sleep(DETAIL_INTERVAL_SECONDS)   # D3：走模組屬性，patch 得到
        html, second = fetch_detail(r["url"])
        fetched += 1
        if html is None:
            continue                 # D4：抓不到就算了，標案照樣留著
        detail = parse_detail(html)
        location = detail.get("location")
        method = detail.get("tender_method")
        # D20：用**實際觀察到的**最終網址覆寫（`second` 是 `resp.geturl()`）。
        final_url = second if (second and second.startswith("http")) else r["url"]
        # ⚠️ `COALESCE(?, tender_method)`：**解析不到就不要蓋掉已經有的**。
        # ☠️ 直接寫 `NULL` 的話，一次對方改版會把列表頁抓到的那一欄清光，
        #    而畫面上會從「有值」變成「—」，**沒有任何錯誤訊息**。
        conn.execute(
            "UPDATE tenders SET location=?, url=?, "
            "tender_method=COALESCE(?, tender_method) WHERE id=?",
            (location, final_url, method, r["id"]))
    if fetched:
        _remember_details_fetched(conn, used_today + fetched)
    return fetched


# ── 抓取 ─────────────────────────────────────────────────────────────────────

_DEFAULT_QUERY = {
    "searchType": "basic", "firstSearch": "true", "isBinding": "N", "isLogIn": "N",
    "level_1": "", "orgName": "", "orgId": "", "tenderName": "", "tenderId": "",
    "tenderType": "TENDER_DECLARATION", "tenderWay": "TENDER_WAY_ALL_DECLARATION",
    "dateType": "isNow", "radProctrgCate": "", "policyAdvocacy": "", "pageSize": "100",
}


def fetch_raw(params=None):
    """拿回列表頁 HTML。回 `(html, error)`，**其中一個必為 None**。

    ⚠️ 簽名不是 `-> str` 是刻意的：**字串沒有辦法表達「我沒拿到」**。
    回空字串的話，`parse_list` 同樣找不到容器 ⇒ `recognised=False` ⇒
    **「網站掛了」會跟「對方改版」長得一模一樣，而處置完全相反**：
    改版要改解析器，掛掉只要等它好。

    **不解析**。解析是 `parse_list` 的事——分開才驗得動。
    """
    import http.cookiejar

    query = dict(_DEFAULT_QUERY)
    query.update(params or {})
    try:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = [("User-Agent", USER_AGENT)]
        # 先取 cookie，否則查詢會被導回表單頁。
        opener.open(TENDER_INDEX_URL, timeout=FETCH_TIMEOUT_SECONDS).read()
        data = urllib.parse.urlencode(query).encode("utf-8")
        with opener.open(urllib.request.Request(TENDER_SOURCE_URL, data=data),
                         timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", "replace"), None
    except Exception as exc:  # noqa: BLE001 — 任何抓不到都是「抓不到」
        return None, f"{type(exc).__name__}: {exc}"


# ── 掃描（呼叫抓取的那一層）──────────────────────────────────────────────────

def _now_iso():
    """現在的時間字串。**走 `now_dt()`，不可以直接 `datetime.now()`。**

    🔴 這裡原本是 `datetime.now()`，而節流查的是 `now_dt()` 的小時
    ⇒ **寫入與查詢用了兩個不同的時間來源**：紀錄寫的是真實時鐘的小時，
    查詢找的是被換掉的那個小時 ⇒ **永遠對不上 ⇒ 節流完全失效**。
    🔑 而失效的方向是「**多抓**」——同一個時段內每觸發一次就真的抓一次。
    ⚠️ 症狀只在時間被換掉時出現（也就是只在測試裡），
    但成因是真的：**一個時間來源的模組，不可以有第二個入口。**
    """
    return now_dt().isoformat(timespec="seconds")


def _already_fetched_this_slot(conn):
    """**這個時段**抓過了沒。

    ⚠️ 名字從 `_already_fetched_today` 改過來，因為語意真的變了。
    🔑 **留著舊名字＝那個名字會說謊**，而那正是 `DETAIL_DAILY_LIMIT` 的毛病
    （它實際是「每次呼叫 20 筆」，只因為一天呼叫一次才剛好等於「每天 20」）。
    ⚠️ 而「留著舊名字但不再呼叫它」更糟：既有測試的 monkeypatch 會**靜默失效**
    ——patch 成功、沒有錯誤、而它什麼也沒做。**那是假綠燈不是相容性。**

    📌 節流仍然是對政府網站的承諾，只是承諾的單位從「一天一次」
    變成「**設定裡的每個時段各一次**」——使用者改得了幾點與幾次，
    **改不了「同一個時段內重複觸發只算一次」**。
    """
    hour = now_dt().hour
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM tender_fetch_log "
        "WHERE substr(fetched_at,1,10)=? AND CAST(substr(fetched_at,12,2) AS INTEGER)=?",
        (today().isoformat(), hour),
    ).fetchone()
    return (row["c"] if row else 0) > 0


def _log_fetch(conn, recognised, dropped, error, suspected=None):
    """留下這一次抓取的紀錄。**它是「雷達瞎了沒」唯一的判斷依據。**

    `recognised` 三個值不可以混：`NULL`＝根本沒解析、`0`＝解析過認不得、`1`＝認得。
    """
    conn.execute(
        "INSERT INTO tender_fetch_log (fetched_at, recognised, dropped, error, suspected) "
        "VALUES (?,?,?,?,?)",
        (_now_iso(), recognised, dropped, error or "", suspected),
    )


def _store(conn, items):
    """寫進 `tenders` 並比對 watch。回 `(新增標案數, 新增命中數)`。

    去重靠 `UNIQUE(org, case_no)` 與 `UNIQUE(watch_id, tender_id)`，不靠這裡的判斷——
    唯一鍵在資料庫裡，而程式碼裡的判斷會被下一個人改掉。
    """
    from modules.tender_radar.match import match_watches

    watches = []
    for r in conn.execute(
        "SELECT id, name, keywords, excludes, org, budget_min, budget_max, enabled "
        "FROM tender_watches WHERE enabled=1"
    ).fetchall():
        w = dict(r)
        for key in ("keywords", "excludes"):
            try:
                w[key] = json.loads(w[key] or "[]")
            except (ValueError, TypeError):
                w[key] = []
        watches.append(w)

    now, new_ids, new_hits = _now_iso(), [], 0
    for item in items:
        # 🔴 TD1：`tender_method` 與 `procurement_type` **解析出來了而沒有寫進去**。
        #
        # 四個地方裡三個是對的：`parse_list_row()` 解析了它們（:342-350）、
        # `tender_radar.py:347-348` 在讀、`email_notify.py:1826` 也在讀 ——
        # ☠️ 而這一行少了那兩個名字 ⇒ 畫面上 200 筆全部顯示「—」，
        # 🔑 **而那跟「來源本來就沒寫」長得一模一樣**，所以沒有人查得出來。
        # 📌 〈兩個都對而路不存在〉：今天第三次（前兩次是 `quotations.location_id`
        #    與 `_clean_locations()` 的五個抬頭欄位）。
        #
        # ⚠️ `INSERT OR IGNORE` ⇒ **既有那 200 筆不會被這一行補上**（`TD2`／`TD3`）。
        cur = conn.execute(
            "INSERT OR IGNORE INTO tenders "
            "(case_no, org, name, published_at, deadline, budget, url, "
            " tender_method, procurement_type, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (item["case_no"], item["org"], item["name"], item["published_at"],
             item["deadline"], item["budget"], item.get("url", ""),
             item.get("tender_method"), item.get("procurement_type"), now),
        )
        inserted = (cur.rowcount or 0) > 0
        row = conn.execute(
            "SELECT id FROM tenders WHERE org=? AND case_no=?",
            (item["org"], item["case_no"]),
        ).fetchone()
        if not row:
            continue
        if inserted:
            new_ids.append(row["id"])
        for w in match_watches(item, watches):
            cur = conn.execute(
                "INSERT OR IGNORE INTO tender_hits (watch_id, tender_id, hit_at) "
                "VALUES (?,?,?)",
                (w["id"], row["id"], now),
            )
            new_hits += cur.rowcount or 0
    return new_ids, new_hits


def run_scan():
    """跑一次掃描。**這是唯一呼叫 `fetch_raw` 的地方。**

    ⚠️ 開關走 `radar_on()`、`fetch_raw` 走模組屬性，兩個都在**呼叫當下**才取，
    所以測試 monkeypatch 得掉（`radar_on()` 讀的是模組全域 `TENDER_RADAR_ENABLED`，
    既有的 `monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)` 照樣有效）。
    呼叫端若寫成 `from tender_source import fetch_raw` 會複製走副本，
    計數器永遠是 0 而條件 8 永遠綠——**那題就什麼都沒證明**。
    """
    if not radar_on():
        return {"skipped": "disabled", "fetched": False}

    conn = get_db()
    try:
        if _already_fetched_this_slot(conn):
            # ⚠️ 失敗那一次**也算用掉了這個時段的額度**：§T.5「連不上 → 記 log、
            # 下次再試」，下次＝下一個時段。重試會把節流變成「失敗就無限重試」，
            # 而**失敗的時候正是對方最不希望被重試的時候**。
            return {"skipped": "slot_limit", "fetched": False}

        html, error = fetch_raw()
        if error is not None or html is None:
            # 抓不到 ⇒ 根本沒解析 ⇒ recognised 是 NULL，不是 False。
            _log_fetch(conn, None, 0, error or "empty response")
            conn.commit()
            return {"fetched": True, "error": error, "recognised": None}

        items, dropped, recognised = parse_list(html)
        suspected = suspect_redesign(len(items), dropped)
        _log_fetch(conn, 1 if recognised else 0, dropped, "",
                   suspected=1 if suspected else 0)
        new_ids, new_hits = ([], 0)
        if recognised:
            new_ids, new_hits = _store(conn, items)
            # 第二層：只對命中的標案抓詳細頁拿地點（D1～D6）。
            # TD3：新的先抓，**剩下的額度給既有的補**。
            # 🔑 順序是刻意的：新的那幾筆是使用者現在在看的東西。
            # ⚠️ 額度由 `_fetch_details()` 自己管（跨呼叫累計），所以第二次
            #    呼叫拿到的是**剩下的**，不是再一份完整的額度。
            _fetch_details(conn, new_ids)
            backlog = [i for i in _backlog_detail_ids(conn)
                       if i not in set(new_ids or [])]
            if backlog:
                _fetch_details(conn, backlog)
        conn.commit()
        return {
            "fetched": True, "error": None, "recognised": recognised,
            "parsed": len(items), "dropped": dropped,
            "suspect_redesign": suspected,
            "new_tenders": len(new_ids), "new_tender_ids": new_ids,
            "new_hits": new_hits,
        }
    finally:
        conn.close()

# ── 收件人 ───────────────────────────────────────────────────────────────────

# ⚠️ **收件人由各 `notify_*` 自己解析，呼叫端不先過濾。**
# 這是既有 44 支 `notify_*` 的一致做法（`to = _admin_emails(key); if not to: return`），
# 而且守門 `test_notification_prefs_coverage.py` 掃的正是那個 `_admin_emails(key)` 呼叫點。
# 我一度在這裡加了一道「沒有收件人就不呼叫」的閘門，拿掉了——理由見 B.md〈給彙整〉：
# 那道閘門能讓 N10 綠，但會讓 N1／N3／N5／N6／N9／N11 全紅，
# 因為 `conftest` 的每測試資料庫只有 demo 帳號、**沒有任何有 email 的 admin**。
# 兩者只能滿足一個，而慣例那一邊才是對的。


# ── 純記錄模式（SPEC §T.5 #3）───────────────────────────────────────────────

def _first_scan_at():
    raw = _get_setting(FIRST_SCAN_SETTING)
    return str(raw) if raw else ""


def _remember_first_scan(now_iso):
    """只在**第一次成功掃描**時寫一次。之後不再動它。"""
    if not _first_scan_at():
        _set_setting(FIRST_SCAN_SETTING, now_iso)


def _in_quiet_period():
    """首次成功掃描起 N 天內 → 只抓只存、不寄「找到標案」的信。

    ⚠️ **只擋「找到標案」，不擋異常告警。** 純記錄期的用途是「讓使用者先看關鍵字
    準不準」，而「雷達瞎了」跟關鍵字準不準無關——把它一起擋掉的話，
    第一週就壞掉的雷達會安靜地壞滿七天。
    """
    days = _days_since_first_scan()
    # ⚠️ **第 0 天（首次成功掃描當天）不算靜默期。**
    # 那一封正是使用者用來判斷關鍵字準不準的樣本，而純記錄期存在的理由就是
    # 「讓他先看準不準」——把它一起擋掉的話，這個機制就只剩下沉默。
    # 靜默的是第 1～7 天，第 8 天恢復。
    return days is not None and 0 < days <= QUIET_PERIOD_DAYS


def _days_since_first_scan():
    """距首次成功掃描幾天。沒有紀錄回 `None`（不是 0——那是兩件事）。"""
    raw = _first_scan_at()
    if not raw:
        return None
    try:
        first = date.fromisoformat(raw[:10])
    except ValueError:
        logger.warning("%s 的值不是日期：%r", FIRST_SCAN_SETTING, raw)
        return None
    return (today() - first).days


def _quiet_period_starts_after_this_mail():
    """這一封寄出去之後，是不是就要進入靜默期。

    ⚠️ **判斷條件是「寄完之後會不會靜默」，不是「現在在不在靜默期」**——
    在靜默期裡根本不會走到寄信這一步，後者永遠不會觸發。

    ⚠️ 而且這句話**只能出現在這一封**。每封都寫的話，第 8 天恢復之後的信
    也會說「接下來 7 天不會再寄信」——**那是錯的，收件人會第二次以為它壞了**。
    🔑 一個防止誤會的訊息，**貼錯位置會製造它原本要防的那個誤會**。
    """
    return _days_since_first_scan() == 0


# ── 邊緣觸發（SPEC §T.5 #5 vs §T.6 的裁決）──────────────────────────────────

def _previous_alert_state(conn):
    """上一次抓取是什麼狀態。**從資料庫讀，不是行程記憶體。**

    存在記憶體裡的話，異常期間重啟服務就會重新觸發一次邊緣、再寄一封
    （驗收條件 N13）。而「服務重啟」在正式機上是常態，不是例外。
    """
    row = conn.execute(
        "SELECT recognised, suspected FROM tender_fetch_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"failed": False, "suspected": False}
    return {"failed": row["recognised"] is None,
            "suspected": bool(row["suspected"])}


def _has_enabled_watch():
    """有沒有任何啟用中的搜尋條件。

    ⚠️ 一條都沒有時，「找到標案」的信會是一份**未經篩選的全部清單**。
    SPEC §T.4 自己寫著「沒有排除詞，這功能會在第三天就被使用者關掉」，
    而「一條件都沒有」比「沒有排除詞」更吵。
    ⚠️ 跟純記錄期疊起來更糟：**前 7 天正是還沒設定關鍵字的時候，
    第 8 天的第一封信會是一份沒篩選過的清單。**
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM tender_watches WHERE enabled=1").fetchone()
    finally:
        conn.close()
    return (row["c"] if row else 0) > 0


# `url` 一定要撈：信裡每一筆都要連得回來源，而**授權條款要求註明出處**
# （SPEC §T.5 #6）。N11 的觀測點是「傳給寄信函式的參數」，所以出處必須在資料裡，
# 不能只在 HTML 樣板裡——樣板在那個觀測點看不到。
_TENDER_COLS = ("id, case_no, org, name, published_at, deadline, budget, url")


def _load_unnotified_hits():
    """**還沒通知過的命中**（不是「這一輪新增的標案」）。

    ⚠️ 這個鍵選錯會讓重試永遠失效，而且我真的寫錯過：
    原本是「這一輪 `INSERT` 進去的標案」，於是投遞失敗之後再跑一次——
    `INSERT OR IGNORE` 判定那些標案**已經存在** ⇒ 新增 0 筆 ⇒ **一封都不會寄**，
    那批標案就此消失。**N12／N15「不標記」那一半是對的，而「下次要再寄」那一半
    需要另一個鍵才成立。**
    🔑 「不要記錄失敗」與「要記得重試」是兩件事，前者做對不代表後者會發生。
    """
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT DISTINCT t.{_TENDER_COLS.replace(', ', ', t.')} "
            "FROM tender_hits h JOIN tenders t ON t.id = h.tender_id "
            "WHERE h.notified_at IS NULL OR h.notified_at='' "
            "ORDER BY (t.deadline IS NULL), t.deadline"
        ).fetchall()
        hits = conn.execute(
            "SELECT h.id AS hit_id, w.name AS watch_name FROM tender_hits h "
            "JOIN tender_watches w ON w.id = h.watch_id "
            "WHERE h.notified_at IS NULL OR h.notified_at=''"
        ).fetchall()
    finally:
        conn.close()
    return ([dict(r) for r in rows],
            [r["hit_id"] for r in hits],
            [r["watch_name"] for r in hits])


def _load_tenders_by_ids(tender_ids):
    """依 id 撈標案。**只給 N17b 那一封用**（沒有搜尋條件 ⇒ 沒有命中可撈）。"""
    if not tender_ids:
        return []
    marks = ",".join("?" * len(tender_ids))
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT {_TENDER_COLS} FROM tenders WHERE id IN ({marks}) "
            f"ORDER BY (deadline IS NULL), deadline", tuple(tender_ids)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _mark_hits_notified(hit_ids):
    """**只有寄信成功之後才呼叫。**

    在寄信之前標記的話，SMTP 掛掉那一次的標案**永遠不會再出現在任何一封信裡**，
    而且不會有任何錯誤訊息（驗收條件 N12）。
    """
    if not hit_ids:
        return
    conn = get_db()
    try:
        now = _now_iso()
        conn.executemany("UPDATE tender_hits SET notified_at=? WHERE id=?",
                         [(now, h) for h in hit_ids])
        conn.commit()
    finally:
        conn.close()


def _notify_health(result, previous):
    """抓取健康度的兩種告警。**綁在「有沒有抓」上，不是綁在寄信時段上。**

    🔴 為什麼與彙總信分家：**它們回答的是不同的問題。**
    「站台抓不到了」是**這一次抓取**的結果，晚幾個小時才講就失去意義；
    而彙總信是「今天有哪些新標案」，那是使用者自己排的節奏。
    ⚠️ 綁在一起的話，把寄信時段設成空（＝不寄彙總信）會**順手關掉故障告警**——
    **而使用者以為他只是不想每天收標案清單。**

    三種事件各自一個 key、各自邊緣觸發。**任何情況都不把例外往外丟。**
    """
    from helpers import email_notify

    failed = result.get("error") is not None or result.get("recognised") is None
    if failed:
        # 邊緣觸發：只有「從正常進入異常」那一次寄。
        # 準位觸發的話，站台掛一週就是七封信——**狼來了的告警等於沒有告警**。
        if not previous["failed"]:
            try:
                email_notify.notify_tender_fetch_failed(result.get("error") or "")
            except Exception:  # noqa: BLE001
                logger.exception("notify_tender_fetch_failed failed")
        return

    if result.get("suspect_redesign") and not previous["suspected"]:
        try:
            email_notify.notify_tender_source_changed(
                result.get("parsed", 0), result.get("dropped", 0))
        except Exception:  # noqa: BLE001
            logger.exception("notify_tender_source_changed failed")

    return


def _notify_found(result=None):
    """彙總信：**這個寄信時段要不要寄、寄什麼。** 回傳有沒有真的寄出去。

    🔴 判準是「**有沒有未通知的命中**」，不是「這一輪有沒有新增標案」。
    `INSERT OR IGNORE` 會讓重試時「新增 0 筆」，於是那批標案就此消失——
    **「不要記錄失敗」與「要記得重試」是兩件事。**

    📌 `result` 可以是 `None`：寄信時段不一定跟著一次抓取
    （設定成「抓 9／寄 18」時，18 點根本沒有 `result`）。
    """
    from helpers import email_notify

    # ⚠️ 疑似改版時**仍然照常通知解析成功的那幾筆**：它們通過了形狀驗證，
    # 是真的標案。因為版面有疑慮就整批不通知的話，**會漏掉真的標案**，
    # 而「不會漏掉標案」正是這條線的承諾。
    # ⚠️ **先判斷再記錄，順序不可以顛倒。**
    # 反過來的話，第一次成功掃描會把起算點設成今天，然後立刻掉進自己剛設的
    # 靜默期裡——「首次啟用」那一封永遠寄不出去，而那一封正是使用者用來判斷
    # 關鍵字準不準的依據（純記錄期存在的理由）。
    quiet = _in_quiet_period()
    _remember_first_scan(_now_iso())
    if quiet:
        return False
    announce = _quiet_period_starts_after_this_mail()
    has_watches = _has_enabled_watch()
    tenders, hit_ids, watch_names = _load_unnotified_hits()

    if not tenders:
        # 沒有未通知的命中，兩種情況要分開：
        #   有條件但今天沒中 → 不寄（今天沒標案不是異常，不該打擾任何人）
        #   一條條件都沒有   → N17：不寄「找到標案」的信（那是未篩選的全部），
        #                      **但 N17b：純記錄期開始那一封仍然要寄**
        # ⚠️ 少了 N17b 的話，使用者啟用之後會收到**完全的沉默**，
        # 而沉默跟「壞掉了」長得一模一樣——那正是 N14 在防的事，只是換一個入口。
        if has_watches or not announce:
            return False
        tenders = _load_tenders_by_ids((result or {}).get("new_tender_ids") or [])
        hit_ids, watch_names = [], []
        if not tenders:
            return False
    try:
        email_notify.notify_tender_found(
            tenders, watch_names,
            announce_quiet_period=announce,
            no_watches=not has_watches)
    except Exception:  # noqa: BLE001
        logger.exception("notify_tender_found failed；已通知標記不會被設定")
        return False    # ⚠️ 不標記——見 _mark_hits_notified 的說明
    _mark_hits_notified(hit_ids)
    return True


# ── 排程 ─────────────────────────────────────────────────────────────────────

def _slot_key(hour):
    """`"2026-09-21:18"`。**日期一起帶**，否則昨天 18 點會擋掉今天 18 點。"""
    return f"{today().isoformat()}:{int(hour):02d}"


def _already_notified_this_slot(hour):
    """這個寄信時段寄過沒。單鍵 ＋ `>=` 比較。

    📌 `>=` 而不是 `==`：同一個時段重複觸發要擋掉，而萬一時鐘往回跳
    （或有人手動改設定造成順序錯亂），**寧可少寄一封也不要重寄一封**。
    """
    mark = _get_setting(NOTIFY_MARK_SETTING)
    return bool(mark) and str(mark) >= _slot_key(hour)


def run_scheduled_scan():
    """排程的執行體。**模組層級的具名函式，不是巢狀 closure。**

    既有四支排程的執行體都是 closure（`_loop`／`_run_all`／`_daily_run`），
    **測試從外面叫不到** ⇒ 只能等 Timer。這裡具名是為了讓它驗得動。

    ## 🔑 兩個判斷，兩個入口，刻意不共用
    ```
    抓取  current_slot()      ← 內部讀 scan_hours()
    寄信  now_dt().hour       ← 直接比對 notify_hours()
    ```
    ⚠️ **寄信不可以問 `current_slot()`**：它在「抓 9／寄 18」那種設定下，
    18 點時回 `None` ⇒ **永遠拿不到小時，而那時正是要寄信的時候**。
    📌 這個錯在預設設定下看不出來（預設抓 9,12,15,18、寄 18，兩者重疊），
    **要等到有人把兩份設定設成不重疊那天才爆。**
    """
    slot = current_slot()
    result = None
    if slot is not None:
        previous = {"failed": False, "suspected": False}
        try:
            conn = get_db()
            try:
                previous = _previous_alert_state(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            logger.exception("讀取上一次抓取狀態失敗，這一輪以「先前正常」處理")

        result = run_scan()
        if result and not result.get("skipped"):
            try:
                _notify_health(result, previous)
            except Exception:  # noqa: BLE001
                logger.exception("標案雷達健康告警失敗")

    hour = now_dt().hour
    if hour in notify_hours() and not _already_notified_this_slot(hour):
        try:
            if _notify_found(result):
                # ⚠️ **只有真的寄出去才標記。** 先標記再寄的話，一次失敗會吃掉
                # 整個時段的重試，而那正是第 5 輪 N15 的教訓。
                _set_setting(NOTIFY_MARK_SETTING, _slot_key(hour))
        except Exception:  # noqa: BLE001
            logger.exception("標案雷達彙總信失敗")
    return result


def _parse_hours(raw, fallback, what):
    """`"9,12,15,18"` → `(9, 12, 15, 18)`。排序去重。

    🔴 **空字串是合法值，不是「沒設定」**：抓取設成空＝完全不抓，
    寄信設成空＝不寄。**「可調整」包含「調成不要」**，而那是最容易被實作漏掉的值，
    因為它看起來像「還沒設」。

    ⚠️ **不合法時退回 `fallback`，而 `fallback` 必須是一個真的存在的具名常數。**
    這裡原本寫的是 `DEFAULT_SCAN_HOUR` —— **那個名字從來沒有被定義過**，
    也就是說「值超出 0-23」這條防禦分支一被走到就是 `NameError`。
    🔑 它活下來是因為寫入端擋了範圍（`tender_radar.py` 的 422），
    **也就是那道防禦從來沒有真的防過任何東西，而它看起來一直在那裡。**
    ⇒ 而那正是這類 bug 唯一能長期存活的地方：**只有異常時才走到的路徑**。

    ⚠️ 部分不合法時**整份退回**，不是「跳過壞的那幾個」——
    跳過會讓 `"9,25,15"` 變成「抓 9 與 15」，而使用者以為他設了三個時段。
    **降級之後它還是會動，而沒有人會發現。**
    """
    if raw is None:
        return tuple(fallback)
    text = str(raw).strip()
    if not text:
        return ()
    hours = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
        except (TypeError, ValueError):
            logger.warning("%s 設定值 %r 不是整數，整份退回預設 %r", what, raw, fallback)
            return tuple(fallback)
        if not 0 <= h <= 23:
            logger.warning("%s 設定值 %r 含超出 0-23 的小時，整份退回預設 %r",
                           what, raw, fallback)
            return tuple(fallback)
        hours.append(h)
    return tuple(sorted(set(hours)))


def parse_hours_strict(raw):
    """寫入端用：解析時段字串，**不合法就丟 `ValueError`，不退回預設**。

    🔴 與 `_parse_hours`（讀取端）是**兩條路，刻意不共用**：
    - **讀取端**遇到壞掉的設定要**退回預設**——那時使用者不在現場，
      而「排程整個不跑」比「用預設時段跑」糟。
    - **寫入端**遇到壞掉的輸入要**當場拒絕**——使用者正在看著畫面，
      **這是唯一能把錯誤講給他聽的時刻**。
    ⚠️ 共用一支的話，只會剩下其中一種行為：
    要嘛使用者打錯字而系統靜默改成預設（他以為存好了），
    要嘛排程因為一筆舊的壞資料而完全不跑。
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ()
    hours = []
    for part in text.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
        except (TypeError, ValueError):
            raise ValueError(f"「{part}」不是整數")
        if not 0 <= h <= 23:
            raise ValueError(f"「{part}」不在 0-23 的範圍內")
        hours.append(h)
    # ⚠️ 去重：`"9,9,9"` 是 1 個時段不是 3 個。不去重的話節流仍然正確
    # （同一個時段只抓一次），但**門檻判定會被灌水**，而那會讓確認視窗
    # 在使用者只設了一個時段時跳出來。
    return tuple(sorted(set(hours)))


def _hours_setting(key, legacy_key, fallback, what):
    """讀時段設定，必要時從舊的單數鍵遷移。

    🔴 **判準是「鍵存在嗎」，不是「值是不是真的」。**
    寫成 `new or old` 的話：使用者把寄信時段**設成空**（合法值＝不寄）
    ⇒ 空字串是 falsy ⇒ **退回舊值 ⇒ 它又開始寄了**，而畫面上看起來完全正常。
    📌 同一天在 `quotations.py:1379` 找到同型的一個（`body.status or ...`，
    而左邊有 truthy 預設 ⇒ 右邊整段是死碼）。

    ⚠️ 舊的單數鍵**留著不刪**：刪掉就沒有回頭路，而留著的成本是這幾行。
    """
    raw = _get_setting(key)
    if raw is not None:
        return _parse_hours(raw, fallback, what)
    if legacy_key:
        old = _get_setting(legacy_key)
        if old is not None:
            # 舊值是單一小時（0-23）⇒ 語意等於「一天一個時段」。
            return _parse_hours(str(old), fallback, what)
    return tuple(fallback)


def scan_hours():
    """每天哪幾個時段抓。空 tuple ＝ 完全不抓（合法設定）。"""
    return _hours_setting(SCAN_HOURS_SETTING, SCAN_HOUR_SETTING,
                          SCAN_HOURS, "抓取時段")


def notify_hours():
    """每天哪幾個時段寄彙總信。空 tuple ＝ 不寄（合法設定）。"""
    return _hours_setting(NOTIFY_HOURS_SETTING, None,
                          NOTIFY_HOURS, "寄信時段")


def current_slot():
    """現在屬於哪一個**抓取**時段；不在設定裡就回 `None`。

    ⚠️ **這個函式只回答抓取那一側。** 寄信要問 `now_dt().hour`，不可以問這裡——
    它內部讀的是 `scan_hours()`，所以「抓 9／寄 18」那種設定下，
    **18 點時它回 `None`，而那時候正是要寄信的時候**。
    🔑 **兩個設定是獨立的，所以判斷時段的入口也必須是獨立的。**
    📌 而這個錯不會在預設設定下出現（預設兩者重疊），
    要等到有人設「抓 9,15／寄 9,12,15,18」那天才爆。
    """
    hour = now_dt().hour
    return hour if hour in scan_hours() else None


def _seconds_until_next_run():
    """到下一個**時段**（抓取或寄信，取較近的那個）還有幾秒。

    ⚠️ 走 `now_dt()`，**不可以直接 `datetime.now()`**——原本那一版就是直接叫的，
    所以測試 patch 不到它，而那是那四個時段邊界上偶爾紅的來源之一。

    📌 **抓取與寄信的時段都要排**：設定成「抓 9／寄 18」時，
    只排抓取時段的話 **18 點沒有人會醒來，信就永遠不會寄**。
    🔑 **排程的醒來時機，是所有時段的聯集。**
    """
    now = now_dt()
    hours = sorted(set(scan_hours()) | set(notify_hours()))
    if not hours:
        # 兩份設定都是空的 ⇒ 沒有任何事要做。
        # ⚠️ 仍然要醒來：設定隨時可能被改回來，而**睡死的排程叫不醒**。
        return 3600.0
    candidates = []
    for h in hours:
        nxt = now.replace(hour=h, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        candidates.append((nxt - now).total_seconds())
    return max(min(candidates), 1.0)


def schedule_tender_scan():
    """啟動時呼叫一次：跑一輪，然後排下一次。

    ⚠️ **不可以抄既有四支的形狀。** `archive._schedule_daily` 把工作放在 Timer
    重排**之前**而且沒包 try——丟一次例外就永遠不會再排，**排程靜默死亡**，
    而「排程死了」跟「今天沒事做」長得一模一樣。
    ⇒ 這裡工作包在 `try` 裡，**重排放在 `finally`**：不管發生什麼，下一次一定排得上。

    ⚠️ `threading.Timer` 走模組屬性，`from threading import Timer` 會讓
    monkeypatch 打不到 ⇒ S3 永遠綠。
    """
    try:
        run_scheduled_scan()
    except Exception:  # noqa: BLE001
        logger.exception("run_scheduled_scan failed")
    finally:
        t = threading.Timer(_seconds_until_next_run(), schedule_tender_scan)
        t.daemon = True
        t.start()

