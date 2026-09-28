# -*- coding: utf-8 -*-
"""背景定位：「查過、查無此地址」不算連續失敗（第十五班；CORE-SPEC「地圖修正包」①；B，2026-09-28）。

正式機（822286ed 上線後）：待辦前三筆是機關名稱（「衛生福利部樂生醫院」…），Nominatim 回空陣列 ⇒ 背景迴圈每輪
「連續失敗 3 次，停下來」、333 筆卡住、地圖 0 點，畫面還說「外部地圖服務可能暫時拒絕本機查詢」。
根因有兩層：
  (a) geocode() 查無時回 err「查無此地址」，_locate_nominatim 把**任何** err 都塞進 errors
      ⇒ locate_cached 把真的查無當成「有階失敗」⇒ 負快取從來沒寫過（既有題的替身回 None 不報錯，所以一直綠）
  (b) warm 迴圈只看「有沒有座標」，查無與連不上一起算連續失敗
另：Google 回 REQUEST_DENIED／OVER_QUERY_LIMIT 時 results 是空的，原本回 None 不報錯 ⇒ 被當成查無。

這裡走**真的 geocode()**，只把 urllib.request.urlopen 換成假的（不連外）：
① 查無（空陣列）⇒ 記負快取、不是 error；連不上／回應不是 JSON ⇒ 不記
② 三筆查無＋一筆可查 ⇒ 不停、成功 1、misses 記得出來、停的理由不是 failures
③ 三筆連不上 ⇒ 停（failures）；回應不是 JSON（HTTP 200 的拒絕頁）⇒ 也算失敗、停
④ 反向控制：失敗之間夾著查無 ⇒ 連續計數歸零、不停（查無＝對方有回應）
⑤ Google：ZERO_RESULTS 是查無；REQUEST_DENIED 是錯誤（進 errors、不記負快取）
⑥ 頁面：warmNote 讀 misses、failures 兩個數字，查無與被拒兩句話分開
"""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from helpers import geo
from tests.test_geocode_warm_2026_09_22 import backlog  # noqa: F401  （fixture：6 筆「待定位機關0～5」）

FRONT = Path(__file__).resolve().parents[2] / "frontend"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(monkeypatch, behave):
    """behave(address) ⇒ bytes（回應內容）或 Exception（丟出去）。記下每一次查的地址。"""
    import urllib.parse
    asked = []

    def _open(req, timeout=None):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        addr = (q.get("q") or q.get("address") or [""])[0]
        asked.append(addr)
        out = behave(addr)
        if isinstance(out, Exception):
            raise out
        return _Resp(out)
    monkeypatch.setattr(geo.urllib.request, "urlopen", _open)
    return asked


@pytest.fixture()
def real_path(monkeypatch):
    """地理查詢開著、不節流、沒有 Google 金鑰（google 階自己跳過）、記憶體快取清空。"""
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_throttle", lambda: None)
    monkeypatch.setattr(geo, "_CACHE", {})
    monkeypatch.setattr(geo, "GEOCODE_WARM_DAILY_LIMIT", 100)
    geo.reset_geocode_misses()
    yield
    geo.reset_geocode_misses()


EMPTY = b"[]"
HIT = json.dumps([{"lat": "24.15", "lon": "120.67", "class": "amenity", "type": "hospital"}]).encode("utf-8")
BLOCK_PAGE = b"<html><body>Access blocked</body></html>"


# ── ① 查無 vs 沒查成功（真的 geocode 路徑）──────────────────────────────────

def test_an_empty_answer_is_a_miss_and_is_remembered(client, real_path, monkeypatch):
    _fake_urlopen(monkeypatch, lambda a: EMPTY)
    r = geo.locate_cached("衛生福利部樂生醫院")
    assert r.coord is None and geo.geocode_missed_recently("衛生福利部樂生醫院"), \
        "對方回空陣列＝查過、查無 ⇒ 要記負快取（原本被當成有階失敗而從來沒記過）"


@pytest.mark.parametrize("behave", [
    lambda a: urllib.error.URLError("連不上"),
    lambda a: BLOCK_PAGE,                            # HTTP 200 而內容是拒絕頁 ⇒ JSON 解析失敗
], ids=["urlerror", "block_page"])
def test_reverse_control_a_failed_lookup_is_not_remembered_as_a_miss(client, real_path, monkeypatch, behave):
    _fake_urlopen(monkeypatch, behave)
    r = geo.locate_cached("苗栗縣立獅潭國民中學")
    assert r.coord is None and not geo.geocode_missed_recently("苗栗縣立獅潭國民中學"), \
        "沒查成功不可以記成查無（那會讓地址七天內不再被查）"


# ── ②③④ 背景迴圈 ──────────────────────────────────────────────────────────

def test_misses_do_not_stop_the_warmer_and_the_hit_is_found(client, backlog, real_path, monkeypatch):
    asked = _fake_urlopen(monkeypatch, lambda a: HIT if a == "待定位機關3" else EMPTY)
    st = geo.warm_geocode_cache()
    assert len(asked) == 6, "查無不算失敗 ⇒ 6 筆都要查到（原本第 3 筆就停）：%r" % asked
    assert st["succeeded"] == 1 and st["misses"] == 5 and st["failures"] == 0, st
    assert st["stoppedBecause"] == "no_backlog", st


def test_three_connection_failures_in_a_row_stop_the_warmer(client, backlog, real_path, monkeypatch):
    asked = _fake_urlopen(monkeypatch, lambda a: urllib.error.URLError("拒絕連線"))
    st = geo.warm_geocode_cache()
    assert len(asked) == 3 and st["stoppedBecause"] == "failures" and st["failures"] == 3, (asked, st)


def test_a_refusal_page_with_http_200_counts_as_failure(client, backlog, real_path, monkeypatch):
    asked = _fake_urlopen(monkeypatch, lambda a: BLOCK_PAGE)
    st = geo.warm_geocode_cache()
    assert len(asked) == 3 and st["stoppedBecause"] == "failures" and st["misses"] == 0, (asked, st)


def test_reverse_control_a_miss_between_failures_resets_the_streak(client, backlog, real_path, monkeypatch):
    plan = iter(["fail", "fail", "miss", "fail", "fail", "miss"])   # 依呼叫次序（不依待辦的排列順序）
    asked = _fake_urlopen(monkeypatch, lambda a: EMPTY if next(plan) == "miss" else urllib.error.URLError("x"))
    st = geo.warm_geocode_cache()
    assert len(asked) == 6 and st["stoppedBecause"] == "no_backlog", (asked, st)
    assert st["failures"] == 4 and st["misses"] == 2, st


# ── ⑤ Google：被拒不是查無 ────────────────────────────────────────────────────

@pytest.mark.parametrize("status,is_error", [("ZERO_RESULTS", False), ("REQUEST_DENIED", True), ("OVER_QUERY_LIMIT", True)])
def test_google_denied_is_an_error_but_zero_results_is_a_miss(client, real_path, monkeypatch, status, is_error):
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile[geo.GOOGLE_KEY_SETTING] = "AIza-test-key"
    _set_setting("company_profile", profile)
    monkeypatch.setattr(geo, "quota_exceeded", lambda *a, **k: False)
    monkeypatch.setattr(geo, "record_geocode_call", lambda *a, **k: None)
    _fake_urlopen(monkeypatch, lambda a: json.dumps({"status": status, "results": [], "error_message": "x"}).encode("utf-8"))
    errors = []
    assert geo._locate_google("內政部警政署刑事警察局", errors=errors) is None
    assert bool(errors) is is_error, (status, errors)


# ── ⑥ 頁面 ────────────────────────────────────────────────────────────────

def test_the_page_says_misses_and_refusals_separately(client):
    src = (FRONT / "pages" / "map.html").read_text(encoding="utf-8")
    i = src.index("warmNote() {")
    body = src[i:src.index("accuracyLabel()", i)]
    assert "w.misses" in body and "w.failures" in body
    assert "可能暫時拒絕" in body, "被拒（failures）那一句要留著"
    assert "手動定位" in body and "改成可查的地址" in body, "查無要告訴使用者去改地址或手動定位"
    status = geo.warm_status()
    assert "misses" in status and "failures" in status


# ── 主持裁示：Google 階本輪連續連線失敗／被拒 ⇒ 跳過 Google、免費來源繼續 ─────────────────

def _set_google_key(value="AIza-test-key", monkeypatch=None):
    """設金鑰。⚠️ 合回 A 的 §6.2 守門（A44）之後，背景迴圈在「非 Google 底圖」時整輪不用 Google ⇒ 這些題要在
    Google 底圖為真的情境：google_basemap 換成回 True（raising=False：本分支還沒有那個函式時只是多設一個屬性）。"""
    if monkeypatch is not None:
        monkeypatch.setattr(geo, "google_basemap", lambda: True, raising=False)
    from helpers.settings import _get_setting, _set_setting
    profile = dict(_get_setting("company_profile", {}) or {})
    profile[geo.GOOGLE_KEY_SETTING] = value
    _set_setting("company_profile", profile)


def _two_sources(monkeypatch, google_behave, nominatim_behave):
    """urlopen：googleapis ⇒ google_behave()；其餘（Nominatim）⇒ nominatim_behave(address)。回 {google: [...], nominatim: [...]}。"""
    import urllib.parse
    calls = {"google": [], "nominatim": []}

    def _open(req, timeout=None):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        if "googleapis.com" in req.full_url:
            calls["google"].append(q.get("address", [""])[0])
            out = google_behave()
        else:
            addr = q.get("q", [""])[0]
            calls["nominatim"].append(addr)
            out = nominatim_behave(addr)
        if isinstance(out, Exception):
            raise out
        return _Resp(out)
    monkeypatch.setattr(geo.urllib.request, "urlopen", _open)
    return calls


GOOGLE_OK = json.dumps({"status": "OK", "results": [
    {"geometry": {"location": {"lat": 25.0, "lng": 121.5}, "location_type": "ROOFTOP"}}]}).encode("utf-8")


@pytest.mark.parametrize("google_fail", [
    lambda: urllib.error.URLError("SSL: CERTIFICATE_VERIFY_FAILED"),
    lambda: json.dumps({"status": "REQUEST_DENIED", "results": [], "error_message": "API keys with referer restrictions"}).encode("utf-8"),
], ids=["transport", "denied"])
def test_google_failing_in_a_row_is_skipped_for_the_round_and_free_sources_carry_on(
        client, backlog, real_path, monkeypatch, google_fail):
    _set_google_key(monkeypatch=monkeypatch)
    monkeypatch.setattr(geo, "quota_exceeded", lambda *a, **k: False)
    calls = _two_sources(monkeypatch, google_fail, lambda a: HIT)
    st = geo.warm_geocode_cache()
    assert len(calls["google"]) == 3, "連續 3 次之後本輪不再問 Google：%r" % calls["google"]
    assert len(calls["nominatim"]) == 6 and st["succeeded"] == 6, (calls, st)
    assert st["stoppedBecause"] == "no_backlog" and st["failures"] == 0, "Google 失敗不是免費來源的失敗，迴圈不停：%r" % st
    assert st["googleSkipped"] is True and st["googleFailures"] == 3 and st["googleSkipReason"], st
    assert geo._stage_allowed(geo.SOURCE_GOOGLE) is True, "「本輪跳過 Google」不可以外漏到背景迴圈以外"


def test_google_failing_while_free_sources_miss_does_not_stop_the_round(client, backlog, real_path, monkeypatch):
    """Google 連不上＋免費來源查無：前 3 筆（Google 有錯）不記負快取、也不算失敗；之後跳過 Google、查無照記。"""
    _set_google_key(monkeypatch=monkeypatch)
    monkeypatch.setattr(geo, "quota_exceeded", lambda *a, **k: False)
    calls = _two_sources(monkeypatch, lambda: urllib.error.URLError("proxy"), lambda a: EMPTY)
    st = geo.warm_geocode_cache()
    assert len(calls["nominatim"]) == 6 and st["stoppedBecause"] == "no_backlog", (calls, st)
    assert st["misses"] == 3 and st["failures"] == 0 and st["googleSkipped"] is True, st


def test_reverse_control_google_working_is_never_skipped(client, backlog, real_path, monkeypatch):
    _set_google_key(monkeypatch=monkeypatch)
    monkeypatch.setattr(geo, "quota_exceeded", lambda *a, **k: False)
    calls = _two_sources(monkeypatch, lambda: GOOGLE_OK, lambda a: HIT)
    st = geo.warm_geocode_cache()
    assert len(calls["google"]) == 6 and calls["nominatim"] == [] and st["googleSkipped"] is False, (calls, st)


def test_reverse_control_a_google_success_between_failures_resets_the_google_streak(client, backlog, real_path, monkeypatch):
    _set_google_key(monkeypatch=monkeypatch)
    monkeypatch.setattr(geo, "quota_exceeded", lambda *a, **k: False)
    plan = iter(["fail", "fail", "ok", "fail", "fail", "ok"])
    calls = _two_sources(monkeypatch, lambda: GOOGLE_OK if next(plan) == "ok" else urllib.error.URLError("x"), lambda a: HIT)
    st = geo.warm_geocode_cache()
    assert len(calls["google"]) == 6 and st["googleSkipped"] is False, (calls, st)


# ── ③ 額度明填 0 要說得出來（不是「本週期用完」，也不會自動恢復）──────────────────────

@pytest.mark.parametrize("quota,zero,degraded", [
    ({"monthly_free_quota": 0}, True, True),
    ({"sku_quotas": {"google:geocoding": "0"}}, True, True),
    ({}, False, False),                                   # 沒填＝不管制（GB7）
    ({"monthly_free_quota": 5}, False, False),            # 反向控制：有額度、還沒用完
])
def test_quota_status_says_zero_quota_separately(client, quota, zero, degraded):
    from helpers.settings import _set_setting
    _set_setting(geo.QUOTA_SETTING, quota)
    st = geo.quota_status()
    assert st["disabledByZero"] is zero and st["degraded"] is degraded, st


def test_quota_used_up_is_degraded_but_not_zero(client, monkeypatch):
    """反向控制：真的用完（5／5）⇒ degraded、但不是「設定為 0」——畫面要顯示「下個週期恢復」那一則。"""
    from helpers.settings import _set_setting
    _set_setting(geo.QUOTA_SETTING, {"monthly_free_quota": 5})
    monkeypatch.setattr(geo, "usage_this_period", lambda source=None: 5)
    st = geo.quota_status()
    assert st["degraded"] is True and st["disabledByZero"] is False, st


def test_map_endpoint_carries_zero_quota_and_the_page_shows_its_own_note(client, make_user, monkeypatch):
    from helpers.settings import _set_setting
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)            # 地圖端點會探圖磚：不連外
    _set_setting(geo.QUOTA_SETTING, {"monthly_free_quota": 0})
    u, p = make_user(username="quota_zero_boss", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    body = client.get("/api/map/points?sources=suppliers", headers={"Authorization": "Bearer " + tok}).json()
    assert body["quota"]["disabledByZero"] is True and body["quota"]["degraded"] is True, body["quota"]
    src = (FRONT / "pages" / "map.html").read_text(encoding="utf-8")
    zero = src[src.index('data-testid="map-quota-zero"'):]
    assert "info.quota.disabledByZero" in zero[:200] and "Google 定位已停用" in zero[:400] and "不會自動恢復" in zero[:600]
    deg = src[src.index('data-testid="map-quota-degraded"'):]
    assert "!info.quota.disabledByZero" in deg[:200], "額度 0 時不可以同時顯示「下個週期自動恢復」那一則"
