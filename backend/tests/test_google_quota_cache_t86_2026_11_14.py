# -*- coding: utf-8 -*-
"""T86 U11：Google 額度頁（`GET /api/settings/google-quota`）慢查詢要快取，查詢時不佔住請求與連線。

正式機回報：這支端點一次 8～10 秒（要掃整個地址快取與所有待暖來源）。連線風暴已在 t84 修掉（見 test_google_quota_conn）；
這一題守的是「重的那一半（地址數）走行程內快取」：
  - `quota_calculator()` 預設行為不變（每次重算）；`use_cache=True` 在 TTL 內不再掃；
  - 過期 ⇒ **先給舊值**、背景重算一次（同時只有一個在算）；
  - 一次都沒算過 ⇒ 同時進來的請求只算一遍；
  - 便宜的那一半（本期用量、額度、剩餘、單價）每次都現算（不被快取住）；
  - 端點走快取，回應的鍵不變。
"""
import threading
import time

import pytest

from helpers import geo


@pytest.fixture(autouse=True)
def _fresh_cache():
    geo.invalidate_quota_counts()
    yield
    geo.invalidate_quota_counts()


@pytest.fixture
def counter(monkeypatch):
    """換掉重的那一半：記呼叫次數，回傳值可以由測試調整。"""
    st = {"n": 0, "value": (10, 3), "delay": 0.0}

    def fake():
        st["n"] += 1
        if st["delay"]:
            time.sleep(st["delay"])
        return st["value"]

    monkeypatch.setattr(geo, "_quota_address_counts", fake)
    return st


def test_default_call_recomputes_every_time(counter):
    geo.quota_calculator()
    geo.quota_calculator()
    assert counter["n"] == 2


def test_cached_call_scans_once_within_the_ttl(counter):
    a = geo.quota_calculator(use_cache=True)
    b = geo.quota_calculator(use_cache=True)
    assert counter["n"] == 1
    assert (a["cached_addresses"], a["uncached_addresses"]) == (10, 3) == (b["cached_addresses"], b["uncached_addresses"])


def test_cheap_half_is_still_live_even_when_the_heavy_half_is_cached(counter, monkeypatch):
    geo.quota_calculator(use_cache=True)
    monkeypatch.setattr(geo, "usage_this_period", lambda *a, **k: 77)
    out = geo.quota_calculator(use_cache=True)
    assert counter["n"] == 1 and out["used_this_period"] == 77


def test_stale_value_is_served_at_once_and_refreshed_once_in_the_background(counter):
    geo.quota_calculator(use_cache=True)
    geo._QC_STATE["at"] -= geo.QUOTA_COUNTS_TTL_S + 1             # 過期
    counter["value"], counter["delay"] = (11, 4), 0.3             # 背景重算要花 0.3 秒
    t0 = time.monotonic()
    outs = [geo.quota_calculator(use_cache=True) for _ in range(5)]
    assert time.monotonic() - t0 < 0.25, "過期時請求不可以等重算"
    assert all((o["cached_addresses"], o["uncached_addresses"]) == (10, 3) for o in outs)      # 先給舊值
    for t in threading.enumerate():
        if t.name == "quota-counts":
            t.join(5)
    assert counter["n"] == 2, "5 個過期請求只能觸發一次背景重算"
    new = geo.quota_calculator(use_cache=True)
    assert (new["cached_addresses"], new["uncached_addresses"]) == (11, 4) and counter["n"] == 2


def test_a_failing_background_refresh_keeps_the_old_value(counter, monkeypatch):
    geo.quota_calculator(use_cache=True)
    geo._QC_STATE["at"] -= geo.QUOTA_COUNTS_TTL_S + 1

    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(geo, "_quota_address_counts", boom)
    geo.quota_calculator(use_cache=True)
    for t in threading.enumerate():
        if t.name == "quota-counts":
            t.join(5)
    assert geo._QC_STATE["refreshing"] is False
    assert geo._QC_STATE["value"] == (10, 3)


def test_concurrent_cold_requests_scan_only_once(counter):
    counter["delay"] = 0.3
    res = []
    ts = [threading.Thread(target=lambda: res.append(geo.quota_calculator(use_cache=True))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert counter["n"] == 1 and len(res) == 6
    assert {(r["cached_addresses"], r["uncached_addresses"]) for r in res} == {(10, 3)}


def test_endpoint_uses_the_cache_and_keeps_its_keys(client, make_user, counter):
    username, password = make_user(username="gq_cache_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    a = client.get("/api/settings/google-quota", headers=h)
    b = client.get("/api/settings/google-quota", headers=h)
    assert a.status_code == b.status_code == 200
    assert counter["n"] == 1
    assert set(a.json()) == {"settings", "status", "calculator", "skus"} == set(b.json())
    assert a.json()["calculator"]["uncached_addresses"] == 3
