"""第七個訊號 `tilesBlocked` —— **失敗偽裝成了成功**。

## ☠️ 事實（A 實測，不是推的）

OSM 正在封鎖這個 IP：

```
GET https://tile.openstreetmap.org/5/26/13.png
HTTP/1.1 200 OK                       ← **200**
Content-Length: 6987
x-blocked: Access denied. See https://operations.osmfoundation.org/policies/tiles/
```

回來的是**一張畫著「Access blocked」的 PNG**。

⇒ 它**繞過了我們所有的錯誤處理**：
- HTTP **200** ⇒ Leaflet 的 `tileerror` **永遠不觸發**
- 圖磚是 `<img>` 載的 ⇒ **JS 讀不到任何標頭**
- ⇒ **前端沒有任何辦法自己發現**

使用者看到的是一張**正常運作**的地圖，而每一格寫著 Access blocked。

> 🔑 **這比前六個訊號那一族更嚴重。**
> 那六個（`officeMissing`／`withoutLocation`／`googleMapsConfigured`／
> `geoEnabled`／雷達關著／被封鎖）至少都是「**沒有東西**」——
> **這一個是「有東西，而且是錯的」。**
> 「沒有東西」還會讓人懷疑；**「有東西」不會。**

## 📌 我釘的名字（A 沒指定，B 要改先講）

| 名字 | 形狀 |
|---|---|
| `geo.tiles_blocked()` | 回 `True`／`False`／**`None`**（模組層，patch 得到）|
| `geo.TILE_PROBE_URL` | 探測用的那一張圖磚 |
| `geo.TILE_PROBE_TIMEOUT_SECONDS` | **≤ 3**（T5）|
| `geo.TILE_PROBE_CACHE_SECONDS` | 快取時間（建議 3600，T4）|
| `/api/map/points` 回應鍵 `tilesBlocked` | T1 |

⚠️ `tiles_blocked` **必須走模組屬性** —— 否則 T6 patch 不掉，而測試會真的連 OSM
（NETGUARD 會在收尾時紅，那是今晚已經抓過兩次的形狀）。
"""
import time

import pytest

from helpers.settings import _set_setting

try:
    from helpers import geo
except Exception as exc:  # noqa: BLE001
    geo = None
    _GEO_ERR = repr(exc)

MAP_PATH = "/api/map/points"
BLOCKED_HEADER = "x-blocked"
BLOCKED_VALUE = ("Access denied. See "
                 "https://operations.osmfoundation.org/policies/tiles/")


def _geo(name=None):
    if geo is None:
        raise AssertionError(f"helpers/geo.py import 失敗：{_GEO_ERR}")
    if name and not hasattr(geo, name):
        raise AssertionError(
            f"helpers/geo.py 缺少 `{name}` —— 見本檔開頭〈我釘的名字〉")
    return getattr(geo, name) if name else geo


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


class _Resp:
    """假的圖磚回應。**永遠是 200** —— 那就是這件事的重點。"""

    def __init__(self, headers=None, delay=0.0):
        self.headers = headers or {}
        self._delay = delay
        self.status = 200

    def __enter__(self):
        if self._delay:
            time.sleep(self._delay)
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return b"\x89PNG\r\n\x1a\n" + b"0" * 6979   # 6987 bytes，跟實際一樣

    def getheader(self, name, default=None):
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default

    def info(self):
        return self

    def get(self, name, default=None):
        return self.getheader(name, default)


def _probe_returns(monkeypatch, headers=None, delay=0.0, boom=None):
    """換掉探測那一次的 `urlopen`。**T6：測試不可以真的連 OSM。**

    ⚠️ 換的是 `geo.urllib.request.urlopen` 而不是 `geo.tiles_blocked` ——
    後者會把**被測邏輯本身**一起換掉（今晚那一族的第七個實例）。
    """
    _geo("tiles_blocked")

    def _fake(req, *a, **kw):
        if boom:
            raise boom
        return _Resp(headers, delay)

    monkeypatch.setattr(_geo().urllib.request, "urlopen", _fake)
    # 每一題都從沒有快取的狀態開始，否則上一題的結果會漏過來
    _reset_cache(monkeypatch)


def _reset_cache(monkeypatch):
    """把探測快取清掉。

    ⚠️ 快取是 T4 要求的，而它同時會讓**每一題互相汙染** ——
    🔑 **一個為了正確性而存在的機制，會變成測試之間的隱形耦合。**
    """
    for name in ("_TILE_PROBE_CACHE", "_tile_probe_cache"):
        if hasattr(_geo(), name):
            monkeypatch.setattr(_geo(), name, None)
            return
    # 還沒有快取 ⇒ T4 會紅，那是它的事，不是這裡的事


# ══════════════════════════════════════════════════════════════════════
# T1／T2／T3／T7 · 三態
# ══════════════════════════════════════════════════════════════════════

def test_t3_blocked_header_means_true(monkeypatch):
    """🔴 T3：探測到 `x-blocked` ⇒ `True`。

    ⚠️ 回應是 **200**，內容是一張合法的 PNG ——
    **除了那個標頭之外，沒有任何地方看得出不對。**
    """
    _probe_returns(monkeypatch, {BLOCKED_HEADER: BLOCKED_VALUE})
    assert _geo("tiles_blocked")() is True, (
        "回應帶著 `x-blocked` 標頭，而探測說沒有被封鎖。\n"
        "⇒ 使用者會看到一張「正常」的地圖，每一格寫著 Access blocked。"
    )


def test_t7_no_blocked_header_means_false(monkeypatch):
    """🔴 T7 反向控制：**拿掉 `x-blocked` ⇒ 必須變 `False`**。

    ⚠️ 沒有這一題，一個 `def tiles_blocked(): return True` 的實作會讓 T3 全綠
    —— 而那會讓**每一台機器**都被告知「圖磚被封鎖了」，包含完全正常的那些。
    🔑 「偵測得到壞的」與「分得出好的」是兩件事。
    """
    _probe_returns(monkeypatch, {})
    assert _geo("tiles_blocked")() is False, (
        "沒有 `x-blocked` 標頭，而探測仍然說被封鎖了 —— "
        "那會讓每一台正常的機器都看到一則假警告"
    )


def test_t2_a_failed_probe_is_none_not_false(monkeypatch):
    """🔴🔴 T2：**探測失敗／逾時 ⇒ `None`，不可以是 `False`。**

    `False` 的意思是「**我確認過，可以用**」。
    探測根本沒成功的時候回 `False`，等於**宣稱確認過一件沒確認的事**。

    🔑 這就是 `null` ≠ `0` 那一條，而這次合併的後果特別具體：
    前端看到 `false` 會**什麼都不說**，而使用者照樣看到滿版的 Access blocked。
    ⚠️ **三態合併之後，「不知道」會被講成「沒問題」。**
    """
    _probe_returns(monkeypatch, boom=OSError("連不上"))
    assert _geo("tiles_blocked")() is None, (
        "探測失敗了，而它回的是 False —— 那等於宣稱「我確認過，可以用」。\n"
        "🔑 `None` ＝不知道，`False` ＝確認可用。**兩者不可以合併。**"
    )


def test_t5_a_slow_probe_times_out_into_none(monkeypatch):
    """🔴 T5：探測**不可以拖慢回應** —— 逾時上限 ≤ 3 秒，逾時回 `None`。

    ⚠️ 而逾時要回 `None` **不是** `False`（T2 同一條）。
    """
    timeout = _geo("TILE_PROBE_TIMEOUT_SECONDS")
    assert timeout <= 3, (
        f"探測逾時設成 {timeout} 秒 —— 每一次開地圖頁都會等這麼久"
    )
    _probe_returns(monkeypatch, boom=TimeoutError("探測逾時"))
    assert _geo("tiles_blocked")() is None, "逾時應該回 None（不知道），不是 False"


def test_t4_the_probe_result_is_cached(monkeypatch):
    """🔴 T4：**探測結果要快取，不可以每次開頁面都對 OSM 打一次。**

    🔑 而理由不是效能：**「每次開頁面就打一次」正是被封鎖的那一類行為** ——
    ⚠️ 用一個探測去問「我是不是被封鎖了」，而那個探測本身在製造被封鎖的理由。
    """
    cache_seconds = _geo("TILE_PROBE_CACHE_SECONDS")
    assert cache_seconds >= 600, (
        f"探測快取只有 {cache_seconds} 秒 —— 太短，等於每次開頁面都打一次"
    )
    calls = []

    def _fake(req, *a, **kw):
        calls.append(req)
        return _Resp({})

    _reset_cache(monkeypatch)
    monkeypatch.setattr(_geo().urllib.request, "urlopen", _fake)
    _geo("tiles_blocked")()
    first = len(calls)
    assert first == 1, f"第一次應該探測一次，實際 {first} 次（前提不成立）"
    for _ in range(5):
        _geo("tiles_blocked")()
    assert len(calls) == first, (
        f"連續問了 6 次，而它對 OSM 打了 {len(calls)} 次 —— 結果沒有被快取。\n"
        "⇒ 用來偵測「有沒有被封鎖」的探測，自己在製造被封鎖的理由。"
    )


# ══════════════════════════════════════════════════════════════════════
# T1 · 端點要把它講出來
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("headers,expected,label", [
    ({BLOCKED_HEADER: BLOCKED_VALUE}, True, "被封鎖"),
    ({}, False, "確認可用"),
])
def test_t1_the_map_endpoint_reports_the_signal(
        client, make_user, monkeypatch, headers, expected, label):
    """🔴 T1：`/api/map/points` 回應要含 `tilesBlocked`，而且值要對。

    ⚠️ **「有這個鍵」與「這個鍵的值是對的」是兩件事** ——
    一個永遠回 `false` 的實作會通過「有這個鍵」那一半，
    **而那正是最糟的值**（宣稱確認過可以用）。
    """
    _set_setting("company_profile", {"name": "測試", "address": ""})
    _probe_returns(monkeypatch, headers)
    hdr = _auth(client, make_user)
    r = client.get(MAP_PATH, headers=hdr)
    assert r.status_code == 200, f"{MAP_PATH} 回 {r.status_code}：{r.text[:300]}"
    body = r.json()
    assert "tilesBlocked" in body, (
        f"地圖端點沒有 `tilesBlocked`。實際：{sorted(body)}\n"
        "⇒ 前端沒有任何辦法自己發現圖磚被擋（HTTP 200＋JS 讀不到標頭）。"
    )
    assert body["tilesBlocked"] is expected, (
        f"探測情境是「{label}」，而端點回 {body['tilesBlocked']!r}"
    )


def test_t1b_an_unknown_probe_is_reported_as_null(client, make_user, monkeypatch):
    """T1 的第三態：探測失敗 ⇒ 端點回 **`null`**，不是 `false`、也不是漏掉那個鍵。

    ⚠️ **漏掉那個鍵**與 **`null`** 在 JS 裡都是 falsy ⇒ 前端若寫
    `if (body.tilesBlocked)` 就把三態壓成兩態了。
    🔑 **端點這一側要把三態講清楚，前端才有機會做對。**
    """
    _set_setting("company_profile", {"name": "測試", "address": ""})
    _probe_returns(monkeypatch, boom=OSError("連不上"))
    hdr = _auth(client, make_user)
    body = client.get(MAP_PATH, headers=hdr).json()
    assert "tilesBlocked" in body, "探測失敗時那個鍵不可以消失"
    assert body["tilesBlocked"] is None, (
        f"探測失敗，而端點回 {body['tilesBlocked']!r} —— 應為 null（不知道）"
    )


def test_t6_the_probe_never_really_talks_to_osm(client, make_user, monkeypatch):
    """T6：**測試裡的探測不可以真的連 OSM。**

    📌 這一題本身就是證明 —— 它跑完而 NETGUARD 沒有在收尾出聲，
    就代表探測確實被 patch 掉了。
    ⚠️ 而它**不是多餘的**：今晚 NETGUARD 已經抓到兩次「換了上游、沒換下游」
    （`_spy_fetch` 沒換 `fetch_detail`、`_run` 沒換 `fetch_detail`），
    🔑 **這是第三個會出現同一個形狀的地方。**
    """
    _set_setting("company_profile", {"name": "測試", "address": ""})
    _probe_returns(monkeypatch, {})
    hdr = _auth(client, make_user)
    for _ in range(3):
        assert client.get(MAP_PATH, headers=hdr).status_code == 200
    # NETGUARD 在收尾時斷言「沒有任何真實連線嘗試」——這一題靠它背書
