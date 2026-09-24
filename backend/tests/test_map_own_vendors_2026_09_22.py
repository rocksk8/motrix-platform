"""§3p 第三節 · 地圖放自己的廠商（P12–P16）。

> **使用者：「地圖部分，我不能看到其他商家就等於沒有效果」／「丙」（自己的廠商＋Google 都要）**

## ✅ 資料已經在（A 實測，我複核過）

```
contractors          5 筆   address           5 筆有值   ← ⚠️ 自然人
vendor_contractors   3 筆   address           3 筆有值
shipping_notes       3 筆   delivery_address  3 筆有值
completion_notes     0 筆   site_address      —          ← P16：完全不碰
```

---

# 🔴 我在寫這一節時查到的兩件規格沒寫的事

## 一、`contractors` 是**外包名冊（自然人）**，不是廠商公司

`routers/contractors.py` 的每一支都是
`_require_user(authorization, require_superadmin=True, module='contractor_list')`。
而那張表的欄位是 `id_number`（身分證號）／`bank_account_number`／`address`
⇒ **那個 `address` 是住家地址，不是營業地址。**

☠️ 把它畫在一張「已登入就看得到」的地圖上，**等於從一扇新的門把權限降級**：
地圖會正常運作，只是保護變低了。
🔑 〈降級之後它還是會動〉：**壞掉會被報修，降級不會。**

⇒ **P12b 釘死：`contractors` 這個來源要沿用 `contractor_list` 的權限**，
沒有權限的人拿到 `skipped="no_permission"` 與**零個點**。
📌 這不是我自己加的需求 —— 現行程式碼的檔頭就寫著
「**端點只要求登入，而每一個資料來源自己檢查自己的權限**」，我只是把它套到新來源上。

## 二、🔴 `_tender_points` 有一個安靜的 bug，而它正好會在 P12 上爆開

`routers/map_points.py` 的點字典裡 **`"source"` 這個鍵出現了兩次**：

```python
points.append({
    "source": "tenders",                                   # 172：資料集
    ...
    "precision": found.precision, "source": found.source,  # 176：定位服務
```
Python 的字典字面值**後面的鍵覆蓋前面的** ⇒ `point["source"]` 實際上是
`"nominatim"`，**不是 `"tenders"`**。

⚠️ 現在看不出來，因為地圖上只有一種資料集。
**而 P12 一旦加進廠商，每一個點都會說自己是 `nominatim`** ——
前端沒有任何辦法把標案與廠商分開上色。

🔑 兩個不同的意思搶同一個名字：**資料集**與**定位服務**。
⇒ 我釘 `dataset`（資料集）與 `source`（定位服務）**兩個分開的鍵**。
📌 §3o 的 25 題釘的是 `geo.locate()` 的回傳，不碰點字典 ⇒ 不受影響。

---

# ⚠️ P14 我**不釘 precision 的值**，只釘它存在且在階梯上

規格寫「廠商是**門牌**地址、標案只到**縣市**」。⚠️ 而 §3o 自己的實測證明
**Nominatim 認不得台灣的門牌與路名** ⇒ 沒有 Google／TGOS 金鑰時，
廠商地址一樣會退到 `district`。開發機沒有金鑰。

⇒ 斷言 `precision == "rooftop"` 的話，**一個正確的實作會在開發機上變紅**。
🔑 今晚第三次同一個錯的機會（CSP 的萬用子網域、連線洩漏的 `with`）：
**我把「有金鑰時的樣子」寫成不變量。**
⇒ 釘的是**不變量**：每個點都帶 `precision`，而它的值來自 `geo.PRECISION_ORDER`。
"""
import pytest

import routers.map_points as mp
from helpers import geo
from tests._map_cache_warm import serve_from_fake

#: 要一起畫在地圖上的四個資料集。
#: 📌 `completion_notes` **不在這裡**（P16：0 筆，不為一張空表寫實作）。
OWN_SOURCES = ("contractors", "vendor_contractors", "shipping_notes")

#: 每個來源**繼承它自己那個模組的權限**（A 2026-09-22 升成通則）。
#:
#: ⚠️ 這張表是**從路由讀出來的**，不是從規格抄的 —— A 明講「我會猜錯，
#: 而猜錯的方向是放寬」。`grep` 的結果：
#: ```
#: routers/contractors.py          module='contractor_list'（＋require_superadmin）
#: routers/vendor_contractors.py   ('procurement', 'case_manage', 'contractor_list')
#: routers/shipping_notes.py       ('case_manage', 'quotation')
#: ```
#: 🔑 **通則的好處是將來加來源時不必再問一次**：去讀那支路由要什麼。
SOURCE_MODULES = {
    "contractors": ("contractor_list",),
    "vendor_contractors": ("procurement", "case_manage", "contractor_list"),
    "shipping_notes": ("case_manage", "quotation"),
}


def _auth(client, make_user, **kw):
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _points(client, hdr, sources):
    r = client.get(f"/api/map/points?sources={sources}", headers=hdr)
    assert r.status_code == 200, f"{sources} 回 {r.status_code}：{r.text[:200]}"
    return r.json()


def _info(body, name):
    """`sources[]` 裡那一個來源的回報。**找不到就是 P13 沒做到。**"""
    for entry in body.get("sources") or []:
        if entry.get("source") == name:
            return entry
    raise AssertionError(
        f"`sources[]` 裡沒有 `{name}` 的回報。\n"
        f"⇒ 使用者要了這個來源而它連提都沒被提到 —— 畫面上那就是一張沒有點的地圖，"
        f"而「沒有權限」「沒有資料」「定位不到」三件事長得一模一樣。\n"
        f"實際回報的是：{[e.get('source') for e in (body.get('sources') or [])]}"
    )


@pytest.fixture(autouse=True)
def _no_tile_probe(monkeypatch):
    """把圖磚探測關掉。**不是為了跑得快，是因為它會真的對外連線。**

    `/api/map/points` 每一次都會呼叫 `geo.tiles_blocked()`，而那一支會去打
    `tile.openstreetmap.org` ⇒ **這個檔的每一題都會是一次真實的對外請求。**

    📌 抓到它的是 `conftest` 的 NETGUARD（在 teardown 斷言）——
    而它報在**第一題**，因為探測結果會被快取
    ⇒ ⚠️ **後面那些題看起來很乾淨，只是因為第一題已經替它們打過了。**
    🔑 〈證據的適用範圍〉：「我沒撞到」不等於「做法沒問題」。

    ⚠️ 這裡刻意回 `None`（不知道），不是 `False`（探過、可以用）——
    回 `False` 的話，任何「三態被壓成兩態」的 bug 在這個檔裡都看不見。
    """
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)


#: 每個測試地址 → 我要餵給端點的 `(座標, 精度)`。
#:
#: 🔴 **三個精度刻意都不一樣，而且刻意不是同一階。**
#: ⚠️ 如果每一筆都回同一個精度，P14b 就只能驗到「有一個精度值」，
#: 驗不到「**它是那一筆自己的精度**」——
#: 而一個「全部寫死成 district」的實作會全綠，**那正是要防的東西**
#: （廠商是門牌、標案是縣市，畫在同一張圖上不標示就是騙人）。
_FAKE_GEO = {
    "台中市梧棲區": ((24.2549, 120.5316), "rooftop"),
    "台中市西屯區": ((24.1815, 120.6400), "street"),
    "台中市南屯區": ((24.1380, 120.6430), "street"),
    "台中市":       ((24.1477, 120.6736), "district"),
}


@pytest.fixture(autouse=True)
def _fake_locate(monkeypatch):
    """把地理查詢換成**查表**。

    ## ⚠️ 這個假貨的形狀是刻意的

    最省事的做法是「一律回同一個座標與精度」。**那會毀掉 P14b**：
    斷言就會變成「我設了 X，端點回了 X」——
    🔑 〈假綠燈：斷言驗到自己設的值〉。

    ⇒ 改成**每個地址回不同的精度**，而 P14b 斷言的是
    「**這一筆的精度等於這一筆的地址該有的精度**」。
    那證明的是**逐點傳遞**：端點若寫死一個值、或把精度掉在路上、
    或全部套用第一筆的值，都會紅。

    📌 地理查詢本身有 §3o 的 25 題在守，這個檔不重複驗它。
    """
    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        if manual_coord:
            return geo.GeoResult(coord=tuple(manual_coord),
                                 precision=geo.PRECISION_EXACT,
                                 source=geo.SOURCE_MANUAL, address=key)
        hit = _FAKE_GEO.get(key)
        if not hit:
            return geo.GeoResult(error="測試查表裡沒有這個地址：%r" % key,
                                 address=key)
        coord, precision = hit
        return geo.GeoResult(coord=coord, precision=precision,
                             source=geo.SOURCE_NOMINATIM, address=key)

    monkeypatch.setattr(geo, "locate_cached", _fake)
    serve_from_fake(monkeypatch, _fake)  # MP8：快取＝查表（背景預熱已完成）


@pytest.fixture()
def own_data(client):
    """塞進三個資料集各一筆**地址查得到**的資料。

    ⚠️ 用的是 §3o 實測過**真的查得到**的行政區（`台中市梧棲區`），
    不是門牌 —— 門牌在 Nominatim 上查不到（§3o 的起因就是這件事）。
    📌 這樣「點沒出現」就只會有一個原因：**實作沒做**，不是地址的問題。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractors (name, address, active, created_at) "
            "VALUES (?,?,1,?)",
            ("地圖測試外包人員", "台中市梧棲區", "2026-09-22T00:00:00"))
        conn.execute(
            "INSERT INTO vendor_contractors (name, address, active, created_at) "
            "VALUES (?,?,1,?)",
            ("地圖測試承攬商", "台中市西屯區", "2026-09-22T00:00:00"))
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, "
            "delivery_address, items_json, created_at) VALUES (?,?,?,?,?,?,?)",
            ("MAP-SN-001", "MQ-MAP-001", "draft", "地圖測試客戶",
             "台中市南屯區", "[]", "2026-09-22T00:00:00"))
        # ⚠️ **也要塞一筆標案。** P12b 驗的是「兩個資料集混在一起時分不分得開」，
        #    而測試資料庫裡一筆標案都沒有
        #    ⇒ 沒有這一筆的話，那一題在 B 做完之後**仍然會紅**，
        #      而它紅的理由會變成「沒有標案」——一個跟 P12b 無關的理由。
        # 🔑 〈判準的寬窄都會騙人〉：紅燈也要紅在對的地方，
        #    否則下一輪會有人去修一個不存在的問題。
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
            "VALUES (?,?,?,?,?)",
            ("MAP-T-001", "地圖測試標案", "地圖測試機關", "台中市",
             "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# P12 · 三個來源各自獨立可開關
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", OWN_SOURCES)
def test_p12_each_own_source_can_be_asked_for_on_its_own(
        client, make_user, own_data, name):
    """🔴 P12：`sources=<單一來源>` 要拿得到那個來源的點，**而且只有那個來源**。

    📌 「各自獨立可開關」的意思是**兩個方向都要成立**：
    要得到 ⇒ 有；**沒要到 ⇒ 沒有**。
    ⚠️ 只驗前者的話，一個「不管你要什麼都全部回傳」的實作會全綠。
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, name)

    info = _info(body, name)
    assert info.get("skipped") is None, (
        f"superadmin 要 `{name}` 卻被跳過了：{info}"
    )

    datasets = {p.get("dataset") for p in body["points"]}
    assert datasets == {name}, (
        f"要的是 `{name}`，而回來的點分屬 {sorted(x for x in datasets if x)}。\n"
        "⇒ 「各自獨立可開關」要兩個方向都成立：沒要到的來源不可以出現。"
    )
    assert body["points"], f"`{name}` 一個點都沒有（測試資料塞了一筆查得到的地址）"


def test_p12b_asking_for_two_sources_keeps_them_apart(
        client, make_user, own_data):
    """🔴🔴 P12b：**同時要兩個來源時，每個點都要說得出自己是哪一個。**

    ☠️ 這一題是這一節的核心，而它現在紅的原因寫在檔頭：
    `map_points.py` 的點字典裡 `"source"` 出現兩次，
    後面那個（定位服務）覆蓋掉前面那個（資料集）
    ⇒ **每個點都會說自己是 `nominatim`。**

    🔑 一個資料集標籤與一個定位服務標籤搶同一個鍵名，
    而**兩個都是合法的值** ⇒ 沒有任何東西會報錯。
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, "tenders,vendor_contractors")

    assert body["points"], (
        "一個點都沒有 —— 這一題的前提不成立。\n"
        "⚠️ 沒有這道前提的話，下面那句 `None not in datasets` 會**空綠**："
        "空集合裡當然沒有 `None`。"
    )
    datasets = {p.get("dataset") for p in body["points"]}
    assert None not in datasets, (
        "有點沒有 `dataset` 這個鍵。\n"
        "⇒ 前端沒有辦法把標案與廠商分開上色，而使用者要的正是「看到其他商家」。"
    )
    assert datasets >= {"tenders", "vendor_contractors"}, (
        f"兩個來源都要了，而回來的點只分屬 {sorted(datasets)}"
    )

    geo_sources = {p.get("source") for p in body["points"]}
    assert geo_sources & {geo.SOURCE_NOMINATIM, geo.SOURCE_NOMINATIM_DISTRICT,
                          geo.SOURCE_GOOGLE, geo.SOURCE_TGOS,
                          geo.SOURCE_MANUAL}, (
        f"點的 `source` 應該是定位服務，實際是 {sorted(x for x in geo_sources if x)}。\n"
        "⇒ `dataset`（資料集）與 `source`（定位服務）是兩個意思，要兩個鍵。"
    )

    # A 2026-09-22 要求：**兩個鍵都要存在且值不同。**
    # ⚠️ 少了「值不同」那一半，一個把兩個鍵都填成資料集名字的實作會綠 ——
    #    而那等於用兩個名字講同一件事，§3o 要的定位服務就不見了。
    for p in body["points"]:
        assert p.get("dataset") and p.get("source"), (
            f"點缺了其中一個鍵：dataset={p.get('dataset')!r} "
            f"source={p.get('source')!r}"
        )
        assert p["dataset"] != p["source"], (
            f"`dataset` 與 `source` 是同一個值 `{p['source']}` —— "
            "那兩個鍵在講兩件事（資料集／定位服務）。"
        )


# ══════════════════════════════════════════════════════════════════════
# P12c · 🔴 `contractors` 是自然人名冊，權限不可以從地圖這扇門降級
# ══════════════════════════════════════════════════════════════════════

def test_p12c_the_personal_roster_keeps_its_own_permission(
        client, make_user, own_data):
    """🔴🔴 P12c：**沒有 `contractor_list` 權限的人，地圖上拿不到外包名冊的點。**

    ☠️ `contractors` 存的是自然人：`id_number`（身分證號）、
    `bank_account_number`、而那個 `address` 是**住家地址**。
    `routers/contractors.py` 每一支都要 `require_superadmin=True`
    ＋ `module='contractor_list'`。

    ⇒ 地圖若不檢查，就是**從一扇新的門把同一份資料的保護降級**，
    而地圖會**正常運作** —— 只是保護變低了。
    🔑 〈降級之後它還是會動〉：**壞掉會被報修，降級不會。**

    📌 這不是我加的需求：`map_points.py` 檔頭本來就寫著
    「端點只要求登入，**而每一個資料來源自己檢查自己的權限**」。
    """
    hdr = _auth(client, make_user, role="sales", modules=["dev_crm"])
    body = _points(client, hdr, "contractors")

    info = _info(body, "contractors")
    assert info.get("skipped") == "no_permission", (
        f"沒有 `contractor_list` 的人要外包名冊，回報是 {info}。\n"
        "⇒ 應該是 `skipped=\"no_permission\"`。"
    )
    leaked = [p for p in body["points"] if p.get("dataset") == "contractors"]
    assert not leaked, (
        f"沒有權限的使用者拿到了 {len(leaked)} 個外包人員的點"
        f"（住家地址）。第一筆：{leaked[0]}"
    )


@pytest.mark.parametrize("name", OWN_SOURCES)
def test_p12d_a_user_who_does_have_the_module_gets_the_points(
        client, make_user, own_data, name):
    """🔴🔴 P12d 反向控制：**有權限的人拿得到點。**

    ☠️ 沒有這一半，一個「**永遠回 `no_permission`**」的實作會讓 P12c 全綠 ——
    而那在畫面上是「地圖一個廠商都沒有」，**正是使用者說等於沒有效果的那件事**。
    🔑 A 的話：**兩半都要。**

    📌 用的權限是**從路由讀出來**的（`SOURCE_MODULES`），不是從規格抄的：
    A 明講「我會猜錯，而猜錯的方向是放寬」。
    ⚠️ 而**不是用 superadmin** —— superadmin 繞過一切，
    它證明不了「權限檢查放對了地方」，只證明得了「有人拿得到點」。
    """
    hdr = _auth(client, make_user, role="sales",
                modules=[SOURCE_MODULES[name][0]])
    body = _points(client, hdr, name)

    info = _info(body, name)
    assert info.get("skipped") != "no_permission", (
        f"帶著 `{SOURCE_MODULES[name][0]}` 的使用者被擋下了：{info}\n"
        f"⇒ 那個來源的權限應該是 `{SOURCE_MODULES[name]}` 其中之一。"
    )
    pts = [p for p in body["points"] if p.get("dataset") == name]
    assert pts, (
        f"有權限的使用者在 `{name}` 上一個點都沒拿到（測試資料塞了一筆查得到的地址）"
    )


# ══════════════════════════════════════════════════════════════════════
# P13 · 每個來源要報自己為什麼是空的
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", OWN_SOURCES)
def test_p13_a_source_says_why_it_is_empty(client, make_user, name):
    """🔴 P13：來源沒有點的時候，要說得出**是哪一種沒有**。

    ☠️ 三件事在畫面上都是「沒有點」，而處置完全不同：
    | 成因 | 使用者要做的事 |
    |---|---|
    | 沒有權限 | 找管理員開權限 |
    | 沒有資料 | 去建一筆 |
    | 地址定位不到 | 去把地址改好 |

    📌 這一題**刻意不塞測試資料**（沒有 `own_data`）⇒ 走的是「沒有資料」那一條。
    ⚠️ 而它必須與 `no_permission` **是不同的值** —— 這裡用 superadmin 登入，
    所以任何 `no_permission` 都是錯的答案。
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, name)
    info = _info(body, name)

    if info.get("skipped") is None:
        assert "count" in info, (
            f"`{name}` 沒有被跳過，那它必須報出 `count`：{info}"
        )
        return

    assert info["skipped"] != "no_permission", (
        f"superadmin 被以 `no_permission` 擋下了：{info}"
    )
    assert isinstance(info.get("note"), str) and info["note"].strip(), (
        f"`{name}` 報了 `skipped={info['skipped']}` 卻沒有給人看的說明：{info}\n"
        "⇒ 那個字串是使用者唯一會看到的東西。"
    )


def test_p13b_a_source_that_was_not_asked_for_is_not_reported(
        client, make_user, own_data):
    """🔴 P13b 反向控制：**沒有被要求的來源不可以出現在 `sources[]` 裡。**

    ⚠️ 沒有這一題，一個「把全部來源都列出來、全部標成 skipped」的實作
    會讓上面每一題都綠 —— 而那會在畫面上長出一排使用者沒有要的理由。
    🔑 `sources[]` 是**回答**，不是**目錄**。
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, "vendor_contractors")
    reported = {e.get("source") for e in body.get("sources") or []}
    assert reported == {"vendor_contractors"}, (
        f"只要了 `vendor_contractors`，而 `sources[]` 回報了 {sorted(reported)}"
    )


# ══════════════════════════════════════════════════════════════════════
# P14 · 每一個點都要帶 precision
# ══════════════════════════════════════════════════════════════════════

def test_p14_the_precision_ladder_is_a_single_named_source():
    """🔴 P14 前置：**精度階梯要有一個具名的有序來源。**

    ⚠️ 現在 `geo.py` 只有四個散的常數（`PRECISION_EXACT` 等），**沒有順序**。
    ⇒ §3p 第三節與 §3q（Q7 要加 `org` 這一級）會各自抄一份階梯，
    而改階梯時**會有一邊安靜地過期** —— 測試不會紅，它只是在驗一個舊的階梯。

    🔑 A 2026-09-22 採用：階梯放 `helpers/geo.py` 一個具名有序常數，
    兩個測試檔都從那裡讀，**不各自寫死字串**。
    📌 〈修作法不要修結果〉：**不必靠大家記得。**
    """
    order = getattr(geo, "PRECISION_ORDER", None)
    assert isinstance(order, (list, tuple)) and order, (
        "`helpers/geo.py` 缺少 `PRECISION_ORDER`（由精確到粗略的有序序列）。"
    )
    assert order[0] == geo.PRECISION_EXACT, (
        f"階梯的第一個應該是最精確的 `{geo.PRECISION_EXACT}`，實際是 `{order[0]}`"
    )
    for finer, coarser in ((geo.PRECISION_ROOFTOP, geo.PRECISION_STREET),
                           (geo.PRECISION_STREET, geo.PRECISION_DISTRICT)):
        assert order.index(finer) < order.index(coarser), (
            f"`{finer}` 應該排在 `{coarser}` 前面（比較精確），而階梯是 {list(order)}"
        )


@pytest.mark.parametrize("name", OWN_SOURCES)
def test_p14b_every_point_carries_its_precision(
        client, make_user, own_data, name):
    """🔴 P14b：**每一個點都要帶 `precision`，而它的值要在階梯上。**

    ⚠️ 廠商是門牌地址、標案只到縣市，而它們**在地圖上都是一個圖釘**
    ⇒ 不標示就是騙人。

    📌 **不釘值**：§3o 實測過 Nominatim 認不得台灣門牌，沒有 Google／TGOS
    金鑰時廠商一樣會退到 `district`，而開發機沒有金鑰
    ⇒ 斷言 `precision == "rooftop"` 會讓**一個正確的實作在開發機上變紅**。
    🔑 釘的是不變量：**它存在、它在階梯上、而且不知道時是 `None` 不是省略。**
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, name)
    pts = [p for p in body["points"] if p.get("dataset") == name]
    assert pts, f"`{name}` 一個點都沒有 —— 這一題的前提不成立"

    for p in pts:
        assert "precision" in p, (
            f"`{name}` 的點沒有 `precision` 這個鍵：{p}\n"
            "⇒ 省略與 `None` 是兩件事：前者讀起來像「這裡不需要精度」。"
        )
        assert p["precision"] in set(geo.PRECISION_ORDER) | {None}, (
            f"`{name}` 的點帶了階梯外的精度 `{p['precision']}`"
            f"（階梯是 {list(geo.PRECISION_ORDER)}）"
        )

    # 🔑 真正的鑑別力在這裡：**每一筆的精度要是「那一筆自己的」。**
    # `_fake_locate` 給三個地址三個不同的精度
    # ⇒ 一個「全部寫死 district」或「全部沿用第一筆」的實作會在這裡紅。
    for p in pts:
        # ⚠️ 這裡本來寫成「查不到對應就 `continue`」——**那是一個空綠**：
        #    點若沒有 `address` 這個鍵，整段迴圈會安靜地什麼都不驗，
        #    而 P14b 會全綠。所以改成斷言。
        addr = (p.get("address") or "").strip()
        assert addr in _FAKE_GEO, (
            f"`{name}` 的點沒有帶得出自己的地址（`address`）：{p}\n"
            "⇒ 點要說得出自己是從哪個地址定位來的，"
            "否則使用者看到一個偏掉的圖釘時無從判斷是地址寫錯還是查不準。"
        )
        expected = _FAKE_GEO[addr]
        assert p["precision"] == expected[1], (
            f"`{name}` 的點 `{p.get('address')}` 精度是 `{p['precision']}`，"
            f"而它的地址對應的是 `{expected[1]}`。\n"
            "⇒ 精度沒有逐點傳遞（寫死了？沿用第一筆？掉在路上了？）"
        )


# ══════════════════════════════════════════════════════════════════════
# P15 · Google 附近商家：沒有金鑰就不發請求
# ══════════════════════════════════════════════════════════════════════

def test_p15_without_a_key_google_is_reported_off_and_never_called(
        client, make_user, own_data):
    """🔴 P15：沒有 `google_maps_api_key` ⇒ `googleMapsConfigured=false`，
    **而且一個請求都不發**（不是發了失敗）。

    ⚠️ 「發了才失敗」與「沒發」在畫面上一樣（都沒有附近商家），
    而代價差一個逾時：**每一次開地圖都多等那幾秒**。
    🔑 跟 T10 是同一個形狀：**壞掉的時候最慢。**

    📌 觀測點是 `conftest` 的 NETGUARD ——
    它把 `urllib.request.urlopen` 換成會記帳並丟例外的版本，
    **而且在 teardown 才斷言**（因為產品碼會把例外吞掉）。
    ⇒ 這一題只要有人真的發了請求，收尾時就會紅。
    """
    hdr = _auth(client, make_user, role="superadmin")
    body = _points(client, hdr, "vendor_contractors")
    assert body["googleMapsConfigured"] is False, (
        "開發機沒有設 `google_maps_api_key`，"
        f"而 `googleMapsConfigured` 是 {body['googleMapsConfigured']!r}"
    )


# ══════════════════════════════════════════════════════════════════════
# P16 · 完全不碰 completion_notes
# ══════════════════════════════════════════════════════════════════════

def test_p16_the_empty_table_is_never_queried(client, make_user, monkeypatch):
    """🔴 P16：**`completion_notes`（0 筆）連查都不要查。**

    ⚠️ 「留介面不實作」很容易做成「查了、發現是空的、回空陣列」——
    那在畫面上跟「沒有實作」一模一樣，而它**多一次查詢**，
    並且讓人以為那個來源已經做好了。

    📌 觀測點是**真的送出去的 SQL**，不是有沒有回傳點 ——
    後者是〈觀測手段與被測對象共用一段程式碼〉那一族：
    **一個查了但丟掉結果的實作會讓「沒有點」這個斷言全綠。**
    """
    import db as db_module
    seen = []

    class _Spy:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *a, **kw):
            seen.append(sql)
            return self._conn.execute(sql, *a, **kw)

        def executemany(self, sql, *a, **kw):
            seen.append(sql)
            return self._conn.executemany(sql, *a, **kw)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

        def __getattr__(self, name):
            return getattr(self._conn, name)

    real = db_module.get_db
    monkeypatch.setattr(db_module, "get_db", lambda *a, **kw: _Spy(real(*a, **kw)))

    hdr = _auth(client, make_user, role="superadmin")
    seen.clear()
    body = _points(client, hdr, "completion_notes,vendor_contractors")

    assert seen, "一句 SQL 都沒送出去 —— 這一題的前提不成立（間諜沒裝上）"
    touched = [s for s in seen if "completion_notes" in s]
    assert not touched, (
        f"查了 `completion_notes` {len(touched)} 次，而那張表是空的：\n  "
        + "\n  ".join(s.strip()[:90] for s in touched[:3])
    )

    info = _info(body, "completion_notes")
    assert info.get("skipped"), (
        f"`completion_notes` 沒有被跳過：{info}\n"
        "⇒ 「留介面不實作」要說出來，否則它看起來像「做好了而且是空的」。"
    )
