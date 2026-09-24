"""§15 GC1–GC10 · 地理編碼的跨階短路與負快取。

---

# ☠️ `A9` 從另一扇門回來了

`locate_cached()` 的 docstring 自己寫的：
> 只用地址當鍵的話：Nominatim 先查到行政區中心點並寫進快取 ⇒
> 使用者後來填了 Google 金鑰 ⇒ **快取命中，永遠拿不到門牌精度**（A9）。
> 而症狀是**沒有症狀**。

🔑 而 `cached_only()` **把這個修正拆掉了** —— 它**跨階**找：
```python
for _name, source in _STAGES:      # google -> tgos -> nominatim
    hit = _cached_stage(address, source)
    if hit: return hit             # 任一階命中就回傳
```
⇒ 📌 `_GeocodeBudget.locate()` 第一行就是它，`_warm_backlog` 的過濾也是它。

---

# ⚠️ A-2 的更正：「填了金鑰也不會升級」**涵蓋太廣**

```
map_points.py:577 / system.py:869   沒有 cached_only 擋著 ⇒ 會升級
其餘走 cached_only 的路徑           ⇒ 不會升級
```
🔑 ⇒ 這一節的判準要釘在 **`cached_only` 這一支**，
☠️ 而不是「整個系統填了金鑰都不會升級」——**後者是錯的，而它聽起來更嚴重。**

---

# 🔑 `GC9`／`GC10` 的負快取，判準與 `GB` 完全不同

```
GB   每月額度 —— 擋的是「總量」
GC8  一個打不到的據點地址，每次有人開地圖就對 Google 發一次，**無上限**
     ⇒ 光加每日上限擋不住它：它會把額度吃光，而每一次都是同一個地址
```
⚠️ 而負快取**不可以和 `geocode_cache` 共用一張表** —— `GC9`：
☠️ **共用的話就分不出「查過查不到」與「沒查成功」**，
而兩者的處置相反（一個要記住，一個要重試）。
"""
import pytest


def _geo():
    from helpers import geo
    return geo


def _need(name):
    geo = _geo()
    fn = getattr(geo, name, None)
    assert fn is not None, (
        f"`helpers/geo.py` 缺少 `{name}` —— 見 §15 GC 的驗收條件")
    return fn


@pytest.fixture
def seeded(client):
    """在 `geocode_cache` 裡種一筆**行政區精度**的舊快取（免費階）。"""
    import db
    geo = _geo()
    address = "台中市西屯區某條路 123 號"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO geocode_cache (address, lat, lon, source, precision, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (address, 24.18, 120.64, geo.SOURCE_NOMINATIM,
             geo.PRECISION_DISTRICT, "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return address


# ══════════════════════════════════════════════════════════════════════
# GC1 / GC2 / GC3 · 有金鑰時，舊階的快取不算「已經知道」
# ══════════════════════════════════════════════════════════════════════

def test_gc1_an_old_free_stage_hit_is_not_treated_as_known_when_a_key_exists(
        seeded, monkeypatch):
    """🔴🔴 GC1／GC3：有 Google 金鑰時，**只有 google 階的快取算「已經知道」**。

    ☠️ 現在 `cached_only()` 跨階找，任一階命中就回傳
    ⇒ 那 147 筆（nominatim 92／district 55）會**一直停在行政區精度
    直到 180 天 TTL 到期** —— 而症狀是**沒有症狀**。

    🔑 判準釘在 `cached_only` 這一支，**不是「整個系統都不會升級」** ——
    📌 A-2 的更正：`map_points.py:577`／`system.py:869` 沒有它擋著，會升級。
    ⚠️ **後者是錯的，而它聽起來更嚴重** —— 一個誇大的缺陷描述會讓人去修錯的地方。
    """
    geo = _geo()
    monkeypatch.setattr(geo, "_google_api_key", lambda: "fake-key",
                        raising=False)
    from helpers import settings as _settings
    monkeypatch.setattr(
        _settings, "_get_setting",
        lambda key, default=None: ({"google_maps_api_key": "fake-key"}
                                   if key == "company_profile" else default))

    assert geo.cached_only(seeded, min_source=geo.SOURCE_GOOGLE) is None, (
        "有金鑰時，一筆 nominatim 階的舊快取仍然被當成「已經知道」——\n"
        "☠️ 那 147 筆會永遠停在行政區精度，而畫面上看不出差別。")


def test_gc3_the_old_hit_can_still_be_drawn(seeded):
    """🔴 GC3：舊階的命中**仍然可以先畫上去**，不要讓地圖變空。

    ☠️ 少了這一半，一個「有金鑰就當作沒快取」的實作會讓上一題綠 ——
    而使用者填完金鑰的那一刻，**地圖上 147 個點會全部消失**，
    🔑 然後一個一個慢慢回來。**那比停在行政區精度更糟。**
    """
    geo = _geo()
    assert geo.cached_only(seeded) is not None, (
        "不指定 `min_source` 時，舊階的快取要照常拿得到 —— 地圖不可以變空。")


def test_gc4_nothing_changes_when_there_is_no_google_key(seeded, monkeypatch):
    """🔴🔴 GC4 反向控制：**沒有金鑰時行為與現在完全一樣。**

    ☠️ 少了這一半，修法會讓**沒有金鑰的人每次開地圖都重查 Nominatim** ——
    🔑 而他們**永遠拿不到更好的精度**（沒有 google 階可以升級），
    📌 所以那些請求是純粹的浪費，而且 Nominatim 有使用條款上的速率限制。
    """
    geo = _geo()
    from helpers import settings as _settings
    monkeypatch.setattr(_settings, "_get_setting",
                        lambda key, default=None: {} if key == "company_profile"
                        else default)

    assert geo.cached_only(seeded, min_source=geo.SOURCE_GOOGLE) is not None, (
        "沒有金鑰而 nominatim 的快取被當成「不算數」——\n"
        "⇒ 沒金鑰的人每次開地圖都會重查一次，而他們永遠升級不了。")


# ══════════════════════════════════════════════════════════════════════
# GC5 / GC7 · Google 那一階沒有節流、也沒有預算保護
# ══════════════════════════════════════════════════════════════════════

def test_gc5_the_google_stage_is_throttled_like_the_free_ones(monkeypatch):
    """🔴 GC5：**Google 那一階要節流。**

    `_throttle()` 目前只在 `_locate_nominatim`（`geo.py:126`）與待暖迴圈
    （`geo.py:837`）—— ☠️ **google 階一個都沒有。**
    ⇒ 一次請求的 6 秒預算內能發出幾個 Google 請求，**取決於網路有多快**。
    🔑 而「取決於網路有多快」的意思是：**網路愈好，帳單愈高。**
    """
    geo = _geo()
    ticks = []
    monkeypatch.setattr(geo, "_throttle", lambda: ticks.append(1))
    monkeypatch.setattr(geo, "_google_api_key", lambda: "k", raising=False)
    from helpers import settings as _settings
    monkeypatch.setattr(
        _settings, "_get_setting",
        lambda key, default=None: ({"google_maps_api_key": "k"}
                                   if key == "company_profile" else default))

    class _Resp:
        def read(self):
            return b'{"status":"ZERO_RESULTS","results":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(geo.urllib.request, "urlopen", lambda *a, **kw: _Resp())
    geo._locate_google("任何地址")
    assert ticks, (
        "`_locate_google()` 沒有經過 `_throttle()` —— "
        "一次請求內能發幾個 Google 請求取決於網路速度。")


def test_gc7_locating_the_offices_respects_a_budget(monkeypatch):
    """🔴 GC7：`_locate_locations()` 要有預算保護。

    ☠️ google 階沒快取時，**每一次 `/api/map/points` 都會去問 Google**
    （成功寫快取後才停）。
    📌 配合 `GC5`（google 階沒節流）⇒ 金鑰一填，那幾個據點就變成
    **每次開地圖各發一次請求**。
    """
    geo = _geo()
    locate_locations = _need("_locate_locations")
    calls = []
    monkeypatch.setattr(geo, "_locate_google",
                        lambda addr, **kw: calls.append(addr) or None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_nominatim", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)

    locations = [{"id": f"L{i}", "name": f"據點{i}",
                  "address": f"查不到的地址 {i}"} for i in range(20)]
    locate_locations(locations)
    assert len(calls) < 20, (
        f"20 個查不到的據點，對 Google 發了 {len(calls)} 次請求 —— "
        "沒有任何預算保護。")


# ══════════════════════════════════════════════════════════════════════
# GC8 / GC9 / GC10 · 負快取
# ══════════════════════════════════════════════════════════════════════

def test_gc9_the_negative_cache_is_not_in_the_geocode_table(client, monkeypatch):
    """🔴🔴 GC9：負快取走**行程內的短退避**，**不落 DB**，與地理快取表分開。

    ☠️ **共用同一張表就分不出「查過查不到」與「沒查成功」** ——
    🔑 而兩者的處置相反：
    ```
    查過查不到   要記住（別再問了）
    沒查成功     要重試（網路壞了不是地址壞了）
    ```
    📌 混在一起的話，一次網路中斷會讓那些地址**永遠不再被查**。
    """
    import db

    geo = _geo()
    remember = _need("remember_geocode_miss")
    monkeypatch.setattr(geo, "_throttle", lambda: None)

    address = "GC9 查不到的地址"
    remember(address)

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM geocode_cache WHERE address=?",
            (address,)).fetchone()
    finally:
        conn.close()
    assert rows["n"] == 0, (
        "負快取被寫進了 `geocode_cache` —— 那張表分不出「查過查不到」"
        "與「沒查成功」，而兩者的處置相反。")


def test_gc10_fixing_a_typo_in_the_address_retries_immediately(monkeypatch):
    """🔴 GC10 反向控制：**改一個字的地址要立刻重查。**

    ⭐ 負快取的鍵是**地址字串** ⇒ 使用者把打錯的地址改對＝換一個鍵
    ⇒ **自動失效**，不需要另外做「清快取」功能。

    ☠️ 少了這一題，一個「用正規化後的地址當鍵」或「用據點 id 當鍵」的實作
    會讓 `GC8` 綠 —— 而**使用者改好了地址，系統還是不去查**，
    🔑 **而畫面上沒有任何東西告訴他為什麼**。

    ## 🔴 A-2 指出我第一版**對目標行為不敏感**，這是改過的版本

    我原本只驗「改對的地址會被查」。
    ☠️ **而那個斷言在有沒有負快取的兩種情況下都成立**：
    ```
    有負快取且鍵正確   打錯的第二次不查、改對的會查
    沒有負快取         兩個都查
    我的斷言（改對會查）  ← 兩種都通過
    ```
    ⇒ 🔑 **它從綠變綠，而那個綠什麼都沒改變。**
    📌 我當時標的是「暫時證明不了什麼」——**而正確的判讀是
    「這一題驗不到它要驗的東西」**，那是兩件不同的事。

    ## ⇒ 觀測點要挑「**只有負快取存在時才會出現**」的那一半

    ```
    ① 第一次查打錯的地址  → 有一次對外請求
    ② 第二次查同一個地址  → 🔴 零次對外請求   ← 這一半才是守門
    ③ 把地址改對          → 又有一次對外請求  ← 這一半是 GC10 的「換鍵」
    ```
    🔑 只驗③證明不了它原本不查；只驗②證明不了換鍵會失效 ——
    **兩半都要，而它們各自擋掉一種錯的實作。**
    """
    geo = _geo()
    calls = []
    monkeypatch.setattr(geo, "_locate_google",
                        lambda addr, **kw: calls.append(addr) or None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_nominatim", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_throttle", lambda: None)

    typo = "台中市西屯區台灣大道三段301號"
    fixed = "台中市西屯區台灣大道三段302號"

    geo.locate_cached(typo)
    after_first = len(calls)
    assert after_first >= 1, "第一次查一個查不到的地址，竟然沒有發出任何請求"

    geo.locate_cached(typo)                       # ② 同一個地址再查一次
    assert len(calls) == after_first, (
        f"同一個查不到的地址被問了第二次（{len(calls) - after_first} 次）——\n"
        "☠️ 沒有負快取，而這一半才是 `GC8`／`GC10` 的守門。")

    geo.locate_cached(fixed)                      # ③ 改一個字
    assert len(calls) > after_first, (
        "改了一個字的地址沒有重新查 ——\n"
        "⇒ 負快取的鍵不是地址字串（可能用了正規化後的地址或據點 id）\n"
        "☠️ 使用者改好了地址而系統還是不去查，而畫面上沒有東西告訴他為什麼。")


# ══════════════════════════════════════════════════════════════════════
# GC2 / GC6 · 兩條「寫下來」的，而它們不是測試
# ══════════════════════════════════════════════════════════════════════

def test_gc6_the_asymmetry_is_visible_in_the_response(client, make_user,
                                                      monkeypatch):
    """🔴 GC6：**不對稱本身是產品問題，而它要看得見。**

    ```
    起算點（辦公室／據點）   會升級到門牌精度
    被量的那 ~200 個點       永遠停在行政區中心
    ```
    ☠️ ⇒ 距離的誤差是**單邊**的，而使用者看到的是一個精確到小數點的數字。
    🔑 判準：**回應裡要帶得出每一個點的精度**，讓畫面說得出「這個點只到行政區」。
    📌 〈缺欄位≠缺訊號〉的反面：**這裡真的缺那個欄位。**
    """
    import db

    geo = _geo()
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None, raising=False)

    # 📌 **這一題自己種前提**：一筆有地址的標案 ＋ 一個已知的定位結果。
    # ⚠️ 定位走替身（不連外網），而**精度是替身給的** ——
    #    🔑 這一題問的是「那個精度有沒有被帶到回應裡」，不是「定位準不準」。
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM tenders WHERE case_no=?", ("GC6-001",))
        conn.execute(
            "INSERT INTO tenders (case_no, name, org, location, fetched_at)"
            " VALUES (?,?,?,?,?)",
            ("GC6-001", "GC6 測試標案", "GC6 測試機關",
             "台中市西屯區", "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        geo, "locate_cached",
        lambda addr, manual_coord=None: geo.GeoResult(
            coord=(24.1477, 120.6736), precision="district",
            source="nominatim_district", address=addr))
    # `MP8`：開地圖只讀快取 ⇒ 快取＝同一個替身（等同背景預熱已完成）
    from tests._map_cache_warm import serve_from_fake
    serve_from_fake(monkeypatch, geo.locate_cached)

    username, password = make_user(username="gc6_admin", role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.253"})
    assert r.status_code == 200, r.text
    r = client.get("/api/map/points",
                   headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    points = body.get("points") or body.get("items") or []

    # 🔴 2026-09-23：**這一題原本是永久 skip。**
    #
    # 它寫的是「這個環境沒有任何點位 ⇒ 略過」，而測試資料庫**從來就沒有**
    # 點位 ⇒ ☠️ **它從出生那天起一次都沒有跑過**，
    # 🔑 而全量報告上它長得像「1 skipped」——**而 skip 不是驗過**。
    # 📌 ⇒ 前提改成自己備：這一題要什麼，這一題自己放進去。
    assert points, (
        "地圖一個點都沒有 —— 而這一題自己種了一筆標案。\n"
        "⇒ 這是前提不成立，**不可以略過**：要嘛種子沒進去，"
        "要嘛那一筆被定位那一段丟掉了，兩個都要有人看。")
    assert any("precision" in p for p in points), (
        f"點位沒有帶精度欄位：{points[0]}\n"
        "⇒ 畫面說不出「這個點只到行政區」，而距離看起來精確到小數點。")
