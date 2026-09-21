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
from datetime import date, timedelta

from db import get_db
from helpers import notification_prefs
from helpers.settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# **預設關。它會對外連線，預設就不該是開的。**
# 關著時**連 `fetch_raw` 都不會被呼叫**——不是「呼叫了但不做事」。
# 那個差別驗得出來（條件 8 的觀測點是呼叫次數，不是有沒有產生資料），
# 而「沒產生資料 ≠ 沒被呼叫」正是 licensing middleware 那次的教訓。
TENDER_RADAR_ENABLED = False

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
SCAN_HOUR = 8            # 預設時間。具名常數才驗得到「預設值是多少」（D14）
SCAN_HOUR_SETTING = "tender_radar_scan_hour"

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


def parse_detail(html):
    """詳細頁 HTML → `{"location": str|None}`。**純函式，不碰網路。**

    ⚠️ **只認 `id="fkPmsExecuteLocation"`。** 不要用「地址」字樣去找——
    那一頁「地址」出現 10 次，9 次是每一頁都一樣的樣板（六個監督機關＋頁尾工程會）。
    用字樣找的話**每一筆標案都會得到同一個臺北市信義區的地址**，
    而它看起來完全像一個合法地點，畫面上不會有任何異常。
    ⚠️ 而監督機關裡有一個**也在桃園市**，抽驗時「桃園市」三個字會讓人以為抓對了。
    """
    if not html:
        return {"location": None}
    # 兩種引號都收：fixture 用雙引號，但不保證對方永遠不改。
    m = None
    for q in (chr(34), chr(39)):
        m = re.search("id=" + q + _LOCATION_FIELD_ID + q + "[^>]*>(.*?)</",
                      html, re.S)
        if m:
            break
    if not m:
        return {"location": None}
    raw = _text(m.group(1))
    # 括號後綴（「桃園市(非原住民地區)」）拆掉，只留縣市。
    place = re.split(r"[（(]", raw, maxsplit=1)[0].strip()
    # ⚠️ 非地名值（「全國」「依契約規定」「多個縣市」）**留 None 不要硬存**——
    # 硬存的話，下游「依地點篩選」會篩出一個叫「依契約規定」的縣市。
    # 🔑 跟 `0` vs `NULL` 同一族：**「不知道」不是一個值。**
    return {"location": place if place in _TW_PLACES else None}


def fetch_detail(url):
    """拿回一筆標案的詳細頁。回 `(html, error)`，**其中一個必為 None**。

    ⚠️ 簽名比照 `fetch_raw`：字串沒有辦法表達「我沒拿到」，
    而「抓不到」與「解析不出」的處置不一樣。
    """
    if not url:
        return None, "no url"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Referer": TENDER_INDEX_URL,
        })
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", "replace"), resp.geturl()
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


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

    fetched = 0
    for i, r in enumerate(rows):
        if fetched >= DETAIL_DAILY_LIMIT:
            logger.warning("詳細頁抓取達每日上限 %d，其餘留到明天", DETAIL_DAILY_LIMIT)
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
        location = parse_detail(html).get("location")
        # D20：用**實際觀察到的**最終網址覆寫（`second` 是 `resp.geturl()`）。
        final_url = second if (second and second.startswith("http")) else r["url"]
        conn.execute("UPDATE tenders SET location=?, url=? WHERE id=?",
                     (location, final_url, r["id"]))
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
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _already_fetched_today(conn):
    """今天抓過了沒。**每日一次是對別人的伺服器的承諾，不是對我們自己的。**"""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM tender_fetch_log WHERE substr(fetched_at,1,10)=?",
        (today().isoformat(),),
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
    from helpers.tender_match import match_watches

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
        cur = conn.execute(
            "INSERT OR IGNORE INTO tenders "
            "(case_no, org, name, published_at, deadline, budget, url, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (item["case_no"], item["org"], item["name"], item["published_at"],
             item["deadline"], item["budget"], item.get("url", ""), now),
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

    ⚠️ `TENDER_RADAR_ENABLED` 與 `fetch_raw` 都在**呼叫當下**才從模組取，
    所以測試 monkeypatch 得掉。呼叫端若寫成 `from tender_source import fetch_raw`
    會複製走副本，計數器永遠是 0 而條件 8 永遠綠——**那題就什麼都沒證明**。
    """
    if not TENDER_RADAR_ENABLED:
        return {"skipped": "disabled", "fetched": False}

    conn = get_db()
    try:
        if _already_fetched_today(conn):
            # ⚠️ 失敗那一次也算用掉了今天的額度：§T.5「連不上 → 記 log、下次再試」，
            # 下次＝明天。重試會把「每日一次」變成「失敗就無限重試」。
            return {"skipped": "daily_limit", "fetched": False}

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
            _fetch_details(conn, new_ids)
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


def _notify(result, previous):
    """依這一輪的結果決定要不要寄信。**任何情況都不把例外往外丟。**

    三種事件各自一個 key、各自邊緣觸發：
      抓不到（`tender_fetch_failed`）／疑似改版（`tender_source_changed`）／
      找到標案（`tender_found`，每日一封彙總）
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
        return
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
            return
        tenders = _load_tenders_by_ids(result.get("new_tender_ids") or [])
        hit_ids, watch_names = [], []
        if not tenders:
            return
    try:
        email_notify.notify_tender_found(
            tenders, watch_names,
            announce_quiet_period=announce,
            no_watches=not has_watches)
    except Exception:  # noqa: BLE001
        logger.exception("notify_tender_found failed；已通知標記不會被設定")
        return          # ⚠️ 不標記——見 _mark_hits_notified 的說明
    _mark_hits_notified(hit_ids)


# ── 排程 ─────────────────────────────────────────────────────────────────────

def run_scheduled_scan():
    """排程的執行體。**模組層級的具名函式，不是巢狀 closure。**

    既有四支排程的執行體都是 closure（`_loop`／`_run_all`／`_daily_run`），
    **測試從外面叫不到** ⇒ 只能等 Timer。這裡具名是為了讓它驗得動。
    """
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
    if not result or result.get("skipped"):
        return result
    try:
        _notify(result, previous)
    except Exception:  # noqa: BLE001
        logger.exception("標案雷達通知失敗")
    return result


def scan_hour():
    """每天幾點掃。存 `system_settings`（有進每日 JSON 備份）。

    ⚠️ **只能改「幾點」不能改「幾次」**：每日一次的硬上限由
    `_already_fetched_today()` 把關，**不因這個設定而改變**（D13）。
    那個上限是對別人的伺服器的承諾，不是我們自己的偏好。
    """
    raw = _get_setting(SCAN_HOUR_SETTING)
    try:
        h = int(raw)
    except (TypeError, ValueError):
        return SCAN_HOUR
    return h if 0 <= h <= 23 else DEFAULT_SCAN_HOUR


def _seconds_until_next_run():
    """下一次掃描時間。比照 `daily_tasks`／`dev_crm` 既有兩支的作法。"""
    from datetime import datetime
    now = datetime.now()
    nxt = now.replace(hour=scan_hour(), minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return max((nxt - now).total_seconds(), 1.0)


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

