# -*- coding: utf-8 -*-
"""附近旅宿：查詢、紀錄（LG-M2 Google 中心點不存座標與距離）、可見範圍、匯出顯名（LG-S2）、
比較（LG-S1 官方登記未變動）、錯值價格（LG-S4）、人工詢價。LODGING-NEARBY.md §2.3、§3.3、§3.7。
"""
from datetime import date, timedelta

import pytest

from helpers import geo
from modules.lodging import search as lsearch
from modules.lodging import source as ls
from modules.lodging.tests import _fixtures as fx

C_LAT, C_LNG = 24.1372, 120.6867


def _seed(hotels, update=fx.DATASET_UPDATE):
    import db
    parsed = ls.parse_dataset(fx.dataset(hotels, update))
    conn = db.get_db()
    try:
        ls.replace_catalog(conn, parsed["rows"])
    finally:
        conn.close()


def _near(i, dlat, **kw):
    """中心點往北 dlat 度（1e-3 度 ≈ 111 公尺）。"""
    return fx.hotel(i, lat=C_LAT + dlat, lng=C_LNG, **kw)


@pytest.fixture()
def seeded(client):
    _seed([_near(1, 0.001, low=2000, high=3000),             # ≈111 m 旅館
           _near(2, 0.005, cls=4, low=1500, high=2500),      # ≈556 m 民宿
           _near(3, 0.02, low=299, high=5000),               # ≈2.2 km 錯值（< 300）
           _near(4, 0.025, low=300, high=100_000),           # ≈2.8 km 邊界：不算錯值
           _near(5, 0.026, low=5000, high=100_001),          # ≈2.9 km 錯值（> 100,000）
           _near(6, 0.05)])                                  # ≈5.6 km 半徑外


@pytest.fixture()
def users(client, make_user):
    return {
        "a": fx.token(client, make_user, "lod_a", "sales", modules=["lodging"]),
        "b": fx.token(client, make_user, "lod_b", "sales", modules=["lodging"]),
        "admin": fx.token(client, make_user, "lod_adm", "admin", modules=["lodging"]),
    }


def _dev(**kw):
    body = {"center": {"kind": "device", "lat": C_LAT, "lng": C_LNG}, "radiusM": 3000}
    body.update(kw)
    return body


def _fake_locate(monkeypatch, *, source="nominatim", precision="street", coord=(C_LAT, C_LNG), error=None):
    seen = []

    def fake(address, manual_coord=None):
        seen.append(geo.google_content_blocked())
        return geo.GeoResult(coord=coord, precision=precision, source=source, error=error, address=address)

    monkeypatch.setattr(geo, "locate_cached", fake)
    return seen


# ── 查詢 ──────────────────────────────────────────────────────────────────────

def test_no_catalog_is_unavailable_not_zero(client, users):
    d = client.post("/api/lodging/search", json=_dev(), headers=users["a"]).json()
    assert d["available"] is False and d["reason"] == "no_catalog" and "更新旅宿資料" in d["message"]
    assert "items" not in d


def test_search_by_device_distance_radius_and_kinds(client, users, seeded):
    d = client.post("/api/lodging/search", json=_dev(), headers=users["a"]).json()
    assert d["available"] is True
    ids = [i["sourceId"][-1] for i in d["items"]]
    assert ids == ["1", "2", "3", "4", "5"]                                  # 距離排序，6 在半徑外
    assert 100 <= d["items"][0]["distanceM"] <= 125
    assert all(i["priceKind"] == "official_reference" for i in d["items"])
    assert d["items"][0]["priceRegisteredAt"] == "2026-07-13T13:42:11+08:00"   # LG-S1
    assert "交通部觀光署 2026" in d["attribution"]
    only_homestay = client.post("/api/lodging/search", json=_dev(kinds=["homestay"]), headers=users["a"]).json()
    assert [i["sourceId"][-1] for i in only_homestay["items"]] == ["2"]
    wide = client.post("/api/lodging/search", json=_dev(radiusM=10000), headers=users["a"]).json()
    assert len(wide["items"]) == 6


def test_suspect_prices_flagged_kept_and_sorted_last(client, users, seeded):
    d = client.post("/api/lodging/search", json=_dev(sort="price"), headers=users["a"]).json()
    by = {i["sourceId"][-1]: i for i in d["items"]}
    assert by["3"]["priceSuspect"] and by["3"]["priceLow"] == 299            # 原值照回（LG-S4）
    assert by["5"]["priceSuspect"] and by["5"]["priceHigh"] == 100_001
    assert not by["4"]["priceSuspect"]                                        # 300／100,000 邊界
    order = [i["sourceId"][-1] for i in d["items"]]
    assert order[:3] == ["4", "2", "1"] and set(order[3:]) == {"3", "5"}     # 錯值不參與價格排序


@pytest.mark.parametrize("low,high,sus", [(300, 100_000, False), (299, None, True), (None, 100_001, True),
                                          (None, None, False)])
def test_price_suspect_thresholds(low, high, sus):
    assert lsearch.price_suspect(low, high) is sus


def test_address_center_never_uses_google_in_interim(client, users, seeded, monkeypatch):
    seen = _fake_locate(monkeypatch, precision="district")
    d = client.post("/api/lodging/search", json={"center": {"kind": "address", "address": "測試市測試區"},
                                                 "radiusM": 3000, "basemap": "google"}, headers=users["a"]).json()
    assert seen == [True]                                   # 定位當下在 without_google_content 範圍內
    assert d["available"] and d["center"]["source"] == "nominatim"
    assert "行政區" in d["center"]["precisionNote"]


def test_address_not_found_is_unavailable(client, users, seeded, monkeypatch):
    _fake_locate(monkeypatch, coord=None, error="查無此地址")
    d = client.post("/api/lodging/search", json={"center": {"kind": "address", "address": "不存在路"}},
                    headers=users["a"]).json()
    assert d["available"] is False and d["reason"] == "center_not_found"


@pytest.mark.parametrize("body", [{"center": {"kind": "x"}}, {"center": {"kind": "device", "lat": 91, "lng": 0}},
                                  {"center": {"kind": "device", "lat": True, "lng": 0}},
                                  {"center": {"kind": "address", "address": ""}},
                                  _dev(radiusM=2000), _dev(kinds=[]), _dev(kinds=["motel"]), _dev(sort="name")])
def test_search_validation(client, users, seeded, body):
    assert client.post("/api/lodging/search", json=body, headers=users["a"]).status_code == 422


# ── 紀錄：LG-M2 ────────────────────────────────────────────────────────────────

def test_record_with_free_center_keeps_coords_and_distances(client, users, seeded, monkeypatch):
    _fake_locate(monkeypatch, source="nominatim")
    r = client.post("/api/lodging/records", json={"center": {"kind": "address", "address": "測試市測試路"},
                                                  "note": "出差"}, headers=users["a"])
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    rec = fx.rows("SELECT * FROM lodging_searches WHERE id=?", rid)[0]
    assert rec["center_lat"] == C_LAT and rec["center_source"] == "nominatim" and rec["created_by"] == "lod_a"
    items = fx.rows("SELECT * FROM lodging_search_items WHERE search_id=?", rid)
    assert len(items) == 5 and all(i["distance_m"] is not None for i in items)


def test_record_with_google_center_stores_no_coords_no_distances(client, users, seeded, monkeypatch):
    _fake_locate(monkeypatch, source=geo.SOURCE_GOOGLE, precision="rooftop")
    rid = client.post("/api/lodging/records", json={"center": {"kind": "address", "address": "測試市測試路1號"}},
                      headers=users["a"]).json()["id"]
    rec = fx.rows("SELECT * FROM lodging_searches WHERE id=?", rid)[0]
    assert rec["center_lat"] is None and rec["center_lng"] is None
    assert rec["center_label"] == "測試市測試路1號" and rec["center_source"] == "google"
    items = fx.rows("SELECT * FROM lodging_search_items WHERE search_id=?", rid)
    assert items and all(i["distance_m"] is None for i in items)
    d = client.get("/api/lodging/records/%d" % rid, headers=users["a"]).json()
    assert d["record"]["googleCenter"] is True and "不保存座標與距離" in d["record"]["googleCenterNote"]
    assert all(i["distanceM"] is None for i in d["items"])


def test_record_device_center_kept(client, users, seeded):
    rid = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    rec = fx.rows("SELECT * FROM lodging_searches WHERE id=?", rid)[0]
    assert rec["center_source"] == "device" and rec["center_lat"] == C_LAT


def test_record_without_catalog_is_refused(client, users):
    r = client.post("/api/lodging/records", json=_dev(), headers=users["a"])
    assert r.status_code == 409 and fx.rows("SELECT * FROM lodging_searches") == []


# ── 可見範圍（Q4） ─────────────────────────────────────────────────────────────

def test_records_visible_to_creator_and_admin_only(client, users, seeded):
    rid = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    assert [r["id"] for r in client.get("/api/lodging/records", headers=users["a"]).json()["records"]] == [rid]
    assert client.get("/api/lodging/records", headers=users["b"]).json()["records"] == []
    for path in ("/api/lodging/records/%d" % rid, "/api/lodging/records/%d/export" % rid,
                 "/api/lodging/compare?a=%d&b=%d" % (rid, rid)):
        r = client.get(path, headers=users["b"])
        assert r.status_code == 404 and r.json()["detail"] == "查無此紀錄", path
    assert client.get("/api/lodging/records/999999", headers=users["a"]).json()["detail"] == "查無此紀錄"
    assert client.delete("/api/lodging/records/%d" % rid, headers=users["b"]).status_code == 404
    assert client.get("/api/lodging/records/%d" % rid, headers=users["admin"]).status_code == 200
    assert client.delete("/api/lodging/records/%d" % rid, headers=users["a"]).status_code == 200
    assert fx.rows("SELECT * FROM lodging_search_items WHERE search_id=?", rid) == []


# ── 顯名（LG-S2） ──────────────────────────────────────────────────────────────

def test_export_csv_and_json_carry_attribution(client, users, seeded, monkeypatch):
    _fake_locate(monkeypatch, source=geo.SOURCE_GOOGLE)
    rid = client.post("/api/lodging/records", json={"center": {"kind": "address", "address": "測試路"}},
                      headers=users["a"]).json()["id"]
    csv_text = client.get("/api/lodging/records/%d/export?format=csv" % rid, headers=users["a"]).text
    first = csv_text.lstrip("﻿").splitlines()[0]
    assert first.startswith("資料來源,") and "交通部觀光署 2026" in first and "data.gov.tw/license" in first
    assert "不保存座標與距離" in csv_text
    js = client.get("/api/lodging/records/%d/export?format=json" % rid, headers=users["a"]).json()
    assert "交通部觀光署 2026" in js["attribution"]
    assert client.get("/api/lodging/records/%d/export?format=xml" % rid, headers=users["a"]).status_code == 422


def test_attribution_lists_every_dataset_year(client, users, seeded):
    r1 = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    _seed([_near(1, 0.001, low=2100, high=3000)], update="2027-01-02T10:00:00+08:00")
    r2 = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    d = client.get("/api/lodging/compare?a=%d&b=%d" % (r1, r2), headers=users["a"]).json()
    assert "交通部觀光署 2026、2027" in d["attribution"]
    lst = client.get("/api/lodging/records", headers=users["a"]).json()
    assert "2026、2027" in lst["attribution"]
    assert "2027" in client.get("/api/lodging/records/%d" % r2, headers=users["a"]).json()["attribution"]


# ── 比較（LG-S1） ──────────────────────────────────────────────────────────────

def test_compare_marks_official_unchanged_not_price_flat(client, users, seeded):
    r1 = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    r2 = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    rows = client.get("/api/lodging/compare?a=%d&b=%d" % (r1, r2), headers=users["a"]).json()["rows"]
    assert rows and all(r["officialUnchanged"] for r in rows)
    _seed([_near(1, 0.001, low=2100, high=3000, upd="2026-09-20T00:00:00+08:00"), _near(7, 0.002)])
    r3 = client.post("/api/lodging/records", json=_dev(), headers=users["a"]).json()["id"]
    rows = {r["sourceId"][-1]: r for r in
            client.get("/api/lodging/compare?a=%d&b=%d" % (r1, r3), headers=users["a"]).json()["rows"]}
    assert rows["1"]["officialUnchanged"] is False and rows["1"]["b"]["priceLow"] == 2100
    assert rows["2"]["only"] == "a" and rows["2"]["b"] is None
    assert rows["7"]["only"] == "b"


# ── 人工詢價 ──────────────────────────────────────────────────────────────────

def _quote(**kw):
    q = {"source": "mot", "sourceId": "Hotel_TEST_000001", "quotedOn": date.today().isoformat(),
         "roomType": "雙人房", "price": 2800, "unit": "per_night", "channel": "phone", "note": "含早"}
    q.update(kw)
    return q


def test_quote_create_and_show_latest_in_search(client, users, seeded):
    old = (date.today() - timedelta(days=3)).isoformat()
    assert client.post("/api/lodging/quotes", json=_quote(quotedOn=old, price=2500), headers=users["a"]).status_code == 200
    assert client.post("/api/lodging/quotes", json=_quote(), headers=users["a"]).status_code == 200
    lst = client.get("/api/lodging/quotes?source=mot&sourceId=Hotel_TEST_000001", headers=users["b"]).json()["quotes"]
    assert [q["price"] for q in lst] == [2800, 2500] and lst[0]["priceKind"] == "manual"
    d = client.post("/api/lodging/search", json=_dev(), headers=users["a"]).json()
    it = [i for i in d["items"] if i["sourceId"] == "Hotel_TEST_000001"][0]
    assert it["latestQuote"]["price"] == 2800 and it["latestQuote"]["enteredBy"] == "lod_a"


@pytest.mark.parametrize("kw,code", [
    ({"sourceId": "Hotel_NOPE"}, 404), ({"source": "osm"}, 422), ({"price": 0}, 422), ({"price": 12.5}, 422),
    ({"price": True}, 422), ({"unit": "per_room"}, 422), ({"channel": "fax"}, 422),
    ({"quotedOn": "2026/09/28"}, 422), ({"quotedOn": (date.today() + timedelta(days=1)).isoformat()}, 422),
    ({"note": "x" * 501}, 422)])
def test_quote_validation(client, users, seeded, kw, code):
    assert client.post("/api/lodging/quotes", json=_quote(**kw), headers=users["a"]).status_code == code
    assert fx.rows("SELECT * FROM lodging_quotes") == []
