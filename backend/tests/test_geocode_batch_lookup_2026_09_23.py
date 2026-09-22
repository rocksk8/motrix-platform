"""§15 · **`cached_only()` 改成「一次連線問完四階」之後，三個沒人守的不變量。**

---

# ☠️ 為什麼會有這一檔

`test_gc8_a_known_miss_does_not_eat_the_time_budget` 在 2026-09-22 的打包那一輪紅了
（`spent = 2.20 秒`，門檻 1.0）。追下去**不是時序敏感，是一個真缺陷**：
```
已知查不到的地址永遠不在記憶體 _CACHE 裡 ⇒ 四階全部落到 DB
20 個地址 × 4 階 = **80 次 get_db()+SELECT+close()**
實測（C 18:20:03，正常優先權）
   20 次 budget.locate(負快取命中)  829 ms  ⇒ cached_only 佔 **94%**
   20 次 geocode_missed_recently()    0 ms  ⇒ 微秒級（負快取本身是免費的）
```
🔑 **而它先前是綠的，只因為門檻剛好等於那個成本**：
```
門檻 1.00s ／ 實測 0.829s ⇒ 餘裕 **1.21x**
而同一棵樹、只差行程優先權的自然變動 ⇒ **2.66x**
⇒ 餘裕小於自然變動 ⇒ **它遲早會紅，而紅的那天最省力的動作是放寬門檻**
```

⇒ B 把 `cached_only()` 改成**一次連線問完四階**（`_cache_get_many`）。
⚠️ **而那個改寫有三件事零題在守** —— 這一檔補上它們。

---

# ⚠️ 這一次是「碼先寫、題後補」，而那不是常態

協定是 **C 先把驗收測試寫成紅的，才輪到 B 寫碼**。
A 2026-09-22 明著破了這一次例，理由是**打包在等**。
☠️ 代價落在題目上：**它們可能一寫出來就是綠的** ——
🔑 ⇒ **所以下面每一題都配量尺**，否則分不出「綠著出生」與「防著一個不存在的問題」。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _geo():
    from helpers import geo
    return geo


ADDR = "批次查詢測試地址 BATCH-1"


def _seed(address, source, lat, lon, precision, created_at):
    """直接寫一列 `geocode_cache` —— **我要控制 `created_at` 才驗得了過期。**"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache WHERE address=? AND source=?",
                     (address, source))
        conn.execute(
            "INSERT INTO geocode_cache (address, source, lat, lon, precision,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (address, source, lat, lon, precision, created_at))
        conn.commit()
    finally:
        conn.close()


def _wipe(address):
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache WHERE address=?", (address,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clean(client, monkeypatch):
    """每一題從乾淨的兩層快取開始，並且**確定不會走 `min_source` 那條早退路**。

    ⚠️ `cached_only(min_source=SOURCE_GOOGLE)` 在有金鑰時會直接回 google 階
    （`geo.py:1210-1211`）—— 那條路 A 明著排除在這次範圍外，
    ⇒ 這裡一律用預設的 `min_source=None`，而且把金鑰關掉，**兩道都不碰它**。
    """
    geo = _geo()
    monkeypatch.setattr(geo, "_google_key_configured", lambda: False,
                        raising=False)
    geo._CACHE.clear()
    _wipe(ADDR)
    yield
    geo._CACHE.clear()
    _wipe(ADDR)


def _today_iso():
    from datetime import date
    return date.today().isoformat()


def _days_ago_iso(n):
    from datetime import date, timedelta
    return (date.today() - timedelta(days=n)).isoformat()


# ══════════════════════════════════════════════════════════════════════
# ① 挑選的順序由 `_STAGES` 決定，不是由 SQL 決定
# ══════════════════════════════════════════════════════════════════════

def test_batch_the_winner_is_picked_by_stage_order(clean):
    """🔴🔴 **四階都有快取時，回的是 `_STAGES` 裡最前面的那一階。**

    ☠️ 批次之後，`SELECT … WHERE source IN (?,?,?,?)` 的**列順序不保證** ——
    🔑 而若有人「優化」成直接用第一列，`GC3` 的 `min_source` 語意
    與「google 階優先」會**靜默改變**，而沒有一題會紅。
    📌 那是 `A9` 那個坑的形狀：**症狀是沒有症狀**。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    hit = geo.cached_only(ADDR)
    assert hit is not None, "兩階都有快取，而 `cached_only()` 回 None"
    assert hit.source == geo.SOURCE_GOOGLE, (
        f"回的是 `{hit.source}`，而 `_STAGES` 裡 google 排在 nominatim 前面。\n"
        "☠️ 那代表順序是別的東西決定的（SQL 的列順序？dict 的插入序？）—— \n"
        "🔑 而那會讓 `GC3` 的 `min_source` 語意靜默改變。")


def test_batch_the_yardstick_reordering_stages_changes_the_winner(clean):
    """📏 量尺：**把 `_STAGES` 的順序反過來 ⇒ 贏家要跟著變。**

    ☠️ 少了這一題，上一題在一個「**永遠回 google**」的實作下照樣全綠 ——
    🔑 而這一題證明它**真的在讀 `_STAGES`**。
    ⚠️ 不改產品碼：只換那個 tuple。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    original = list(geo._STAGES)
    try:
        geo._STAGES = tuple(reversed(original))
        geo._CACHE.clear()
        hit = geo.cached_only(ADDR)
    finally:
        geo._STAGES = tuple(original)
        geo._CACHE.clear()

    assert hit is not None and hit.source == geo.SOURCE_NOMINATIM, (
        f"把 `_STAGES` 反過來之後，回的仍然是 `{getattr(hit, 'source', None)}` ——\n"
        "☠️ 那代表挑選**沒有讀 `_STAGES`**，\n"
        "🔑 而上一題的綠證明不了任何事。")


def test_batch_sql_row_order_does_not_decide_the_winner(clean, monkeypatch):
    """⚙️ 反向控制：**把資料庫回來的順序倒過來 ⇒ 結果不可以變。**

    🔑 與上面那支量尺**成對**：
    ```
    量尺   改 _STAGES  ⇒ 結果**要**變   （證明它讀 _STAGES）
    本題   改 DB 順序  ⇒ 結果**不可**變（證明它不讀 DB 的順序）
    ```
    ☠️ **單獨任何一條都會被另一種實作繞過** —— 兩條合起來才釘得住「誰決定順序」。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    real_many = geo._cache_get_many

    def _reversed_many(address, sources):
        got = real_many(address, sources)
        # dict 保留插入序 ⇒ 反過來插一次，模擬「SQL 換了列順序」
        return {k: got[k] for k in reversed(list(got))}

    monkeypatch.setattr(geo, "_cache_get_many", _reversed_many)
    geo._CACHE.clear()

    hit = geo.cached_only(ADDR)
    assert hit is not None and hit.source == geo.SOURCE_GOOGLE, (
        f"把資料庫回來的順序倒過來之後，贏家變成 `{getattr(hit,'source',None)}` ——\n"
        "☠️ 那代表順序是 SQL 決定的，而 SQL 的列順序**不保證**。\n"
        "🔑 症狀會是「某天升級之後精度突然退回行政區」，而沒有人動過程式。")


# ══════════════════════════════════════════════════════════════════════
# ② 過期的那一列不可以遮住後面的階
# ══════════════════════════════════════════════════════════════════════

def test_batch_an_expired_row_does_not_mask_a_later_stage(clean):
    """🔴🔴 **google 階過期、nominatim 階有效 ⇒ 要回 nominatim 那一筆。**

    ☠️ 四階分開問時，過期的 google 會讓迴圈**繼續往下問** ——
    而批次之後若挑「第一列」，過期的 google 會被當成 google 階的答案
    ⇒ 回 `None` ⇒ **整個 `cached_only()` 回 None**，而後面明明有有效資料。
    🔑 症狀：**地圖上少一個點，而沒有人說為什麼。**
    """
    geo = _geo()
    old = geo.GEOCODE_CACHE_TTL_DAYS + 10
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _days_ago_iso(old))
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    hit = geo.cached_only(ADDR)
    assert hit is not None, (
        "google 階過期、nominatim 階有效，而 `cached_only()` 回 None ——\n"
        "☠️ 過期的那一列遮住了後面的階 ⇒ 地圖上少一個點。")
    assert hit.source == geo.SOURCE_NOMINATIM, (
        f"回的是 `{hit.source}` —— 而 google 那一列已經過期 "
        f"（{old} 天 ≥ TTL {geo.GEOCODE_CACHE_TTL_DAYS}）。\n"
        "☠️ 過期的快取被當成有效 ⇒ **地圖上的點停在舊座標**，而它不會報錯。")


def test_batch_a_fresh_first_stage_still_wins(clean):
    """⚙️ 反向控制①：**google 階沒過期 ⇒ 仍然要回 google。**

    ☠️ 少了這一題，一個「**永遠跳過 google**」的實作會讓上一題全綠 ——
    🔑 而那正好把 `GC1`／`A9` 想解決的事情反過來做。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    hit = geo.cached_only(ADDR)
    assert hit is not None and hit.source == geo.SOURCE_GOOGLE, (
        f"google 階是新的，而回的是 `{getattr(hit,'source',None)}`")


def test_batch_everything_expired_is_a_miss(clean):
    """⚙️ 反向控制②：**全部過期 ⇒ 回 `None`。**

    ☠️ 少了這一題，一個「過期照收」的實作會讓上面兩題全綠（它們只驗誰贏）——
    🔑 而那會讓 180 天的 TTL 完全失效，**症狀是點停在舊座標**。
    """
    geo = _geo()
    old = geo.GEOCODE_CACHE_TTL_DAYS + 10
    for src in (geo.SOURCE_GOOGLE, geo.SOURCE_NOMINATIM):
        _seed(ADDR, src, 25.0, 121.0, "rooftop", _days_ago_iso(old))

    assert geo.cached_only(ADDR) is None, (
        "所有階都過期了，而 `cached_only()` 仍然回了一筆 ——\n"
        "☠️ TTL 沒有生效 ⇒ 地圖上的點會停在舊座標，而它不會報錯。")


def test_batch_the_yardstick_shrinking_the_ttl_changes_the_answer(clean):
    """📏 量尺：**把 TTL 改小 ⇒ 同一列從「有效」變成「過期」。**

    ☠️ 少了這一題，上面三題在一個把 `180` 寫死在比較式裡的實作下照樣全綠 ——
    🔑 而這一題證明過期判斷**真的讀那個常數**。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _days_ago_iso(30))

    geo._CACHE.clear()
    assert geo.cached_only(ADDR) is not None, "30 天前的快取在 TTL=180 下應該有效"

    original = geo.GEOCODE_CACHE_TTL_DAYS
    try:
        geo.GEOCODE_CACHE_TTL_DAYS = 10
        geo._CACHE.clear()
        after = geo.cached_only(ADDR)
    finally:
        geo.GEOCODE_CACHE_TTL_DAYS = original
        geo._CACHE.clear()

    assert after is None, (
        "把 TTL 改成 10 天之後，30 天前那一列**仍然**被當成有效 ——\n"
        "☠️ 那代表過期判斷讀的不是 `GEOCODE_CACHE_TTL_DAYS`，\n"
        "🔑 而上面三題的綠證明不了任何事。")


# ══════════════════════════════════════════════════════════════════════
# ③ 記憶體層要逐階寫入 —— 否則第二次還是落到資料庫
# ══════════════════════════════════════════════════════════════════════

def test_batch_every_fetched_stage_lands_in_the_memory_cache(clean):
    """🔴 **一次 `cached_only()` 之後，撈回來的每一階都要在 `_CACHE` 裡。**

    ⚠️ 只把「贏的那一階」寫進記憶體的話，**答案完全正確** ——
    ☠️ 而其他階下一次還是落到資料庫，**那正是這一整件事要解決的成本**。
    🔑 **它只影響成本不影響答案 ⇒ 現有的題一個都守不到它。**
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    geo.cached_only(ADDR)

    for src in (geo.SOURCE_GOOGLE, geo.SOURCE_NOMINATIM):
        assert (ADDR, src) in geo._CACHE, (
            f"`{src}` 那一階撈回來了，而它沒有進記憶體快取。\n"
            "☠️ 下一次它還是會落到資料庫 —— **成本沒有省到**，\n"
            "🔑 而答案是對的，所以沒有別的題會紅。")


def test_batch_the_second_call_does_not_re_ask_the_stages_that_hit(
        clean, monkeypatch):
    """📏 量尺：**第二次呼叫不可以再問「已經命中過」的那幾階。**

    ## ⚠️ 我第一版斷言的是「第二次完全不碰資料庫」，而那是要求過頭

    ```
    A 的原話   「**撈回來的**每一個未過期的 (address, source) 都要在 _CACHE 裡」
    我寫成     「第二次呼叫時 DB 不再被碰」
    ⇒ 後者等於要求**連「這一階沒有列」也要快取起來**
    ```
    ☠️ 而那會讓**另一個行程**寫進來的新列被遮住 ——
    症狀是「別人補好了座標，而這台機器一直看不到」，
    📌 〈降級之後它還是會動〉：比現在這個成本難查得多。
    🔑 ⇒ **我的題要求了一個不該做的實作**，已收窄成 A 原本的那一句。


    🔑 觀測點是 `_cache_get_many` **被呼叫幾次**，不是「跑得快不快」——
    ☠️ 用時間量的話，就是 `test_gc8_a_known_miss_does_not_eat_the_time_budget`
    那一題的下場：**門檻挑得剛好，而 BelowNormal 下就紅**。
    📌 那一題 2026-09-22 擋下過一次打包，成因正是這一段程式。
    """
    geo = _geo()
    _seed(ADDR, geo.SOURCE_GOOGLE, 25.0, 121.0, "rooftop", _today_iso())
    _seed(ADDR, geo.SOURCE_NOMINATIM, 24.0, 120.0, "street", _today_iso())

    calls = []
    real_many = geo._cache_get_many
    monkeypatch.setattr(
        geo, "_cache_get_many",
        lambda address, sources: calls.append(tuple(sources))
        or real_many(address, sources))

    geo.cached_only(ADDR)
    assert calls, "第一次呼叫沒有去問資料庫（前提不成立）"
    first_asked = set(calls[0])
    assert geo.SOURCE_GOOGLE in first_asked, "第一次沒問 google 階（前提不成立）"

    calls.clear()
    geo.cached_only(ADDR)

    asked_again = set().union(*calls) if calls else set()
    hit_sources = {geo.SOURCE_GOOGLE, geo.SOURCE_NOMINATIM}
    re_asked = hit_sources & asked_again
    assert not re_asked, (
        f"第二次呼叫又去問了已經命中過的階：{sorted(re_asked)}\n"
        "☠️ 記憶體那一層沒有接住它們 ⇒ 每一次開地圖都重新付一次 DB 成本。")

    # 🔴 **而沒有命中的那幾階，第二次仍然會被問 —— 那是已知且未修的成本。**
    #
    # ```
    # 第一次問   google / tgos / nominatim / nominatim_district   ← 四個
    # 第二次問   tgos / nominatim_district                        ← 只剩沒有列的那兩個
    # ```
    # 🔑 `_cache_get_many()` **只回有列的來源** ⇒ 沒有列的那幾階不會進 `_CACHE`
    #    ⇒ 它們每一次請求都會被重新問一次。
    # ☠️ 而**一個「已知查不到」的地址四階都沒有列** ⇒ 它每次都還是一趟 DB 往返。
    #    批次把 4 次連線降成 1 次（省 4 倍），**而不是降到零**。
    # ⚠️ **我不主張在這裡快取「不存在」**：那會讓另一個行程寫進來的新列被遮住，
    #    而症狀是「別人補好了座標，而這台機器一直看不到」——
    #    📌 〈降級之後它還是會動〉，比現在這個成本難查得多。
    # ⇒ 這一條留在 `NEXT`（A 2026-09-22 已登記），**這裡只把它寫下來，不擋。**
    assert asked_again, (
        "第二次呼叫完全沒有問資料庫 —— 那與上面那段註解描述的行為不符。\n"
        "⚠️ 若是因為現在**連沒有列的來源也快取了**，"
        "請先讀那段註解：那會讓別的行程寫進來的新列被遮住。")
