# -*- coding: utf-8 -*-
"""L1 `geo.map_request_scope`：地圖頁送來的請求，頁面底圖只准收窄設定（LODGING-NEARBY §3.1.1，D 稽核 LG2-M1）。

- 判定只有一支，/api/map/points（missing="setting"）與附近旅宿搜尋（missing="osm"）共用。
- map_points 的 None／google／osm 行為不變（既有 GB-M2 題 test_map_google_basemap_2026_09_28 不改而全過）；
  唯一差異：不認得的值（含空字串 `basemap=`）原本可用 Google，現在視同 osm（LG3-O1）——本檔 test_map_points_empty_… 守它。
"""
import pytest

from helpers import geo
# 沿用 GB-M2 題的夾具（同一個情境：設定剛切 google、快取裡有一筆只有 Google 座標的客戶地址）
from tests.test_map_google_basemap_2026_09_28 import BROWSER_KEY, _set_keys, gpoint, h  # noqa: F401


@pytest.mark.parametrize("setting_google", [True, False])
@pytest.mark.parametrize("page,missing,expect_if_setting", [
    ("google", "osm", True), ("google", "setting", True),
    ("osm", "osm", False), ("osm", "setting", False),
    (None, "osm", False), (None, "setting", True),
    ("", "setting", False), ("GOOGLE", "setting", False), (" google", "setting", False), ("x", "osm", False),
])
def test_map_request_scope_only_narrows(monkeypatch, setting_google, page, missing, expect_if_setting):
    monkeypatch.setattr(geo, "google_basemap", lambda: setting_google)
    with geo.map_request_scope(page, missing=missing) as ok:
        assert ok is (setting_google and expect_if_setting)
        assert geo.google_content_blocked() is (not ok)      # 不准用 ⇒ 範圍內真的擋住
    assert geo.google_content_blocked() is False             # 離開範圍就還原


def test_map_request_scope_restores_after_exception(monkeypatch):
    monkeypatch.setattr(geo, "google_basemap", lambda: True)
    with pytest.raises(RuntimeError):
        with geo.map_request_scope("osm"):
            raise RuntimeError("boom")
    assert geo.google_content_blocked() is False


def test_map_request_scope_default_missing_is_fail_closed(monkeypatch):
    monkeypatch.setattr(geo, "google_basemap", lambda: True)
    with geo.map_request_scope(None) as ok:
        assert ok is False


def _points_raw(client, h, query):
    from tests._map_cache_warm import clear_map_response_cache
    clear_map_response_cache()
    r = client.get("/api/map/points?sources=customers" + query, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_map_points_empty_or_unknown_basemap_now_narrows(client, h, gpoint):
    """LG3-O1：`basemap=`（空字串）與不認得的值，原本等同「沒帶＝照設定」而可用 Google；現在視同 osm。"""
    _set_keys(browser=BROWSER_KEY)                                   # 設定是 google
    for q in ("&basemap=", "&basemap=GOOGLE", "&basemap=x"):
        body = _points_raw(client, h, q)
        assert body["basemap"] == "osm", q
        assert not [p for p in body["points"] if p["source"] == geo.SOURCE_GOOGLE], q
    # 反向控制：沒帶（None）照設定、帶 google 可用
    assert _points_raw(client, h, "")["basemap"] == "google"
    assert _points_raw(client, h, "&basemap=google")["basemap"] == "google"
