# -*- coding: utf-8 -*-
"""`MP0b` · Google 定位結果的快取只能留 30 天，其他來源維持 180 天。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP0b。
依據：Google Maps Platform 服務條款（SST §14.3）——經緯度快取上限 30 天。

⚙️ 觀測點：同樣「31 天前」寫進快取的兩列，google 那列讀不到（過期），nominatim 那列還讀得到。
兩條讀取路徑都量：單筆 `_cache_get()` 與批次 `_cache_get_many()`（地圖一次查很多個地址走後者）。
"""
import datetime as _dt


def _seed(address, source, days_ago):
    import db
    created = (_dt.date.today() - _dt.timedelta(days=days_ago)).isoformat() + "T00:00:00"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO geocode_cache (address, source, lat, lon, precision, created_at)"
                     " VALUES (?,?,?,?,?,?)", (address, source, 24.1, 120.6, "street", created))
        conn.commit()
    finally:
        conn.close()


def test_mp0b_a_google_row_expires_after_30_days_but_others_do_not(client):
    from helpers import geo
    addr = "台中市西屯區MP0b路31號"
    _seed(addr, geo.SOURCE_GOOGLE, 31)
    _seed(addr, "nominatim", 31)
    g, n = geo._cache_get(addr, geo.SOURCE_GOOGLE), geo._cache_get(addr, "nominatim")
    many = geo._cache_get_many(addr, [geo.SOURCE_GOOGLE, "nominatim"])
    print("MP0b 實測：31 天前 ⇒ google %s／nominatim %s；批次 %r"
          % ("過期" if g is None else "仍有效", "過期" if n is None else "仍有效", sorted(many)))
    assert g is None, "google 快取 31 天了還讀得到（條款上限 30 天）"
    assert n is not None, "nominatim 31 天就過期了——其他來源應該維持 180 天"
    assert sorted(many) == ["nominatim"], many


def test_mp0b_a_google_row_is_still_valid_within_30_days(client):
    """對照組：29 天的 google 列仍然有效（沒有把 google 一律當過期）。"""
    from helpers import geo
    addr = "台中市西屯區MP0b路29號"
    _seed(addr, geo.SOURCE_GOOGLE, 29)
    assert geo._cache_get(addr, geo.SOURCE_GOOGLE) is not None
