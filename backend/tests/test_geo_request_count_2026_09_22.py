"""§3o · A16：退階路徑對 Nominatim 的**請求次數**。

> D 用計數器實測（不是讀碼推的）：
> 冷快取＋查不到的地址 ⇒ **3 次**，而正確是 **2 次**。

## 成因（讀 `helpers/geo.py` 確認過）

```
locate_cached(address)
  ├─ 自己跑完整個梯子：_run_stage("_locate_nominatim", address)   ← 第 1 次
  └─ 全部 miss ⇒ 呼叫 locate(address)
       ├─ locate() 又從第一階把梯子重跑一遍                        ← 第 2 次（浪費）
       └─ 才退到行政區                                             ← 第 3 次
```

## ☠️ 它是常態路徑，不是邊角

那一次浪費**只發生在「查不到」的地址上** ——
🔴 **而沒有 Google 金鑰的機器上，每一個門牌地址都是查不到的**
（§3o 的起因就是這件事：Nominatim 認不得台灣的路名與門牌）。

代價不是慢 1.1 秒：
🔑 **重複查詢正是 Nominatim 封 IP 的理由**，而這個專案已經在防被封
（`tilesBlocked` 三態）。
☠️ 被封之後的樣子：**地圖上沒有點、而 `geoEnabled` 仍然是 `true`**
⇒ **看起來像使用者地址填錯。**

## ⚠️ 觀測層級：我數的是 `_locate_nominatim` 的呼叫，不是 HTTP 封包

那一層是「**對同一個地址查了幾次**」，正是這一條要防的東西。
📌 而我把它寫出來，不留給別人猜：**如果哪天 `_locate_nominatim` 自己
變成一次發兩個請求，這個計數器看不到。** 那是另一條題目。
"""
import pytest

from helpers import geo

#: 查不到的門牌（§3o 實測過 Nominatim 認不得它），與它的行政區。
UNFINDABLE = "台中市西屯區台灣大道三段99號"
ITS_DISTRICT = "台中市西屯區"

#: 查得到的行政區（§3o 實測過）。
FINDABLE = "台中市梧棲區"

_COORD = (24.2549239, 120.5316259)


@pytest.fixture()
def nominatim_calls(client, monkeypatch):
    """把三階都換成假的，並**記下每一次 Nominatim 被問到的地址**。

    ⚠️ Google／TGOS 也要換掉：真實環境沒有金鑰時它們回 `None`，
    而**「沒有金鑰」與「查不到」在計數上長得一樣** ——
    不換的話，這一題會依賴開發機剛好沒設金鑰，
    🔑 而那是〈證據的適用範圍〉：**「我沒撞到」不等於「做法沒問題」。**
    """
    calls = []

    def _nominatim(address, **_kw):
        calls.append(address)
        if address in (FINDABLE, ITS_DISTRICT):
            return (_COORD, geo.PRECISION_DISTRICT)
        return None

    monkeypatch.setattr(geo, "_locate_google", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_tgos", lambda *a, **kw: None)
    monkeypatch.setattr(geo, "_locate_nominatim", _nominatim)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    _cold_cache(monkeypatch)
    return calls


def _cold_cache(monkeypatch):
    """把兩層快取都清空：記憶體 `_CACHE` ＋ 資料庫 `geocode_cache`。

    ⚠️ 只清其中一層的話，A16b／A16c 會量到上一題留下的東西 ——
    而那個污染的方向是**次數變少**，也就是**往綠的那一邊**。
    """
    monkeypatch.setattr(geo, "_CACHE", {})
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM geocode_cache")
        conn.commit()
    finally:
        conn.close()


def test_a16_an_address_that_cannot_be_found_costs_two_requests_not_three(
        nominatim_calls):
    """🔴 A16：冷快取＋查不到的地址 ⇒ 對 Nominatim **2 次，不是 3 次**。

    正確的兩次是：**① 問完整地址（沒有）② 問行政區（有）**。
    第三次是 `locate_cached` 與 `locate` **各自把梯子跑了一遍**。

    📌 斷言連**問了哪些地址**一起印出來 —— 只印次數的話，
    「3 次」與「3 次而且其中兩次一模一樣」讀起來一樣，
    而後者才說得出成因。
    """
    result = geo.locate_cached(UNFINDABLE)

    assert result.coord, (
        f"退階之後應該拿得到行政區座標，實際：{result!r}\n"
        "⇒ 這一題的前提不成立（假貨接錯了？）"
    )
    assert len(nominatim_calls) == 2, (
        f"對 Nominatim 發了 {len(nominatim_calls)} 次請求：{nominatim_calls}\n"
        "⇒ 正確是 2 次（完整地址 ✗ → 行政區 ✓）。\n"
        "☠️ 重複的那一次來自 `locate_cached` 全部 miss 之後呼叫 `locate()`，"
        "而 `locate()` 又從第一階把整個梯子重跑一遍。\n"
        "🔑 重複查詢正是 Nominatim 封 IP 的理由，而被封之後的樣子是"
        "「地圖上沒有點、`geoEnabled` 仍然是 true」—— 看起來像地址填錯。"
    )
    assert nominatim_calls[0] == UNFINDABLE, (
        f"第一次應該問完整地址，實際問了 {nominatim_calls[0]!r}"
    )
    assert nominatim_calls[-1] == ITS_DISTRICT, (
        f"最後一次應該問行政區 {ITS_DISTRICT!r}，實際 {nominatim_calls[-1]!r}"
    )


def test_a16b_an_address_that_is_found_costs_one_request(nominatim_calls):
    """🔴 A16b 反向控制：冷快取＋**查得到**的地址 ⇒ **1 次**。

    ☠️ 少了這一題，一個「**永遠回 2**」的判準會讓 A16 綠 ——
    例如把退階整個拿掉（那樣查不到的地址會是 1 次…）或把計數器接錯層。
    🔑 **兩題合起來才證明那個計數器真的在動**：
    1 次與 2 次的差別必須來自**輸入**，不是來自常數。
    """
    result = geo.locate_cached(FINDABLE)

    assert result.coord, f"這個地址應該查得到：{result!r}"
    assert len(nominatim_calls) == 1, (
        f"查得到的地址發了 {len(nominatim_calls)} 次請求：{nominatim_calls}\n"
        "⇒ 第一階就命中，不該有第二次。"
    )


def test_a16c_a_cached_address_costs_nothing(nominatim_calls):
    """🔴 A16c：快取命中 ⇒ **0 次**。

    📌 這一題同時是前兩題的量尺：如果快取根本沒在寫，
    A16／A16b 量到的次數會是「每一次都重查」，
    而它們**仍然可能剛好等於 2 與 1**。
    ⚠️ 那種巧合不會自己現形，要有一題專門去撞它。
    """
    first = geo.locate_cached(FINDABLE)
    assert first.coord, f"前提不成立：第一次就查不到 {first!r}"
    assert nominatim_calls, "前提不成立：第一次一個請求都沒發"

    nominatim_calls.clear()
    second = geo.locate_cached(FINDABLE)

    assert second.coord == first.coord, (
        f"第二次拿到不同的座標：{first.coord} vs {second.coord}"
    )
    assert nominatim_calls == [], (
        f"快取命中之後仍然發了 {len(nominatim_calls)} 次請求："
        f"{nominatim_calls}\n"
        "⇒ 那表示快取沒有寫進去，或者鍵對不上。"
    )


def test_a16d_both_entry_points_still_fall_back_to_the_district(
        nominatim_calls):
    """🔴 A16d：**`locate()` 與 `locate_cached()` 各自都要退到行政區。**

    ## ⚠️ 這一題防的是「修 A16 的那次重構」

    D 建議的修法是：`locate_cached` 不要呼叫 `locate()`，
    把「退到行政區」抽成一個函式，兩邊都叫它。

    ☠️ 而抽出來之後，**`locate()` 的退階行為就只剩一個呼叫者了** ——
    如果只有 `locate_cached` 那一條路徑有測試，
    `locate()` 直接被呼叫時退不退階**沒有人知道**。
    🔑 〈兩個都對而路不存在〉：**我們會用一次重構製造一個新的斷點。**
    📌 D 自己提出了這個後果，這一題是照它做的。
    """
    got_cached = geo.locate_cached(UNFINDABLE)
    assert got_cached.coord, (
        f"`locate_cached` 沒有退到行政區：{got_cached!r}"
    )

    nominatim_calls.clear()
    got_plain = geo.locate(UNFINDABLE)
    assert got_plain.coord, (
        f"`locate()` 直接被呼叫時沒有退到行政區：{got_plain!r}\n"
        "⇒ 兩個入口都要能退階，不可以只有其中一個有這個行為。"
    )
    assert got_plain.coord == got_cached.coord, (
        f"兩個入口退出來的座標不一樣："
        f"{got_cached.coord} vs {got_plain.coord}"
    )
