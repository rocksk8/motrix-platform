"""地圖端點的測試隔離：**關掉圖磚探測。**

## ☠️ 為什麼需要它：`/api/map/points` 每一次都會真的對外連線

那支端點會呼叫 `geo.tiles_blocked()`，而它去打 `tile.openstreetmap.org`
⇒ **任何碰到那個端點的測試都會是一次真實的對外請求。**

📌 抓到它的是 `conftest` 的 NETGUARD（在 teardown 斷言），
⚠️ **而它只報在第一題** —— 探測結果有快取
⇒ **後面那些題看起來很乾淨，只是第一題已經替它們打過了。**
🔑 〈證據的適用範圍〉：「我沒撞到」不等於「做法沒問題」。

## 為什麼抽出來

2026-09-22：**第四個檔**各自複製同一行 `monkeypatch.setattr(geo,
"tiles_blocked", ...)`。〈修作法不要修結果〉的判準是
「這個修法會不會讓**第五次**不可能發生」——
一行一行抄下去的答案是「不會」。

⚠️ **既有三個檔這一輪不改**（`test_map_own_vendors`／`test_map_user_location`／
`test_map_customers_suppliers`）：它們是綠的，而現在正要打包，
**churn 的風險大於重複的成本**。下一輪收掉。
📌 這句寫在這裡而不是只存在我腦袋裡 —— 否則它就是一筆看不見的欠帳。
"""
import pytest

from helpers import geo


@pytest.fixture()
def no_tile_probe(monkeypatch):
    """讓 `geo.tiles_blocked()` 回 `None`（不知道），**不發任何請求**。

    ⚠️ 刻意回 `None` 而不是 `False`（探過、可以用）——
    回 `False` 的話，任何「**三態被壓成兩態**」的缺陷在用到這個 fixture 的
    檔案裡都會看不見。
    🔑 假貨要保留被測的那個維度，其餘才可以假。
    """
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
