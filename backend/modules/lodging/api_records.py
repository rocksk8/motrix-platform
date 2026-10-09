# -*- coding: utf-8 -*-
"""附近旅宿：查詢、紀錄、匯出、比較、人工詢價（只查本機快照，不對外連線）。

對外連線：旅宿資料本身不連線（只查本機快照）；但「輸入地址」的定位若快取沒命中，會經 L1 `geo.locate_cached()` 對外查詢
  （受 `MOTRIX_GEO` 開關與 L1 節流；Nominatim／TGOS，頁面與設定都是 Google 底圖時才可能用 Google）——D 稽核 E2-S3。
中心點定位：包在 L1 `geo.map_request_scope(頁面底圖, missing="osm")` 內（LODGING-NEARBY §3.1.1，LG2-M1）——
  頁面底圖只准收窄設定；沒帶或不認得的值 ⇒ 不用 Google。回應帶實際 `basemap`，覆蓋層與頁面不一致 ⇒ 不畫、請重新整理（LG3-S1）。
紀錄可見範圍：建立者＋admin+（D 審 Q4）；看不到與不存在同一個 404。
"""
import csv
import io
import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from db import get_db
from helpers import _audit, _tok
from helpers.xlsx_out import log_export
# 走模組：測試要換得掉 geo.locate_cached
from helpers import geo
from modules.lodging import attribution as lodging_attr
from modules.lodging import search as lodging_search
from modules.lodging import source as lodging_source
from modules.lodging.api import _require_lodging

router = APIRouter()

_MAX_ADDRESS = 200
_MAX_NOTE = 500
_ADMIN_ROLES = ("superadmin", "admin")


# ── 查詢 ─────────────────────────────────────────────────────────────────────

def _body_center(body: dict) -> dict:
    """驗證中心點輸入（不定位）。"""
    c = body.get("center")
    if not isinstance(c, dict) or c.get("kind") not in ("device", "address"):
        raise HTTPException(422, "center.kind 必須是 device 或 address")
    if c["kind"] == "device":
        lat, lng = c.get("lat"), c.get("lng")
        if isinstance(lat, bool) or isinstance(lng, bool) or not isinstance(lat, (int, float)) \
                or not isinstance(lng, (int, float)) or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise HTTPException(422, "目前位置的經緯度無效")
        return {"kind": "device", "lat": float(lat), "lng": float(lng)}
    addr = c.get("address")
    if not isinstance(addr, str) or not addr.strip() or len(addr) > _MAX_ADDRESS:
        raise HTTPException(422, "請輸入地址（%d 字以內）" % _MAX_ADDRESS)
    return {"kind": "address", "address": addr.strip()}


def _body_options(body: dict):
    radius = body.get("radiusM", lodging_search.DEFAULT_RADIUS_M)
    if isinstance(radius, bool) or radius not in lodging_search.RADII_M:
        raise HTTPException(422, "radiusM 只能是 %s" % "／".join(str(r) for r in lodging_search.RADII_M))
    kinds = body.get("kinds", ["hotel", "homestay"])
    if not isinstance(kinds, list) or not kinds or any(k not in lodging_search.KIND_CLASSES for k in kinds):
        raise HTTPException(422, "kinds 只能是 hotel／homestay（至少一項）")
    sort = body.get("sort", "distance")
    if sort not in ("distance", "price"):
        raise HTTPException(422, "sort 只能是 distance 或 price")
    return radius, kinds, sort


def _resolve_center(c: dict) -> dict:
    """中心點 → {kind, label, lat, lng, source, precision, precisionNote}；定位不到 ⇒ {"error": 原因}。
    呼叫端必須已在 `geo.map_request_scope(...)` 範圍內（_run_search）。"""
    if c["kind"] == "device":
        return {"kind": "device", "label": "目前位置", "lat": c["lat"], "lng": c["lng"],
                "source": "device", "precision": "device", "precisionNote": ""}
    found = geo.locate_cached(c["address"])
    if not found.coord:
        return {"error": found.error or "查無此地址"}
    note = ""
    if found.precision == geo.PRECISION_DISTRICT:
        note = "中心點只定位到行政區，距離誤差可能數公里"
    return {"kind": "address", "label": c["address"], "lat": found.coord[0], "lng": found.coord[1],
            "source": found.source or "", "precision": found.precision or "", "precisionNote": note}


def _run_search(conn, body: dict):
    """回 (payload, center, items, cat)。沒有快照、定位不到 ⇒ payload 帶 available=False（不是 0 筆）。"""
    c = _body_center(body)
    radius, kinds, sort = _body_options(body)
    page_basemap = body.get("basemap")
    cat = lodging_source.catalog_state(conn)
    with geo.map_request_scope(page_basemap, missing=geo.MAP_SCOPE_MISSING_OSM) as google_ok:
        base = {"radiusM": radius, "kinds": kinds, "sort": sort, "basemap": "google" if google_ok else "osm",
                "datasetUpdatedAt": cat["dataset_updated_at"], "stale": cat["stale"],
                "staleDays": lodging_source.STALE_DAYS}
        if not cat["count"]:
            return dict(base, available=False, reason="no_catalog",
                        message="尚未下載旅宿資料，請最高管理者按「更新旅宿資料」"), None, [], cat
        center = _resolve_center(c)
        if center.get("error"):
            return dict(base, available=False, reason="center_not_found",
                        message="無法定位中心點：%s" % center["error"]), None, [], cat
        items = lodging_search.nearby(conn, center["lat"], center["lng"], radius, kinds, sort)
    payload = dict(base, available=True, center=center, count=len(items), items=items,
                   attribution=lodging_attr.attribution_text([cat["dataset_updated_at"]]))
    return payload, center, items, cat


@router.post("/api/lodging/search")
def lodging_search_endpoint(body: dict = Body(...), authorization: str = Header(None)):
    """查詢（只查本機快照，不存）。"""
    _require_lodging(authorization)
    conn = get_db()
    try:
        payload = _run_search(conn, body)[0]
    finally:
        conn.close()
    return payload


# ── 紀錄 ─────────────────────────────────────────────────────────────────────

def _can_see(user: dict, rec: dict) -> bool:
    """建立者＋admin+（D 審 Q4）；中心點地址可能指向自然人，照 IP-97 處理（不寫 log）。"""
    return user.get("role") in _ADMIN_ROLES or rec["created_by"] == user.get("username")


def _get_record(conn, user, rid: int) -> dict:
    row = conn.execute("SELECT * FROM lodging_searches WHERE id=?", (rid,)).fetchone()
    if not row or not _can_see(user, dict(row)):
        raise HTTPException(404, "查無此紀錄")
    return dict(row)


@router.post("/api/lodging/records")
def lodging_record_create(body: dict = Body(...), authorization: str = Header(None)):
    """重新查詢一次並存成紀錄（不信任前端送來的結果）。"""
    user = _require_lodging(authorization)
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note) > _MAX_NOTE:
        raise HTTPException(422, "備註需為 %d 字以內的文字" % _MAX_NOTE)
    from core.txn import write_txn
    conn = get_db()
    try:
        payload, center, items, cat = _run_search(conn, body)
        if not payload.get("available"):
            raise HTTPException(409, payload["message"])
        with write_txn(conn):
            rid = lodging_search.save_search(
                conn, user=user, center=center, radius_m=payload["radiusM"], kinds=payload["kinds"],
                sort=payload["sort"], items=items, dataset_updated_at=cat["dataset_updated_at"], note=note)
            conn.commit()
    finally:
        conn.close()
    # 稽核（W1c）：只記紀錄編號與筆數；中心點地址可能指向自然人（IP-97），不進稽核內容
    _audit(_tok(authorization), "lodging_record_create", "lodging_search", str(rid), "旅宿查詢紀錄", {"count": len(items)})
    return {"id": rid, "count": len(items)}


@router.get("/api/lodging/records")
def lodging_record_list(authorization: str = Header(None)):
    user = _require_lodging(authorization)
    conn = get_db()
    try:
        if user.get("role") in _ADMIN_ROLES:
            rows = conn.execute("SELECT * FROM lodging_searches ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM lodging_searches WHERE created_by=? ORDER BY id DESC",
                                (user["username"],)).fetchall()
    finally:
        conn.close()
    recs = [lodging_search.record_out(dict(r)) for r in rows]
    return {"records": recs,
            "attribution": lodging_attr.attribution_text([r["datasetUpdatedAt"] for r in recs]) if recs else ""}


def _detail(conn, user, rid: int) -> dict:
    rec = _get_record(conn, user, rid)
    items = lodging_search.record_items(conn, rid)
    quotes = lodging_search._latest_quotes(conn, {(i["source"], i["sourceId"]) for i in items})
    for i in items:
        i["latestQuote"] = quotes.get((i["source"], i["sourceId"]))
    return {"record": lodging_search.record_out(rec), "items": items,
            "attribution": lodging_attr.attribution_text([rec["dataset_updated_at"]])}


@router.get("/api/lodging/records/{rid}")
def lodging_record_detail(rid: int, authorization: str = Header(None)):
    user = _require_lodging(authorization)
    conn = get_db()
    try:
        return _detail(conn, user, rid)
    finally:
        conn.close()


@router.delete("/api/lodging/records/{rid}")
def lodging_record_delete(rid: int, authorization: str = Header(None)):
    user = _require_lodging(authorization)
    from core.txn import write_txn
    conn = get_db()
    try:
        with write_txn(conn):
            _get_record(conn, user, rid)
            conn.execute("DELETE FROM lodging_search_items WHERE search_id=?", (rid,))
            conn.execute("DELETE FROM lodging_searches WHERE id=?", (rid,))
            conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "lodging_record_delete", "lodging_search", str(rid), "旅宿查詢紀錄", {})
    return {"ok": True}


#: CSV 公式注入（D 稽核 E2-S2）：開頭是這些字元的儲存格，前面加 ' 讓試算表當文字
_CSV_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(v):
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith(_CSV_FORMULA_LEAD):
        return "'" + v
    return v


_EXPORT_COLS = (("name", "名稱"), ("classLabel", "類別"), ("licenseNo", "登記證號"), ("address", "地址"),
                ("distanceM", "直線距離（公尺）"), ("priceLow", "官方參考最低房價"), ("priceHigh", "官方參考最高房價"),
                ("priceRegisteredAt", "業者登記時間"))


@router.get("/api/lodging/records/{rid}/export")
def lodging_record_export(rid: int, format: str = "csv", authorization: str = Header(None)):
    """紀錄匯出（CSV／JSON），**必帶顯名**（LG-S2）。"""
    if format not in ("csv", "json"):
        raise HTTPException(422, "format 只能是 csv 或 json")
    user = _require_lodging(authorization)
    conn = get_db()
    try:
        d = _detail(conn, user, rid)
    finally:
        conn.close()
    attr = d["attribution"]
    if format == "json":
        body = json.dumps({"attribution": attr, "record": d["record"], "items": d["items"]},
                          ensure_ascii=False, indent=1)
        log_export(authorization, "json", "lodging", "lodging-record", {"format": format, "rid": rid}, len(d["items"]))     # 每次匯出都留紀錄（2026-09-30）
        return Response(body, media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="lodging-%d.json"' % rid})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["資料來源", _csv_cell(attr)])
    if d["record"]["googleCenter"]:
        w.writerow(["說明", _csv_cell(d["record"]["googleCenterNote"])])
    w.writerow([label for _k, label in _EXPORT_COLS])
    for it in d["items"]:
        w.writerow([_csv_cell(it[k]) for k, _l in _EXPORT_COLS])
    log_export(authorization, "csv", "lodging", "lodging-record", {"format": format, "rid": rid}, len(d["items"]))
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="lodging-%d.csv"' % rid})


@router.get("/api/lodging/compare")
def lodging_compare(a: int, b: int, authorization: str = Header(None)):
    user = _require_lodging(authorization)
    conn = get_db()
    try:
        ra, rb = _get_record(conn, user, a), _get_record(conn, user, b)
        ia, ib = lodging_search.record_items(conn, a), lodging_search.record_items(conn, b)
    finally:
        conn.close()
    return {"a": lodging_search.record_out(ra), "b": lodging_search.record_out(rb),
            "rows": lodging_search.compare(ia, ib),
            "attribution": lodging_attr.attribution_text([ra["dataset_updated_at"], rb["dataset_updated_at"]])}


# ── 人工詢價 ─────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_quote_date(qd) -> bool:
    if not (isinstance(qd, str) and _DATE_RE.match(qd)):
        return False
    try:
        return date.fromisoformat(qd) <= date.today()
    except ValueError:
        return False


@router.post("/api/lodging/quotes")
def lodging_quote_create(body: dict = Body(...), authorization: str = Header(None)):
    """使用者自己輸入的詢價（使用者資料，永久保存）。"""
    user = _require_lodging(authorization)
    src, sid = body.get("source"), body.get("sourceId")
    if src != lodging_source.SOURCE_KEY or not isinstance(sid, str) or not sid.strip():
        raise HTTPException(422, "source／sourceId 無效")
    qd = body.get("quotedOn")
    if not _valid_quote_date(qd):
        raise HTTPException(422, "詢價日期需為 YYYY-MM-DD，且不可晚於今天")
    price = body.get("price")
    if isinstance(price, bool) or not isinstance(price, int) or not (0 < price <= 10_000_000):
        raise HTTPException(422, "金額需為正整數（元）")
    unit, channel = body.get("unit"), body.get("channel")
    if unit not in lodging_search.QUOTE_UNITS:
        raise HTTPException(422, "unit 只能是 %s" % "／".join(lodging_search.QUOTE_UNITS))
    if channel not in lodging_search.QUOTE_CHANNELS:
        raise HTTPException(422, "channel 只能是 %s" % "／".join(lodging_search.QUOTE_CHANNELS))
    texts = {}
    for k, lim in (("roomType", 100), ("includes", 100), ("note", _MAX_NOTE)):
        v = body.get(k) or ""
        if not isinstance(v, str) or len(v) > lim:
            raise HTTPException(422, "%s 需為 %d 字以內的文字" % (k, lim))
        texts[k] = v.strip()
    from core.txn import write_txn
    conn = get_db()
    try:
        with write_txn(conn):
            known = conn.execute("SELECT 1 FROM lodging_catalog WHERE source=? AND source_id=?",
                                 (src, sid)).fetchone() \
                or conn.execute("SELECT 1 FROM lodging_search_items WHERE source=? AND source_id=? LIMIT 1",
                                (src, sid)).fetchone()
            if not known:
                raise HTTPException(404, "查無此旅宿")
            cur = conn.execute(
                "INSERT INTO lodging_quotes (source, source_id, quoted_on, room_type, price, unit, includes, channel,"
                " note, entered_by, entered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (src, sid, qd, texts["roomType"], price, unit, texts["includes"], channel, texts["note"],
                 user["username"], datetime.now().isoformat(timespec="seconds")))
            qid = cur.lastrowid
            conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "lodging_quote_create", "lodging_quote", str(qid), "旅宿詢價紀錄", {"source": src, "sourceId": sid})   # 稽核（W1c）：不記金額
    return {"id": qid}


@router.get("/api/lodging/quotes")
def lodging_quote_list(source: str, sourceId: str, authorization: str = Header(None)):
    _require_lodging(authorization)
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM lodging_quotes WHERE source=? AND source_id=?"
                            " ORDER BY quoted_on DESC, id DESC", (source, sourceId)).fetchall()
    finally:
        conn.close()
    return {"quotes": [lodging_search.quote_out(dict(r)) for r in rows]}
