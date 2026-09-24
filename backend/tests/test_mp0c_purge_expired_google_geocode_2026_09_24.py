# -*- coding: utf-8 -*-
"""`MP0c` · 每日自動刪除超過 30 天的 Google 定位快取（使用者表單：「加每日自動刪除」）。

依據：Google Maps Platform 服務條款（SST §14.3）——經緯度快取上限 30 天。`MP0b` 只做到
「讀取時視為過期」，列還留在 `geocode_cache`；這一項把它刪掉。
A 裁示：只 DELETE `source='google'` 且超過 30 天的列；其他來源與任何業務資料都不碰；
寫一筆 system audit 記錄刪了幾筆；掛在既有排程上（背景預熱每一輪開頭）。

⚙️ 走排程真的會呼叫的那一支（`geo.warm_geocode_cache()`），不是只測清除函式本身——
   證明「有接上排程」。
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


def _rows():
    import db
    conn = db.get_db()
    try:
        return sorted((r["address"], r["source"]) for r in conn.execute(
            "SELECT address, source FROM geocode_cache"))
    finally:
        conn.close()


def test_mp0c_the_scheduled_run_deletes_only_google_rows_older_than_30_days(client, monkeypatch):
    import db
    from helpers import geo
    monkeypatch.setattr(geo, "GEO_ENABLED", False)   # 關著也要清（清除不對外連線）
    _seed("G31", geo.SOURCE_GOOGLE, 31)
    _seed("G29", geo.SOURCE_GOOGLE, 29)
    _seed("N200", "nominatim", 200)
    geo.warm_geocode_cache()
    left = _rows()
    conn = db.get_db()
    try:
        audit = [dict(r) for r in conn.execute(
            "SELECT action, detail FROM audit_log WHERE action='geocode.purge_google'")]
    finally:
        conn.close()
    print("MP0c 實測：排程一輪後剩 %r；audit %r" % (left, audit))
    assert ("G31", "google") not in left, "31 天的 google 列沒有被刪"
    assert ("G29", "google") in left, "29 天的 google 列被刪了"
    assert ("N200", "nominatim") in left, "nominatim 200 天的列被刪了（這支只刪 google）"
    assert len(audit) == 1 and '"deleted": 1' in audit[0]["detail"], audit


def test_mp0c_nothing_to_delete_leaves_no_audit_noise(client, monkeypatch):
    """每一輪都跑；沒有刪到東西時不寫 audit（不要每 6 小時留一筆 0）。"""
    import db
    from helpers import geo
    monkeypatch.setattr(geo, "GEO_ENABLED", False)
    _seed("G1", geo.SOURCE_GOOGLE, 1)
    geo.warm_geocode_cache()
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='geocode.purge_google'").fetchone()[0]
    finally:
        conn.close()
    assert n == 0 and ("G1", "google") in _rows()
