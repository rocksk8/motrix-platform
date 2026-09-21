"""地圖：把有地址的東西畫在同一張圖上。**共用能力，不是標案雷達的一部分。**

2026-09-21 使用者裁示：「**我即便沒有在雷達內，也要能用地圖**」。

## 🔴 這不是改個名字

搬家之前：`/api/tender-radar/map`、`_require_radar()`、跟著 `radar_on()`。
⇒ **沒有雷達模組權限的人叫不到地圖；雷達一關，地圖跟著死。**
而那牴觸模組化原則：**共用能力要下沉，L2 功能模組之間不可相依。**
**地圖是共用能力，標案只是它的其中一個資料來源。**

## ⚠️ 權限：端點對「已登入」開放，**資料來源各自過濾**

`require_any_module` 只有 superadmin 直通（`helpers/auth.py:148`），
所以把整個端點綁在 `map` 這個 key 上，會讓「沒有雷達也能用地圖」變成
「**沒有地圖 key 也不能用地圖**」——換了一個名字的同一個問題。

⇒ 端點只要求登入，**而每一個資料來源自己檢查自己的權限**：
沒有雷達模組的人看得到地圖，**只是上面沒有標案點**。
🔑 而那個「沒有」**必須說出來**（`sources` 欄位），不可以只是少一層點——
☠️ 「你沒有權限看標案」與「今天沒有標案」在畫面上都是一張沒有點的地圖，
而那是今天第五個長成那個樣子的成因。
"""
from fastapi import APIRouter, Header

from db import get_db
from helpers import _require_user
from helpers import geo
from helpers import tender_source

router = APIRouter()

#: 地圖自己的模組 key。**刻意不沿用 `tender_radar`** ——
#: 沿用的話「不在雷達內也能用地圖」這件事就沒有地方成立。
#: 📌 它管的是**側邊欄入口**，不是這個端點的守衛（見檔頭〈權限〉）。
MAP_MODULE_KEY = "map"


def _may_see_tenders(user) -> bool:
    if (user or {}).get("role") == "superadmin":
        return True
    mods = (user or {}).get("modules") or []
    if isinstance(mods, str):
        import json
        try:
            mods = json.loads(mods)
        except (TypeError, ValueError):
            mods = []
    return "tender_radar" in mods


@router.get("/api/map/points")
def map_points(sources: str = "tenders", authorization: str = Header(None)):
    """地圖上的點，以及**所有「為什麼這裡是空的」的理由**。

    ## ☠️ 這個畫面有五個成因會長成同一個樣子（一張乾淨、沒有點的地圖）
    | 成因 | 訊號 |
    |---|---|
    | 標案沒有地點資訊 | `withoutLocation` |
    | 辦公室地址沒填 | `officeMissing` |
    | 沒有 Google 金鑰（附近廠商） | `googleMapsConfigured` |
    | 地理查詢沒開 / 被對方封鎖 | `geoEnabled` |
    | **沒有那個來源的權限** | `sources[].skipped` |
    🔑 **每一個都必須有自己的訊號**，不能靠使用者看圖分辨——
    處置完全不同，而少幾個點跟「那些東西不存在」長得一模一樣，
    **而且沒有人會報修。**

    📌 `sources` 目前只實作 `tenders`。其餘（`contractors`／`vendor_contractors`／
    `shipping_notes`／`completion_notes` 都有 `address` 欄位）**留介面不實作**——
    使用者叫停過範圍，不要一次做完。
    """
    user = _require_user(authorization)
    wanted = [s.strip() for s in (sources or "").split(",") if s.strip()]

    profile = _company_profile()
    office_address = (profile.get("address") or "").strip()
    api_key = (profile.get("google_maps_api_key") or "").strip()

    office = None
    if office_address:
        coord, _err = geo.geocode_cached(office_address)
        if coord:
            office = {"address": office_address, "lat": coord[0], "lon": coord[1]}

    points, without_location, source_info = [], 0, []
    if "tenders" in wanted:
        if not _may_see_tenders(user):
            # 🔴 **說出來，不要只是少一層點。**
            source_info.append({"source": "tenders", "skipped": "no_permission",
                                "note": "沒有標案雷達模組權限，地圖上不會顯示標案"})
        else:
            pts, missing = _tender_points(office)
            points += pts
            without_location += missing
            source_info.append({"source": "tenders", "skipped": None,
                                "count": len(pts), "withoutLocation": missing})

    return {
        "office": office,
        "officeMissing": not office_address,
        "points": points,
        "withoutLocation": without_location,
        "googleMapsConfigured": bool(api_key),
        # ⚠️ 地理查詢關著時，**已填的地址也定位不到** ⇒ 距離全是 null。
        # 不講的話使用者會以為地址填錯了。
        "geoEnabled": geo.geo_on(),
        # 🔴 第七個訊號，而它跟前六個不同級：前六個是「沒有東西」，
        # 這個是「**有東西而且是錯的**」——OSM 封鎖的回應是 HTTP 200 ＋
        # 一張寫著 Access blocked 的圖 ⇒ 瀏覽器不觸發 error、JS 讀不到標頭
        # ⇒ **前端沒有任何辦法自己發現。** 只有後端讀得到那個標頭。
        # ⚠️ 三態：True 被擋／False 探過可以用／**None 不知道**。
        "tilesBlocked": geo.tiles_blocked(),
        "sources": source_info,
    }


def _company_profile():
    from helpers.settings import _get_setting
    return {**(_get_setting("company_profile", {}) or {})}


def _tender_points(office):
    """標案來源。回 `(points, 沒有地點的筆數)`。

    ⚠️ **雷達關著時這裡照常跑**：它讀的是資料庫裡已經抓回來的標案，
    **不對外連線**。開關管的是「要不要去抓」，不是「能不能看已經抓到的」。
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT case_no, name, org, location, budget, deadline, url "
            "FROM tenders ORDER BY id DESC").fetchall()
    finally:
        conn.close()

    points, missing = [], 0
    for r in rows:
        place = (r["location"] or "").strip()
        if not place:
            missing += 1
            continue
        coord, _err = geo.geocode_cached(place)
        if not coord:
            # ⚠️ 一筆定位失敗不可以拖垮其他筆，而它要歸到「沒有地點」那一欄
            # ——使用者至少看得到它存在，而不是它不存在。
            missing += 1
            continue
        points.append({
            "source": "tenders",
            "caseNo": r["case_no"], "name": r["name"], "org": r["org"],
            "location": place, "lat": coord[0], "lon": coord[1],
            "budget": r["budget"], "deadline": r["deadline"], "url": r["url"],
            "distanceKm": (round(geo.haversine_km((office["lat"], office["lon"]),
                                                  coord), 1)
                           if office else None),
        })
    return points, missing


__all__ = ["router", "MAP_MODULE_KEY"]
