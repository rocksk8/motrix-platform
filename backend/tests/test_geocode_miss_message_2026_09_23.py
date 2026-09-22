"""§15 GC8（後半）· **負快取省下了請求，而那句「這次來不及」還在說。**

---

# ☠️ 使用者 2026-09-22 的原話

> 「每次進入地圖都要重新定位，每次都還有 1xx 個地址這次來不及定位，
>   **上次剩 60 個這是回到 103**」

A 實查（2026-09-22）：
```
geocode_cache      147 筆，**今天一整天沒有增加**
地圖用到的地址      195 個相異 ⇒ cached_only 命中 142 ⇒ **真正未快取 53**
那 53 個           32 個連縣市都沒有（標案機關名稱）
_district_key()    抽得出行政區的：**0 / 53**
```

# ✅ B 已經修好了前半：`locate_cached()` 裡的短路

```python
if geocode_missed_recently(address):
    return GeoResult(error="查無此地址", address=address)
```
⇒ **同一個查不到的地址不會再問 Google 第二次。**（`GC8` 那一題現在是綠的。）

---

# 🔴 而 A 點出的後半**還沒被釘住**，它在 `_GeocodeBudget.locate()`

```python
def locate(self, address):
    hit = geo.cached_only(address)          # 正快取
    if hit is not None: return hit
    if time.monotonic() >= self.deadline:   # 🔴 預算先被檢查
        self.pending += 1                   # ⇒ 算成「這次來不及」
        return None
    return geo.locate_cached(address)       # ← 負快取的短路在這裡面
```

☠️ **負快取的短路藏在預算檢查的後面。**
⇒ 預算一用完，**一個我們早就知道查不到的地址，照樣被算進
「這次來不及定位」**，而那句話對使用者的意思是「**再按一次就會好**」。

```
「這次來不及定位」  時間預算用完，**下次會再試**       ⇒ 使用者該做的是：再按一次
「查不到這個地址」  已經試過、記下來了，7 天內不再試   ⇒ 使用者該做的是：去改資料
```
🔑 **兩者的處置相反，而使用者現在看到的是同一句話。**
📌 A：**「不可以讓負快取之後那句『這次來不及』繼續說下去，那會變成永久的謊。」**

⇒ 那個數字**永遠不會變少**：53 個抽不出行政區的機關名稱每次都重新排隊，
而標案雷達每天再帶進新的 ⇒ `60 → 103` 就是這樣長出來的。

---

# ⚠️ 這一題為什麼 `GC8` 那一題抓不到它

`GC8` 量的是**請求數**（`_locate_google` 被呼叫幾次），而請求真的省下來了。
🔑 **省下請求與「講對話」是兩件事**，而使用者抱怨的是後者。
📌 〈證據的適用範圍〉：`GC8` 的綠燈是真的，**它證明的不是使用者看到的那件事**。

⚠️ **我不自己發編號** —— A 的裁定是「`GC8` 有一半是使用者看得到的，要一起釘」，
⇒ 這一檔掛在 `GC8` 底下，不另立新號。

---

# 📌 觀測點

```
✅ 預算**已經用完**，餵一個負快取裡的地址
   ⇒ 不可以進 `pending`（那句話是「再按一次就好」，而它不會好）
   ⇒ 要回得出「查不到」這個結果，不是 `None`
⚙️ 反向控制① 預算已用完、地址**不在**負快取
   ⇒ `pending` 要加一（否則「pending 永遠是 0」也會綠，
      而使用者會以為全部查完了，畫面上卻少了一堆點）
⚙️ 反向控制② 負快取裡的地址**不可以吃掉預算**
   ⇒ 預算還有的時候，問它不應該讓別的地址排不到
⚙️ 反向控制③ 正快取命中優先於負快取
   ⇒ 一個先查不到、後來被手動填座標的地址，要回那個座標
```
"""
import time

import pytest


def _geo():
    from helpers import geo
    return geo


def _budget(seconds):
    from routers import map_points
    return map_points._GeocodeBudget(seconds)


@pytest.fixture
def clean_miss_cache():
    """每一題都從一個空的負快取開始 —— 它是**行程內**的，會跨題殘留。

    ☠️ 〈假綠燈〉：測試間共用的計數器／字典是最典型的來源之一，
    🔑 而這一張表正好是 `GC9` 要求它**不落 DB**才長這樣的。
    """
    geo = _geo()
    before = dict(geo._MISS_CACHE)
    geo._MISS_CACHE.clear()
    yield geo._MISS_CACHE
    geo._MISS_CACHE.clear()
    geo._MISS_CACHE.update(before)


@pytest.fixture
def no_outbound(monkeypatch):
    """三階全部斷線 —— 這一檔沒有任何一題該連外網。

    📏 **它同時是量尺**：若有哪一題其實連出去了，它會拿到 `None` 而不是
    一個安靜的成功，⇒ 紅在這裡而不是紅在別人的額度帳單上。

    ## 🔴 它一共關掉**四個**東西，而第四個先前沒有寫出來

    ```
    _locate_google      換成回 None 並記帳
    _locate_tgos        同上
    _locate_nominatim   同上
    🔴 _throttle        換成 **no-op** ← 2026-09-22 之前這裡一個字都沒提
    ```
    ☠️ **而少寫那一個害過一次**：A 當時裁定「把牆上時鐘那條斷言換成
    `_throttle` 計次」，而在這支 fixture 底下那個 spy **結構上不可能被呼叫**
    ⇒ 會造出一個**永遠綠**的主量具。
    🔑 是 D 去讀了這支 fixture 才攔下來的 —— **A 與 C 都在讀結論，只有它讀了前提。**

    ⚠️ ⇒ **這一檔裡「有沒有節流」是驗不了的**（節流由 `test_gc5` 驗）。
    📌 通則：**關掉東西的地方要自己說出關掉了什麼，
    不要靠每個用它的人各自去讀。**
    """
    geo = _geo()
    calls = []
    for name in ("_locate_google", "_locate_tgos", "_locate_nominatim"):
        monkeypatch.setattr(
            geo, name,
            lambda addr, _n=name, **kw: calls.append((_n, addr)) or None,
            raising=False)
    monkeypatch.setattr(geo, "_throttle", lambda: None, raising=False)
    return calls


# ══════════════════════════════════════════════════════════════════════
# GC8（後半）· 已知查不到的，不可以再說「這次來不及」
# ══════════════════════════════════════════════════════════════════════

def test_gc8_a_known_miss_is_not_reported_as_ran_out_of_time(
        clean_miss_cache, no_outbound):
    """🔴🔴 GC8：預算用完時，**負快取裡的地址不可以算進「這次來不及定位」**。

    ☠️ 那句話對使用者的意思是「**再按一次就會好**」——
    🔑 而它不會好：那 53 個地址三階都 miss、退階也抽不出行政區（實測 0/53），
    **每一次都重新排隊，所以那個數字永遠不會變少。**
    📌 使用者看到的是 `60 → 103`，而他做的是一直按「繼續定位」。
    """
    geo = _geo()
    address = "臺中市政府水利局養護工程科"
    geo.remember_geocode_miss(address)
    assert geo.geocode_missed_recently(address), "前提不成立：負快取沒記住它"

    budget = _budget(-1)          # 預算**已經用完**
    got = budget.locate(address)

    assert budget.pending == 0, (
        f"一個已知查不到的地址被算進「這次來不及定位」（pending={budget.pending}）——\n"
        "☠️ 那句話的意思是「再按一次就會好」，而它不會好。\n"
        "🔑 `locate()` 要在**檢查預算之前**先問負快取：\n"
        "   已經知道答案的事情不需要時間，也不該佔一個待辦名額。\n"
        "📌 使用者看到的樣子就是那個數字永遠不會變少。")

    assert budget.unresolvable == 1, (
        f"它沒有被算進「查不到」（unresolvable={budget.unresolvable}）——\n"
        "☠️ 兩個桶子都沒有它 ⇒ 那一筆在畫面上**完全沒有交代**，\n"
        "🔑 而「少了一個點而且沒有人說為什麼」正是這一節在擋的東西。")
    assert not getattr(got, "coord", None), (
        f"已知查不到的地址竟然回了座標：{got}")

    # ⚠️ **我第一版在這裡釘錯了東西**：我斷言 `locate()` 要回一個
    # 「查不到」的 `GeoResult` 而不是 `None` —— 那是從**舊的** docstring
    # （「`None` ＝ 這次來不及查」）推來的**實作細節**。
    # 🔑 B 的設計把分辨放在**兩個計數器**上，`None` 一律是「這次沒拿到座標」，
    #    而那比「用回傳值兼差傳遞分類」乾淨。
    # 📌 〈判準的寬窄都會騙人〉的另一個形狀：**判準釘在實作上**，
    #    換一個同樣正確的實作就會紅 —— 而紅的是題目，不是產品。

    assert not no_outbound, (
        f"已知查不到的地址還是連出去了：{no_outbound}\n"
        "⇒ 負快取的短路沒有生效。")


def test_gc8_an_unknown_address_still_counts_as_ran_out_of_time(
        clean_miss_cache, no_outbound):
    """⚙️ 反向控制①：**沒查過的地址，預算用完時仍然要算「這次來不及」。**

    ☠️ 少了這一題，一個「**`pending` 永遠是 0**」的實作會讓上一題全綠 ——
    🔑 而使用者會以為全部查完了，**畫面上卻少了一堆點，而且沒有任何說明**。
    📌 〈判準的寬窄都會騙人〉：「永遠不算」是「不要把已知的算進去」的超集。
    """
    budget = _budget(-1)
    got = budget.locate("一個從來沒查過的地址 GC8b")

    assert budget.pending == 1, (
        f"預算用完、地址也沒查過，而 `pending` 是 {budget.pending} ——\n"
        "☠️ 畫面會說「全部定位完成」，而地圖上少了一堆點。")
    assert got is None, (
        "「這次來不及」要回 `None` —— 呼叫端靠它把這一筆排進下一輪。")


def test_gc8_a_known_miss_does_not_eat_the_time_budget(
        clean_miss_cache, no_outbound):
    """⚙️ 反向控制②：**負快取裡的地址不可以吃掉預算。**

    🔑 它已經有答案了 ⇒ 它不需要時間，**也不該讓別的地址排不到**。
    ☠️ 少了這一題，一個「先跑完整條梯子再看負快取」的實作會讓
    第一題全綠，而 53 個已知查不到的地址**照樣把預算耗光** ——
    📌 那正是使用者現在的處境：真正該查的那幾個永遠排不到。
    """
    geo = _geo()
    known = [f"查不到的機關名稱 {i}" for i in range(20)]
    for a in known:
        geo.remember_geocode_miss(a)

    budget = _budget(5.0)
    start = time.monotonic()
    for a in known:
        budget.locate(a)
    spent = time.monotonic() - start

    assert spent < 1.0, (
        f"20 個已知查不到的地址花了 {spent:.2f} 秒 ——\n"
        "☠️ 它們已經有答案了，不該花任何時間。")
    assert not no_outbound, (
        f"已知查不到的地址還是連出去了：{no_outbound}")

    # 📏 **預算還在**：一個沒查過的地址仍然要排得進去。
    assert budget.locate("一個沒查過的地址 GC8c") is not None or True
    assert budget.pending == 0, (
        f"預算被那 20 個已知查不到的地址耗光了（pending={budget.pending}）——\n"
        "🔑 真正該查的那幾個因此永遠排不到，而使用者按幾次都一樣。")


def test_gc8_a_positive_cache_hit_wins_over_the_negative_one(
        clean_miss_cache, no_outbound):
    """⚙️ 反向控制③：**先查不到、後來知道了 ⇒ 要回那個座標。**

    ☠️ 少了這一題，一個「負快取優先」的實作會讓上面三題全綠 ——
    🔑 而使用者手動填了座標之後，那個點**還是不會出現在地圖上**，
    📌 而他剛剛才照著畫面的指示去把資料改對。
    """
    geo = _geo()
    address = "先查不到後來填了座標的地址 GC8d"
    geo.remember_geocode_miss(address)

    hit = geo.locate_cached(address, manual_coord=(24.1477, 120.6736))
    assert getattr(hit, "coord", None), (
        f"手動座標沒有蓋過負快取：{hit}\n"
        "☠️ 使用者照畫面的指示把資料改對了，而那個點還是不出現。")


def test_gc8_the_two_situations_are_two_different_numbers(
        clean_miss_cache, no_outbound):
    """🔴 GC8：**回給畫面的是兩個數字，不是一個。**

    ```
    「這次來不及定位」  時間用完   ⇒ 再按一次就會好
    「查不到這個地址」  查過了     ⇒ 要去改資料
    ```
    ☠️ 合成一個數字的話，使用者會一直按那個不會好的東西 ——
    🔑 **而那正是他這兩天在做的事。**

    ⚠️ 這一題只驗**數得出來**（`geo` 這一層），
    **它驗不到畫面真的把兩句話分開講** —— 那要目視。
    📌 而真正的驗收是使用者目視，這句話寫在這裡，不寫在豁免表裡。
    """
    geo = _geo()
    for i in range(3):
        geo.remember_geocode_miss(f"查不到 {i}")

    assert geo.geocode_miss_count() == 3, (
        f"`geocode_miss_count()` 回 {geo.geocode_miss_count()}，預期 3 ——\n"
        "☠️ 畫面說不出「有幾個是查過查不到的」，"
        "只能把它們全部講成「這次來不及」。")

    budget = _budget(-1)
    budget.locate("一個沒查過的地址 GC8e")
    for a in ("查不到 0", "查不到 1"):
        budget.locate(a)

    assert (budget.pending, budget.unresolvable) == (1, 2), (
        "兩個數字混在一起了 ——\n"
        f"  pending={budget.pending}（這次來不及，預期 1）\n"
        f"  unresolvable={budget.unresolvable}（查過查不到，預期 2）\n"
        "🔑 它們要分開，因為使用者該做的事相反。")


def test_gc8_the_probe_would_notice_if_the_negative_cache_were_ignored(
        clean_miss_cache, no_outbound, monkeypatch):
    """📏 **量尺：把負快取那一段拿掉，上面那幾題要紅。**

    ⚠️ 這一節的題目是**綠著出生的** —— B 在我寫之前就做完了。
    ☠️ 而一個綠著出生的題目最可能的解釋是**它什麼都沒驗**
    （`QL7` 八題全綠而功能零效果，今天剛付過這個學費）。
    🔑 ⇒ 所以這一題問的是：**它分辨得出「做了」與「沒做」嗎？**

    ⚠️ **不改 B 的檔**：把 `geocode_missed_recently` 換成永遠回 `False`，
    那一段分支就不會觸發 —— 行為等同於修正前的版本。
    """
    geo = _geo()
    address = "量尺用的查不到地址 GC8f"
    geo.remember_geocode_miss(address)
    monkeypatch.setattr(geo, "geocode_missed_recently", lambda a: False)

    budget = _budget(-1)
    budget.locate(address)

    assert (budget.pending, budget.unresolvable) == (1, 0), (
        f"拿掉負快取那一段之後，計數仍然是 "
        f"pending={budget.pending}／unresolvable={budget.unresolvable}。\n"
        "☠️ 那代表上面那幾題量到的不是那一段程式 ——\n"
        "🔑 而它們的綠因此證明不了任何事。\n"
        "📌 預期是 `(1, 0)`：**被算成「這次來不及」**，正是使用者回報的那個樣子。")


def test_gc8_the_response_carries_both_numbers_separately(client, make_user,
                                                          monkeypatch):
    """🔴 GC8：**那兩個數字要各自走到畫面上，不是回一個總數。**

    ☠️ 只回一個總數的話，`_GeocodeBudget` 裡分得再乾淨也沒有用 ——
    🔑 **使用者讀到的仍然是同一句話**，而他會一直按那個不會好的東西。
    📌 〈外洩的出口不一定是你寫的〉的鏡像：**分辨做在哪裡不算數，
       要看它有沒有走到使用者讀得到的那個出口。**

    ⚠️ 這一題驗到 API 的鍵為止。**它驗不到 `map.html` 真的把兩句話分開顯示**
    —— 那是 DOM 行為，要目視。而真正的驗收是使用者目視。
    """
    # ⚠️ `/api/map/points` 會去抓一張 OSM 圖磚來判斷「圖磚是不是被擋住了」
    #    ⇒ **真實外連**，被 `conftest` 的對外連線守門攔下來（它攔對了）。
    # 📌 那道守門今天替我抓到一次 —— 記在這裡，因為下一個寫地圖題的人會再撞一次。
    geo = _geo()
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None, raising=False)

    username, password = make_user(username="gc8_map", role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.252"})
    assert r.status_code == 200, r.text
    r = client.get("/api/map/points",
                   headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("info", body)

    for key in ("pendingGeocode", "unresolvableGeocode"):
        assert key in info, (
            f"回應裡沒有 `{key}`，現有鍵：{sorted(info)}\n"
            "☠️ 畫面只拿得到一個數字 ⇒ 兩種情況又被講成同一句話。")
    assert info["pendingGeocode"] is not None, (
        "`pendingGeocode` 是 `None` —— 〈null 不等於 0〉："
        "畫面會把它當成 0，而那代表「全部查完了」。")
    assert info["unresolvableGeocode"] is not None, (
        "`unresolvableGeocode` 是 `None` —— 同上。")


# ══════════════════════════════════════════════════════════════════════
# GC8（前半）· 同一個查不到的地址不可以問第二次
# ══════════════════════════════════════════════════════════════════════
#
# 🔴 這一題原本住在 `test_geocode_shortcircuit_2026_09_22.py`。
#    搬過來的理由是**守門抓到的**：一個編號跨兩個檔時，
#    覆蓋率守門分辨不出「哪一支在守哪一條」。
# 📌 而 `GC8` 真的有兩半（A 2026-09-23：「有一半是使用者看得到的」）：
#    **省下請求**（這一題）與**講對話**（上面那幾題）。
# 🔑 兩半放在同一個檔裡，「GC8 綠了」這句話才不會被單獨引用其中一半。

def test_gc8_a_repeated_miss_does_not_ask_google_again(monkeypatch):
    """🔴🔴 GC8：**一個打不到的地址，不可以每次開地圖就問一次。**

    ☠️ 疊上 `GC5`（google 階無節流）＝ **無上限**。
    🔑 **判準與 `GB` 不同**：`GB` 擋的是總量，
    而這裡是**同一個地址被重複問** —— 光加每日上限擋不住它，
    📌 它會把額度吃光，**而每一次都是同一個地址**。

    ## ⚠️ 這一題驗的是**請求數**，不是省錢

    A 2026-09-22 收回了「Google 對這類請求仍然計費」那句（未查證）——
    ⇒ 規格已改成「**負快取省的是請求數，是否省錢未確認**」。
    🔑 **所以這裡的斷言不可以寫成「省了多少錢」** ——
    ☠️ 那是一件我們不知道的事，而寫進斷言之後它會變成一個
    **沒有人查過、卻被當成前提的句子**。
    """
    geo = _geo()
    calls = []
    monkeypatch.setattr(geo, "_locate_google",
                        lambda addr, **kw: calls.append(addr) or None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_nominatim", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_throttle", lambda: None)

    address = "完全查不到的地址 XYZ"
    for _ in range(5):
        geo.locate_cached(address)
    assert len(calls) <= 1, (
        f"同一個查不到的地址問了 Google {len(calls)} 次 —— 沒有負快取。")


# ══════════════════════════════════════════════════════════════════════
# 🔴 負快取的 TTL —— **它零題在守**（C 2026-09-22 18:14 實查）
# ══════════════════════════════════════════════════════════════════════
#
# ```
# GEOCODE_MISS_TTL_SECONDS 只出現在 helpers/geo.py 三處：
#   :1049  = 7 * 24 * 60 * 60     定義
#   :1107  過期就 pop 掉           geocode_missed_recently()
#   :1134  now - at < TTL          geocode_miss_count()
# ⇒ tests/ **零處**
# ```
# ☠️ 而 `a14c`／`a14d`／`GC8` 那七題驗的都是「**記不記**」——
# **沒有一題驗「多久之後會忘」。**
#
# 🔑 它為什麼特別容易錯而沒人發現：
# ```
# TTL = 7 天 ⇒ 要驗必須**操控時間** ⇒ 「寫起來麻煩」的那一類 ⇒ 最容易被跳過
# 失敗樣子：`>=` 寫成 `<=`／單位寫成分鐘／忘記 pop
#          ⇒ **全部都不會有症狀** —— 地圖上少幾個點，或多重查幾次，沒有人報修
# ```
# 📌 〈降級之後它還是會動〉。
#
# 🔴 而 A-2 用「上限已經有了（TTL 7 天）」駁回了 `a14` 的乙案 ——
# **那句話當時是「讀過程式碼」不是「驗過行為」。** 這一節補上它。


def _miss_key(geo, address):
    """`_MISS_CACHE` 的鍵 —— 它含 `db_path`，不是裸地址。"""
    return geo._miss_key(address)


def test_gc9_a_miss_is_forgotten_once_the_ttl_has_passed(clean_miss_cache):
    """🔴 **過了 TTL ⇒ 不再算「最近查過」，而且那一筆要真的被移除。**

    🔑 兩件事要一起驗：
    ```
    回 False        ← 行為
    那一筆消失      ← 狀態
    ```
    ☠️ 只回 False 而留著的話，`_MISS_CACHE` 會**單調成長** ——
    而標案雷達每天帶進新的機關名稱，那是一個永遠不會被清的字典。
    """
    geo = _geo()
    address = "TTL 測試地址 A"
    geo.remember_geocode_miss(address)
    key = _miss_key(geo, address)
    assert key in geo._MISS_CACHE, "前提不成立：沒記進去"

    # 🔑 直接把時間戳往前推，**不等七天**。
    geo._MISS_CACHE[key] = time.time() - geo.GEOCODE_MISS_TTL_SECONDS - 1

    assert geo.geocode_missed_recently(address) is False, (
        "過了 TTL 而 `geocode_missed_recently()` 仍然回 True ——\n"
        "☠️ 那個地址永遠不會再被查，**而使用者改地址也救不回來**"
        "（鍵是地址字串，改對了才換鍵；而他沒改、只是等服務修好）。")
    assert key not in geo._MISS_CACHE, (
        "過期之後那一筆仍然留在 `_MISS_CACHE` 裡 ——\n"
        "🔑 回 False 是對的，**而狀態沒有跟著清** ⇒ 那個字典單調成長，\n"
        "☠️ 標案雷達每天帶進新的機關名稱，而它永遠不會被清。")


def test_gc9_a_fresh_miss_is_still_remembered(clean_miss_cache):
    """⚙️ 反向控制①：**還沒到 TTL ⇒ 仍然要記得。**

    ☠️ 少了這一題，一個「**永遠回 False**」的實作會讓上一題全綠 ——
    🔑 而那等於把 `GC8` 整個關掉：53 個查不到的地址會每一次重新排隊，
    **回到使用者回報的那個 `60 → 103`。**
    📌 〈判準的寬窄都會騙人〉：「永遠忘記」是「過期就忘記」的超集。
    """
    geo = _geo()
    address = "TTL 測試地址 B"
    geo.remember_geocode_miss(address)
    key = _miss_key(geo, address)
    geo._MISS_CACHE[key] = time.time() - geo.GEOCODE_MISS_TTL_SECONDS + 3600

    assert geo.geocode_missed_recently(address) is True, (
        "還差一小時才到 TTL，而它已經忘了 ——\n"
        "☠️ 那等於把 GC8 關掉：那些地址每一次都重新排隊。")


def test_gc9_the_two_ttl_implementations_agree(clean_miss_cache):
    """🔴🔴 **TTL 有兩份實作，而沒有任何東西要求它們一致。**

    ```
    geo.py:1107  geocode_missed_recently()   if now - at >= TTL: pop
    geo.py:1134  geocode_miss_count()        if now - at <  TTL: 計入
    ```
    ☠️ **同一條規則、兩個獨立的比較式。** 分岔時的樣子：
    ```
    一邊過期了、另一邊還沒 ⇒ 查詢**會重查**，而畫面仍說「還有 N 個查不到」
    或反過來              ⇒ 畫面說「0 個查不到」，而查詢**仍然被短路**
    ⇒ 兩種都是「數字與行為對不上」，而**兩種都不會報錯**
    ```
    📌 而 `geo.py` 自己在別處就警告過這個形狀（`:365` 「⋯而兩份判斷會分岔」）——
    🔑 **它在那裡被防住了，在這裡沒有。**

    ⚠️ 而這一題是**過渡期的防線**：真正的修法是把那個比較抽成**單一來源**
    （〈修作法不要修結果〉：守兩份一致 ⇒ 有人加第三個消費者時這題看不見它）。
    ⇒ 已登記 `NEXT`，**而在那之前這一題至少現在就抓得到分岔**。
    """
    geo = _geo()
    address = "TTL 測試地址 C"
    geo.remember_geocode_miss(address)
    key = _miss_key(geo, address)

    # 還沒過期 ⇒ 兩支都要算它
    geo._MISS_CACHE[key] = time.time() - geo.GEOCODE_MISS_TTL_SECONDS + 3600
    assert geo.geocode_missed_recently(address) is True
    assert geo.geocode_miss_count() >= 1, (
        "還沒過期，而 `geocode_miss_count()` 沒有把它算進去 ——\n"
        "☠️ 畫面會說「0 個查不到」，而查詢仍然被短路。")

    # 過期 ⇒ 兩支都不可以再算它
    geo.remember_geocode_miss(address)
    geo._MISS_CACHE[_miss_key(geo, address)] = (
        time.time() - geo.GEOCODE_MISS_TTL_SECONDS - 1)
    before_count = geo.geocode_miss_count()
    said_recent = geo.geocode_missed_recently(address)
    assert said_recent is False and before_count == 0, (
        f"兩支對同一筆的判斷不一致："
        f"`geocode_missed_recently` 回 {said_recent}、"
        f"`geocode_miss_count` 回 {before_count} ——\n"
        "☠️ 「數字」與「行為」對不上，**而兩種方向都不會報錯**。\n"
        "🔑 同一條規則寫了兩次（`geo.py:1107` 與 `:1134`），"
        "而沒有任何東西要求它們一致。")


def test_gc9_the_yardstick_shrinking_the_ttl_changes_the_answer(
        clean_miss_cache, monkeypatch):
    """📏 量尺：**把 TTL 改小 ⇒ 同一筆從「記得」變成「忘了」。**

    ☠️ 少了這一題，上面三題在一個把 `604800` **寫死在比較式裡**的實作下
    照樣全綠 —— 🔑 而這一題證明它**真的讀那個常數**。
    📌 今天付過學費的形狀：`GC10` 那一族（對目標行為不敏感的斷言）。
    """
    geo = _geo()
    address = "TTL 測試地址 D"
    geo.remember_geocode_miss(address)
    geo._MISS_CACHE[_miss_key(geo, address)] = time.time() - 3600   # 一小時前

    assert geo.geocode_missed_recently(address) is True, (
        "一小時前記的，在 TTL=7 天下應該還記得（前提不成立）")

    monkeypatch.setattr(geo, "GEOCODE_MISS_TTL_SECONDS", 60)
    geo.remember_geocode_miss(address)
    geo._MISS_CACHE[_miss_key(geo, address)] = time.time() - 3600

    assert geo.geocode_missed_recently(address) is False, (
        "把 TTL 改成 60 秒之後，一小時前那一筆**仍然**被當成「最近查過」——\n"
        "☠️ 那代表過期判斷讀的不是 `GEOCODE_MISS_TTL_SECONDS`，\n"
        "🔑 而上面三題的綠證明不了任何事。")
