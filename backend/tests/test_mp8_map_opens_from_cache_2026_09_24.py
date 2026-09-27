# -*- coding: utf-8 -*-
"""`MP8` · 開地圖不再同步查外部定位；回應快取；前端一次抓完。

使用者逐字：「地圖模組每次使用者都要載入一次，讓流量很快卡死」。
權威原文：`HANDOFF-PENDING-2026-09-23.md`「MP 追加」MP8 ＋ A 裁示：

```
請求路徑只讀快取，不向外部查定位；未定位的交給背景預熱
伺服器回應快取：鍵＝使用者可見的 dataset 組合（權限算進鍵），短 TTL，資料異動時失效
題：開地圖期間外部定位呼叫＝0（替身計數）；同一個人連開兩次，第二次命中快取
界線：不可以改變 dataset 權限——A 看得到的點不可以回給 B
```
⚙️ 觀測點：`geo.geocode`（最底層的對外查詢）與 `geo.locate_cached` 的呼叫次數；
回應標頭 `X-Map-Cache: hit|miss`。
"""
import pytest

from helpers import geo

MAP = "/api/map/points?sources=tenders,customers"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    from tests._map_cache_warm import clear_map_response_cache
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "_CACHE", {})
    clear_map_response_cache()
    yield
    clear_map_response_cache()


def _spy(monkeypatch):
    calls = []
    real_locate = geo.locate_cached

    def _geocode(address, *a, **kw):
        calls.append(("geocode", address))
        return ((24.15, 120.67), None)

    def _locate(address, manual_coord=None):
        if manual_coord is None:
            calls.append(("locate_cached", address))
        return real_locate(address, manual_coord)

    monkeypatch.setattr(geo, "geocode", _geocode)
    monkeypatch.setattr(geo, "locate_cached", _locate)
    return calls


def _seed_tender(case_no, org, location):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location) VALUES (?,?,?,?)",
                     (case_no, case_no + " 標案", org, location))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_mp8_opening_the_map_makes_no_external_geocode_call(client, make_user, monkeypatch):
    _seed_tender("MP8-001", "MP8 測試機關", "台中市西屯區")
    calls = _spy(monkeypatch)
    hdr = _hdr(client, make_user, "mp8_a")
    r = client.get(MAP, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    print("MP8 實測：開地圖對外呼叫 %d 次；pendingGeocode=%s" % (len(calls), body.get("pendingGeocode")))
    assert calls == [], "開地圖的請求對外定位了：%r" % calls
    assert body["pendingGeocode"] >= 1, "沒查過的地址要算「待定位」交給背景，不可以靜默消失"


def test_mp8_the_same_person_opening_twice_hits_the_cache(client, make_user, monkeypatch):
    _seed_tender("MP8-002", "MP8 機關二", "台中市南屯區")
    hdr = _hdr(client, make_user, "mp8_b")
    a = client.get(MAP, headers=hdr)
    b = client.get(MAP, headers=hdr)
    print("MP8 實測：第一次 %s／第二次 %s" % (a.headers.get("X-Map-Cache"), b.headers.get("X-Map-Cache")))
    assert (a.headers.get("X-Map-Cache"), b.headers.get("X-Map-Cache")) == ("miss", "hit")
    assert a.json()["points"] == b.json()["points"]


def test_mp8_a_data_change_invalidates_the_cache(client, make_user, monkeypatch):
    geo._cache_put(geo.GeoResult(coord=(24.2, 120.6), precision="street",
                                 source="nominatim", address="MP8 已定位機關"))
    _seed_tender("MP8-003", "MP8 已定位機關", "")
    hdr = _hdr(client, make_user, "mp8_c")
    first = client.get(MAP, headers=hdr)
    _seed_tender("MP8-004", "MP8 已定位機關", "")
    second = client.get(MAP, headers=hdr)
    names = sorted(p.get("caseNo") for p in second.json()["points"])
    assert second.headers.get("X-Map-Cache") == "miss", "資料變了還回快取"
    assert names == ["MP8-003", "MP8-004"], names
    assert len(first.json()["points"]) == 1


def test_mp8_the_cache_never_hands_one_users_points_to_another(client, make_user, monkeypatch):
    """權限算進鍵：看得到標案的人先開（進快取），看不到的人再開 ⇒ 不可以拿到標案點。"""
    geo._cache_put(geo.GeoResult(coord=(24.2, 120.6), precision="street",
                                 source="nominatim", address="MP8 權限機關"))
    _seed_tender("MP8-005", "MP8 權限機關", "")
    boss = _hdr(client, make_user, "mp8_boss")
    assert len(client.get(MAP, headers=boss).json()["points"]) == 1
    clerk = _hdr(client, make_user, "mp8_clerk", role="admin", modules=["customers"])
    r = client.get(MAP, headers=clerk)
    tenders = [p for p in r.json()["points"] if p.get("sourceKey") == "tenders"]
    skipped = [s for s in r.json()["sources"] if s["source"] == "tenders"]
    print("MP8 實測：沒有標案權限的人 ⇒ 快取 %s、標案點 %d、skipped %r"
          % (r.headers.get("X-Map-Cache"), len(tenders), skipped and skipped[0].get("skipped")))
    assert tenders == [], "沒有標案權限的人從快取拿到了標案點：%r" % tenders
    assert skipped and skipped[0]["skipped"] == "no_permission"


def test_mp8_the_user_distance_is_computed_per_request_not_cached(client, make_user, monkeypatch):
    geo._cache_put(geo.GeoResult(coord=(24.2, 120.6), precision="street",
                                 source="nominatim", address="MP8 距離機關"))
    _seed_tender("MP8-006", "MP8 距離機關", "")
    hdr = _hdr(client, make_user, "mp8_dist")
    near = client.get(MAP, headers=dict(hdr, **{"X-Map-Position": "24.2,120.6,30"}))
    far = client.get(MAP, headers=dict(hdr, **{"X-Map-Position": "25.03,121.56,30"}))
    d1 = near.json()["points"][0]["distanceFromUserKm"]
    d2 = far.json()["points"][0]["distanceFromUserKm"]
    print("MP8 實測：%s 距離 %s km／%s 距離 %s km" % (near.headers.get("X-Map-Cache"), d1,
                                                  far.headers.get("X-Map-Cache"), d2))
    assert far.headers.get("X-Map-Cache") == "hit", "量尺：第二次要命中快取，這一題才量得到東西"
    assert d1 is not None and d2 is not None and d1 < 1 and d2 > 100, (d1, d2)


# ══════════════════════════════════════════════════════════════════════
# 前端：一次抓完，切換勾選不重抓
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests._map_tiles import block_tiles  # noqa: E402
from tests._e2e_login import inject_login as _login  # noqa: E402

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


@pytest.mark.e2e
def test_mp8_toggling_a_dataset_filters_locally_without_refetching(live_server, make_user, e2e_browser):
    import json as _json
    u, p = make_user(username="mp8_page", role="superadmin")
    body = _json.dumps({"points": [
        {"dataset": "tenders", "sourceKey": "tenders", "lat": 24.1, "lon": 120.6, "name": "標案甲",
         "precision": "street"},
        {"dataset": "customers_delivery", "sourceKey": "customers", "lat": 24.2, "lon": 120.7,
         "name": "客戶乙", "precision": "street"}],
        "sources": [{"source": "tenders", "skipped": None, "count": 1, "note": "1 筆標案"},
                    {"source": "customers", "skipped": None, "count": 1, "note": "客戶 1 筆"}],
        "locations": [], "pendingGeocode": 0, "unresolvableGeocode": 0})
    asked = []
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    block_tiles(page)   # 地圖圖磚不連外（conftest._browser_netguard）
    def _serve(route):
        asked.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=body)
    page.route("**/api/map/points*", _serve)
    _login(page, live_server, u, p)
    page.goto(live_server + "/pages/map.html")
    page.wait_for_function("() => %s.info && %s.info.points.length === 2" % (_D, _D),
                           timeout=15000)
    n0 = len(asked)
    page.uncheck('input[type="checkbox"][value="tenders"]')
    page.wait_for_timeout(300)
    shown = page.evaluate("() => %s.view.points.map(p => p.name)" % _D)
    print("MP8 頁面實測：取消「標案」後請求數 %d → %d、畫面點 %r；請求網址 %r"
          % (n0, len(asked), shown, asked[:1]))
    assert len(asked) == n0, "切換勾選又向伺服器重抓了"
    assert shown == ["客戶乙"], shown
    assert "sources=tenders,customers,suppliers" in asked[0], "第一次就要一次抓完全部來源"
    assert page.locator('button:has-text("繼續定位")').count() == 0, "「繼續定位」鈕應該拿掉"
