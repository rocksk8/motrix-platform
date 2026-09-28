# -*- coding: utf-8 -*-
"""Google 定位階什麼時候會被跳過（第十五班 地圖修正包 ③；B，2026-09-28）。

正式機：MOTRIX_GEO=1、金鑰手動測試 status=OK，而 geocode_usage 0 筆、geocode_cache 沒有 google 來源。
geocode_usage 的計數點是「收到回應之後、解析之前」（含 ZERO_RESULTS 與被拒）⇒ 0 筆只有兩種可能：
  (甲) google 階**根本沒發**：沒有金鑰／額度判定已超過（含額度明填 0）／這個地址在負快取裡
  (乙) **有發、每次都在連線層失敗**（SSL 驗證、proxy、防火牆）：連線失敗不計數
這一檔把每一條件釘成題（urlopen 換成記錄器，不連外），並驗 (乙) 的樣子「嘗試了、usage 仍是 0」。
"""
import json
import ssl
import urllib.parse

import pytest

from helpers import geo

ADDR = "內政部警政署刑事警察局"


class _Resp:
    def __init__(self, body):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def spy(client, monkeypatch):
    """地理查詢開著、不節流、清快取與負快取；urlopen 換成記錄器：Google ⇒ 依 google_behave、Nominatim ⇒ 空陣列。"""
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    # 合回 A 的 §6.2 守門（A44）之後：非 Google 底圖時背景迴圈整輪不用 Google ⇒ 這一檔在 Google 底圖為真的情境（raising=False：本分支還沒有那個函式）
    monkeypatch.setattr(geo, "google_basemap", lambda: True, raising=False)
    monkeypatch.setattr(geo, "_CACHE", {})
    geo.reset_geocode_misses()
    calls = {"google": [], "nominatim": [], "google_behave": lambda: _Resp(json.dumps(
        {"status": "OK", "results": [{"geometry": {"location": {"lat": 25.0, "lng": 121.5}, "location_type": "ROOFTOP"}}]}).encode())}

    def _open(req, timeout=None):
        url = req.full_url
        if "googleapis.com" in url:
            calls["google"].append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("address", [""])[0])
            out = calls["google_behave"]()
            if isinstance(out, Exception):
                raise out
            return out
        calls["nominatim"].append(url)
        return _Resp(b"[]")
    monkeypatch.setattr(geo.urllib.request, "urlopen", _open)
    yield calls
    geo.reset_geocode_misses()


def _key(value="AIza-test-key"):
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile[geo.GOOGLE_KEY_SETTING] = value
    _set_setting("company_profile", profile)


def _quota(**kw):
    from helpers.settings import _set_setting
    _set_setting(geo.QUOTA_SETTING, kw)


def test_with_a_key_and_no_quota_set_google_is_asked_and_counted(spy):
    """正對照：有金鑰、額度沒填（None＝不管制）⇒ google 階會發、geocode_usage 記 1。"""
    _key()
    r = geo.locate_cached(ADDR)
    assert spy["google"] == [ADDR] and r.source == geo.SOURCE_GOOGLE, (spy, r)
    assert geo.usage_this_period() == 1


def test_no_key_skips_google(spy):
    _key("")
    geo.locate_cached(ADDR)
    assert spy["google"] == [] and spy["nominatim"], spy


@pytest.mark.parametrize("quota", [
    {"monthly_free_quota": 0},                                   # 明填 0 ＝「一次都不准查」（0 >= 0）
    {"sku_quotas": {geo.USAGE_SKU_GEOCODING: 0}},
])
def test_quota_filled_as_zero_skips_google_and_the_status_says_degraded(spy, quota):
    _key()
    _quota(**quota)
    geo.locate_cached(ADDR)
    assert spy["google"] == [] and spy["nominatim"], spy
    st = geo.quota_status()
    assert st["managed"] is True and st["degraded"] is True, st


def test_a_negative_cached_address_is_not_asked_again(spy):
    _key()
    geo.remember_geocode_miss(ADDR)
    geo.locate_cached(ADDR)
    assert spy["google"] == [] and spy["nominatim"] == [], spy


@pytest.mark.parametrize("exc", [ssl.SSLError("CERTIFICATE_VERIFY_FAILED"), OSError("proxy 拒絕連線")], ids=["ssl", "proxy"])
def test_transport_failures_are_attempts_that_are_never_counted(spy, exc):
    """(乙) 的樣子：google 階**有發**，但連線層失敗 ⇒ geocode_usage 仍是 0、不記負快取、快取沒有 google 來源。
    這正是正式機的數字形狀；分辨 (甲)／(乙) 要看伺服器記錄裡「不記負快取（有階失敗）」那行有沒有 ('google', …)。"""
    _key()
    spy["google_behave"] = lambda: exc
    r = geo.locate_cached(ADDR)
    assert spy["google"] == [ADDR], "有嘗試"
    assert geo.usage_this_period() == 0 and r.coord is None
    assert not geo.geocode_missed_recently(ADDR), "連線失敗不可以記成查無"


def test_warm_loop_asks_google_first_for_each_backlog_address(spy, monkeypatch):
    """背景迴圈每一筆都會先問 Google（有金鑰、額度沒鎖時）——所以正式機三輪都在跑而 usage 0，google 不是被迴圈本身跳過的。"""
    _key()
    monkeypatch.setattr(geo, "_WARM_SOURCES", [lambda: ["地址甲", "地址乙"]])
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)
    st = geo.warm_geocode_cache()
    assert spy["google"] == ["地址甲", "地址乙"] and st["succeeded"] == 2, (spy, st)
