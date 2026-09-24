# -*- coding: utf-8 -*-
"""`MP0d` · Google 用量計算器的「每月經常性用量」改依 Google 快取的實際有效期（30 天）。

使用者表單：「更正為 30 天」。`MP0b` 之後 google 列 30 天就過期重查，而計算器仍用 180 天攤提
⇒ 估算少算約 6 倍，畫面也寫「快取有效期 180 天」。
⚙️ 觀測點：`geo.quota_calculator()` 的 `ttl_days` 與 `monthly_recurring_estimate`
（公式照舊：相異地址數 ÷ 有效天數 × 30）。
"""


def test_mp0d_the_recurring_estimate_uses_the_google_ttl(client):
    import db
    from helpers import geo
    conn = db.get_db()
    try:
        for i in range(60):
            conn.execute("INSERT INTO geocode_cache (address, source, lat, lon, precision, created_at)"
                         " VALUES (?,?,?,?,?,?)", ("MP0d 地址 %d" % i, geo.SOURCE_GOOGLE,
                                                   24.1, 120.6, "rooftop", "2026-09-24T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    out = geo.quota_calculator()
    print("MP0d 實測：ttl_days=%s、每月經常性=%s（60 個相異地址）"
          % (out["ttl_days"], out["monthly_recurring_estimate"]))
    assert out["ttl_days"] == 30, out["ttl_days"]
    assert out["monthly_recurring_estimate"] == 60.0, out["monthly_recurring_estimate"]
