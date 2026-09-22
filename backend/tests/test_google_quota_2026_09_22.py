"""§16 GB1–GB16 · Google 額度治理（真實計算器＋自動降回免費）。

使用者 2026-09-22：
> 「你做一個真實計算器，並讓超級管理員可以依據現在 google 的免費額度去調整，
>   當準備到達上限額度自動寄信並將附近客戶跟查找功能先回歸免費，待月週期結束開放」

---

# 🔑 設計約束：這一整節的預設是「關著」

沒有 Google 金鑰、或沒填額度 ⇒ **行為要跟現在完全一樣**（`GB13`）。

---

# ☠️ 這一節最容易假綠的四題，以及它們各自會怎麼綠

```
GB16  額度恢復後那些地址要「真的再去問 Google」
      ☠️ 降級期間把免費階的結果寫進 google 階快取 ⇒ 恢復後永遠命中快取
      🔑 而「永遠不再問」與「問了而答案一樣」在畫面上完全相同

GB14  計數要跨重啟存活
      ☠️ 記憶體計數器的「永遠沒觸發」跟「運作良好」長得一模一樣

GB13  關閉時行為與現在完全一樣
      ☠️ 少了這一半，修法會讓沒有金鑰的人每次開地圖都多跑一段管制邏輯

GB15  達上限時 /api/map/points 仍要回得出點位
      ☠️ 「鎖死了所以地圖是空的」也會讓「沒有超支」這個斷言綠
```

---

# 📌 觀測點：計數要對得上帳單，不是對得上意圖

```
GB2  計數加在「真的發出 HTTP 請求」那一行，不是「決定要查」的地方
     快取命中、預算用完、提前返回 => 都不計
GB3  失敗的請求也要計 —— 判準是「**有沒有收到回應**」
     計數點在**發出之後、解析之前**；連線失敗（timeout／DNS）不計
```
🔑 **只計成功的話，一個查不到的地址可以無限重試而不進計數。**

⚠️ **這裡原本寫的是「Google 對 `ZERO_RESULTS` 仍然計費」** ——
A 2026-09-22 自陳那半句未查證並收回。**行為不變，理由換掉。**
📌 〈證據的適用範圍〉：**一個斷言的理由，要跟那個斷言一樣驗得到。**

---

# 🔴 `source` 是 **SKU 粒度**，不是 `"google"`

Google **2025-03-01 廢掉每月 $200 共用 credit**，改成
**每個 SKU 各自一組免費額度，而且不 pool**（A-2 讀過官方頁面逐字）。
```
google:geocoding            Geocoding
google:places-text-search   §17 的 Places（還沒做）
```
☠️ **兩個 SKU 的用量不可以加在一起去對同一個門檻** ——
🔑 所以這個檔一律釘 `geo.USAGE_SKU_*` **常數**，不釘字面值：
📌 **釘字面值的話，Places 進來的那一天不會有人發現。**
"""
import sqlite3

import pytest


def _geo():
    from helpers import geo
    return geo


def _need(name):
    geo = _geo()
    fn = getattr(geo, name, None)
    assert fn is not None, (
        f"`helpers/geo.py` 缺少 `{name}` —— 見 §16 GB 的驗收條件")
    return fn


def _superadmin(client, make_user, name, ip):
    username, password = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": ip})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ══════════════════════════════════════════════════════════════════════
# GB1 · 計數器要有落點
# ══════════════════════════════════════════════════════════════════════

def test_gb1_the_usage_counter_has_a_table_to_land_in(client):
    """🔴 GB1：計數要存進 `geocode_usage` 表（月、來源、次數、最後更新）。

    📌 〈計數器要有落點〉：「累積到 N 就停」要先指出 **N 寫在哪張表**。
    ☠️ 記憶體計數器一重啟就歸零，而**「永遠沒觸發」跟「運作良好」長得一模一樣**。
    """
    import db
    conn = db.get_db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(geocode_usage)")}
    finally:
        conn.close()
    assert cols, "`geocode_usage` 這張表不存在 —— 計數沒有落點"
    missing = {"month", "source", "count"} - cols
    assert not missing, f"`geocode_usage` 少了欄位：{sorted(missing)}（現有 {sorted(cols)}）"


def test_gb14_the_counter_survives_a_restart(client):
    """🔴🔴 GB14 反向控制：**寫入後重新載入，數字要還在。**

    ☠️ 這一題是 `GB1` 的實測版：表存在**不等於**計數真的寫進去了。
    🔑 而記憶體計數器的失敗方式是最難看見的一種：
    **它不報錯、不歸零到負數，它只是每次重啟都從 0 開始** ——
    ⇒ 硬上限永遠不會被觸發，**而那與「用量一直很低」完全一樣。**

    ⚠️ 觀測手法：**關掉連線再開一條新的**去讀。
    用同一個連線讀的話，驗到的可能是尚未提交的交易。
    """
    import db
    geo = _geo()
    bump = _need("record_geocode_call")
    bump(geo.USAGE_SKU_GEOCODING)
    bump(geo.USAGE_SKU_GEOCODING)

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT count FROM geocode_usage WHERE source=? "
            "ORDER BY month DESC LIMIT 1",
            (geo.USAGE_SKU_GEOCODING,)).fetchone()
    finally:
        conn.close()
    assert row is not None, "呼叫兩次之後，`geocode_usage` 裡一列都沒有"
    assert row["count"] >= 2, (
        f"計數只有 {row['count']}，而剛才呼叫了兩次 —— 計數沒有真的落地")


# ══════════════════════════════════════════════════════════════════════
# GB2 / GB3 · 計數點要對得上帳單
# ══════════════════════════════════════════════════════════════════════

def test_gb2_a_cache_hit_is_not_counted(client, monkeypatch):
    """🔴 GB2：**快取命中不計數。**

    🔑 計的是「帳單上的那個數」，不是「我們想查幾次」。
    ☠️ 把計數加在「決定要查」的地方 ⇒ 算出來的數字會**大於**帳單
    ⇒ 而那會讓我們提前降級，**使用者拿到的精度比他付的錢低**。
    """
    geo = _geo()
    calls = []
    monkeypatch.setattr(geo, "record_geocode_call",
                        lambda source: calls.append(source), raising=False)
    monkeypatch.setattr(geo, "_locate_google", lambda *a, **kw: None)

    geo.cached_only("台中市西屯區台灣大道三段301號")
    assert not calls, f"快取查詢也被計數了：{calls}"


def test_gb3_a_zero_results_response_is_still_counted(client, monkeypatch):
    """🔴🔴 GB3：**Google 回 `ZERO_RESULTS` 也要計數。**

    ## ⚠️ 2026-09-22 修正**理由**（A 收回了原本那句，行為不變）

    ```
    原本的理由   「Google 對 ZERO_RESULTS 仍然計費」  ← A 自陳未查證，收回
    改成         「它發出去了、也收到回應了，而我們量的是請求數」
    ```
    🔑 **兩個理由導向同一個行為，而它們可被驗證的程度差很多** ——
    ☠️ 「會不會計費」要去查 Google 的價目表，
    而「有沒有收到回應」**就在這一段程式碼裡**。
    📌 〈證據的適用範圍〉：**一個斷言的理由，要跟那個斷言一樣驗得到。**

    ⚠️ 而原本那個理由若寫進 docstring 並被下一個人引用，
    **它會變成一個沒有人查過、卻被當成前提的句子。**

    ⇒ 計數點在 **發出之後、解析之前**。

    ## ⚠️ 而連線失敗（timeout／DNS）**不計**

    那種情況**沒有收到回應** ⇒ 我們量不到那一次請求有沒有到達對方。
    🔑 判準是「**有沒有收到回應**」，不是「**有沒有拿到座標**」——
    📌 而只看「有沒有拿到座標」的話，
    **「查到了但沒結果」與「根本沒問到」會被歸成同一類**，
    ☠️ 而那兩件事的處置相反（一個要記住，一個要重試）。
    """
    import io
    import json as _json

    geo = _geo()
    calls = []
    monkeypatch.setattr(geo, "record_geocode_call",
                        lambda source: calls.append(source), raising=False)
    monkeypatch.setattr(geo, "_google_api_key", lambda: "fake-key",
                        raising=False)
    from helpers import settings as _settings
    monkeypatch.setattr(
        _settings, "_get_setting",
        lambda key, default=None: ({"google_maps_api_key": "fake-key"}
                                   if key == "company_profile" else default))

    class _Resp:
        def read(self):
            return _json.dumps({"status": "ZERO_RESULTS", "results": []}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(geo.urllib.request, "urlopen", lambda *a, **kw: _Resp())
    geo._locate_google("查不到的地址")
    # 🔴 2026-09-22：釘**常數**不釘字面值（B 指出，A 已裁 SKU 粒度）。
    #
    # Google 2025-03-01 廢掉每月 $200 共用 credit ⇒ **每個 SKU 各自一組免費
    # 額度，而且不 pool**（A-2 讀過官方頁面逐字）。
    # ⇒ `source` 存的是 `google:geocoding`，不是 `google`。
    #
    # 🔑 而用常數的理由不只是「現在對」：等 §17 的 Places 進來時會有
    # `google:places-text-search`，而**兩個 SKU 的用量不可以加在一起去對
    # 同一個門檻** —— ☠️ **釘字面值的話，那一天不會有人發現。**
    assert calls == [geo.USAGE_SKU_GEOCODING], (
        f"Google 回 ZERO_RESULTS 而沒有計到 `{geo.USAGE_SKU_GEOCODING}`：{calls}\n"
        "⇒ 查不到的地址可以無限重試而不進計數，而那個 SKU 的額度會被吃掉。")

    calls.clear()

    def _timeout(*a, **kw):
        raise TimeoutError("連線逾時")

    monkeypatch.setattr(geo.urllib.request, "urlopen", _timeout)
    geo._locate_google("另一個地址")
    assert calls == [], (
        f"連線失敗也被計數了：{calls} —— 請求沒有到達對方，不會被計費。")


# ══════════════════════════════════════════════════════════════════════
# GB7 · 留空 ≠ 0
# ══════════════════════════════════════════════════════════════════════

def test_gb7_a_blank_quota_means_unmanaged_not_zero(client):
    """🔴🔴 GB7：「每月免費額度」**留空 ＝ 不管制**，不是 ＝ 0。

    📌 〈null 不等於 0〉—— 用 `is None`，不要用真假值。
    ☠️ 寫成真假值的話：**沒填額度 ＝ 額度 0 ＝ 第一次請求就鎖死**，
    🔑 **而那看起來很像「金鑰有問題」** —— 使用者會去查金鑰，查不出東西。
    """
    over = _need("quota_exceeded")
    assert over(used=999_999, quota=None) is False, (
        "額度留空（None）時被當成 0 ⇒ 第一次請求就鎖死。用 `is None` 判斷。")
    assert over(used=0, quota=0) is True, (
        "額度明著填 0 應該代表「一次都不准查」—— 那與留空是兩件事。")


# ══════════════════════════════════════════════════════════════════════
# GB13 / GB15 / GB16 · A 指名的三題反向控制
# ══════════════════════════════════════════════════════════════════════

def test_gb13_everything_is_unchanged_when_there_is_no_key(client, monkeypatch):
    """🔴 GB13 反向控制：**沒有 Google 金鑰時，行為與現在完全一樣。**

    ☠️ 少了這一半，修法會讓沒有金鑰的人每次開地圖都多跑一段管制邏輯 ——
    🔑 而他們**從來不會用到 Google 那一階**，那段邏輯對他們只有成本沒有作用。
    📌 這一節的預設是「關著」，而「關著」要能被證明。
    """
    geo = _geo()
    calls = []
    monkeypatch.setattr(geo, "record_geocode_call",
                        lambda source: calls.append(source), raising=False)
    from helpers import settings as _settings
    monkeypatch.setattr(_settings, "_get_setting",
                        lambda key, default=None: {} if key == "company_profile"
                        else default)

    assert geo._locate_google("任何地址") is None, "沒有金鑰卻送出了請求"
    assert calls == [], f"沒有金鑰而計了數：{calls}"


def test_gb15_the_map_still_returns_points_at_the_hard_limit(
        client, make_user, monkeypatch):
    """🔴🔴 GB15 反向控制：**達硬上限時 `/api/map/points` 仍然要回得出點位。**

    ⭐ 使用者要的是「附近客戶跟查找功能**先回歸免費**」——
    **功能照用，只是精度降級**（`GB8`）。

    ☠️ 少了這一題，**「鎖死了所以地圖是空的」也會讓「沒有超支」那個斷言綠** ——
    🔑 而那是把一個成本問題換成一個功能故障。
    """
    geo = _geo()
    monkeypatch.setattr(geo, "quota_exceeded", lambda **kw: True, raising=False)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None, raising=False)

    auth = _superadmin(client, make_user, "gb15_admin", "203.0.113.251")
    r = client.get("/api/map/points", headers=auth)
    assert r.status_code == 200, (
        f"達上限之後地圖端點回 {r.status_code} —— 功能被關掉了，"
        "而使用者要的是降級不是關閉。\n" + r.text[:200])


def test_gb16_a_degraded_result_is_not_written_into_the_google_cache_key(
        client, monkeypatch):
    """🔴🔴 GB16：**額度恢復之後，降級期間那些地址要真的會再去問 Google。**

    ## ☠️ 它是 `A9`／`GC1` 同一個坑

    降級期間退到 Nominatim ⇒ 拿到行政區中心點。
    **若把那個結果寫進 `google` 階的快取鍵**：
    ```
    額度恢復 ⇒ cached_only() 在 google 階命中 ⇒ 永遠不會再問 Google
    ```
    🔑 **而「永遠不再問」與「問了而答案一樣」在畫面上完全相同** ——
    📌 症狀是**沒有症狀**：地圖一直是行政區精度，而金鑰、額度、設定全都正常。

    ## 📌 觀測點是「快取列的 `source` 欄」，不是「座標對不對」

    座標在降級期間本來就會是行政區中心 ⇒ 驗座標分不出這兩件事。
    """
    import db

    geo = _geo()
    monkeypatch.setattr(geo, "quota_exceeded", lambda **kw: True, raising=False)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_locate_google",
                        lambda *a, **kw: pytest.fail(
                            "降級期間仍然呼叫了 _locate_google"))
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(
        geo, "_locate_nominatim",
        lambda addr, **kw: ((24.1, 120.6), geo.PRECISION_DISTRICT))

    address = "台中市西屯區某條路 999 號"
    geo.locate_cached(address)

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT source FROM geocode_cache WHERE address=?", (address,)
        ).fetchall()
    finally:
        conn.close()
    sources = [r["source"] for r in rows]
    assert sources, f"降級期間查完之後，`geocode_cache` 裡一列都沒有：{address}"
    assert geo.SOURCE_GOOGLE not in sources, (
        f"降級期間拿到的免費階結果被寫進了 google 階的快取鍵：{sources}\n"
        "☠️ 額度恢復之後，這些地址永遠不會再去問 Google —— 就是 A9／GC1 那個坑。"
    )


def test_gb16_the_probe_itself_would_notice_a_google_row(client):
    """📏 量尺：上一題的觀測點要看得見 `google` 這個值。

    ☠️ 少了這一題，`SOURCE_GOOGLE` 哪天改名（或 `source` 欄改存別的東西），
    上面那個 `not in` 會**永遠成立** —— 一個安全斷言靠著對不上而通過。
    🔑 同一族：〈否定式的安全斷言，會被「什麼都沒量到」滿足〉。

    📌 這一題第一版自己紅了，而紅在我猜錯欄位名（`fetched_at`，實際是
    `created_at`）—— **量尺先驗到了自己**。留著這一行：
    ⚠️ 憑印象寫欄位名是我今天第六次，而**只有這一次被當場擋住**，
    因為這一題的工作就是「去撞一次真的資料表」。
    """
    import db

    geo = _geo()
    assert isinstance(geo.SOURCE_GOOGLE, str) and geo.SOURCE_GOOGLE, (
        "`SOURCE_GOOGLE` 不是一個非空字串 —— 上一題的斷言驗不到東西")

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO geocode_cache (address, lat, lon, source, precision, "
            "created_at) VALUES (?,?,?,?,?,?)",
            ("量尺用的地址", 24.0, 120.0, geo.SOURCE_GOOGLE, "rooftop",
             "2026-09-22T00:00:00"))
        conn.commit()
        rows = conn.execute(
            "SELECT source FROM geocode_cache WHERE address='量尺用的地址'"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        pytest.fail(f"`geocode_cache` 的欄位跟這一題的假設對不上：{exc}")
    finally:
        conn.close()
    assert [r["source"] for r in rows] == [geo.SOURCE_GOOGLE], (
        "寫進去的 `source` 讀不回來 —— 上一題的觀測點無效")


# ══════════════════════════════════════════════════════════════════════
# GB4 / GB5 / GB6 · 設定與計算器
# ══════════════════════════════════════════════════════════════════════

def test_gb4_the_billing_cycle_start_day_is_configurable(client):
    """GB4：月週期起算日要可設定（預設 1 號）。

    ☠️ Google 的帳單週期**不一定是自然月** —— 寫死 1 號的話，
    跨週期那幾天的管制會完全錯位：**我們以為歸零了，而帳單還在累積。**
    """
    period = _need("current_billing_period")
    assert period(start_day=1) != period(start_day=15), (
        "起算日換成 15 號而週期沒有變 —— 那個參數沒有被使用到")


def test_gb5_the_calculator_reads_real_rows_not_estimates(client):
    """GB5：計算器的數字一律從**實際資料**算。

    使用者要的「真實」兩個字是重點。
    ⚠️ 單價與免費額度都是**超級管理員填的欄位**（GB6），不可以寫死在程式裡 ——
    🔑 **Google 改過不止一次，而寫死的價格不會報錯，只會算錯。**
    """
    import db

    calc = _need("quota_calculator")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO geocode_cache (address, lat, lon, source, precision, "
            "created_at) VALUES (?,?,?,?,?,?)",
            ("GB5 已快取的地址", 24.0, 120.0, "nominatim", "district",
             "2026-09-22T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    out = calc()
    assert out.get("cached_addresses", 0) >= 1, (
        f"計算器算不出「目前已快取的相異地址數」：{out}")
    for field in ("cached_addresses", "uncached_addresses", "used_this_period"):
        assert field in out, f"計算器少了欄位 `{field}`：{sorted(out)}"


def test_gb6_only_a_superadmin_can_change_the_quota_settings(client, make_user):
    """GB6：額度設定只有超級管理員可以改（比照 SA1）。

    📌 它決定的是**錢**：額度、單價、警戒線、硬上限。
    ⚠️ 反向控制用 `role=viewer` ＋ `modules` 含 `settings` ——
    ☠️ 那正是 §10 查出來的那個真實帳號形狀（`automation`）。
    """
    username, password = make_user(username="gb6_viewer", role="viewer",
                                   modules=["settings"])
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Forwarded-For": "203.0.113.252"})
    assert r.status_code == 200, r.text
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    r = client.put("/api/settings/google-quota", headers=auth,
                   json={"monthly_free_quota": 1, "warn_pct": 80,
                         "hard_pct": 100, "cycle_start_day": 1})
    assert r.status_code == 403, (
        f"持有 settings 模組的 viewer 改得動額度設定（{r.status_code}）—— "
        "那個欄位決定的是錢。")


# ══════════════════════════════════════════════════════════════════════
# GB8 / GB9 / GB10 / GB11 / GB12 · 降級、看得見、自動恢復、告警
# ══════════════════════════════════════════════════════════════════════

def test_gb8_the_google_stage_is_skipped_at_the_hard_limit(client, monkeypatch):
    """GB8：達硬上限 ⇒ **google 那一階直接跳過**，退到免費階。

    ⭐ 使用者要的是「先回歸免費」—— **功能照用，只是精度降級。**
    """
    geo = _geo()
    monkeypatch.setattr(geo, "quota_exceeded", lambda **kw: True, raising=False)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_locate_google",
                        lambda *a, **kw: pytest.fail("達上限後仍呼叫 Google"))
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(
        geo, "_locate_nominatim",
        lambda addr, **kw: ((24.1, 120.6), geo.PRECISION_DISTRICT))

    got = geo.locate_cached("GB8 測試地址")
    assert got is not None, "退到免費階之後什麼都沒回 —— 功能被關掉了不是降級"


def test_gb9_the_map_page_says_it_is_in_saving_mode():
    """🔴 GB9：降級**必須看得見**。

    📌 〈降級之後它還是會動〉：**壞掉會被報修，降級不會。**
    ☠️ 少了那一行字，使用者會把「地圖變不準了」當成 bug 來報，
    **而沒有人查得出來** —— 金鑰正常、設定正常、程式沒有例外。

    ⚠️ 結構檢查：釘的是「頁面裡有沒有一個講降級狀態的欄位」，
    不釘文案（那是設計）。
    """
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent.parent
            / "frontend" / "pages" / "map.html")
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")
    assert any(w in text for w in ("省錢模式", "額度", "quota")), (
        "`map.html` 裡沒有任何講額度／降級狀態的東西 ——\n"
        "⇒ 降級之後畫面跟平常一樣，而使用者會把它當成 bug 報上來。")


def test_gb10_the_free_stage_result_keeps_its_own_source(client, monkeypatch):
    """🔴 GB10：降級期間**不可以**把免費階的結果寫進 `google` 階的快取鍵。

    這是 `GB16` 驗的那個不變量的單元版本。兩題都要：
    ```
    GB10  快取列的 source 欄不可以是 google   ← 寫入那一刻
    GB16  額度恢復之後真的會再問 Google      ← 下一個週期
    ```
    🔑 只有前者的話，**擋得住這一種寫法，擋不住「恢復時不再檢查」的另一種**。
    """
    geo = _geo()
    stage = _need("_cached_stage")
    monkeypatch.setattr(geo, "quota_exceeded", lambda **kw: True, raising=False)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_locate_google", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(
        geo, "_locate_nominatim",
        lambda addr, **kw: ((24.1, 120.6), geo.PRECISION_DISTRICT))

    address = "GB10 測試地址"
    geo.locate_cached(address)
    assert stage(address, geo.SOURCE_GOOGLE) is None, (
        "降級期間的結果被寫進了 google 階的快取鍵 —— 額度恢復後永遠不會再問。")


def test_gb11_recovery_is_computed_not_stored(client):
    """GB11：月週期結束**自動恢復**，判斷用**當下時間算出來的週期**。

    ⚠️ 不要用一個「下次恢復日」欄位 ——
    ☠️ **那種欄位在排程漏跑一次之後就永遠不會觸發**，
    🔑 而症狀是「額度早就重置了，而系統還在省錢模式」。
    """
    period = _need("current_billing_period")
    from datetime import date as _date
    a = period(start_day=1, today=_date(2026, 9, 30))
    b = period(start_day=1, today=_date(2026, 10, 1))
    assert a != b, (
        "跨過月週期而 `current_billing_period()` 回同一個值 —— 不會自動恢復")


def test_gb12_the_warning_mail_is_sent_once_per_cycle_and_raises(
        client, monkeypatch):
    """🔴 GB12：達警戒線寄信給超級管理員，**一個週期只寄一次**，且走 `_send_raising`。

    ☠️ 走 `_async_send` 的話會**射後不理**：
    「已通知」被標起來而信沒出去（同 §3s 的標案雷達）。
    📌 〈告警必須有速率上限〉：設計時就要想「失控時怎麼關掉」。
    """
    from helpers import email_notify

    notify = _need("notify_quota_warning")
    sent = []
    monkeypatch.setattr(email_notify, "_send_raising",
                        lambda *a, **kw: sent.append(a) or email_notify.SEND_SENT,
                        raising=False)
    monkeypatch.setattr(
        email_notify, "_async_send",
        lambda *a, **kw: pytest.fail("走了 _async_send —— 射後不理會標記已通知而信沒出去"),
        raising=False)

    notify(used=800, quota=1000)
    notify(used=850, quota=1000)
    assert len(sent) == 1, (
        f"同一個週期寄了 {len(sent)} 封警戒信 —— 一個週期只能寄一次。")


# ══════════════════════════════════════════════════════════════════════
# GB7 行為版 · 現在的證據只有註解，而註解不會在行為改變時變紅
# ══════════════════════════════════════════════════════════════════════
#
# A-2 明著標了它的限制：`GB7`／`GB13` 目前的證據是**讀 `geo.py` 的註解與
# 預設值**（`geo.py:437`／`448`／`464`／`416`），**沒有跑過任何一條路徑**。
#
# 🔴 而這件事的後果方向**剛剛被更正過，而且反過來了**：
# ```
# 先前以為   留空 = 功能沒開   ⇒ 保守失敗（看得見、會被報修）
# 實際上     留空 = 不設上限   ⇒ **沒有任何東西會擋住費用**
# ```
# 🔑 ⇒ 這一題不是補文件，是**把一個方向相反的假設變成可執行的斷言**。


def test_gb7_a_blank_quota_neither_warns_nor_degrades_but_still_counts(
        client, monkeypatch):
    """🔴🔴 GB7 行為版：`monthly_free_quota is None` 時

    ```
    ① 警戒線那一條路   不寄信
    ② 硬上限那一條路   不降級
    ③ 而計數**仍然照記**   ← 不是「關掉整個模組」
    ```
    🔑 ③ 是這一題最容易被做錯的一半：
    ☠️ 「不管制」很容易被實作成「連計數都不做」——
    **而那會讓使用者哪天想開始管制時，手上一筆歷史用量都沒有。**
    """
    geo = _geo()
    from helpers import email_notify, settings as _settings

    monkeypatch.setattr(geo, "quota_for", lambda *a, **kw: None, raising=False)
    sent = []
    monkeypatch.setattr(email_notify, "_send_raising",
                        lambda *a, **kw: sent.append(a) or email_notify.SEND_SENT,
                        raising=False)

    assert geo.notify_quota_warning(used=999_999) is False, (
        "額度留空（不管制）而它寄了警戒信 —— 沒有門檻就沒有警戒線可言。")
    assert sent == [], f"額度留空而信真的送出去了：{sent}"

    assert geo.quota_exceeded(used=999_999, quota=None) is False, (
        "額度留空而它判定「已達上限」⇒ 會降級。\n"
        "☠️ 留空的意思是不管制，不是額度 0。")

    # ③ 計數仍然要記 —— 不管制不等於不量。
    import db
    before = _usage_rows(db, geo)
    geo.record_geocode_call(geo.USAGE_SKU_GEOCODING)
    after = _usage_rows(db, geo)
    assert after > before, (
        "額度留空時連計數都停掉了 ——\n"
        "⇒ 使用者哪天想開始管制，手上一筆歷史用量都沒有。")


def _usage_rows(db, geo):
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS n FROM geocode_usage "
            "WHERE source=?", (geo.USAGE_SKU_GEOCODING,)).fetchone()
    finally:
        conn.close()
    return row["n"]


def test_gb7_a_small_quota_really_does_warn_and_degrade(client, monkeypatch):
    """🔴🔴 GB7 反向控制：**填一個小額度 ⇒ 那兩條路要真的會觸發。**

    ☠️ 少了這一半，**「整段程式碼都沒跑到」也會讓上一題綠** ——
    🔑 而「不管制」與「這個模組根本沒接上」在畫面上完全一樣：
    **兩者都是沒有信、沒有降級。**
    📌 〈假綠燈〉：一個什麼都沒發生的實作，滿足所有「不應該發生」的斷言。
    """
    geo = _geo()
    from helpers import email_notify

    monkeypatch.setattr(geo, "quota_for", lambda *a, **kw: 100, raising=False)
    monkeypatch.setattr(geo, "usage_this_period", lambda *a, **kw: 95,
                        raising=False)
    sent = []
    monkeypatch.setattr(email_notify, "_send_raising",
                        lambda *a, **kw: sent.append(a) or email_notify.SEND_SENT,
                        raising=False)

    assert geo.notify_quota_warning(used=95, quota=100) is True, (
        "已用 95／100（超過預設警戒線 80%）而沒有寄信 ——\n"
        "⇒ 那兩條路可能根本沒接上，而上一題的綠因此證明不了任何事。")
    assert geo.quota_exceeded(used=100, quota=100) is True, (
        "已用 100／100 而沒有判定達上限 —— 硬上限那條路沒有接上。")


# ══════════════════════════════════════════════════════════════════════
# GB17–GB22 · SKU 粒度，而其中兩條是「明著標不知道」
# ══════════════════════════════════════════════════════════════════════

def test_gb17_usage_is_recorded_at_sku_granularity(client):
    """🔴 GB17：`geocode_usage.source` 要存 **SKU 粒度**，不是 provider 粒度。

    ```
    ❌ google                       一個值管不到兩個獨立額度
    ✅ google:geocoding ／ google:places-text-search ／ google:place-details
    ```
    ☠️ Google **2025-03-01 廢掉每月 $200 共用 credit**，改成
    **每個 SKU 各自一組免費額度而且不 pool**
    ⇒ 🔑 **兩個 SKU 的用量加在一起去對同一個門檻，兩邊都會算錯。**
    """
    geo = _geo()
    for name in ("USAGE_SKU_GEOCODING", "USAGE_SKU_PLACES_TEXT"):
        value = getattr(geo, name, None)
        assert isinstance(value, str) and ":" in value, (
            f"`geo.{name}` 不是一個 SKU 粒度的字串（實際 {value!r}）——\n"
            "⇒ provider 粒度管不到兩個獨立額度。")
    assert geo.USAGE_SKU_GEOCODING != geo.USAGE_SKU_PLACES_TEXT, (
        "兩個 SKU 用同一個字串 —— 它們的用量會被加在一起。")


def test_gb18_the_per_sku_quota_has_no_hardcoded_default(client):
    """🔴 GB18：額度設定要 **per-SKU**，而**預設值不可以寫死 10,000**。

    A-2 明說「**台灣適用哪一組數字我沒查**」。
    ☠️ 寫死一個沒查證的數字，**錯的方向若偏晚，使用者會先收到帳單再收到告警** ——
    🔑 而那時「我們有額度管制」這句話已經被相信了很久。
    📌 同 `GB5`「不要在程式裡寫死單價」與〈版本適配：不可變成孤兒〉。
    """
    geo = _geo()
    quota_for = _need("quota_for")
    got = quota_for(geo.USAGE_SKU_GEOCODING)
    assert got is None, (
        f"沒有人填過額度，而 `quota_for()` 回了 {got!r} ——\n"
        "☠️ 那是一個寫死的預設值，而 A-2 明說台灣適用哪一組數字沒查過。\n"
        "🔑 留空 ＝ 不管制（GB7），不是「用我們猜的那個數字」。")


def test_gb19_the_two_unknowns_are_marked_unknown_not_assumed(client):
    """🔴 GB19：**兩格明著標「查不到」，程式裡不可以寫成已知。**

    ```
    ZERO_RESULTS 算不算計費                    ❌ 官方頁沒有明文
    INVALID_REQUEST／OVER_QUERY_LIMIT 是否計費  ❌ 同上
    ```
    🔑 而這一題驗的是**程式碼沒有假裝知道** ——
    ☠️ 一個 `# ZERO_RESULTS 會計費，所以要計數` 的註解，
    **會在下一個人讀到時變成一個前提**，而那個前提沒有人查過。

    📌 判準：`geo.py` 裡不可以出現「宣稱計費」的句子。
    ⚠️ 而它擋不住換一種說法寫同一件事 —— 這一題是**提醒**不是**證明**，
    🔑 真正的處置是「**理由要跟斷言一樣驗得到**」，那寫在 `GB3` 裡。
    """
    from pathlib import Path as _Path
    src = (_Path(__file__).resolve().parent.parent / "helpers" / "geo.py"
           ).read_text(encoding="utf-8")
    import re as _re
    claims = [ln.strip() for ln in src.splitlines()
              if _re.search(r"(ZERO_RESULTS|INVALID_REQUEST|OVER_QUERY_LIMIT)",
                            ln) and "計費" in ln and "未" not in ln
              and "沒有" not in ln and "不確定" not in ln]
    assert not claims, (
        "`geo.py` 裡把「這些狀態會不會計費」寫成已知：\n  "
        + "\n  ".join(claims)
        + "\n⇒ 官方頁沒有明文（A-2 查過）。標成未知，不要寫成前提。")


def test_gb21_the_percent_fields_are_marked_inactive_when_quota_is_blank():
    """🔴 GB21：額度留空時，**警戒線／硬上限要變灰或標「未生效」**。

    ```
    畫面   警戒線 = 80、硬上限 = 100      ← 兩個欄位有值
    實際   quota is None 時，這兩個值完全不會被用到
    ```
    ☠️ **一個有值而不生效的欄位，比一個空的欄位更會騙人** ——
    🔑 使用者看到 80／100 會以為「有在管」，
    而實際上**沒有任何東西會擋住費用**（這個方向剛被更正過）。

    ⚠️ 結構檢查：釘「畫面有沒有依額度是否留空去改那兩欄的狀態」，
    不釘 `disabled` 還是 `opacity`（那是實作）。

    ## ⚠️ 判準收緊過一次，而第一版是我自己抓到的

    我原本寫「`quota` 後面 120 字內出現 `null`／`''`／`disabled`…」——
    ☠️ **而 `quota: ''` 這種初始值就會讓它過**。
    📌 它這次是**為了對的理由綠的**（B 真的做了 `quotaUnmanaged()`／
    `未生效`／`:disabled`），🔑 **而那是運氣不是判準。**

    ⇒ 改成兩件都要，而且要**在附近**：
    ```
    ① 一個「額度沒填」的判斷式（quota 與 null／undefined 比）
    ② 一個「未生效」的表現（未生效／disabled／opacity）
    ```
    """
    from pathlib import Path as _Path

    page = (_Path(__file__).resolve().parent.parent.parent / "frontend"
            / "pages" / "company-profile-settings.html")
    assert page.exists(), f"找不到 {page}"
    text = page.read_text(encoding="utf-8")
    import re as _re

    lines = text.splitlines()
    predicate = [i for i, ln in enumerate(lines)
                 if _re.search(r"quota", ln, _re.I)
                 and _re.search(r"(===?\s*(null|undefined)|Unmanaged)", ln)]
    assert predicate, (
        "設定頁裡找不到任何「額度有沒有填」的判斷式。\n"
        "📌 搜尋範圍：`company-profile-settings.html` 全文，"
        "找的是 `quota` 與 `null`／`undefined` 比較、或名字含 `Unmanaged` 的呼叫。")

    marked = False
    for i in predicate:
        window = "\n".join(lines[max(0, i - 10):i + 11])
        if _re.search(r"(未生效|disabled|opacity)", window):
            marked = True
            break
    assert marked, (
        "有「額度沒填」的判斷式，而附近沒有任何「未生效」的表現 ——\n"
        "☠️ 使用者看到 80／100 會以為有在管，而那兩個值完全不會被用到。\n"
        "🔑 一個有值而不生效的欄位，比一個空的欄位更會騙人。")


def test_gb22_the_blank_quota_shortcut_does_not_need_a_mail_module(
        client, monkeypatch):
    """⚠️ GB22：**這是測試成本，不是缺陷** —— 但它值得一題。

    `notify_quota_warning()` 的第一行是 `from helpers import email_notify`，
    **而那在 `if quota is None: return False` 之前**
    ⇒ 想測「留空時短路」必須先備好那個模組。

    ## 🔑 而它有一個真的後果，不只是麻煩

    ☠️ **「不管制」那條路依賴一個它用不到的模組** ——
    寄信那一塊哪天壞了（匯入失敗、設定缺漏），
    **連「不管制」都會跟著炸**，而那條路本來什麼都不該做。
    📌 〈防護的副作用落在盲側〉：**最不該有依賴的那條路上有一個依賴。**

    ⇒ 這一題釘的是「**額度留空時，不碰寄信那一塊也能跑完**」。
    """
    geo = _geo()
    monkeypatch.setattr(geo, "quota_for", lambda *a, **kw: None, raising=False)

    import helpers.email_notify as _en

    def _boom(*a, **kw):
        raise AssertionError("額度留空時不該碰到寄信那一塊")

    monkeypatch.setattr(_en, "_send_raising", _boom, raising=False)
    monkeypatch.setattr(_en, "_async_send", _boom, raising=False)

    assert geo.notify_quota_warning(used=999_999) is False, (
        "額度留空而它沒有短路 —— 見 `GB7`。")
