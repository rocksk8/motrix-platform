"""§3n · 瀏覽器定位：使用者的位置與辦公室**並列**（G1–G9）。

> **使用者：「我即便沒有在雷達內，也要能用地圖」**（§3n 是它的延伸：
> 「從我現在的位置有多遠」）

## 🔑 這一節的核心決定：**不要用定位取代辦公室座標，兩個並列**

辦公室是穩定的錨點，定位是會變的。兩個距離都給，使用者自己看哪個有用。
⚠️ **定位失敗時絕對不可以靜靜退回辦公室距離** ——
使用者會以為定位成功了，而距離是從公司算的。
🔑 〈降級之後它還是會動〉：那個畫面**完全正常**，只是數字是另一件事的答案。

---

# ⚠️ 兩件我在寫之前查出來的事，B 動工前要看

## 一、🔴 `distanceKm` 改名會讓地圖**安靜地不顯示距離**

G1 要的欄位是 `distanceFromOfficeKm`，而現在叫 `distanceKm`，
**`frontend/pages/map.html` 有 5 處在用它**（230／233／236／397／398）。

而那幾處長這樣：
```js
<template x-if="p.distanceKm === null || p.distanceKm === undefined">
```
⇒ 改了後端而沒改前端的話，**每個圖釘都會走進「沒有距離」那個分支** ——
畫面不會壞、不會報錯，**它只是再也不顯示距離了**。
📌 兩邊一起改，或後端兩個鍵都給一段時間。**這件事測試這一側看不見。**

## 二、⚠️ G7 照字面寫會是**空綠**，我改了它的形狀

G7 說「`geo_on()` 關著時，兩個距離都是 `null`」。
⚠️ 而 `geo.locate()` 在 `geo_on()` 關著時**直接回錯誤**（`helpers/geo.py:420`）
⇒ **一個點都產不出來** ⇒「每個點的距離都是 null」在空清單上**永遠成立**。

🔑 今天反覆出現的空集合假綠燈，而這一次它藏在規格條文本身裡。
⇒ 我把 G7 改成**對照**：同一個請求，關著 → 沒有點且 `geoEnabled` 是 false；
開著 → 有點且有距離。**「關掉真的有差」才是這一條要證明的事。**
"""
import sqlite3

import pytest

from helpers import geo
from tests._map_cache_warm import serve_from_fake

#: 兩組**明顯不同**的使用者座標（台北 / 高雄，直線約 300 公里）。
#: 🔑 G8 用它們證明 `distanceFromUserKm` 真的隨座標改變 ——
#: 差距要大到「四捨五入之後仍然不同」，否則一個回固定值的實作可能剛好矇混過去。
USER_TAIPEI = (25.0339123, 121.5644987)
USER_KAOHSIUNG = (22.6272311, 120.3014567)

#: 辦公室（公司登記地）。用 §3o 實測查得到的行政區。
OFFICE_ADDRESS = "台中市梧棲區"

_FAKE_GEO = {
    OFFICE_ADDRESS: ((24.2549, 120.5316), geo.PRECISION_DISTRICT),
    "台中市":        ((24.1477, 120.6736), geo.PRECISION_DISTRICT),
    "高雄市":        ((22.6273, 120.3014), geo.PRECISION_DISTRICT),
}


@pytest.fixture(autouse=True)
def _isolate_geo(monkeypatch):
    """關掉圖磚探測、把地理查詢換成查表。

    ⚠️ **假貨刻意仍然遵守 `geo_on()`** —— 不遵守的話 G7 就驗不到任何東西，
    而它會**綠**（因為點照樣產得出來，距離照樣算得出來）。
    🔑 〈觀測手段與被測對象共用一段程式碼〉的反面用法：
    **假貨要保留被測的那一個開關，其餘才可以假。**
    """
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)

    def _fake(address, manual_coord=None):
        if manual_coord:
            return geo.GeoResult(coord=tuple(manual_coord),
                                 precision=geo.PRECISION_EXACT,
                                 source=geo.SOURCE_MANUAL, address=address)
        if not geo.geo_on():
            return geo.GeoResult(error="地理查詢未啟用（需要 MOTRIX_GEO=1）",
                                 address=address)
        hit = _FAKE_GEO.get((address or "").strip())
        if not hit:
            return geo.GeoResult(error="測試查表裡沒有：%r" % address,
                                 address=address)
        return geo.GeoResult(coord=hit[0], precision=hit[1],
                             source=geo.SOURCE_NOMINATIM, address=address)

    monkeypatch.setattr(geo, "locate_cached", _fake)
    serve_from_fake(monkeypatch, _fake)  # MP8：快取＝查表（背景預熱已完成）


@pytest.fixture()
def geo_enabled(monkeypatch):
    monkeypatch.setattr(geo, "GEO_ENABLED", True)


@pytest.fixture()
def office(client):
    """把公司地址種進 `company_profile`。"""
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile["address"] = OFFICE_ADDRESS
    profile.pop("office_lat", None)
    profile.pop("office_lon", None)
    _set_setting("company_profile", profile)


@pytest.fixture()
def no_office(client):
    """公司地址**沒填**（G6）。"""
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile["address"] = ""
    profile.pop("office_lat", None)
    profile.pop("office_lon", None)
    _set_setting("company_profile", profile)


@pytest.fixture()
def tenders(client):
    """兩筆有地點的標案，讓地圖上真的有點。"""
    import db
    conn = db.get_db()
    try:
        for n, loc in (("GEO-T-001", "台中市"), ("GEO-T-002", "高雄市")):
            conn.execute(
                "INSERT INTO tenders (case_no, name, org, location, fetched_at) "
                "VALUES (?,?,?,?,?)",
                (n, "定位測試標案 " + n, "定位測試機關", loc,
                 "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


#: 🔴 使用者的座標走**標頭**，不走 query string。格式 `<lat>,<lon>,<accuracy>`。
#:
#: ## ☠️ 為什麼改形狀：B 實測出一個我們三個都沒想到的出口
#:
#: ```
#: INFO: 127.0.0.1:34378 - "GET /api/map/points?sources=tenders
#:       &lat=24.1657&lon=120.6402&accuracy=35 HTTP/1.1" 200 OK
#: ```
#: 正式機的 `autostart.bat` 是 `uvicorn … --log-level info >> logs\server.log`
#: ⇒ **每按一次「使用我的位置」，那個人當下的座標就被追加進一個永久檔案。**
#:
#: ⚠️ **而我的 G9 三張表全是乾淨的**：`system_settings` 沒寫、`audit_log` 沒寫、
#: `user_request_log` 存的是 `request.url.path`（**不含** query string）。
#: 🔑 **三個想得到的出口都堵了，漏的是沒有人列進清單的那一個** ——
#: **它不在我們的程式碼裡，在 web server 裡。**
#: 📌 **我們列的是「我們會寫入的地方」，而資料外洩不需要我們寫入，
#: 只需要有人記錄。**
POSITION_HEADER = "X-Map-Position"


def _ask(client, hdr, *, position=None, query=None, expect=200):
    """打一次地圖端點。`position` 走標頭，`query` 是刻意走舊路（G10 用）。"""
    q = "sources=tenders" + (("&" + query) if query else "")
    headers = dict(hdr)
    if position is not None:
        headers[POSITION_HEADER] = position
    r = client.get("/api/map/points?" + q, headers=headers)
    assert r.status_code == expect, (
        f"?{q}  {POSITION_HEADER}={position!r}\n"
        f"預期 {expect}，實際 {r.status_code}：{r.text[:250]}"
    )
    return r.json() if r.status_code == 200 else r


def _pos(coords, accuracy=42):
    return f"{coords[0]},{coords[1]},{accuracy}"


# ══════════════════════════════════════════════════════════════════════
# G1 · 三個參數都給 ⇒ 兩個距離並列
# ══════════════════════════════════════════════════════════════════════

def test_g1_both_distances_are_reported_side_by_side(
        client, make_user, geo_enabled, office, tenders):
    """🔴 G1：`lat`＋`lon`＋`accuracy` 都給 ⇒ **每一筆同時有兩個距離**，
    而頂層有 `userAccuracyM`。

    🔑 **並列不是二選一。** 辦公室是穩定的錨點、定位是會變的，
    使用者自己看哪個有用。
    ⚠️ 少了 `userAccuracyM`，畫面就只剩一個數字而沒有它的可信度 ——
    **今晚第四次同一件事：一個數字不帶它的誤差，就會被當成事實。**
    """
    hdr = _auth(client, make_user)
    body = _ask(client, hdr, position=_pos(USER_TAIPEI))

    assert body["points"], "一個點都沒有 —— 這一題的前提不成立"
    assert body.get("userAccuracyM") == 42, (
        f"頂層 `userAccuracyM` 應該是 42，實際 {body.get('userAccuracyM')!r}"
    )
    for p in body["points"]:
        assert p.get("distanceFromOfficeKm") is not None, (
            f"少了 `distanceFromOfficeKm`：{p}"
        )
        assert p.get("distanceFromUserKm") is not None, (
            f"少了 `distanceFromUserKm`：{p}\n"
            "⇒ 兩個距離要並列，不是用定位取代辦公室。"
        )


# ══════════════════════════════════════════════════════════════════════
# G2 / G4 / G5 · 參數驗證
# ══════════════════════════════════════════════════════════════════════

def test_g2_coordinates_without_accuracy_are_rejected(
        client, make_user, geo_enabled, office, tenders):
    """🔴 G2：只給 `lat`/`lon` 不給 `accuracy` ⇒ **422**。

    ☠️ **不可以預設一個誤差值。** 預設的話，畫面上會出現一個
    「誤差約 N 公尺」而那個 N **不是量出來的** ——
    🔑 〈一個數字不帶它的可信度就會被當成事實〉的更壞版本：
    **那個可信度本身是編的。**

    ## 🔴 這一題第一版沒有驗到它自己宣稱的東西，⑤ 抓出來的

    第一版只送兩段的標頭（`lat,lon`）。⚠️ 而那樣的 422 來自
    **標頭的格式檢查**（「格式是 `<lat>,<lon>,<accuracy>`」），
    **不是來自「不可以預設誤差」那一條**。
    ⇒ 我把 `_user_position` 突變成「沒給 accuracy 就預設 50」之後，
    **這一題照樣綠**（只有 `test_g5[""]` 紅了）。

    🔑 跟 G10b 同一個形狀：**「回 422」太寬了，要問的是「為什麼 422」。**
    ⇒ 兩種形狀都送：**少一段**（格式錯）與**三段但誤差是空的**（真正的那一條）。
    """
    hdr = _auth(client, make_user)

    # ① 少一段：格式錯
    _ask(client, hdr, position=f"{USER_TAIPEI[0]},{USER_TAIPEI[1]}", expect=422)

    # ② 三段而誤差是空的 —— **這一個才是「不可以預設一個誤差值」**
    r = _ask(client, hdr, position=f"{USER_TAIPEI[0]},{USER_TAIPEI[1]},",
             expect=422)
    assert "accuracy" in r.text or "誤差" in r.text, (
        f"誤差留空時回了 422，但訊息沒提到誤差：{r.text[:200]}\n"
        "⇒ 那道 422 可能來自格式檢查，而「不可以預設一個誤差值」仍然沒有人守。"
    )


@pytest.mark.parametrize("lat,lon", [
    (91.0, 121.0), (-91.0, 121.0),
    (25.0, 181.0), (25.0, -181.0),
    ("abc", 121.0), (25.0, "xyz"),
])
def test_g4_out_of_range_coordinates_are_rejected(
        client, make_user, geo_enabled, office, tenders, lat, lon):
    """🔴 G4：`lat` 不在 -90~90／`lon` 不在 -180~180 ⇒ **422**。

    ⚠️ 不擋的話，一個打錯的座標會算出一個**看起來很正常的距離**
    （地球是圓的，什麼數字都算得出來）—— 而沒有人會發現。
    """
    hdr = _auth(client, make_user)
    _ask(client, hdr, position=f"{lat},{lon},42", expect=422)


@pytest.mark.parametrize("accuracy", [-1, -0.5, "abc", ""])
def test_g5_a_bad_accuracy_is_rejected(
        client, make_user, geo_enabled, office, tenders, accuracy):
    """🔴 G5：`accuracy` 是負數或非數字 ⇒ **422**。

    📌 `0` 一開始**刻意不在這張表裡**：它的語意不明（「完美精準」還是
    「沒量到」？），而當時沒有人裁過它。
    ⚠️ 我不把一個沒有人決定過的值寫成斷言 —— 那會變成**我替使用者做了決定**。
    ⇒ A 2026-09-22 裁了，見下面的 G5b。
    """
    hdr = _auth(client, make_user)
    _ask(client, hdr, position=_pos(USER_TAIPEI, accuracy), expect=422)


def test_g5b_an_accuracy_of_zero_is_rejected_too(
        client, make_user, geo_enabled, office, tenders):
    """🔴 G5b：`accuracy=0` ⇒ **422**，跟負數同一條路（A 2026-09-22 裁定）。

    ☠️ **理由不是「0 不合理」，是「0 會讓我們說一句謊」。**
    瀏覽器定位**沒有任何情境能宣稱誤差為零**（GPS 最佳也是數公尺）
    ⇒ 收下 `0` 的話，畫面會顯示「誤差約 0 公尺」。
    🔑 **那比不顯示誤差更糟 —— 它是一個具體而錯誤的保證。**

    📌 而它直接繞過 §3n 的核心設計：**距離與誤差綁在一起**，
    而綁上去的誤差如果可以是 0，**整個設計就白做了**。
    （A 的話，我照收；我原本只是不替使用者決定，沒想到這一層。）
    """
    hdr = _auth(client, make_user)
    _ask(client, hdr, position=_pos(USER_TAIPEI, 0), expect=422)


# ══════════════════════════════════════════════════════════════════════
# G3 · 三個都不給
# ══════════════════════════════════════════════════════════════════════

def test_g3_without_user_coordinates_the_user_distance_is_null_not_zero(
        client, make_user, geo_enabled, office, tenders):
    """🔴 G3：三個都不給 ⇒ `distanceFromUserKm` 是 **`null` 不是 `0`**。

    ☠️ `0` 的意思是「**你就站在那個標案上**」。
    🔑 〈null 不等於 0〉：合併之後的錯誤**看起來完全正常**，所以沒有人會報修 ——
    而這一次它會把使用者送到一個他其實離得很遠的地方。
    """
    hdr = _auth(client, make_user)
    body = _ask(client, hdr)

    assert body["points"], "一個點都沒有 —— 這一題的前提不成立"
    assert body.get("userAccuracyM") is None, (
        f"沒有給定位 ⇒ 頂層 `userAccuracyM` 要是 null，"
        f"實際 {body.get('userAccuracyM')!r}"
    )
    for p in body["points"]:
        assert p.get("distanceFromOfficeKm") is not None, (
            f"辦公室地址填了，`distanceFromOfficeKm` 不該是 null：{p}"
        )
        assert "distanceFromUserKm" in p, (
            f"少了 `distanceFromUserKm` 這個鍵：{p}\n"
            "⇒ 省略與 null 是兩件事：省略讀起來像「這裡不適用」。"
        )
        assert p["distanceFromUserKm"] is None, (
            f"沒有給定位，而 `distanceFromUserKm` 是 {p['distanceFromUserKm']!r}"
            " —— 必須是 null。0 的意思是「你就站在那個標案上」。"
        )


# ══════════════════════════════════════════════════════════════════════
# G6 · 兩個錨點互相獨立
# ══════════════════════════════════════════════════════════════════════

def test_g6_a_missing_office_does_not_break_the_user_distance(
        client, make_user, geo_enabled, no_office, tenders):
    """🔴 G6：辦公室地址沒填 ⇒ `distanceFromOfficeKm` 是 null、
    `officeMissing` 是 true，**而 `distanceFromUserKm` 照樣算得出來**。

    🔑 **兩個錨點互相獨立，一個壞不影響另一個。**
    ⚠️ 共用一段計算的話，「公司地址還沒填」會讓定位功能整個看起來壞掉 ——
    而那是一個**新使用者第一天就會遇到**的狀態。
    """
    hdr = _auth(client, make_user)
    body = _ask(client, hdr, position=_pos(USER_TAIPEI))

    assert body.get("officeMissing") is True, (
        f"地址沒填，而 `officeMissing` 是 {body.get('officeMissing')!r}"
    )
    assert body["points"], "一個點都沒有 —— 這一題的前提不成立"
    for p in body["points"]:
        assert p.get("distanceFromOfficeKm") is None, (
            f"辦公室地址沒填，而 `distanceFromOfficeKm` 是 "
            f"{p.get('distanceFromOfficeKm')!r}"
        )
        assert p.get("distanceFromUserKm") is not None, (
            f"辦公室沒填**不該**影響定位距離：{p}\n"
            "⇒ 兩個錨點要互相獨立。"
        )


# ══════════════════════════════════════════════════════════════════════
# G7 · 地理查詢關著時
# ══════════════════════════════════════════════════════════════════════

def test_g7_turning_geo_off_is_visibly_different_from_zero_kilometres(
        client, make_user, office, tenders, monkeypatch):
    """🔴 G7：`geo_on()` 關著時，`geoEnabled` 是 false，
    **而且要分得出「沒開地理查詢」與「算出來是 0 公里」。**

    ## ⚠️ 這一條照字面寫會是空綠，我改了它的形狀

    `geo.locate()` 在 `geo_on()` 關著時**直接回錯誤** ⇒ **一個點都產不出來**
    ⇒「每個點的距離都是 null」在一個空清單上**永遠成立**。

    🔑 所以這一題驗的是**對照**：同一個請求、同一份資料，
    **關著 → 沒有點且 `geoEnabled` 是 false；開著 → 有點且有距離。**
    ⇒ 證明的是「**這個開關真的有差**」，而不是「空清單裡沒有非 null 的東西」。
    """
    hdr = _auth(client, make_user)

    monkeypatch.setattr(geo, "GEO_ENABLED", False)
    monkeypatch.delenv("MOTRIX_GEO", raising=False)
    off = _ask(client, hdr, position=_pos(USER_TAIPEI))

    assert off.get("geoEnabled") is False, (
        f"地理查詢關著，而 `geoEnabled` 是 {off.get('geoEnabled')!r}\n"
        "⇒ 不講的話，使用者會以為是地址填錯了。"
    )
    for p in off["points"]:
        assert p.get("distanceFromUserKm") is None, (
            f"地理查詢關著，而某個點有定位距離：{p}"
        )
        assert p.get("distanceFromOfficeKm") is None, (
            f"地理查詢關著，而某個點有辦公室距離：{p}"
        )

    # ── 對照組：打開之後，同一個請求要拿得到點與距離 ──
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    on = _ask(client, hdr, position=_pos(USER_TAIPEI))
    assert on.get("geoEnabled") is True
    assert on["points"], (
        "打開地理查詢之後仍然一個點都沒有 —— "
        "那表示上面那段「關著就沒有點」其實跟開關無關，**這一題是空的**。"
    )
    assert any(p.get("distanceFromUserKm") is not None for p in on["points"]), (
        "打開之後仍然沒有任何定位距離 —— 同上，這一題證明不了開關有差。"
    )


# ══════════════════════════════════════════════════════════════════════
# G8 · 反向控制：距離要真的隨座標改變
# ══════════════════════════════════════════════════════════════════════

def test_g8_the_user_distance_actually_follows_the_coordinates(
        client, make_user, geo_enabled, office, tenders):
    """🔴🔴 G8 反向控制：**`distanceFromUserKm` 必須真的隨 `lat`/`lon` 改變。**

    ☠️ 少了這一題，一個**回傳固定值**的實作會讓 G1 全綠 ——
    而畫面上每個標案都「離你 12.3 公里」，看起來完全正常。
    🔑 〈假綠燈：斷言驗到自己設的值〉的鄰居：
    **「有值」與「那個值跟輸入有關」是兩件事。**

    📌 用台北與高雄（直線約 300 公里），差距大到四捨五入之後仍然不同。
    """
    hdr = _auth(client, make_user)

    def _by_case(coords):
        body = _ask(client, hdr, position=_pos(coords))
        assert body["points"], "一個點都沒有 —— 前提不成立"
        return {p["caseNo"]: p["distanceFromUserKm"] for p in body["points"]}

    north = _by_case(USER_TAIPEI)
    south = _by_case(USER_KAOHSIUNG)

    assert set(north) == set(south) and north, (
        f"兩次拿到的標案不一樣，沒得比：{sorted(north)} vs {sorted(south)}"
    )
    same = [k for k in north if north[k] == south[k]]
    assert not same, (
        f"從台北與從高雄算出來的距離一模一樣：{ {k: north[k] for k in same} }\n"
        "⇒ 那個距離沒有真的用到傳進去的座標（回了固定值？用了辦公室座標？）"
    )


# ══════════════════════════════════════════════════════════════════════
# G9 · 隱私：使用者的位置不可以被存下來
# ══════════════════════════════════════════════════════════════════════

def test_g9_the_users_position_is_never_written_down(
        client, make_user, geo_enabled, office, tenders, caplog):
    """🔴🔴 G9：傳進來的 `lat`/`lon`/`accuracy` **不可以被寫進資料庫或 log**。

    ☠️ **那是使用者的位置。** 而 `audit_log` 有 2,254 列、
    `user_request_log` 有 1,893 列，兩張都會進每日備份、都會被匯出。
    ⚠️ `user_request_log` 存的是 `path` —— **query string 在 path 裡**，
    所以「順手記下完整網址」就足以把一個人的位置留在磁碟上七天。

    🔑 A 說得對：**這一條現在不寫，之後不會有人想到。**
    📌 而它的失敗方式是最安靜的一種：**功能完全正常，只是多留了一筆。**
    """
    import logging

    hdr = _auth(client, make_user)
    lat, lon = USER_TAIPEI
    with caplog.at_level(logging.DEBUG):
        body = _ask(client, hdr, position=_pos((lat, lon)))
    assert body["points"], "一個點都沒有 —— 前提不成立（請求沒有真的被處理？）"

    # 🔴 **第四層：log。** 前三層是「**我們會寫入的地方**」，而這一層不是。
    # B 實測發現 uvicorn 的 access log 會把整個 URL（含 query string）
    # 追加進 `logs/server.log`，**而我們三個都沒有把它列進清單**。
    # 🔑 **資料外洩不需要我們寫入，只需要有人記錄。**
    #
    # ⚠️ **我明講這一層擋得到什麼**：`caplog` 抓的是 Python `logging`
    #    ⇒ 它擋得住「我們自己順手把座標印出來」，
    #    **抓不到 uvicorn 自己的 access log**（那是伺服器設定，不是我們的程式碼）。
    # ⇒ 那個真正的出口由**形狀**擋住：座標不走 query string（G10／G11）。
    #    🔑 **一道守門要說得出它守不到什麼，否則它的綠燈會被當成更大的保證。**
    logged = [rec.getMessage() for rec in caplog.records
              if str(lat) in rec.getMessage() or str(lon) in rec.getMessage()]
    assert not logged, (
        "使用者的座標出現在 log 裡：\n  " + "\n  ".join(logged[:4])
    )

    # 🔴 **前提：那組座標真的被端點收下了。**
    # ⚠️ 少了這一道，這一題在「端點根本不認得 lat/lon/accuracy」時會**空綠** ——
    #    而那正是寫這一題的當下的狀態（G1 還是紅的）。
    # 🔑 我自己在 G9b 寫過：**一道永遠綠的隱私守門，比沒有守門更糟，
    #    因為它讓人不再去看。** 那句話對 G9 自己同樣適用。
    assert body.get("userAccuracyM") == 42, (
        "端點沒有收下這組定位參數（`userAccuracyM` 不是 42）⇒ "
        "下面那段掃描證明不了任何事：沒有被收下的東西當然不會被寫下來。"
    )

    needles = (f"{lat}", f"{lon}")
    import db
    conn = db.get_db()
    try:
        found = []
        for table, columns in (("system_settings", ("key", "value_json")),
                               ("audit_log", ("action", "target_label",
                                              "detail")),
                               ("user_request_log", ("path", "page"))):
            for col in columns:
                for needle in needles:
                    try:
                        rows = conn.execute(
                            f"SELECT {col} FROM {table} "
                            f"WHERE {col} LIKE ?", (f"%{needle}%",)
                        ).fetchall()
                    except sqlite3.Error as exc:       # pragma: no cover
                        pytest.fail(f"掃 {table}.{col} 失敗：{exc}")
                    for row in rows:
                        found.append(f"{table}.{col}: {str(row[0])[:120]}")
    finally:
        conn.close()

    assert not found, (
        f"使用者的座標 {lat},{lon} 出現在這些地方：\n  "
        + "\n  ".join(found[:6])
        + "\n\n⇒ 那是使用者的位置，不可以留在磁碟上。"
        "⚠️ 特別注意 `user_request_log.path` —— query string 在 path 裡。"
    )


def test_g9b_the_privacy_scan_can_actually_find_something(
        client, make_user, geo_enabled, office, tenders):
    """🔴 G9b 量尺：**先證明那個掃描真的找得到東西。**

    ⚠️ 少了這一題，G9 在「表名打錯」「欄位改名」「`LIKE` 寫壞」
    「`user_request_log` 根本沒在寫」的時候都會**安靜地全綠** ——
    🔑 而一道永遠綠的隱私守門，比沒有守門更糟：**它讓人不再去看。**

    📌 做法：故意把座標種進 `audit_log`，證明 G9 的掃描抓得到它。
    """
    lat, lon = USER_TAIPEI
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at, username, action, detail) "
            "VALUES (?,?,?,?)",
            ("2026-09-22T00:00:00", "g9b", "隱私量尺",
             f"故意種下的座標 {lat},{lon}"))
        conn.commit()
        rows = conn.execute(
            "SELECT detail FROM audit_log WHERE detail LIKE ?",
            (f"%{lat}%",)).fetchall()
    finally:
        conn.close()

    assert rows, (
        "把座標種進 `audit_log.detail` 之後，G9 用的那個 LIKE 查詢卻找不到它"
        " ⇒ **G9 的綠燈不代表任何事。**"
    )


# ══════════════════════════════════════════════════════════════════════
# G10 / G11 · 🔴 座標不可以走 query string
# ══════════════════════════════════════════════════════════════════════

def test_g10_coordinates_in_the_query_string_are_refused(
        client, make_user, geo_enabled, office, tenders):
    """🔴🔴 G10：`?lat=&lon=&accuracy=` ⇒ **422**，而訊息要**指路到標頭**。

    ## ☠️ 這一條不是參數潔癖，它堵的是一個真實的外洩

    B 起了一個真的 uvicorn 打一次請求：
    ```
    INFO: 127.0.0.1:34378 - "GET /api/map/points?sources=tenders
          &lat=24.1657&lon=120.6402&accuracy=35 HTTP/1.1" 200 OK
    ```
    正式機的 `autostart.bat` 是 `uvicorn … --log-level info >> logs\server.log`
    ⇒ **每按一次「使用我的位置」，那個人當下的座標就被追加進一個永久檔案。**

    🔑 **而我的 G9 三張表全是乾淨的** —— 三個想得到的出口都堵了，
    **漏的是沒有人列進清單的那一個，而它不在我們的程式碼裡，在 web server 裡。**
    📌 **我們列的是「我們會寫入的地方」，而資料外洩不需要我們寫入，
    只需要有人記錄。**

    ⚠️ **訊息要指路**：只回「參數不合法」的話，下一個人（或下一個我）
    會以為是格式寫錯，然後**把座標換個寫法再塞進 query string 一次**。
    🔑 **一個不說明理由的拒絕，擋得住這一次，擋不住下一次。**
    """
    hdr = _auth(client, make_user)
    lat, lon = USER_TAIPEI
    r = _ask(client, hdr, query=f"lat={lat}&lon={lon}&accuracy=42",
             expect=422)
    body = r.text
    assert POSITION_HEADER in body, (
        f"422 的訊息裡沒有提到 `{POSITION_HEADER}`：{body[:300]}\n"
        "⇒ 要指路，否則下一個人會以為只是格式寫錯，再塞一次。"
    )


@pytest.mark.parametrize("query", ["lat=25.03", "lon=121.56", "accuracy=42"])
def test_g10b_even_one_of_them_in_the_query_string_is_refused(
        client, make_user, geo_enabled, office, tenders, query):
    """🔴 G10b：**三個裡任何一個**出現在 query string 都要 422。

    ⚠️ 只擋「三個都齊」的話，`?lat=…&lon=…` 這種寫法照樣會被 uvicorn 記下來
    —— 而**兩個座標就足以定位一個人**，`accuracy` 本來就不是敏感的那一部分。
    🔑 判準要對齊**外洩的條件**，不是對齊**功能的條件**。

    ## 🔴 這一題第一版是假綠的，⑤ 把它抓出來了

    第一版只斷言 `expect=422`。⚠️ 而我把 `map_points.py` 裡那個
    「query string 一律拒絕」的 `raise` 突變掉之後，**G10 紅了而這一題沒有** ——
    因為 `?lat=25.03` 單獨給時，422 來自**另一道檢查**
    （`_user_position` 的「lat 與 lon 要一起給」）。

    ☠️ **也就是說：把整條禁令拿掉，這一題照樣全綠**，而那正是外洩的情境。
    🔑 〈判準的寬窄都會騙人〉：**「回 422」太寬了，要問的是「為什麼 422」。**
    ⇒ 改成連**理由**一起驗：訊息必須指向標頭。
    """
    hdr = _auth(client, make_user)
    r = _ask(client, hdr, query=query, expect=422)
    assert POSITION_HEADER in r.text, (
        f"`?{query}` 確實回了 422，**但不是因為座標不可以走 query string** ——\n"
        f"訊息是：{r.text[:200]}\n"
        "⇒ 那道 422 來自別的參數檢查，而把 query string 的禁令整個拿掉之後，"
        "這一題還是會綠。"
    )


def test_g11_the_same_values_in_the_header_work_fine(
        client, make_user, geo_enabled, office, tenders):
    """🔴🔴 G11 反向控制：**同一組值放在標頭裡要正常運作。**

    ☠️ 少了這一半，一個「**兩條路都擋**」的實作會讓 G10 全綠 ——
    而那在畫面上是「按了『使用我的位置』什麼都沒發生」，
    **使用者會以為是瀏覽器不給權限**（而那正是 V1～V3 在分辨的三個成因，
    這下又多一個假的）。

    📌 這一題與 G1 的差別：G1 驗的是**欄位齊不齊**，
    這一題驗的是**「走標頭這條路真的通」** —— 兩題會在不同的修法下變紅。
    """
    hdr = _auth(client, make_user)
    lat, lon = USER_TAIPEI
    body = _ask(client, hdr, position=_pos((lat, lon)))
    assert body.get("userAccuracyM") == 42, (
        f"標頭 `{POSITION_HEADER}` 帶了合法的值，而端點沒有收下："
        f"userAccuracyM={body.get('userAccuracyM')!r}"
    )
    assert any(p.get("distanceFromUserKm") is not None
               for p in body["points"]), (
        "標頭收下了，但沒有任何點算出定位距離"
    )
