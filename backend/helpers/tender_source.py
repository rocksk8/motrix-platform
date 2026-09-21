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
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

from db import get_db

# ── 總開關 ───────────────────────────────────────────────────────────────────
#
# **預設關。它會對外連線，預設就不該是開的。**
# 關著時**連 `fetch_raw` 都不會被呼叫**——不是「呼叫了但不做事」。
# 那個差別驗得出來（條件 8 的觀測點是呼叫次數，不是有沒有產生資料），
# 而「沒產生資料 ≠ 沒被呼叫」正是 licensing middleware 那次的教訓。
TENDER_RADAR_ENABLED = False

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
_COL_PUBLISHED, _COL_DEADLINE, _COL_BUDGET = 6, 7, 8
_MIN_COLUMNS = 9

_DATE_SANITY_YEARS = 5
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

    return {
        "case_no":   case_no,
        "name":      name,
        "org":       org,
        "published": published.isoformat() if published else None,
        "deadline":  deadline.isoformat() if deadline else None,
        "budget":    budget,
        "url":       TENDER_SOURCE_URL,
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


def _log_fetch(conn, recognised, dropped, error):
    """留下這一次抓取的紀錄。**它是「雷達瞎了沒」唯一的判斷依據。**

    `recognised` 三個值不可以混：`NULL`＝根本沒解析、`0`＝解析過認不得、`1`＝認得。
    """
    conn.execute(
        "INSERT INTO tender_fetch_log (fetched_at, recognised, dropped, error) "
        "VALUES (?,?,?,?)",
        (_now_iso(), recognised, dropped, error or ""),
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

    now, new_tenders, new_hits = _now_iso(), 0, 0
    for item in items:
        cur = conn.execute(
            "INSERT OR IGNORE INTO tenders "
            "(case_no, org, name, published_at, deadline, budget, url, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (item["case_no"], item["org"], item["name"], item["published"],
             item["deadline"], item["budget"], item.get("url", ""), now),
        )
        new_tenders += cur.rowcount or 0
        row = conn.execute(
            "SELECT id FROM tenders WHERE org=? AND case_no=?",
            (item["org"], item["case_no"]),
        ).fetchone()
        if not row:
            continue
        for w in match_watches(item, watches):
            cur = conn.execute(
                "INSERT OR IGNORE INTO tender_hits (watch_id, tender_id, hit_at) "
                "VALUES (?,?,?)",
                (w["id"], row["id"], now),
            )
            new_hits += cur.rowcount or 0
    return new_tenders, new_hits


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
        _log_fetch(conn, 1 if recognised else 0, dropped, "")
        new_tenders = new_hits = 0
        if recognised:
            new_tenders, new_hits = _store(conn, items)
        conn.commit()
        return {
            "fetched": True, "error": None, "recognised": recognised,
            "parsed": len(items), "dropped": dropped,
            "suspect_redesign": suspect_redesign(len(items), dropped),
            "new_tenders": new_tenders, "new_hits": new_hits,
        }
    finally:
        conn.close()
