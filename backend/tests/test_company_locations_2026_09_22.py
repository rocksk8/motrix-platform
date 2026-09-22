"""§5 BR · 複數據點（分公司）。

> **使用者：「在地址的部分可增加複數選項，由使用者新增名稱跟位置，我們有分公司」**

---

# 🔑 這一節最重要的決定（A 裁）

```
distanceFromOfficeKm   →  到**最近據點**的直線距離
nearestLocationName    →  那個據點的名稱        ← 新增
```

理由：地圖上「離公司多遠」這個問題，背後真正要回答的是
**「這個案子該由哪個據點去」**。
📌 只有一個據點時**行為與現在完全相同** ⇒ 向下相容。

---

# 🔴 三條特別容易寫成假綠燈（A 先點出來的，我照著設計）

## BR7 —— **定位不到的據點不可以安靜地被排除**

☠️ 台北分公司定位失敗 ⇒ 台北的案子全部算成「離梧棲 150 km」
⇒ 🔑 **每個數字都是對的，而整張表在回答一個沒有人問的問題。**
📌 〈答案沒錯，是題目問錯了〉。

## BR9 —— **反向控制是這一節的成敗**

兩個據點，A 較近 ⇒ 名稱是 A；**把 A 刪掉 ⇒ 距離要變、名稱變成 B**。
⚠️ 沒有這一題，一個「**永遠回 `locations[0]`**」的實作會讓 BR6 綠 ——
而那正是「只有一個據點時看不出差別」的那個形狀。

## BR8 —— **`null` 不是 `0`**

一個都定位不到 ⇒ 兩個欄位**都要是 `null`**。
☠️ 回 `0` 的話畫面顯示「離公司 0 km」，**看起來像「就在公司」。**

---

# ⚠️ A 替我查過一件，而它明講要我自己再驗一次

> **「`company_profile.address` 的讀取者只有 `map_points.py:430`；
> `pdf_gen.py` 只讀銀行欄位 ⇒ 改地址結構不會弄壞單據 PDF。
> 這個結論我是用 grep 得到的，而今天我因為 grep 吃到註解誤報過三次 ——
> 你若要釘『PDF 不受影響』這一條，自己再驗一次。」**

⇒ **BR2b 就是那一次覆驗**，而它讀的是「真的被執行的那一份」
（`ast` 找屬性／下標存取），不是 grep。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import geo  # noqa: E402
from helpers.settings import _get_setting, _set_setting  # noqa: E402

PROFILE_PATH = "/api/settings/company-profile"
MAP_PATH = "/api/map/points?sources=tenders"

#: 兩個據點：梧棲（近高雄那筆）與台北（近台北那筆）。
WUQI = {"name": "總公司", "address": "台中市梧棲區"}
TAIPEI = {"name": "台北分公司", "address": "台北市"}

_COORDS = {
    "台中市梧棲區": (24.2549, 120.5316),
    "台北市": (25.0375, 121.5637),
    "高雄市": (22.6273, 120.3014),
}


@pytest.fixture(autouse=True)
def _isolate_geo(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        if manual_coord:
            return geo.GeoResult(coord=tuple(manual_coord),
                                 precision=geo.PRECISION_EXACT,
                                 source=geo.SOURCE_MANUAL, address=key)
        hit = _COORDS.get(key)
        if not hit:
            return geo.GeoResult(error="查表裡沒有：%r" % key, address=key)
        return geo.GeoResult(coord=hit, precision=geo.PRECISION_DISTRICT,
                             source=geo.SOURCE_NOMINATIM, address=key)

    monkeypatch.setattr(geo, "locate_cached", _fake)


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _put(client, hdr, payload, expect=200):
    r = client.put(PROFILE_PATH, json=payload, headers=hdr)
    assert r.status_code == expect, (
        f"PUT {payload} 預期 {expect}，實際 {r.status_code}：{r.text[:220]}"
    )
    return r


def _profile():
    return dict(_get_setting("company_profile", {}) or {})


@pytest.fixture()
def one_tender(client):
    """一筆在高雄的標案 —— 它離梧棲近、離台北遠。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no LIKE 'BR-%'")
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
            "VALUES (?,?,?,?,?)",
            ("BR-0001", "據點測試標案", "據點測試機關", "高雄市",
             "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return "BR-0001"


def _map(client, hdr):
    r = client.get(MAP_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def _point(body, case_no="BR-0001"):
    for p in body["points"]:
        if p.get("caseNo") == case_no:
            return p
    raise AssertionError(
        f"地圖上找不到 {case_no}，有的是："
        f"{[p.get('caseNo') for p in body['points']]}"
    )


# ══════════════════════════════════════════════════════════════════════
# BR1 / BR2 / BR18 · locations 是唯一真相，而舊欄位由它導出
# ══════════════════════════════════════════════════════════════════════

def test_br1_locations_is_the_single_source_of_truth(client, make_user):
    """🔴 BR1／BR2：存 `locations` ⇒ 後端把 `address` 等舊欄位**導出**寫入。

    🔑 理由不是整潔：那三個舊欄位**還有讀取者**
    ⇒ **留著它們是為了相容，而不是為了再編輯一次**。
    ☠️ **兩個地方都能編輯同一件事 = 今天整天在修的那一族缺陷。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(WUQI), dict(TAIPEI)]})

    prof = _profile()
    locs = prof.get("locations")
    assert isinstance(locs, list) and len(locs) == 2, (
        f"`locations` 沒有被存下來：{locs!r}"
    )
    assert prof.get("address") == WUQI["address"], (
        f"`address` 沒有從 `locations[0]` 導出："
        f"{prof.get('address')!r} vs {WUQI['address']!r}\n"
        "⇒ 舊的讀取者（`map_points.py`）會看到過期的地址。"
    )


def test_br2_the_legacy_fields_are_derived_not_edited(client, make_user):
    """🔴 BR2：`address`／`office_lat`／`office_lon` **由 `locations[0]` 導出**，
    而且是**後端在存檔時寫入**，不是前端兩邊各寫一次。

    ⚠️ 這一題原本折在 `test_br1_` 裡 —— 而 **BR1 與 BR2 是兩條**
    （前者是「`locations` 是唯一真相」，後者是「舊欄位怎麼來」）。
    🔑 「寫了但編號對不上」——**今天第五次**（SO6／WB3／YA3／YB2／這一條），
    而五次都是我把兩條規格折進一支測試。
    📌 〈判準的寬窄都會騙人〉的一個新面向：**一支測試涵蓋兩條條件時，
    守門只看得到其中一條** —— 而它報的是「另一條沒有人寫」。

    ⇒ 判準：**只送 `locations`**（完全不送那三個舊欄位）⇒ 它們要被後端填好。
    ☠️ 前端也送的話就是「兩個地方都能編輯同一件事」，
    而那是今天整天在修的那一族缺陷。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [
        {**TAIPEI, "lat": 25.0375, "lon": 121.5637},
        dict(WUQI),
    ]})

    prof = _profile()
    assert prof.get("address") == TAIPEI["address"], (
        f"`address` 不是從 `locations[0]` 導出的：{prof.get('address')!r}"
    )
    assert (prof.get("office_lat"), prof.get("office_lon")) == (25.0375, 121.5637), (
        f"`office_lat`／`office_lon` 沒有跟著 `locations[0]` 走："
        f"{prof.get('office_lat')!r}, {prof.get('office_lon')!r}\n"
        "⇒ 舊的讀取者（`map_points.py` 的 `_manual_coord`）會拿到過期的座標。"
    )


def test_br18_a_reload_agrees_with_locations_zero(client, make_user):
    """🔴 BR18 反向控制：**存檔後重新讀取 ⇒ `address` 等於 `locations[0].address`。**

    ☠️ 少了這一題，一個「**只在回應裡算，沒有寫進去**」的實作會讓 BR2 綠 ——
    而下一次重新載入時 `address` 還是舊的，
    🔑 而症狀是「**改了地址，地圖上的距離沒變**」——
    使用者會再改一次，然後以為系統很慢。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(TAIPEI), dict(WUQI)]})

    r = client.get(PROFILE_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    locs = body.get("locations") or []
    assert locs, "GET 回來沒有 `locations`"
    assert body.get("address") == locs[0].get("address"), (
        f"`address`（{body.get('address')!r}）與 `locations[0].address`"
        f"（{locs[0].get('address')!r}）不一致"
    )


def test_br2b_changing_the_address_shape_cannot_break_the_pdfs():
    """🟢 BR2b：**覆驗 A 的結論 —— `pdf_gen.py` 只讀銀行欄位。**

    ## ⚠️ A 明講要我自己再驗一次，理由是它自己的工具不可靠

    > 「這個結論我是用 grep 得到的，**而今天我因為 grep 吃到註解誤報過三次**。」

    ⇒ 所以這一題**不用 grep** —— 它用 `ast` 找**真的被執行的那些存取**
    （屬性存取與下標存取），註解與 docstring 不在 AST 裡。
    🔑 〈診斷的層級決定覆蓋率〉：**文字比對答的是「有沒有被提到」。**

    📌 判準：`pdf_gen.py` 裡對 `company_profile` 的下標存取，
    **不可以包含 `address`／`locations`／`office_lat`／`office_lon`**。
    """
    import ast

    src = (Path(__file__).resolve().parent.parent / "helpers" / "pdf_gen.py")
    if not src.exists():
        src = Path(__file__).resolve().parent.parent / "pdf_gen.py"
    assert src.exists(), f"找不到 pdf_gen.py（試過 helpers/ 與 backend/）"

    tree = ast.parse(src.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                keys.add(node.slice.value)
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr == "get"
              and node.args
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)):
            keys.add(node.args[0].value)

    assert keys, "AST 裡一個字串鍵都沒抓到 —— 這一題的前提不成立（解析壞了？）"
    risky = keys & {"address", "locations", "office_lat", "office_lon"}
    assert not risky, (
        f"`pdf_gen.py` 會讀到這些地址相關的鍵：{sorted(risky)}\n"
        "⇒ 改 `company_profile` 的地址結構會影響單據 PDF。"
    )


# ══════════════════════════════════════════════════════════════════════
# BR3 · 升級遷移
# ══════════════════════════════════════════════════════════════════════

def test_br3_an_existing_address_becomes_one_location(client, make_user):
    """🔴 BR3：`locations` 不存在而 `address` 非空 ⇒ **建一筆「總公司」**。

    📌 那是**既有安裝**走的路：他們的 `company_profile` 裡有 `address`
    而沒有 `locations`。
    """
    prof = _profile()
    prof.pop("locations", None)
    prof["address"] = "台中市梧棲區"
    prof["office_lat"] = 24.2549
    prof["office_lon"] = 120.5316
    _set_setting("company_profile", prof)

    hdr = _auth(client, make_user)
    r = client.get(PROFILE_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    locs = r.json().get("locations")

    assert isinstance(locs, list) and len(locs) == 1, (
        f"既有的 `address` 沒有被遷移成一筆據點：{locs!r}"
    )
    assert locs[0].get("address") == "台中市梧棲區", locs[0]
    assert (locs[0].get("lat"), locs[0].get("lon")) == (24.2549, 120.5316), (
        f"手動座標沒有跟著搬過來：{locs[0]}"
    )


def test_br3b_an_empty_address_does_not_become_an_empty_location(
        client, make_user):
    """🔴🔴 BR3b：`address` 是**空的** ⇒ **給空清單，不要造一筆空的據點**。

    ☠️ 一筆「有名字沒地址」的據點會在地圖上變成「**定位不到的據點**」，
    🔑 **而那與「使用者真的填錯了地址」長得一模一樣。**
    📌 ⇒ 新裝的機器會在第一天就看到一個「總公司定位不到」的警告，
    而他**什麼都還沒填**。
    """
    prof = _profile()
    prof.pop("locations", None)
    prof["address"] = ""
    prof.pop("office_lat", None)
    prof.pop("office_lon", None)
    _set_setting("company_profile", prof)

    hdr = _auth(client, make_user)
    r = client.get(PROFILE_PATH, headers=hdr)
    locs = r.json().get("locations")
    assert locs == [], (
        f"地址是空的，而它造出了 {locs!r}\n"
        "⇒ 新裝的機器第一天就會看到「總公司定位不到」，而他什麼都還沒填。"
    )


# ══════════════════════════════════════════════════════════════════════
# BR4 / BR5 · 名稱與 id
# ══════════════════════════════════════════════════════════════════════

def test_br4_a_duplicate_name_is_refused(client, make_user):
    """🔴 BR4：名稱必填且**不可重複** ⇒ 重複要 422。

    🔑 理由不是整潔：距離欄位要寫「離**台北分公司** 3.2 km」，
    **兩個同名的據點會讓那句話沒有意義。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr,
         {"locations": [{"name": "台北", "address": "台北市"},
                        {"name": "台北", "address": "台中市梧棲區"}]},
         expect=422)


def test_br4b_an_empty_name_is_refused(client, make_user):
    """🔴 BR4b：名稱**必填** ⇒ 空字串要 422。

    ⚠️ 與 BR4 分開是因為它們的失敗方式不同：重複名稱**看起來正常**，
    而空名稱會讓距離欄位寫出「離 3.2 km」這種沒有主詞的句子。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [{"name": "", "address": "台北市"}]},
         expect=422)


def test_br5_ids_are_assigned_and_never_reused(client, make_user):
    """🔴 BR5：`id` 由後端配發，**不可重用已刪除的 id**。

    ☠️ 重用的後果：某個地方存著「這個案子歸據點 3」，
    而據點 3 被刪掉、新的台北分公司拿到同一個 3
    ⇒ **那筆歸屬悄悄換了對象**，而畫面上完全正常。
    🔑 〈降級之後它還是會動〉的一種：**資料看起來完整，只是指錯了人。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(WUQI), dict(TAIPEI)]})
    first = [loc.get("id") for loc in _profile().get("locations") or []]
    assert all(i is not None for i in first), f"後端沒有配發 id：{first}"
    assert len(set(first)) == 2, f"兩筆據點拿到重複的 id：{first}"

    # 刪掉第二筆，再新增一筆
    _put(client, hdr, {"locations": [dict(WUQI)]})
    _put(client, hdr, {"locations": [dict(WUQI),
                                     {"name": "高雄分公司",
                                      "address": "高雄市"}]})
    later = [loc.get("id") for loc in _profile().get("locations") or []]
    new_id = [i for i in later if i not in first[:1]]
    assert new_id and new_id[0] not in first, (
        f"新據點重用了已刪除的 id：新 {new_id}，舊 {first}\n"
        "⇒ 存著「歸屬於據點 N」的資料會悄悄換對象。"
    )


# ══════════════════════════════════════════════════════════════════════
# BR6 / BR7 / BR8 / BR9 · 距離的語意
# ══════════════════════════════════════════════════════════════════════

def test_br6_the_distance_is_to_the_nearest_location(
        client, make_user, one_tender):
    """🔴 BR6：距離是到**最近據點**的，而回應要說出是哪一個。

    📌 那筆標案在高雄 ⇒ 梧棲（約 130 km）比台北（約 290 km）近。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(TAIPEI), dict(WUQI)]})

    p = _point(_map(client, hdr))
    assert p.get("nearestLocationName") == WUQI["name"], (
        f"最近的應該是 `{WUQI['name']}`，實際 "
        f"{p.get('nearestLocationName')!r}\n"
        "⚠️ 注意 `locations[0]` 是台北 —— 回台北就表示它回的是第一筆不是最近的。"
    )
    assert p.get("distanceFromOfficeKm") is not None, p


def test_br9_removing_the_nearest_location_changes_the_answer(
        client, make_user, one_tender):
    """🔴🔴 BR9 反向控制：**把最近的那個據點刪掉 ⇒ 距離要變、名稱變成另一個。**

    ☠️ 少了這一題，一個「**永遠回 `locations[0]`**」的實作會讓 BR6 綠 ——
    而那正是「只有一個據點時看不出差別」的那個形狀。
    🔑 **兩個據點才分得出「最近」與「第一個」。**
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(TAIPEI), dict(WUQI)]})
    before = _point(_map(client, hdr))
    assert before.get("nearestLocationName") == WUQI["name"], "前提不成立（見 BR6）"

    _put(client, hdr, {"locations": [dict(TAIPEI)]})
    after = _point(_map(client, hdr))

    assert after.get("nearestLocationName") == TAIPEI["name"], (
        f"刪掉梧棲之後，最近的應該變成台北，實際 "
        f"{after.get('nearestLocationName')!r}"
    )
    assert after.get("distanceFromOfficeKm") != before.get("distanceFromOfficeKm"), (
        f"據點換了而距離沒變：兩次都是 "
        f"{before.get('distanceFromOfficeKm')} km\n"
        "⇒ 那個距離不是從最近據點算的。"
    )


def test_br7_locations_that_cannot_be_located_are_visible(
        client, make_user, one_tender):
    """🔴🔴 BR7：**定位不到的據點要被看見**，回應要有數量**與清單**。

    ## ☠️ 不講的後果

    台北分公司定位失敗 ⇒ 台北的案子**全部算成「離梧棲 150 km」**
    ⇒ 🔑 **每個數字都是對的，而整張表在回答一個沒有人問的問題。**
    📌 〈答案沒錯，是題目問錯了〉。

    ⚠️ 而「數量」不夠 —— **要指得出是哪幾筆**：
    一個「2 個據點定位不到」的數字，使用者無從知道該去修哪一個地址。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [
        dict(WUQI),
        {"name": "查不到分公司", "address": "某某完全查不到的地址ZZZ"},
    ]})

    body = _map(client, hdr)
    assert body.get("locationsUnlocated"), (
        "有一個據點定位不到，而 `locationsUnlocated` 是 "
        f"{body.get('locationsUnlocated')!r}\n"
        "☠️ 不講的話，那個據點附近的案子全部會被算到別的據點上，"
        "而每個數字都是對的。"
    )
    blob = json.dumps(body.get("locationsUnlocated"), ensure_ascii=False,
                      default=str)
    assert "查不到分公司" in blob, (
        f"`locationsUnlocated` 說不出是哪一筆：{blob[:200]}\n"
        "⇒ 使用者無從知道該去修哪一個地址。"
    )


def test_br8_no_locatable_location_means_null_not_zero(
        client, make_user, one_tender):
    """🔴 BR8：**一個據點都定位不到 ⇒ 兩個欄位都要是 `null`，不是 `0`。**

    ☠️ 回 `0` 的話畫面顯示「離公司 0 km」，**看起來像「就在公司」** ——
    🔑 而使用者會照著那個數字排行程。
    📌 〈null 不等於 0〉。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [
        {"name": "查不到甲", "address": "某某查不到的地址AAA"},
        {"name": "查不到乙", "address": "某某查不到的地址BBB"},
    ]})

    # 🔴 **前提：那兩筆據點真的被收下了。**
    # ⚠️ 少了這一道，這一題在「`locations` 還不支援」時會**空綠** ——
    #    距離是 `None` 只是因為根本沒有辦公室地址，
    #    **而不是因為「據點都定位不到」**。
    # 🔑 那正是今天反覆出現的那個形狀：**綠燈是真的，而理由不是我以為的那個。**
    stored = _profile().get("locations") or []
    assert len(stored) == 2, (
        f"那兩筆據點沒有被收下（`locations` 是 {stored!r}）⇒ "
        "下面的斷言證明不了任何事。"
    )

    p = _point(_map(client, hdr))
    assert p.get("distanceFromOfficeKm") is None, (
        f"一個據點都定位不到，而距離是 {p.get('distanceFromOfficeKm')!r}\n"
        "☠️ `0` 看起來像「就在公司」。"
    )
    assert p.get("nearestLocationName") is None, (
        f"沒有可用的據點，而名稱是 {p.get('nearestLocationName')!r}"
    )


def test_br8b_one_location_behaves_exactly_like_before(
        client, make_user, one_tender):
    """🟢 BR8b 反向控制：**只有一個據點時，行為與改版前完全相同。**

    📌 那是 A 裁決能成立的前提（「向下相容」）——
    ⚠️ 而它同時擋住一個實作方向：「有多個據點才算最近的，否則回 null」。
    🔑 少了這一題，那個實作會讓 BR8 綠**而讓既有使用者的距離全部消失**。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(WUQI)]})

    p = _point(_map(client, hdr))
    assert p.get("distanceFromOfficeKm") is not None, (
        "只有一個據點而距離是 null —— 既有使用者的距離會全部消失"
    )
    assert p.get("nearestLocationName") == WUQI["name"], p


# ══════════════════════════════════════════════════════════════════════
# BR13 / BR21 · 背景佇列與備份
# ══════════════════════════════════════════════════════════════════════

def test_br13_the_background_queue_includes_the_location_addresses(
        client, make_user):
    """🔴 BR13：**背景暖快取要把據點地址也納入佇列。**

    ⚠️ 不納入的話，新增一個分公司之後**要等到有人打開地圖才會被定位** ——
    🔑 而那正是 §3v 整節要解決的事（使用者不必按任何按鈕）。
    📌 而它與 VD1 不衝突：**據點是公司的營業地址，不是自然人的住家。**
    """
    import routers.map_points as mp

    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(WUQI), dict(TAIPEI)]})

    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache")
        conn.commit()
    finally:
        conn.close()

    backlog = set(mp._map_geocode_backlog())
    assert TAIPEI["address"] in backlog, (
        f"據點地址 `{TAIPEI['address']}` 不在背景佇列裡"
        f"（佇列有 {len(backlog)} 筆）\n"
        "⇒ 新增分公司之後要等到有人打開地圖才會被定位。"
    )


def test_br21_the_locations_survive_a_restore_without_geocode_cache(
        client, make_user):
    """🔴 BR21：**據點座標要存在 `company_profile`（會被備份）**，
    `geocode_cache` 只是加速。

    ## ☠️ 為什麼這一條存在

    `geocode_cache` 今天才因為隱私被**排除出每日備份**（§3t）
    ⇒ **還原之後那張表是空的。**
    🔑 若據點的座標只存在快取裡，還原之後**每個據點都要重新定位**，
    而那需要對外連線 —— ⚠️ **而災難還原的當下不一定有網路。**
    📌 ⇒ 座標要跟著 `company_profile` 一起被備份。

    (這一題模擬「還原之後」：清空 `geocode_cache`，據點仍要有座標。)
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, {"locations": [dict(WUQI)]})

    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache")
        conn.commit()
    finally:
        conn.close()

    locs = _profile().get("locations") or []
    assert locs, "前提不成立：沒有據點"
    assert locs[0].get("lat") is not None and locs[0].get("lon") is not None, (
        f"清空 `geocode_cache` 之後，據點沒有自己的座標：{locs[0]}\n"
        "☠️ 災難還原之後每個據點都要重新定位，而那時不一定有網路。"
    )


# ══════════════════════════════════════════════════════════════════════
# BR22 · 🔴 每一筆據點可以帶自己的銀行欄位（**結構先留位置**）
# ══════════════════════════════════════════════════════════════════════

def test_br22_a_location_can_carry_its_own_bank_fields(client, make_user):
    """🔴 BR22：`locations` 的每一筆**可以帶自己的銀行欄位**（留空＝沿用主要據點）。

    ## ☠️ 這是 §5 的隱藏需求，而它差一點被我們兩個一起漏掉

    A 早上告訴我：「`pdf_gen.py` **只讀銀行欄位** ⇒ 改地址結構不會弄壞 PDF」
    —— **那句話本身沒錯**（我用 AST 覆驗過，見 BR2b）。
    🔑 **而它讓我們兩個都沒問下一個問題：那銀行欄位要不要跟著據點走？**

    ☠️ **分公司的報價單不能印總公司的帳號。**
    📌 〈答案沒錯，是題目問錯了〉的一個新變體：
    **一個正確的答案，把問題的邊界畫在錯的地方。**

    ## ⚠️ 這一題刻意只釘「結構存得下」，不釘「PDF 真的讀它」

    讓 PDF 讀它是 **WL1**（§7 白標化），不是這一輪。
    🔑 **而結構現在就要留位置** —— 否則 §5 定稿之後要再改一次資料結構，
    **而那時已經有正式機資料了**（那一改就變成 migration，不是編輯）。

    📌 所以判準是：存進去、拿出來、**值沒有被吞掉**。
    ⚠️ 留空（或整個沒有那幾個鍵）**必須也合法** —— 那是「沿用主要據點」，
    ☠️ 而把它做成必填會讓既有的單一據點使用者**存不了檔**。
    """
    hdr = _auth(client, make_user)
    bank = {"bank_name": "測試銀行", "bank_branch": "梧棲分行",
            "bank_account_name": "分公司帳戶", "bank_account_number": "12345678"}

    _put(client, hdr, {"locations": [
        dict(WUQI),                      # ← 完全沒有銀行欄位：合法（沿用）
        {**TAIPEI, **bank},              # ← 帶自己的
    ]})

    locs = _profile().get("locations") or []
    assert len(locs) == 2, f"兩筆據點沒有都存下來：{locs!r}"

    taipei = next((l for l in locs if l.get("name") == TAIPEI["name"]), None)
    assert taipei, f"找不到台北那一筆：{locs!r}"
    missing = {k: v for k, v in bank.items() if taipei.get(k) != v}
    assert not missing, (
        f"台北分公司的銀行欄位被吞掉了：{missing}\n"
        "☠️ 分公司的報價單不能印總公司的帳號（WL1 會讀這裡）。"
    )

    wuqi = next((l for l in locs if l.get("name") == WUQI["name"]), None)
    assert wuqi, f"找不到梧棲那一筆：{locs!r}"
    assert not any(str(wuqi.get(k) or "").strip() for k in bank), (
        f"沒有填銀行欄位的那一筆被塞了預設值：{wuqi}\n"
        "⇒ 「留空」與「填了空字串」要分得開：留空的語意是**沿用主要據點**，"
        "而一個被塞了空字串的欄位讀起來像「這個據點沒有帳號」。"
    )
