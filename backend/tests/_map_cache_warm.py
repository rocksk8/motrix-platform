# -*- coding: utf-8 -*-
"""`MP8` 之後，開地圖的請求**只讀定位快取**（沒查過的交給背景預熱，不當場對外查）。

既有的地圖題用一張「查表替身」頂替 `geo.locate_cached`，驗的是**定位之後**的邏輯
（機關名稱優先、行政區退路、最近據點、距離、計數……）。那些邏輯沒有變，
變的只是「查表的結果從哪一條路進來」——現在是快取。

⇒ `serve_from_fake()`：讓快取＝同一張查表，等同「背景預熱已經跑完」。
   查表裡有的 ⇒ 快取命中；查表裡沒有的 ⇒ 「查過而查不到」（與改版前的計數一致）。
📌 「開地圖期間對外定位 0 次」由 `test_mp8_*` 用**真的** `cached_only` 證明，不靠這一支。
"""
from helpers import geo


def serve_from_fake(monkeypatch, fake):
    def _cached_only(address, min_source=None):
        r = fake(address)
        return r if (r is not None and r.coord) else None

    def _missed(address):
        r = fake(address)
        return r is None or not r.coord

    monkeypatch.setattr(geo, "cached_only", _cached_only)
    monkeypatch.setattr(geo, "geocode_missed_recently", _missed)
    clear_map_response_cache()


def clear_map_response_cache():
    """回應快取是模組層級的；測試之間的資料庫每題都是新的，而替身換了資料庫不會變
    ⇒ 指紋可能相同而內容不同，每題開始先清掉。"""
    from routers import map_points
    # ⚠️ 改版前的版本沒有回應快取——沒有就不用清（讓「HEAD 上先紅」紅在產品上，不是紅在這裡）。
    if not hasattr(map_points, "_RESP_CACHE"):
        return
    with map_points._RESP_LOCK:
        map_points._RESP_CACHE.clear()
