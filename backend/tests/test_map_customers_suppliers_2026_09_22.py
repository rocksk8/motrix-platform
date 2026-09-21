"""§3r · 客戶／供應商上地圖 ＋ 標案改用機關名稱定位（R1–R8）。

> **使用者：「地圖少了客戶、供應商、供應商建立的地址內容帶入」／裁「丙」（兩種地址都畫）**

---

# 🔴 一、比使用者問的那件更急：**標案點現在是零個**

A 實測、我複驗（`motrix_erp.db`）：

```
tenders.location   200 筆   filled = 0      相異值只有 [None]
tenders.org        200 筆   filled = 200
```

☠️ **地圖上現在一個標案點都沒有**，而畫面不會說原因 ——
使用者看到的是**一張只有自己廠商的地圖**，然後以為雷達壞了。

⚠️ 而 `_tender_points` 把它們**全部算進 `withoutLocation`**
⇒ **那個數字是對的，只是沒有人會去看它。**
🔑 §3q 不是「改善精度」，它是「**標案點能不能存在**」。

# ⚠️ 二、我實測到與規格不同的數字（已回報 A）

```
規格寫的                        我量到的
customers.invoiceAddress   13      9
customers.deliveryAddress  11      7
suppliers.address          23      23  ✅
```
（13／11 應該是把 `customers` 的**總列數**當成有值的數。）
⇒ 不影響任何決定，但**測試不從那個數字推任何結論** ——
每一題都自己塞資料、自己數。

# 📌 三、權限（R7）：從**路由**讀出來的，不是從規格抄的

```
routers/customers.py   ('customer', 'case_manage', 'dev_crm', 'procurement')
routers/suppliers.py   ('customer', 'procurement', 'inventory')
```
"""
import json

import pytest

from helpers import geo

#: 從路由 grep 出來的模組權限。**R7 明講不要猜。**
SOURCE_MODULES = {
    "customers": ("customer", "case_manage", "dev_crm", "procurement"),
    "suppliers": ("customer", "procurement", "inventory"),
}

#: 客戶的兩種地址各自是一個 `dataset`（R5）。
#: 🔑 **送貨地址才是業務上會跑的地方，發票地址通常是登記地** ——
#: 合併的話「我要去哪裡」這個問題就答不出來。
CUSTOMER_DATASETS = ("customers_invoice", "customers_delivery")

ORG_FINDABLE = "交通部航港局"
ORG_COORD = (25.0252831, 121.5470035)

_ADDRESSES = {
    ORG_FINDABLE:      (ORG_COORD, geo.PRECISION_STREET),
    "台北市":           ((25.0375198, 121.5636796), geo.PRECISION_DISTRICT),
    "台中市西屯區":      ((24.1815, 120.6400), geo.PRECISION_STREET),
    "台中市南屯區":      ((24.1380, 120.6430), geo.PRECISION_STREET),
    "高雄市前鎮區":      ((22.5743, 120.3352), geo.PRECISION_STREET),
}


@pytest.fixture(autouse=True)
def _isolate_geo(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        hit = _ADDRESSES.get(key)
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


def _points(client, hdr, sources):
    r = client.get(f"/api/map/points?sources={sources}", headers=hdr)
    assert r.status_code == 200, f"{sources} 回 {r.status_code}：{r.text[:220]}"
    return r.json()


def _info(body, name):
    for entry in body.get("sources") or []:
        if entry.get("source") == name:
            return entry
    raise AssertionError(
        f"`sources[]` 裡沒有 `{name}` 的回報，有的是："
        f"{[e.get('source') for e in (body.get('sources') or [])]}"
    )


def _of(body, dataset):
    return [p for p in body["points"] if p.get("dataset") == dataset]


# ══════════════════════════════════════════════════════════════════════
# R1 / R2 / R3 · 標案點能不能存在
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def tenders_without_location(client):
    """**照正式機的實況**：`org` 有值、`location` 是 NULL。

    📌 這不是我造出來的邊角 —— 200 筆全部長這樣。
    """
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
            "VALUES (?,?,?,NULL,?)",
            ("R-001", "航港局工程", ORG_FINDABLE, "2026-09-22T00:00:00"))
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
            "VALUES (?,?,?,NULL,?)",
            ("R-002", "查不到的機關的案子", "某某完全查不到的機關ZZZ",
             "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_r1_a_tender_is_located_by_its_organisation_name(
        client, make_user, tenders_without_location):
    """🔴 R1：標案的定位依據是 **`org`**，`location` 只當退階。

    ⚠️ 現況是只讀 `location` ⇒ 200 筆全 NULL ⇒ **一個點都沒有**。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "tenders")
    got = [p for p in body["points"] if p.get("caseNo") == "R-001"]
    assert got, (
        "R-001 的機關名稱查得到，而它沒有出現在地圖上。\n"
        f"地圖上有的是：{[p.get('caseNo') for p in body['points']]}"
    )
    assert got[0].get("address") == ORG_FINDABLE, (
        f"拿去查的應該是機關名稱，實際是 {got[0].get('address')!r}"
    )
    assert (got[0]["lat"], got[0]["lon"]) == ORG_COORD


def test_r2_a_tender_that_cannot_be_located_is_counted_not_dropped(
        client, make_user, tenders_without_location):
    """🔴🔴 R2 反向控制：機關名稱查不到的那一筆，
    **必須落進 `withoutLocation`，不可以靜靜消失**。

    ☠️ 少了這一題，一個「查不到就 `continue`」的實作會讓 R1 全綠 ——
    而畫面上少幾個點，**跟那些標案不存在長得一模一樣**，
    🔑 **而且沒有人會報修。**

    📌 這一題同時驗「數字要動」：`withoutLocation` 必須**至少**含那一筆，
    不是「有這個鍵」。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "tenders")

    shown = {p.get("caseNo") for p in body["points"]}
    assert "R-002" not in shown, (
        "查不到座標的標案不該有圖釘（它要被算進 `withoutLocation`）"
    )
    assert body.get("withoutLocation", 0) >= 1, (
        f"`withoutLocation` 是 {body.get('withoutLocation')!r}，"
        "而有一筆標案定位不到 —— 它必須被數進去。\n"
        "⇒ 少了這個數字，使用者無從分辨「沒有標案」與「標案定位不到」。"
    )
    info = _info(body, "tenders")
    assert info.get("withoutLocation", 0) >= 1, (
        f"來源回報裡也要有：{info}"
    )


def test_r3_a_name_hit_and_a_city_centre_are_not_labelled_the_same(
        client, make_user, tenders_without_location):
    """🔴 R3：`precision` 要標得出「用名稱查到的」與「縣市中心」的差別。

    ⚠️ 這一題**只釘「分得開」**，不釘那一階叫什麼、排在哪 ——
    🔴 §3q 的 Q7（`org`，比 street 粗）與 §3r 的 R9（`poi`，比 street 細）
    **對同一個概念要求相反的位置**，兩條都還活在規格裡。
    ⇒ 釘位置的話，**照其中一條做的正確實作會在另一條上變紅**。已回報 A 擇一。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "tenders")
    got = [p for p in body["points"] if p.get("caseNo") == "R-001"]
    assert got, "R-001 不在地圖上 —— 這一題的前提不成立（見 R1）"

    assert got[0].get("precision") not in (None, geo.PRECISION_DISTRICT), (
        f"用機關名稱查到建物座標，而 `precision` 是 "
        f"{got[0].get('precision')!r}\n"
        "⇒ 那會讓畫面上把一個建物座標與一個縣市中心點講成同一種準度"
        "（誤差差了三個數量級）。"
    )


# ══════════════════════════════════════════════════════════════════════
# R4 / R5 / R6 / R8 · 客戶與供應商
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def crm_data(client):
    """四筆客戶 ＋ 一筆供應商，**每一筆測一件事**。

    | | 測什麼 |
    |---|---|
    | C-A | 兩種地址**不同** ⇒ 兩個點（R5） |
    | C-B | 兩種地址**相同** ⇒ 只畫一個（R8） |
    | C-C | `data_json` 是**壞 JSON** ⇒ 那一筆落進 `withoutLocation`（R6） |
    | C-D | `data_json` **缺鍵** ⇒ 同上 |
    | S-A | 供應商，地址在 `data_json.address` |
    """
    import db
    conn = db.get_db()
    try:
        def cust(name, raw):
            conn.execute(
                "INSERT INTO customers (name, data_json, created_at) "
                "VALUES (?,?,?)", (name, raw, "2026-09-22T00:00:00"))

        cust("C-A", json.dumps({"invoiceAddress": "台中市西屯區",
                                "deliveryAddress": "台中市南屯區"},
                               ensure_ascii=False))
        cust("C-B", json.dumps({"invoiceAddress": "高雄市前鎮區",
                                "deliveryAddress": "高雄市前鎮區"},
                               ensure_ascii=False))
        cust("C-C", "{這不是合法的 JSON")
        cust("C-D", json.dumps({"taxId": "12345678"}, ensure_ascii=False))
        conn.execute(
            "INSERT INTO suppliers (name, data_json, created_at) "
            "VALUES (?,?,?)",
            ("S-A", json.dumps({"address": "台北市"}, ensure_ascii=False),
             "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_r4_customers_and_suppliers_are_independent_sources(
        client, make_user, crm_data):
    """🔴 R4：`customers` 與 `suppliers` 各自獨立可開關。

    📌 「獨立」要兩個方向：**要得到 ⇒ 有；沒要到 ⇒ 沒有。**
    """
    hdr = _auth(client, make_user)

    only_sup = _points(client, hdr, "suppliers")
    assert _of(only_sup, "suppliers"), "只要供應商卻一個點都沒有"
    assert not [p for p in only_sup["points"]
                if str(p.get("dataset", "")).startswith("customers")], (
        "只要了 `suppliers`，而客戶的點也回來了"
    )

    only_cus = _points(client, hdr, "customers")
    assert not _of(only_cus, "suppliers"), (
        "只要了 `customers`，而供應商的點也回來了"
    )


def test_r5_the_two_customer_addresses_are_two_datasets(
        client, make_user, crm_data):
    """🔴 R5：發票地址與送貨地址是**兩個 `dataset`**，不是同一個點的兩個屬性。

    🔑 **送貨地址才是業務上會跑的地方，發票地址通常是登記地** ——
    合併的話「**我要去哪裡**」這個問題就答不出來。
    📌 使用者裁「丙」＝兩種都畫，而「都畫」的前提是**畫得出差別**。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "customers")

    datasets = {p.get("dataset") for p in body["points"]}
    assert set(CUSTOMER_DATASETS) <= datasets, (
        f"客戶的點只分屬 {sorted(x for x in datasets if x)}，"
        f"而兩種地址要是兩個 dataset：{CUSTOMER_DATASETS}"
    )

    invoice = {p.get("address") for p in _of(body, "customers_invoice")}
    delivery = {p.get("address") for p in _of(body, "customers_delivery")}
    assert "台中市西屯區" in invoice, f"C-A 的發票地址不在發票那一組：{invoice}"
    assert "台中市南屯區" in delivery, f"C-A 的送貨地址不在送貨那一組：{delivery}"


def test_r8_identical_invoice_and_delivery_addresses_draw_one_point(
        client, make_user, crm_data):
    """🔴 R8：兩種地址**相同**時只畫一個點。

    ⚠️ 不去重的話，地圖上會有**完全重疊**的兩個標記 ——
    而使用者會以為那裡有兩個據點。
    📌 重疊的標記在畫面上**看不出來是兩個**，所以這個缺陷不會被報修，
    它只會讓「我有幾個據點」這個問題長期答錯。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "customers")

    same = [p for p in body["points"]
            if (p.get("address") or "").strip() == "高雄市前鎮區"]
    assert same, "C-B 的點不在地圖上 —— 這一題的前提不成立"
    assert len(same) == 1, (
        f"C-B 的發票與送貨地址相同，而地圖上有 {len(same)} 個點："
        f"{[p.get('dataset') for p in same]}"
    )


def test_r6_a_broken_data_json_does_not_take_the_whole_source_down(
        client, make_user, crm_data):
    """🔴🔴 R6：`data_json` 壞掉或缺鍵的那一筆落進 `withoutLocation`，
    **不可以讓整個來源炸掉**。

    ☠️ 一筆壞資料讓整個 `customers` 來源回 500 或回空 ⇒
    **其餘 12 筆一起消失**，而畫面上那是「沒有客戶」。
    🔑 〈讀不到的欄位要拒絕那一筆，不要送空值〉的鄰居：
    **拒絕那一筆，不是拒絕整批。**

    📌 反向控制在同一題裡：**其餘筆數必須照常回來** ——
    只驗「不會 500」的話，一個 `except: return []` 的實作會綠。
    """
    hdr = _auth(client, make_user)
    body = _points(client, hdr, "customers")

    addresses = {(p.get("address") or "").strip() for p in body["points"]}
    assert "台中市西屯區" in addresses and "高雄市前鎮區" in addresses, (
        f"壞掉的那一筆把其餘的一起帶走了。地圖上剩下：{sorted(addresses)}"
    )
    assert body.get("withoutLocation", 0) >= 2, (
        f"`withoutLocation` 是 {body.get('withoutLocation')!r}，"
        "而有兩筆客戶（壞 JSON、缺鍵）拿不到地址 —— 它們必須被數進去，"
        "不可以靜靜消失。"
    )


# ══════════════════════════════════════════════════════════════════════
# R7 · 權限照 §3p 通則
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", sorted(SOURCE_MODULES))
def test_r7_a_source_without_its_module_is_skipped(
        client, make_user, crm_data, name):
    """🔴 R7：沒有那個模組的人拿到 `skipped="no_permission"` 與**零個點**。

    📌 權限是從**路由**讀出來的（見檔頭），不是從規格抄的 ——
    A 在 §3p 立的通則：**「它自己那個模組要什麼」請從路由讀，不要猜，
    而猜錯的方向是放寬。**
    """
    hdr = _auth(client, make_user, role="sales", modules=["tender_radar"])
    body = _points(client, hdr, name)

    info = _info(body, name)
    assert info.get("skipped") == "no_permission", (
        f"沒有 {SOURCE_MODULES[name]} 任一模組的人要 `{name}`，回報是 {info}"
    )
    leaked = [p for p in body["points"]
              if str(p.get("dataset", "")).startswith(name)]
    assert not leaked, f"沒有權限卻拿到 {len(leaked)} 個點：{leaked[0]}"


@pytest.mark.parametrize("name", sorted(SOURCE_MODULES))
def test_r7b_a_user_who_has_the_module_gets_the_points(
        client, make_user, crm_data, name):
    """🔴🔴 R7b 反向控制：**有權限的人拿得到點。**

    ☠️ 少了這一半，一個「永遠回 `no_permission`」的實作會讓 R7 全綠 ——
    而那在畫面上是「地圖上一個客戶都沒有」，**正是使用者在抱怨的那件事**。
    ⚠️ 刻意**不用 superadmin**：它繞過一切，證明不了權限檢查放對了地方。
    """
    hdr = _auth(client, make_user, role="sales",
                modules=[SOURCE_MODULES[name][0]])
    body = _points(client, hdr, name)

    info = _info(body, name)
    assert info.get("skipped") != "no_permission", (
        f"帶著 `{SOURCE_MODULES[name][0]}` 的使用者被擋下了：{info}"
    )
    got = [p for p in body["points"]
           if str(p.get("dataset", "")).startswith(name)]
    assert got, f"有權限的使用者在 `{name}` 上一個點都沒拿到"


# ══════════════════════════════════════════════════════════════════════
# R9 / R10 · `street` 目前一詞兩用，新增 `poi` 一階
# ══════════════════════════════════════════════════════════════════════
#
# D 實測：`交通部航港局`（建物）回 `street`，而 `台中市西屯區台灣大道三段`
# （路段中心）**也是** `street` —— 因為 `_locate_nominatim` 不管命中什麼
# 都回 `PRECISION_STREET`（`helpers/geo.py:386`），而 `geocode()` 把
# Nominatim 回應裡的 `class`／`type`／`addresstype` **整個丟掉了**。
# ⇒ 前端的 `precisionIsCoarse()` 把 `street` 算成「細」⇒ **不會警告**。


def _fake_nominatim_response(monkeypatch, row):
    """讓 `geo` 收到一筆我指定的 Nominatim 回應。

    ⚠️ 換的是 `urllib.request.urlopen`（`geo` 真正用的那個名字），
    不是 `geocode` 或 `_locate_nominatim` —— 換後者的話，
    **「有沒有去讀 class／type」這件事就驗不到了**，
    而那正是 R9 唯一要求的東西。
    """
    import io
    import json as _json
    import urllib.request

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake(req, *a, **kw):
        return _Resp(_json.dumps([row]).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _fake)


_POI_ROW = {"lat": "25.0252831", "lon": "121.5470035",
            "class": "office", "type": "government",
            "addresstype": "office", "display_name": "交通部航港局"}

_STREET_ROW = {"lat": "24.1815", "lon": "120.6400",
               "class": "highway", "type": "primary",
               "addresstype": "road", "display_name": "台灣大道三段"}

_UNKNOWN_ROW = {"lat": "24.1815", "lon": "120.6400",
                "display_name": "沒有分類資訊的東西"}


def test_r9_a_named_place_is_finer_than_a_road_segment(monkeypatch):
    """🔴 R9：命中**地物**時回 `poi`，命中**路段**時回 `street`。

    🔑 判斷要**從 Nominatim 的 `class`／`type`／`addresstype` 讀**，不可以用猜的。
    📌 A 的限制，值得逐字留著：
    > **不要因為「是用名稱查的」就假設它是地物** ——
    > 那會讓 `poi` 變成「**我用什麼字串查的**」而不是「**我查到了什麼**」。

    ⚠️ 現況：`_locate_nominatim` 不管命中什麼都回 `PRECISION_STREET`
    （`helpers/geo.py:386`），而 `geocode()` 把分類**整個丟掉**
    ⇒ 兩者在回傳上**沒有任何差別**。
    """
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})
    poi = getattr(geo, "PRECISION_POI", None)
    assert poi, "`helpers/geo.py` 缺少 `PRECISION_POI`"

    _fake_nominatim_response(monkeypatch, _POI_ROW)
    got = geo._locate_nominatim("交通部航港局")
    assert got, "前提不成立：假回應沒有被解析出座標"
    assert got[1] == poi, (
        f"命中的是 `class=office`（地物），而精度回 {got[1]!r}，應該是 {poi!r}"
    )

    _fake_nominatim_response(monkeypatch, _STREET_ROW)
    got = geo._locate_nominatim("台中市西屯區台灣大道三段")
    assert got and got[1] == geo.PRECISION_STREET, (
        f"命中的是 `class=highway`（路段），而精度回 "
        f"{got[1] if got else None!r}，應該是 {geo.PRECISION_STREET!r}"
    )


def test_r9b_an_unclassified_hit_stays_at_street(monkeypatch):
    """🔴🔴 R9b 反向控制：**分類讀不出來就維持 `street`。**

    ☠️ 少了這一題，一個「**用名稱查的就算 `poi`**」的實作會讓 R9 綠 ——
    而那正是 A 明文禁止的：**`poi` 會變成「我用什麼字串查的」
    而不是「我查到了什麼」**。

    🔑 而它錯的方向是**往樂觀那一側**：把一個其實很粗的座標標成細的
    ⇒ 前端不會警告 ⇒ **使用者按著一個差好幾公里的圖釘出門。**
    """
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    _fake_nominatim_response(monkeypatch, _UNKNOWN_ROW)
    got = geo._locate_nominatim("某個沒有分類資訊的名稱")
    assert got, "前提不成立：假回應沒有被解析出座標"
    assert got[1] == geo.PRECISION_STREET, (
        f"回應裡沒有 `class`／`type`／`addresstype`，而精度回 {got[1]!r}。\n"
        "⇒ 讀不出來就維持 `street`，不可以因為「是用名稱查的」就假設是地物。"
    )


def test_r10_poi_and_street_are_adjacent_with_poi_finer():
    """🔴 R10：`poi` 與 `street` 在 `PRECISION_ORDER` 裡**相鄰**且 `poi` 較細。

    📌 「相鄰」不是排版潔癖：中間插進別的階，就表示有人對「地物」與「路段」
    之間還做了別的區分，**而那個區分沒有人裁過**。
    """
    order = list(getattr(geo, "PRECISION_ORDER", []))
    poi = getattr(geo, "PRECISION_POI", None)
    assert order and poi, "前提不成立：缺 `PRECISION_ORDER` 或 `PRECISION_POI`"

    i, j = order.index(poi), order.index(geo.PRECISION_STREET)
    assert j - i == 1, (
        f"`poi` 與 `street` 不相鄰或順序反了：{order}\n"
        f"（poi 在第 {i} 位、street 在第 {j} 位，要求是 poi 緊接在 street 之前）"
    )
    assert order.index(geo.PRECISION_ROOFTOP) < i, (
        f"`poi` 要比 `rooftop` 粗，而階梯是 {order}"
    )


def test_r10b_the_frontend_treats_poi_and_street_differently():
    """🟡 R10b：前端的 `precisionIsCoarse()` 對 `poi` 與 `street` 判定不同。

    ## ⚠️ 這是一道**文字比對**，我把它的限制寫在這裡

    `precisionIsCoarse()` 在 `frontend/pages/map.html` 裡，是 JS。
    這一題只能確認**那個字串出現在那個函式裡**，
    🔑 **它答的是「有沒有被提到」，不是「有沒有被執行」** ——
    今天我已經因為同一種工具誤報過一次（U5c 把註解裡的 `DROP TABLE` 當成真的）。

    ⇒ 它的價值只在「**有人改動它時會留下痕跡**」。
    📌 真正的驗收是目視：`poi` 的點**不該**出現粗精度警告，`street` 的**該**出現。
    ⚠️ 而 R9 沒有加的話這一題也沒有意義，所以它綁在 `PRECISION_POI` 上。
    """
    from pathlib import Path

    poi = getattr(geo, "PRECISION_POI", None)
    assert poi, "前提不成立：後端還沒有 `PRECISION_POI`"

    page = (Path(__file__).resolve().parent.parent.parent
            / "frontend" / "pages" / "map.html")
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")

    # 🔴 **錨點要挑到「定義」，不是「呼叫端」。**
    #
    # 第一版用 `text.find("precisionIsCoarse")` ⇒ 抓到的是 **map.html:78**
    # 那個 `x-show` 的**呼叫**，而定義在 **:342**。
    # ⇒ B 把定義改對了（`poi` 現在與 `street` 同側算細），**而這道比對看不到**。
    #
    # 🔑 B 沒有為了讓它綠而在呼叫端塞一句提到 `'poi'` 的註解 ——
    # **那就變成「寫給比對器看的字」**，而那正是我在這支 docstring 裡
    # 自己寫下的限制（「它答的是有沒有被提到，不是有沒有被執行」）。
    # 📌 所以這一次錯的是**錨點**，不是那個限制：
    # **判準要挑得到「被執行的那一份」。**
    import re

    m = re.search(r"precisionIsCoarse\s*\([^)]*\)\s*\{", text)
    assert m, (
        "`map.html` 裡找不到 `precisionIsCoarse()` 的**定義**"
        "（只有呼叫端也算沒有）"
    )
    window = text[m.end():m.end() + 400]
    assert f"'{poi}'" in window or f'"{poi}"' in window, (
        f"`precisionIsCoarse()` 的定義裡沒有處理 `{poi}`：\n{window[:200]}\n"
        "⇒ 後端加了一階而前端沒跟上，那一階在畫面上等於不存在"
        "（加了等於沒加）。"
    )
