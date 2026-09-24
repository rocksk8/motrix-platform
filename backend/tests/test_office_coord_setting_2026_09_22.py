"""§3u · 辦公室手動座標的輸入位置（UA5）。

> **A 2026-09-22：這一條優先於金鑰。**
> 🔑 **那個欄位一填，使用者的「辦公室只定位到區級」立刻變成精確座標** ——
> **不需要 Google 金鑰、不需要任何外部查詢、不需要等背景定位。**

---

# 🔴 現況：又一句指向不存在欄位的指路

```
後端  system.py:625-626   office_lat / office_lon 欄位在
      system.py:650-668   範圍檢查在（±90 / ±180）
      map_points.py       地圖在讀（`_manual_coord`）
前端  grep office_lat frontend/    **0 處**
而 map.html:83 寫著：「可以在公司資料設定直接填經緯度，那會跳過所有查詢。」
```

📌 這是我複核 A 的金鑰回報時**多找到的第二句** ——
A 的自省值得逐字留著：
> **「我 grep 了 `google_maps_api_key`，而我要找的其實是
> 『所有指向設定頁而設定頁沒有的東西』。
> 我查的是一個實例，而問題是一個類別。」**

⇒ 通則那一題在 `test_google_key_setting_2026_09_22.py::test_ua1b`。

---

# ⚠️ 這一節我驗得到什麼

| | |
|---|---|
| **UA5**（輸入框存在） | 🟡 樣板文字比對，弱的 |
| **UA5b**（貼一串自動拆兩欄） | 🟡 同上 —— 那是 JS 的行為 |
| **UA5c**（填了 ⇒ `precision` 是 `exact`） | ✅ **後端，真的驗** |
| **UA5d**（範圍檢查還在） | ✅ **後端，真的驗** |
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _mapiso import no_tile_probe  # noqa: E402,F401

PROFILE_PATH = "/api/settings/company-profile"
MAP_PATH = "/api/map/points?sources=tenders"
SETTINGS_PAGE = "company-profile-settings.html"

#: 台中市梧棲區的一個門牌級座標（§3o 實測：地址查詢只到得了區級）。
OFFICE_LAT, OFFICE_LON = 24.2549239, 120.5316259

#: 使用者從 Google 地圖複製出來的**一串**長這樣。
PASTED = "24.2549239, 120.5316259"


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _put(client, hdr, payload, expect=200):
    r = client.put(PROFILE_PATH, json=payload, headers=hdr)
    assert r.status_code == expect, (
        f"PUT {payload} 預期 {expect}，實際 {r.status_code}：{r.text[:200]}"
    )
    return r


def _page(name):
    p = (Path(__file__).resolve().parent.parent.parent
         / "frontend" / "pages" / name)
    assert p.exists(), f"找不到 {p}"
    return p.read_text(encoding="utf-8")


@pytest.fixture()
def office_address(client):
    """先把地址填好 —— UA5c 要比的是「有座標」與「只有地址」的差別。"""
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile["address"] = "台中市梧棲區"
    profile["office_lat"] = None
    profile["office_lon"] = None
    _set_setting("company_profile", profile)


# ══════════════════════════════════════════════════════════════════════
# UA5 / UA5b · 輸入框
# ══════════════════════════════════════════════════════════════════════

def test_ua5_the_settings_page_has_inputs_for_the_coordinates():
    """🟡 UA5：設定頁要有 `office_lat`／`office_lon` 兩個輸入框。

    ⚠️ 文字比對，弱的（它答的是「有沒有被寫出來」）。
    📌 而它擋得住的正是今天這個狀態：**畫面叫使用者去填一個不存在的欄位。**
    """
    text = _page(SETTINGS_PAGE)
    missing = [f for f in ("office_lat", "office_lon") if f not in text]
    assert not missing, (
        f"`{SETTINGS_PAGE}` 裡沒有 {missing} ——\n"
        "⇒ 而 `map.html:83` 寫著「可以在公司資料設定直接填經緯度」。"
    )


def test_ua5b_a_pasted_pair_can_be_split_into_two_fields():
    """🟡 UA5b：**貼一串要能自動拆成兩欄。**

    📌 使用者從 Google 地圖複製出來的是 `24.2549239, 120.5316259` **一串**。
    ⚠️ 逼他手動拆的話，最可能的錯誤是**兩個數字貼反** ——
    ☠️ 而 `(120.53, 24.25)` 是一個**合法**的座標（在阿拉伯海上），
    範圍檢查擋不住它，地圖也會乖乖畫出來。
    🔑 **一個會通過所有驗證的錯誤，比一個被擋下來的錯誤貴得多。**

    ⚠️ 判準刻意寬：接受 `split(',')` 或一個抓兩個數字的 regex，
    **不釘實作**。它只確認「有人處理過『貼一串』這件事」。
    """
    text = _page(SETTINGS_PAGE)
    assert "office_lat" in text, "前提不成立：欄位還沒加（見 UA5）"

    idx = text.find("office_lat")
    window = text[max(0, idx - 1500):idx + 1500]
    handled = any(k in window for k in ("split(", "paste", "match(", "trim()"))
    assert handled, (
        "找不到任何「把貼上的一串拆成兩欄」的處理：\n"
        f"{window[:200]}\n"
        "⇒ 使用者要自己拆，而最可能的錯誤是把兩個數字貼反 —— "
        "那是一個會通過所有驗證的錯誤。"
    )


# ══════════════════════════════════════════════════════════════════════
# UA5c · 填了座標 ⇒ precision 是 exact（後端，真的驗）
# ══════════════════════════════════════════════════════════════════════

def test_ua5c_manual_coordinates_make_the_office_exact(
        client, make_user, office_address, no_tile_probe, monkeypatch):
    """🔴 UA5c：填了手動座標 ⇒ 辦公室的 `precision` 是 **`exact`**，
    而且**不再查任何地址**。

    🔑 那是 §3o 退階梯的第一階，也是這一條存在的理由：
    **圖資認不得台灣的門牌，而使用者知道自己在哪裡。**

    📌 觀測點是 `/api/map/points` 的 `office` —— 使用者看得到的那一層。
    ⚠️ 並且驗「**沒有查地址**」：地址查詢被我換成會記帳的假貨，
    填了座標之後那個計數必須是 0 ⇒ 證明它**跳過**了查詢，
    而不是「查了、然後剛好也標成 exact」。
    """
    from helpers import geo

    calls = []
    real = geo.locate_cached

    def _counting(address, manual_coord=None):
        if manual_coord is None:
            calls.append(address)
        return real(address, manual_coord)

    monkeypatch.setattr(geo, "locate_cached", _counting)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)

    hdr = _auth(client, make_user)
    _put(client, hdr, {"office_lat": OFFICE_LAT, "office_lon": OFFICE_LON})

    calls.clear()
    r = client.get(MAP_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    office = r.json().get("office")

    assert office, "填了座標而 `office` 是空的"
    assert (office["lat"], office["lon"]) == (OFFICE_LAT, OFFICE_LON), (
        f"辦公室座標不是填進去的那一組：{office}"
    )
    assert office.get("precision") == geo.PRECISION_EXACT, (
        f"手動座標的精度應該是 `{geo.PRECISION_EXACT}`，"
        f"實際 {office.get('precision')!r}"
    )
    assert not any(c == "台中市梧棲區" for c in calls), (
        f"填了手動座標，卻仍然去查了地址：{calls}\n"
        "⇒ 那一階存在的意義就是**跳過查詢**。"
    )


def test_ua5d_clearing_the_coordinates_falls_back_to_the_address(
        client, make_user, office_address, no_tile_probe, monkeypatch):
    """🔴🔴 UA5d 反向控制：**清空座標 ⇒ 退回地址查詢那條路。**

    ☠️ 少了這一題，一個「**一旦填過就永遠用那組座標**」的實作會讓 UA5c 綠 ——
    而使用者搬家之後改了地址，地圖**還停在舊辦公室**，
    🔑 而畫面上完全正常：有點、有距離，只是那些距離全是從舊地址算的。

    ⚠️ 清空要送 `null` 不是 `0` —— **`0.0` 是幾內亞灣上的一個點，不是「沒有填」**
    （`system.py:623` 的註解就寫著這件事）。
    """
    from helpers import geo

    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(
        geo, "locate_cached",
        lambda address, manual_coord=None: (
            geo.GeoResult(coord=tuple(manual_coord),
                          precision=geo.PRECISION_EXACT,
                          source=geo.SOURCE_MANUAL, address=address)
            if manual_coord else
            geo.GeoResult(coord=(24.2549, 120.5316),
                          precision=geo.PRECISION_DISTRICT,
                          source=geo.SOURCE_NOMINATIM, address=address)))
    # `MP8`：開地圖只讀快取 ⇒ 快取＝同一個替身（等同背景預熱已完成）
    from tests._map_cache_warm import serve_from_fake
    serve_from_fake(monkeypatch, geo.locate_cached)

    hdr = _auth(client, make_user)
    _put(client, hdr, {"office_lat": OFFICE_LAT, "office_lon": OFFICE_LON})
    _put(client, hdr, {"office_lat": None, "office_lon": None})

    r = client.get(MAP_PATH, headers=hdr)
    assert r.status_code == 200, r.text
    office = r.json().get("office")
    assert office, "清空座標之後 `office` 不見了 —— 地址那條路沒有接上"
    assert office.get("precision") == geo.PRECISION_DISTRICT, (
        f"清空座標之後應該退回地址查詢（`district`），"
        f"實際 {office.get('precision')!r} —— 它還停在手動座標上。"
    )


# ══════════════════════════════════════════════════════════════════════
# UA5e · 範圍檢查還在（後端，已綠）
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("payload", [
    {"office_lat": 91.0, "office_lon": 120.0},
    {"office_lat": -91.0, "office_lon": 120.0},
    {"office_lat": 24.0, "office_lon": 181.0},
    {"office_lat": 24.0, "office_lon": -181.0},
    {"office_lat": "abc", "office_lon": 120.0},
])
def test_ua5e_out_of_range_coordinates_are_refused(client, make_user, payload):
    """🟢 UA5e：超出範圍的座標 ⇒ **422**（`system.py:650` 已經做對了）。

    📌 那支的註解值得留著：**緯度 ±90、經度 ±180 是地球的範圍，不是台灣的**
    —— 刻意不收窄到台灣，因為「**一個為了你好而擋住合法輸入的驗證，會被繞過去**」。

    ↩︎ 什麼改動會讓它紅：把 `_check_office_coord(body)` 從
       `set_company_profile` 裡拿掉，或把它移到 `_set_setting` **之後**
       （那會變成「回了 422 而值已經生效了」）。
    """
    hdr = _auth(client, make_user)
    _put(client, hdr, payload, expect=422)


def test_ua5f_validation_happens_before_the_write(client, make_user):
    """🔴 UA5f：**先驗證，再寫入。**

    ☠️ 一邊驗一邊寫的話，使用者會看到 422 **而值已經生效了** ——
    🔑 **「回了錯誤碼」與「沒有存進去」是兩件事。**
    📌 `set_company_profile` 的註解已經寫著這個決定，這一題把它釘住
    （那個順序很容易在重構時被調換，而調換之後**沒有任何測試會紅**……
    除非有這一題）。
    """
    from helpers.settings import _get_setting

    hdr = _auth(client, make_user)
    _put(client, hdr, {"name": "驗證順序測試公司"})
    before = dict(_get_setting("company_profile", {}) or {})

    _put(client, hdr, {"name": "不該被寫進去", "office_lat": 999.0},
         expect=422)

    after = dict(_get_setting("company_profile", {}) or {})
    assert after.get("name") == before.get("name"), (
        f"422 之後公司名被改成了 {after.get('name')!r} —— "
        "那一筆請求被部分寫入了。\n"
        "⇒ 使用者看到錯誤訊息，而值已經生效。"
    )
