"""§3q · 命中另外列出＋手動搜尋＋機關名稱當定位依據（Q1–Q10）。

> **使用者：「標案雷達有命中的搜尋條件的要額外列出，或是我手動搜尋特定的也可以獨立顯示」**
> **「機關名稱基本上就是地圖搜尋的名稱」**

---

# ⚠️ 我釘什麼、不釘什麼

## 不釘：**命中區排在全部清單之上**（Q1 的排版那一半）

`matchedWatches` 已經在每一筆上（§3p 的 P6），**前端拿它自己分區就成立**。
⇒ 我若釘後端回一個獨立的 `matched` 陣列，就是**把一種實作寫成不變量** ——
而一個在前端分區的正確實作會紅。
🔑 今晚第四次同一個機會（CSP 萬用子網域／連線洩漏的 `with`／P14 的 precision 值）。

## 釘：**後端分辨得出來、而前端分辨不出來的那些**

**Q3／Q4 是這一節真正的後端條件**，理由都是同一個形狀：

| | 為什麼非後端不可 |
|---|---|
| **Q3** 手動搜尋要套 `tender_match.normalize` | 那是 Python。前端自己寫一套異體字表 ⇒ **同一個字，兩個地方兩種結果** |
| **Q4** 命中區為空要說出為什麼 | 「沒有搜尋條件」與「有條件但沒命中」⇒ **前端要再打一支 API 才分得出來**，而那是兩次往返加一個競態 |

⇒ 所以手動搜尋**必須是後端的查詢參數**（`?q=`），不是前端的 `Array.filter`。

---

# 🔴 Q8：規格文字已經過期，我照 A 的裁定寫

規格 §3q 現在還寫著兩件已被推翻的事：

1. 「`交通部民用航空局飛航…` ← **名稱在資料庫裡被截斷**」
   ⚠️ **不是。** 我量過 `tenders` 的 200 筆／158 個相異 `org`：
   完整值是 `交通部民用航空局飛航服務總臺`（14 字），
   **以 `…`／`...` 結尾的相異名稱：0 個**，最長 19 字而且長度分布連續
   （尖峰在 12，不是在最大值 ⇒ **沒有上限的特徵**）。
   A 複驗後確認：被截斷的是**它自己的 print**（`unicode_escape` 讓每個中文字
   變成 6 個字元，`[:60]` 只印了 10 個字）。
2. 「或**長度剛好等於某個上限**時不可以拿去查」
   ⇒ **A 已裁定拿掉這一半**：資料裡沒有那個上限，那個常數只能用猜的，
   而**猜高了它永遠不觸發（跟運作良好長得一樣），猜低了它砍掉合法名稱**。

✅ **保留的是那個不對稱**，它本身沒有被推翻：
🔑 **查不到會退階（安全），查到錯的不會。**
「交通部民用航空局飛航」如果剛好命中某個不相關的地點，
**我們會得到一個看起來合理而完全錯誤的座標。**
"""
import pytest

from helpers import geo
from helpers import tender_match

TENDERS_PATH = "/api/tender-radar/tenders"

#: 一個**真的查得到**的機關名稱（A 實測：建物級座標）。
ORG_FINDABLE = "交通部航港局"
ORG_COORD = (25.0252831, 121.5470035)

#: 一個名稱本身沒有地點資訊的機關（A 實測 FAIL，正當退階）。
ORG_UNFINDABLE = "中華郵政股份有限公司"

#: 被截斷的名稱。⚠️ **資料庫裡目前一個都沒有** —— 這是合成的。
#: 🔑 而那正是 Q8 要的：一道**現在不會觸發**的守門，必須有一題證明它活著。
ORG_TRUNCATED = "交通部民用航空局飛航…"

LOCATION = "台北市"
LOCATION_COORD = (25.0375198, 121.5636796)


@pytest.fixture(autouse=True)
def _isolate_geo(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    table = {ORG_FINDABLE: (ORG_COORD, geo.PRECISION_STREET),
             LOCATION: (LOCATION_COORD, geo.PRECISION_DISTRICT)}

    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        hit = table.get(key)
        if not hit:
            return geo.GeoResult(error="測試查表裡沒有：%r" % key, address=key)
        return geo.GeoResult(coord=hit[0], precision=hit[1],
                             source=geo.SOURCE_NOMINATIM, address=key)

    monkeypatch.setattr(geo, "locate_cached", _fake)


def _auth(client, make_user, **kw):
    kw.setdefault("role", "superadmin")
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def seeded(client):
    """三筆標案 ＋ 零個搜尋條件。**條件由各題自己加**（Q4 要分辨有沒有條件）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tender_watches")
        rows = [
            ("Q-001", "臺中市政府採購案", "臺中市政府", "臺中市"),
            ("Q-002", "台北港務工程", ORG_FINDABLE, LOCATION),
            ("Q-003", "郵務車採購", ORG_UNFINDABLE, LOCATION),
        ]
        for case_no, name, org, loc in rows:
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
                "VALUES (?,?,?,?,?)",
                (case_no, name, org, loc, "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return 3


def _add_watch(keyword):
    """加一筆搜尋條件。

    ⚠️ 欄位是 `name` ＋ **`keywords`（JSON 陣列）**，不是 `keyword` ——
    我第一版憑印象寫成單數的 `keyword`，而 sqlite 直接
    `no column named keyword` 把我擋下來。
    📌 今天第四次「列一張表／寫一個欄位名的時候用回想代替查」，
    而這一次**是資料庫替我擋的**，不是我自己想到要查。
    """
    import json

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tender_watches (name, keywords, excludes, enabled, "
            "created_at, updated_at) VALUES (?,?,'[]',1,?,?)",
            (keyword, json.dumps([keyword], ensure_ascii=False),
             "2026-09-22T00:00:00", "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _list(client, hdr, query=""):
    r = client.get(TENDERS_PATH + ("?" + query if query else ""), headers=hdr)
    assert r.status_code == 200, f"?{query} 回 {r.status_code}：{r.text[:220]}"
    return r.json()


def _items(body):
    """清單本體。**兩種回傳形狀都接受**（裸陣列或帶外殼的物件）。

    ⚠️ 刻意不釘外殼的形狀：Q4 要求多一個欄位，而那讓回傳可能從
    裸陣列變成物件。**兩種都是對的實作**，釘死其中一種會在另一種上變紅。
    """
    if isinstance(body, list):
        return body
    for key in ("tenders", "items", "rows", "data"):
        if isinstance(body.get(key), list):
            return body[key]
    raise AssertionError(f"找不到清單本體，回傳的鍵有：{sorted(body)}")


# ══════════════════════════════════════════════════════════════════════
# Q1 · 命中的要標示出來（**標示**，排版不釘）
# ══════════════════════════════════════════════════════════════════════

def test_q1_every_tender_says_which_watches_matched_it(
        client, make_user, seeded):
    """🔴 Q1：每一筆都要說得出**是哪幾個條件命中它**，而沒命中的也照樣在清單裡。

    📌 **不釘「命中區排在上面」** —— 那是排版，前端拿 `matchedWatches`
    自己分區就成立，釘了會讓一個正確的前端分區實作變紅。
    🔑 我釘的是「**後端說得出來**」，不是「後端排好了」。
    """
    _add_watch("臺中")
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr))

    assert len(items) == seeded, (
        f"清單裡有 {len(items)} 筆，而資料庫裡有 {seeded} 筆 —— "
        "沒命中的也要看得到（§3p 的 P5）。"
    )
    by_case = {it["case_no"] if "case_no" in it else it.get("caseNo"): it
               for it in items}
    hit = by_case.get("Q-001")
    assert hit, f"找不到 Q-001，鍵是：{sorted(by_case)}"
    assert hit.get("matchedWatches"), (
        f"`臺中市政府` 應該被條件「臺中」命中：{hit}"
    )
    miss = by_case.get("Q-003")
    assert miss.get("matchedWatches") in ([], None), (
        f"`郵務車採購` 不該被「臺中」命中：{miss}"
    )


# ══════════════════════════════════════════════════════════════════════
# Q2 / Q3 / Q5 · 手動搜尋
# ══════════════════════════════════════════════════════════════════════

def test_q2_a_manual_search_filters_the_list(client, make_user, seeded):
    """🔴 Q2：`?q=` 即時篩選，**而且不會被存成 watch**。

    ⚠️ 兩半都要驗。少了後半，一個「把 q 存成一筆 watch 再篩」的實作會綠 ——
    而使用者隨手打三個字就會在設定裡長出三個搜尋條件，
    **然後他每天會收到那三個條件的通知信。**
    """
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr, "q=郵務"))
    cases = {it.get("case_no") or it.get("caseNo") for it in items}
    assert cases == {"Q-003"}, f"`q=郵務` 應該只留下 Q-003，實際 {sorted(cases)}"

    import db
    conn = db.get_db()
    try:
        watches = conn.execute(
            "SELECT keyword FROM tender_watches").fetchall()
    finally:
        conn.close()
    assert not watches, (
        f"手動搜尋之後，`tender_watches` 多出了 {[w[0] for w in watches]}\n"
        "⇒ 手動搜尋與搜尋條件無關，不可以被存起來。"
    )


def test_q3_the_manual_search_uses_the_same_variant_normalisation(
        client, make_user, seeded):
    """🔴🔴 Q3：手動搜尋要套**同一套**異體字正規化（`tender_match.normalize`）。

    ☠️ 使用者手打「台中」查不到 `臺中市政府`，**而他剛剛才看到
    搜尋條件「台中」命中了那一筆** ——
    🔑 **同一個字，兩個地方兩種結果。**

    📌 那是這一節最容易漏的一條，因為前端的 `Array.filter` 是最自然的做法，
    而異體字表在 Python 裡（`tender_match.VARIANT_MAP`）。
    ⇒ 前端做不到「同一套」，所以手動搜尋必須在後端。
    """
    assert tender_match.normalize("台中") == tender_match.normalize("臺中"), (
        "前提不成立：`normalize` 沒有把台/臺視為同一個字"
    )
    hdr = _auth(client, make_user)
    items = _items(_list(client, hdr, "q=台中"))
    cases = {it.get("case_no") or it.get("caseNo") for it in items}

    # ⚠️ **第一版我只斷言 `"Q-001" in cases`，而那是空綠**：
    #    篩選還不存在時三筆全回，`in` 自動成立。
    # 🔑 〈判準的寬窄都會騙人〉的寬那一側，而這一次它就在我自己寫的斷言裡。
    #    ⇒ 改成相等：異體字要命中 Q-001，**而且不相干的兩筆要被篩掉**。
    assert cases == {"Q-001"}, (
        f"手打「台中」應該只留下 `臺中市政府`（Q-001），實際留下 {sorted(cases)}\n"
        "⇒ 三筆全回 = 手動搜尋沒有在篩；只少了 Q-001 = 沒有套 "
        "`tender_match.normalize`（台/臺被當成兩個字）。"
    )


def test_q5_clearing_the_search_brings_everything_back(
        client, make_user, seeded):
    """🔴 Q5 反向控制：`q` 清空 ⇒ 回到全部，**證明它是篩選不是查詢**。

    ⚠️ 少了這一題，一個「`q` 一旦用過就永遠只留下那幾筆」的實作
    （例如把篩選結果寫回去、或把 `q` 記在 session 裡）會讓 Q2／Q3 全綠。
    """
    hdr = _auth(client, make_user)
    narrowed = _items(_list(client, hdr, "q=郵務"))
    assert len(narrowed) == 1, f"前提不成立：`q=郵務` 應該只剩 1 筆，實際 {len(narrowed)}"

    for query in ("", "q="):
        items = _items(_list(client, hdr, query))
        assert len(items) == seeded, (
            f"`?{query}` 之後只剩 {len(items)} 筆，應該回到 {seeded} 筆"
        )


# ══════════════════════════════════════════════════════════════════════
# Q4 · 命中區為空時要說出為什麼
# ══════════════════════════════════════════════════════════════════════

def test_q4_an_empty_matched_section_says_which_kind_of_empty_it_is(
        client, make_user, seeded):
    """🔴 Q4：**「沒有搜尋條件」與「有條件但沒命中」要分得出來。**

    ☠️ 兩件在畫面上都是一塊空白，而處置完全相反：
    一個要去**新增條件**，一個要去**改條件**。
    🔑 今晚第 N 個「同一個畫面、多個成因」——而這一次連**動作**都相反。

    📌 前端不可能自己分辨：它得再打一支 `watches` API，
    **那是兩次往返加一個競態**（中間有人刪掉條件就會講錯話）。
    ⇒ 所以這個訊號必須跟清單同一個回應出來。我釘 `matchedEmptyReason`，
    沿用 B 在 `sources[].skipped` 用過的形狀（同一個問題，同一種答案）。
    """
    hdr = _auth(client, make_user)

    body = _list(client, hdr)
    assert not isinstance(body, list), (
        "回傳是裸陣列，沒有地方放 `matchedEmptyReason` —— "
        "Q4 要求這個訊號跟清單同一個回應出來。"
    )
    assert body.get("matchedEmptyReason") == "no_watches", (
        f"一個搜尋條件都沒有時，`matchedEmptyReason` 應該是 `no_watches`，"
        f"實際 {body.get('matchedEmptyReason')!r}"
    )

    _add_watch("絕對不會命中的字串ZZZ")
    body = _list(client, hdr)
    assert body.get("matchedEmptyReason") == "no_hits", (
        f"有條件但沒命中時應該是 `no_hits`，"
        f"實際 {body.get('matchedEmptyReason')!r}"
    )

    _add_watch("臺中")
    body = _list(client, hdr)
    assert body.get("matchedEmptyReason") is None, (
        f"有命中時 `matchedEmptyReason` 應該是 null，"
        f"實際 {body.get('matchedEmptyReason')!r}\n"
        "⇒ 三態：沒有條件／有條件沒命中／有命中。"
    )


# ══════════════════════════════════════════════════════════════════════
# Q6 / Q7 / Q9 · 機關名稱當定位依據
# ══════════════════════════════════════════════════════════════════════

def _tender_point(client, hdr, case_no):
    r = client.get("/api/map/points?sources=tenders", headers=hdr)
    assert r.status_code == 200, r.text
    for p in r.json()["points"]:
        if p.get("caseNo") == case_no:
            return p
    raise AssertionError(
        f"地圖上找不到 {case_no}，有的是："
        f"{[p.get('caseNo') for p in r.json()['points']]}"
    )


def test_q6_the_organisation_name_is_tried_before_the_location(
        client, make_user, seeded):
    """🔴 Q6：退階順序是**機關名稱 → `location` → 失敗**，每一階標出來。

    🔑 A 實測：命中的機關名稱是**建物級**座標，而 `location` 只有縣市級
    ⇒ 先問機關名稱，拿得到的精度高一整級。

    📌 觀測點是點上的 `address`（§3p 釘的鍵）：
    它等於**實際被拿去查的那個字串** ⇒ 順序從它讀得出來，
    不必去猜內部呼叫了哪個函式。
    """
    hdr = _auth(client, make_user)
    p = _tender_point(client, hdr, "Q-002")
    assert p.get("address") == ORG_FINDABLE, (
        f"Q-002 的機關名稱 `{ORG_FINDABLE}` 查得到，"
        f"而實際拿去查的是 {p.get('address')!r}\n"
        "⇒ 機關名稱要排在 `location` 之前。"
    )
    assert (p["lat"], p["lon"]) == ORG_COORD, (
        f"座標應該是機關名稱查出來的 {ORG_COORD}，實際 {(p['lat'], p['lon'])}"
    )


def test_q7_a_name_hit_has_its_own_precision_tier():
    """🔴 Q7：以名稱查到的東西，精度**要與縣市級分得開**。

    ☠️ 跟縣市級共用一個 `precision` 的話，**§3o 整個設計會失效**：
    那個設計的全部價值就是「一個座標要帶得出它有多準」，
    而建物級與縣市級的誤差差了三個數量級（~10m vs ~20km）。

    ## 🔴 規格自己有兩條在打架，我只釘兩邊都同意的那一半

    | | 要的位置 | 依據 |
    |---|---|---|
    | **§3q Q7**（行 358） | `org`，**介於 street 與 district** ⇒ 比 street **粗** | 「建議」，沒有量測 |
    | **§3r R9**（行 286） | `poi`，**介於 rooftop 與 street** ⇒ 比 street **細** | D 實測：`交通部航港局` 回真實建物座標 |

    ⇒ **方向相反**。而 R9 有實測、Q7 寫的是「建議」
    ⇒ 照 R9 做的話，一個**正確的實作會在這一題上變紅**。
    🔑 今晚第五次同一個機會，而這一次來源不是我的猜測，
    **是規格裡兩條活著的條文互相牴觸。**

    ⇒ 這一題只釘**兩條都同意的那個不變量**：
    **「以名稱查到的」有自己的一階，而且它比 `district` 細。**
    精確位置由 R9／R10 釘（那裡有量測）。已回報 A 擇一。
    """
    order = list(getattr(geo, "PRECISION_ORDER", []))
    assert order, "`helpers/geo.py` 缺少 `PRECISION_ORDER`"

    tier = next((getattr(geo, n) for n in ("PRECISION_POI", "PRECISION_ORG")
                 if hasattr(geo, n)), None)
    assert tier is not None, (
        "`helpers/geo.py` 缺少「以名稱查到的」那一階"
        "（`PRECISION_POI`／`PRECISION_ORG` 都沒有）。\n"
        "⚠️ §3q Q7 與 §3r R9 對它的**位置**有衝突，但兩條都要求它存在。"
    )
    assert tier in order, f"那一階不在 `PRECISION_ORDER` 裡：{order}"
    assert order.index(tier) < order.index(geo.PRECISION_DISTRICT), (
        f"`{tier}` 必須比 `district` 細，而階梯是 {order}\n"
        "⇒ 不然畫面上會把一個建物座標與一個縣市中心點講成同一種準度。"
    )


def test_q9_an_unfindable_organisation_falls_back_to_the_location(
        client, make_user, seeded):
    """🔴 Q9 反向控制：機關名稱查不到 ⇒ **退回 `location`，而且 `source` 要變**。

    ☠️ 少了這一題，一個「**永遠用 `location`**」的實作會讓 Q6 變成
    「剛好那一筆的 `location` 也查得到同一個座標」那種巧合 ——
    🔑 **兩題合起來才證明「先問機關名稱」這件事真的發生了。**

    📌 用的是 A 實測 FAIL 的那一個（`中華郵政股份有限公司`，
    名稱本身沒有地點資訊、全台數百據點）——**退階在這裡是對的處置**。
    """
    hdr = _auth(client, make_user)
    p = _tender_point(client, hdr, "Q-003")
    assert p.get("address") == LOCATION, (
        f"`{ORG_UNFINDABLE}` 查不到，應該退回 `location`（{LOCATION}），"
        f"實際拿去查的是 {p.get('address')!r}"
    )
    assert (p["lat"], p["lon"]) == LOCATION_COORD, (
        f"退階之後的座標應該是 {LOCATION_COORD}，實際 {(p['lat'], p['lon'])}"
    )
    # ⚠️ 用 getattr 取那一階的名字：§3q Q7 叫它 `org`、§3r R9 叫它 `poi`，
    #    而規格裡兩條都活著（見 Q7 的說明）。寫死任一個名字都會在另一邊變紅。
    name_tier = next((getattr(geo, n) for n in ("PRECISION_POI", "PRECISION_ORG")
                      if hasattr(geo, n)), None)
    assert p.get("precision") != name_tier or name_tier is None, (
        f"退回縣市之後 `precision` 還標成 `{name_tier}` —— "
        "那會讓畫面上說一個縣市中心點是建物級精度。"
    )


# ══════════════════════════════════════════════════════════════════════
# Q8 · 截斷偵測（A 2026-09-22 裁定：只留明確標記）
# ══════════════════════════════════════════════════════════════════════

def test_q8_a_truncated_name_is_never_sent_to_the_geocoder():
    """🔴 Q8：以 `…`／`...` 結尾的名稱**不可以拿去查**，直接退回 `location`。

    ## 它防的不是「查不到」，是「查到錯的」

    🔑 **查不到會退階（安全），查到錯的不會。**
    「交通部民用航空局飛航」如果剛好命中某個不相關的地點，
    **我們會得到一個看起來合理而完全錯誤的座標** ——
    而地圖上那個圖釘**看起來跟正確的一模一樣**。

    ## ⚠️ 規格裡「長度剛好等於某個上限」那一半已被 A 拿掉

    資料裡沒有那個上限（我量過：200 筆／158 個相異 `org`，
    以 `…` 結尾的 **0 個**，最長 19 字而長度分布連續、尖峰在 12 不在最大值）
    ⇒ 那個常數只能用猜的，而**猜高了它永遠不觸發，猜低了它砍掉合法名稱**。

    📌 而「永遠不觸發」正是這一題存在的理由：
    **資料庫裡現在一個被截斷的名稱都沒有**，所以這道守門今天不會被觸發。
    🔑 〈計數器要有落點〉：一道現在不會觸發的守門，**必須有一題證明它活著**
    —— 這一題就是餵一個合成的截斷名稱進去。
    """
    detect = getattr(geo, "looks_truncated", None)
    assert callable(detect), (
        "`helpers/geo.py` 缺少 `looks_truncated(name)` —— "
        "Q8 需要一個具名的判斷，而不是散在呼叫端的 `endswith`。"
    )
    markers = getattr(geo, "TRUNCATION_MARKERS", None)
    assert markers, (
        "`TRUNCATION_MARKERS` 要是具名常數（目前只該有 `…` 與 `...`）"
    )

    for name in (ORG_TRUNCATED, "交通部民用航空局飛航...", "某某機關…"):
        assert detect(name) is True, f"{name!r} 應該被判定為截斷"


@pytest.mark.parametrize("name", [
    ORG_FINDABLE,
    ORG_UNFINDABLE,
    "交通部民用航空局飛航服務總臺",          # 完整的那個，14 字
    "國家科學及技術委員會新竹科學園區管理局",  # 資料庫裡最長的，19 字
    "",
])
def test_q8b_a_complete_name_is_not_mistaken_for_a_truncated_one(name):
    """🔴 Q8b 反向控制：**完整的名稱不可以被誤判成截斷。**

    ☠️ 少了這一題，一個「永遠回 True」的偵測會讓 Q8 綠 ——
    而那會讓**每一筆標案都退回縣市級**，也就是把 §3q 整節的價值抵銷掉，
    **而畫面上完全看不出來**（只是每個圖釘都不太準）。

    📌 名單裡包含資料庫裡**最長的那一個**（19 字）——
    那正是「長度上限」那個判準會誤殺的第一個受害者。
    """
    detect = getattr(geo, "looks_truncated", None)
    assert callable(detect), "前提不成立：`looks_truncated` 不存在"
    assert detect(name) is False, (
        f"{name!r}（{len(name)} 字）被誤判成截斷。\n"
        "⇒ 判準只該看 `…`／`...` 結尾，不該看長度（A 2026-09-22 裁定）。"
    )


# ══════════════════════════════════════════════════════════════════════
# Q10 · 快取鍵要分得開「機關名稱」與「location」
# ══════════════════════════════════════════════════════════════════════

def test_q10_two_lookups_for_one_tender_do_not_overwrite_each_other(client):
    """🔴 Q10：同一筆標案的兩個查詢來源，**在快取裡不可以互相覆蓋**。

    ☠️ 若快取以「標案 id」為鍵：先用機關名稱查到建物座標並寫進去，
    之後某次退階用 `location` 查到縣市中心點**蓋掉它**
    ⇒ 那一筆從此永遠是縣市級，**而症狀是沒有症狀**：
    地圖上有點、距離有數字，只是一直差幾公里。
    📌 §3o 的 A9 踩過同一個坑（快取只用地址當鍵 ⇒ 填了 Google 金鑰也拿不到門牌）。

    🔑 這裡驗的是**兩筆都還在**，不是「鍵長什麼樣子」——
    釘鍵的形狀就是釘一種實作。
    """
    import db
    from helpers.geo import GeoResult

    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache")
        conn.commit()
    finally:
        conn.close()

    geo._remember(ORG_FINDABLE, GeoResult(
        coord=ORG_COORD, precision=getattr(geo, "PRECISION_ORG", "org"),
        source=geo.SOURCE_NOMINATIM, address=ORG_FINDABLE))
    geo._remember(LOCATION, GeoResult(
        coord=LOCATION_COORD, precision=geo.PRECISION_DISTRICT,
        source=geo.SOURCE_NOMINATIM, address=LOCATION))

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT address FROM geocode_cache").fetchall()
    finally:
        conn.close()

    addresses = {r["address"] for r in rows}
    assert {ORG_FINDABLE, LOCATION} <= addresses, (
        f"兩個來源寫進快取之後，只剩下 {sorted(addresses)}\n"
        "⇒ 其中一筆蓋掉了另一筆。同一筆標案的機關名稱與 location "
        "是兩個不同的查詢，必須各自有自己的快取項。"
    )
