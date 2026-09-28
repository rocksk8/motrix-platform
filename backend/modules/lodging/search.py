# -*- coding: utf-8 -*-
"""附近旅宿的查詢、紀錄、詢價、比較（只查本機快照，不對外連線）。

- 距離：伺服器端 haversine（直線距離，不呼叫任何距離服務）。
- 價格：官方「參考最低／最高房價」（`price_kind="official_reference"`，業者登記值，非即時）與人工詢價（`manual`）。
  錯值（< PRICE_SANE_MIN 或 > PRICE_SANE_MAX）⇒ `price_suspect=True`、不參與價格排序，原值照回（畫面灰字，LG-S4）。
- 中心點來源是 Google ⇒ 存紀錄時**座標與距離一律不寫**（LG-M2；SST §6.3 lat/lng 最多 30 天，而 T1 會進永久保留的備份）。
"""
import json
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from modules.lodging import source as lodging_source

PRICE_SANE_MIN = 300
PRICE_SANE_MAX = 100_000
RADII_M = (1000, 3000, 5000, 10000)
DEFAULT_RADIUS_M = 3000
KIND_CLASSES = {"hotel": lodging_source.HOTEL_CLASSES, "homestay": lodging_source.HOMESTAY_CLASSES}
QUOTE_UNITS = {"per_night": "每晚", "per_person": "每人"}
QUOTE_CHANNELS = {"phone": "電話", "website": "官網", "onsite": "現場", "other": "其他"}
GOOGLE_SOURCE = "google"   # 與 helpers.geo.SOURCE_GOOGLE 同值；比對時兩個都認（見 is_google_source）


def is_google_source(src) -> bool:
    from helpers import geo
    return src in (GOOGLE_SOURCE, geo.SOURCE_GOOGLE)


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    r = 6371008.8
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lng2 - lng1)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(min(1.0, sqrt(h)))


def price_suspect(low, high) -> bool:
    vals = [v for v in (low, high) if v is not None]
    return any(not (PRICE_SANE_MIN <= v <= PRICE_SANE_MAX) for v in vals)


def kind_of(cls) -> str:
    return "homestay" if cls in lodging_source.HOMESTAY_CLASSES else "hotel"


def _latest_quotes(conn, keys):
    """{(source, source_id): 最近一筆詢價}；keys 為空 ⇒ {}。"""
    out = {}
    keys = list(keys)
    for i in range(0, len(keys), 400):
        chunk = keys[i:i + 400]
        where = " OR ".join("(source=? AND source_id=?)" for _ in chunk)
        args = [x for k in chunk for x in k]
        for r in conn.execute(
                "SELECT * FROM lodging_quotes WHERE %s ORDER BY quoted_on DESC, id DESC" % where, args).fetchall():
            k = (r["source"], r["source_id"])
            if k not in out:
                out[k] = quote_out(dict(r))
    return out


def quote_out(r: dict) -> dict:
    return {"id": r["id"], "quotedOn": r["quoted_on"], "roomType": r["room_type"], "price": r["price"],
            "unit": r["unit"], "unitLabel": QUOTE_UNITS.get(r["unit"], r["unit"]), "includes": r["includes"],
            "channel": r["channel"], "channelLabel": QUOTE_CHANNELS.get(r["channel"], r["channel"]),
            "note": r["note"], "enteredBy": r["entered_by"], "enteredAt": r["entered_at"], "priceKind": "manual"}


def nearby(conn, lat, lng, radius_m, kinds=("hotel", "homestay"), sort="distance"):
    """半徑內的旅宿（先以經緯度方框預篩，再算直線距離）。"""
    classes = sorted({c for k in kinds for c in KIND_CLASSES.get(k, ())})
    if not classes:
        return []
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * max(cos(radians(lat)), 0.01))
    rows = conn.execute(
        "SELECT * FROM lodging_catalog WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND class IN (%s)"
        % ",".join("?" * len(classes)),
        (lat - dlat, lat + dlat, lng - dlng, lng + dlng, *classes)).fetchall()
    out = []
    for r in rows:
        d = haversine_m(lat, lng, r["lat"], r["lng"])
        if d <= radius_m:
            out.append((round(d), dict(r)))
    quotes = _latest_quotes(conn, {(r["source"], r["source_id"]) for _, r in out})
    items = [item_out(r, d, quotes.get((r["source"], r["source_id"]))) for d, r in out]
    return sort_items(items, sort)


def item_out(r: dict, distance_m, latest_quote=None) -> dict:
    lo, hi = r.get("price_low"), r.get("price_high")
    return {
        "source": r["source"], "sourceId": r["source_id"], "licenseNo": r.get("license_no") or "",
        "name": r["name"], "class": r["class"], "classLabel": lodging_source.CLASS_LABELS.get(r["class"], ""),
        "kind": kind_of(r["class"]), "address": r.get("address") or "",
        "lat": r["lat"], "lng": r["lng"], "distanceM": distance_m,
        "priceLow": lo, "priceHigh": hi, "priceKind": "official_reference",
        "priceSuspect": price_suspect(lo, hi),
        # LG-S1：每筆的業者登記時間（catalog＝record_updated_at；紀錄＝price_registered_at）
        "priceRegisteredAt": r.get("record_updated_at", r.get("price_registered_at")) or "",
        "roomInfo": r.get("room_info") or "",
        "latestQuote": latest_quote,
    }


def _price_key(it):
    if it["priceSuspect"] or it["priceLow"] is None:
        return (1, 0)
    return (0, it["priceLow"])


def sort_items(items, sort):
    if sort == "price":
        return sorted(items, key=lambda it: (_price_key(it), it["distanceM"] if it["distanceM"] is not None else 0,
                                             it["sourceId"]))
    return sorted(items, key=lambda it: (it["distanceM"] if it["distanceM"] is not None else 0, it["sourceId"]))


# ── 紀錄 ─────────────────────────────────────────────────────────────────────

def save_search(conn, *, user, center, radius_m, kinds, sort, items, dataset_updated_at, note=""):
    """存一次查詢。中心點來源是 Google ⇒ center_lat/lng 與每筆 distance_m 都寫 NULL（LG-M2）。
    呼叫端負責交易與 commit。回新紀錄 id。"""
    google = is_google_source(center.get("source"))
    cur = conn.execute(
        "INSERT INTO lodging_searches (created_at, created_by, center_kind, center_label, center_lat, center_lng,"
        " center_source, center_precision, radius_m, filters_json, dataset_updated_at, result_count, note)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), user["username"], center["kind"], center.get("label") or "",
         None if google else center["lat"], None if google else center["lng"],
         center.get("source") or "", center.get("precision") or "", int(radius_m),
         json.dumps({"kinds": list(kinds), "sort": sort}, ensure_ascii=False),
         dataset_updated_at or "", len(items), note or ""))
    sid = cur.lastrowid
    conn.executemany(
        "INSERT INTO lodging_search_items (search_id, source, source_id, license_no, name, class, address, lat, lng,"
        " distance_m, price_low, price_high, price_registered_at, dataset_updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(sid, it["source"], it["sourceId"], it["licenseNo"], it["name"], it["class"], it["address"],
          it["lat"], it["lng"], None if google else it["distanceM"], it["priceLow"], it["priceHigh"],
          it["priceRegisteredAt"], dataset_updated_at or "") for it in items])
    return sid


def record_out(r: dict) -> dict:
    filters = {}
    try:
        filters = json.loads(r.get("filters_json") or "{}")
    except (TypeError, ValueError):
        filters = {}
    google = is_google_source(r.get("center_source"))
    return {
        "id": r["id"], "createdAt": r["created_at"], "createdBy": r["created_by"],
        "centerKind": r["center_kind"], "centerLabel": r["center_label"],
        "centerLat": r["center_lat"], "centerLng": r["center_lng"],
        "centerSource": r["center_source"], "centerPrecision": r["center_precision"],
        "googleCenter": google,
        "googleCenterNote": "中心點為 Google 定位，依 Google 條款不保存座標與距離" if google else "",
        "radiusM": r["radius_m"], "kinds": filters.get("kinds") or [], "sort": filters.get("sort") or "distance",
        "datasetUpdatedAt": r["dataset_updated_at"], "resultCount": r["result_count"], "note": r["note"],
    }


def record_items(conn, search_id):
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM lodging_search_items WHERE search_id=? ORDER BY id", (search_id,)).fetchall()]
    return [item_out(r, r["distance_m"]) for r in rows]


def compare(items_a, items_b):
    """兩筆紀錄以 (source, sourceId) 對齊。同一家兩次的官方參考房價與登記時間都相同 ⇒ official_unchanged
    （LG-S1：不讀成「價格沒漲」，只是官方登記沒變）。"""
    a = {(i["source"], i["sourceId"]): i for i in items_a}
    b = {(i["source"], i["sourceId"]): i for i in items_b}
    out = []
    for k in sorted(set(a) | set(b), key=lambda k: ((a.get(k) or b.get(k))["name"], k)):
        ia, ib = a.get(k), b.get(k)
        base = ia or ib

        def side(i):
            if not i:
                return None
            return {"distanceM": i["distanceM"], "priceLow": i["priceLow"], "priceHigh": i["priceHigh"],
                    "priceSuspect": i["priceSuspect"], "priceRegisteredAt": i["priceRegisteredAt"]}

        unchanged = bool(ia and ib and ia["priceLow"] == ib["priceLow"] and ia["priceHigh"] == ib["priceHigh"]
                         and ia["priceRegisteredAt"] == ib["priceRegisteredAt"])
        out.append({"source": k[0], "sourceId": k[1], "name": base["name"], "classLabel": base["classLabel"],
                    "kind": base["kind"], "licenseNo": base["licenseNo"], "address": base["address"],
                    "a": side(ia), "b": side(ib), "officialUnchanged": unchanged,
                    "only": "a" if not ib else ("b" if not ia else "")})
    return out
