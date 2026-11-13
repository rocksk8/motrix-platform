# -*- coding: utf-8 -*-
"""Google 額度頁一次請求開了約 200 條資料庫連線（fix/google-quota-conn-t84）。

正式機回報（2026-11-13 18:43）：`GET /api/settings/google-quota` 一次 9.8 秒（15:36 也有 8.6 秒）；
同一個請求開了約 200 條 `get_db()`，位置在 `helpers/geo.py` 的 `_read_conn`。
根因：`quota_calculator()` 對「待暖清單」裡每個地址呼叫一次 `cached_only()`，而它在範圍外每次都自己開一條讀連線；
`_warm_backlog()` 是同一個寫法。修法：包進 `geo.cache_read_session()`（範圍內共用一條讀連線，finally 關閉）。

驗收（守門）：單一請求開的連線數**不隨地址數成長**。這裡用「5 個地址 vs 200 個地址，連線數相同」加上一個寬鬆的絕對上限，
而不是釘一個很小的絕對值：端點本身會經過設定讀取與用量查詢，固定開幾條是別的事。
🔑 計數器本身要有正對照：同樣的 200 個地址在範圍外必須開出 ≥ 200 條，否則「計到 0」與「沒有問題」長得一樣。
"""
import pytest


def _addresses(n, tag):
    return ["連線數守門測試 %s 路 %d 號" % (tag, i) for i in range(n)]


@pytest.fixture
def count_conns(monkeypatch):
    """攔 `db.get_db`，回 list（每開一條連線加一筆）。geo 的函式在呼叫當下才 `from db import get_db` ⇒ 攔得到。"""
    import db
    calls = []
    real = db.get_db

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(db, "get_db", counting)
    return calls


def _use_warm_source(monkeypatch, addrs):
    from helpers import geo
    monkeypatch.setattr(geo, "_WARM_SOURCES", [lambda: list(addrs)])
    return geo


def test_the_counter_sees_one_connection_per_address_outside_a_session(client, count_conns):
    """正對照：不進 `cache_read_session` 時，每個地址各開一條 ⇒ 計數器抓得到這種寫法。"""
    from helpers import geo
    addrs = _addresses(200, "positive")
    for a in addrs:
        assert geo.cached_only(a) is None
    assert len(count_conns) >= 200, "計數器沒有看到範圍外的逐筆連線：它抓不到問題，下面的題目都不算數"


def test_quota_calculator_connections_do_not_grow_with_the_address_count(client, count_conns, monkeypatch):
    geo = _use_warm_source(monkeypatch, _addresses(5, "calc"))
    count_conns.clear()
    geo.quota_calculator()
    few = len(count_conns)

    _use_warm_source(monkeypatch, _addresses(200, "calc2"))
    count_conns.clear()
    out = geo.quota_calculator()
    many = len(count_conns)

    assert out["uncached_addresses"] == 200, "共用連線不可以改變計算結果"
    assert many == few, "待暖清單從 5 個變 200 個，連線數從 %d 變 %d：又回到逐筆開連線" % (few, many)
    assert many < 20, "一次計算器就開了 %d 條連線" % many


def test_warm_backlog_connections_do_not_grow_with_the_address_count(client, count_conns, monkeypatch):
    geo = _use_warm_source(monkeypatch, _addresses(5, "warm"))
    count_conns.clear()
    geo._warm_backlog()
    few = len(count_conns)

    addrs = _addresses(200, "warm2")
    _use_warm_source(monkeypatch, addrs)
    count_conns.clear()
    backlog = geo._warm_backlog()
    many = len(count_conns)

    assert backlog == addrs, "待辦清單的內容與順序不可以因共用連線而改變"
    assert many == few and many < 20, "待暖清單 5→200 個，連線數 %d→%d" % (few, many)


def test_warm_backlog_still_drops_known_addresses_and_duplicates(client, monkeypatch):
    """行為不變：已快取的地址不算待辦、重複的只算一次（先收齊再過濾的寫法要保住舊語意）。"""
    import db
    known = "連線數守門測試 已知地址 1 號"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO geocode_cache (address, lat, lon, source, precision, created_at) VALUES (?,?,?,?,?,?)",
                     (known, 24.0, 120.0, "nominatim", "district", __import__("datetime").date.today().isoformat()))
        conn.commit()
    finally:
        conn.close()
    geo = _use_warm_source(monkeypatch, [known, "連線數守門測試 新地址 A", "連線數守門測試 新地址 A", " ", "連線數守門測試 新地址 B"])
    assert geo._warm_backlog() == ["連線數守門測試 新地址 A", "連線數守門測試 新地址 B"]


def test_the_google_quota_endpoint_opens_a_bounded_number_of_connections(client, make_user, count_conns, monkeypatch):
    """端點層：整個 `GET /api/settings/google-quota`（含設定、狀態、計算器）的連線數不隨地址數成長。"""
    username, password = make_user(username="quota_conn_admin", role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}

    def one_request(addrs):
        _use_warm_source(monkeypatch, addrs)
        count_conns.clear()
        resp = client.get("/api/settings/google-quota", headers=h)
        assert resp.status_code == 200, resp.text
        return len(count_conns), resp.json()

    few, _ = one_request(_addresses(5, "ep"))
    many, body = one_request(_addresses(200, "ep2"))
    assert body["calculator"]["uncached_addresses"] == 200
    assert many == few, "端點的連線數隨地址數成長（%d → %d）" % (few, many)
    assert many <= 20, "一次請求開了 %d 條連線" % many
