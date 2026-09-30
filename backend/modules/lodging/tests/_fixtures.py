# -*- coding: utf-8 -*-
"""附近旅宿測試共用：合成觀光署資料 zip、登入。不含任何真實業者資料。"""
import io
import json
import zipfile

#: 哨兵：這些字串只出現在「不該被存」的欄位（電話、經營者、統編）；任何表裡出現 ⇒ 紅
SENTINEL_PHONE = "(099)SENTINEL-PHONE-7788"
SENTINEL_OPERATOR = "哨兵經營者某某某"
SENTINEL_TAXCODE = "99887766"

DATASET_UPDATE = "2026-09-28T14:30:31+08:00"


def hotel(i, lat=24.1372, lng=120.6867, cls=3, low=2000, high=3600, upd="2026-07-13T13:42:11+08:00", **kw):
    h = {
        "HotelID": "Hotel_TEST_%06d" % i,
        "HotelLicenseNumber": "測試市旅館%03d號" % i,
        "HotelName": "測試旅宿%d" % i,
        "PositionLat": lat, "PositionLon": lng,
        "HotelClasses": [cls], "HotelStars": 0,
        "PostalAddress": {"City": "測試市", "CityCode": "0", "Town": "測試區", "TownCode": "0",
                          "ZipCode": "000", "StreetAddress": "測試路%d號" % i},
        "Telephones": [{"Tel": SENTINEL_PHONE}],
        "Organizations": [{"Name": SENTINEL_OPERATOR, "Class": "Operator", "TaxCode": SENTINEL_TAXCODE}],
        "RoomInfo": "雙人房%d;" % high,
        "LowestPrice": low, "CeilingPrice": high,
        "ServiceStatus": 1,
        "UpdateTime": upd,
    }
    h.update(kw)
    return h


def dataset(hotels, update=DATASET_UPDATE) -> bytes:
    doc = {"UpdateTime": update, "UpdateInterval": 86400, "Language": "zh-tw", "ProviderID": "A15010000H",
           "Hotels": hotels}
    return json.dumps(doc, ensure_ascii=False).encode("utf-8-sig")


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)), data)   # 固定時間戳（zip 位元組不隨現在時間變；2026-10-01）
    return buf.getvalue()


def good_zip(hotels=None, update=DATASET_UPDATE) -> bytes:
    hotels = hotels if hotels is not None else [hotel(i) for i in range(1, 6)]
    return make_zip({"HotelList.json": dataset(hotels, update), "manifest.csv": b"name\n"})


def token(client, make_user, username, role, modules=None):
    u, pw = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def rows(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
