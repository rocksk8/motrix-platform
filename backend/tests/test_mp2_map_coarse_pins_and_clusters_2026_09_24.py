# -*- coding: utf-8 -*-
"""`MP2` · 粗精度點變淡（空心）＋重疊點群聚。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP2：
「`precisionIsCoarse` 的點用淡色／空心 pin；重疊點群聚（Leaflet.markercluster 自架於 vendor，
照 leaflet 的 PROVENANCE 模式）」。

⚙️ 觀測點：圖上的標記（`.mp-pin`／`.mp-pin--coarse`／`.marker-cluster`），不是元件的狀態。
⚙️ 對照組：細精度照舊實心；群聚外掛載不到時點照樣全部畫出來（退回一般圖層）。
"""
import hashlib
import json
import pathlib
import re

import pytest

from helpers import geo

VENDOR = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "static" / "vendor"
          / "leaflet.markercluster-1.5.3")


def test_mp2_vendored_cluster_files_match_their_recorded_hashes():
    """憑證要對得上：PROVENANCE 記的雜湊＝repo 裡的位元組（`.gitattributes -text` 保住它）。"""
    prov = (VENDOR / "PROVENANCE.md").read_text(encoding="utf-8")
    rows = re.findall(r"^([0-9a-f]{64})  (\S+)\s+(\d+) bytes$", prov, re.M)
    assert len(rows) == 4, "量尺：PROVENANCE 應記 4 個檔：%r" % rows
    for digest, name, size in rows:
        data = (VENDOR / name).read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, int(size)), name


def test_mp2_the_cluster_dir_is_kept_byte_for_byte():
    attrs = (pathlib.Path(__file__).resolve().parents[2] / ".gitattributes").read_text(encoding="utf-8")
    assert "frontend/static/vendor/leaflet.markercluster-1.5.3/** -text" in attrs


pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


def _pt(i, lat, lon, precision="street"):
    return {"dataset": "customers_delivery", "sourceKey": "customers", "recordId": i,
            "name": "點%d" % i, "address": "台中市", "lat": lat, "lon": lon, "precision": precision,
            "distanceFromUserKm": None, "distanceFromOfficeKm": None}


#: 五個擠在一起（約 100 公尺內；其中 3／4／5 **完全同址**——同一機關的標案就是這樣，
#: 放到最大仍分不開，要靠散開）＋ 一個遠的粗精度點 ＋ 一個遠的細精度點（對照組，不會被群聚吃掉）。
_POINTS = [_pt(i, 24.1800 + min(i, 3) * 0.0002, 120.6400) for i in range(1, 6)] + [
    _pt(9, 22.5700, 120.3300, precision="district"), _pt(8, 23.5000, 121.0000)]


@pytest.fixture()
def _no_tiles(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)


def _open(page, live_server, query="", block_cluster=False):
    page.route("**/api/map/points*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"points": _POINTS, "locations": [], "sources": []})))
    page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
    if block_cluster:
        page.route("**/leaflet.markercluster-1.5.3/**", lambda route: route.abort())
    page.goto(live_server + "/pages/map.html" + query)
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                           " && d.info.points.length === 7 }", timeout=15000)
    page.evaluate("() => { const d = " + _D + "; if (!d.mapOpen) d.openMap() }")
    page.wait_for_function("() => document.querySelectorAll('.leaflet-marker-icon').length > 0",
                           timeout=15000)
    page.wait_for_timeout(800)


def _state(page):
    return page.evaluate("""() => ({
        pins: document.querySelectorAll('.leaflet-marker-icon .mp-pin').length,
        coarse: Array.from(document.querySelectorAll('.leaflet-marker-icon .mp-pin--coarse'))
                  .map(e => ({text: e.textContent, op: getComputedStyle(e).opacity,
                              bg: getComputedStyle(e).backgroundColor})),
        solid: Array.from(document.querySelectorAll('.leaflet-marker-icon .mp-pin:not(.mp-pin--coarse)'))
                  .map(e => getComputedStyle(e).opacity),
        clusters: Array.from(document.querySelectorAll('.marker-cluster')).map(e => e.textContent.trim()),
    })""")


@pytest.mark.e2e
def test_mp2_coarse_points_are_hollow_and_faded_and_overlapping_points_cluster(
        live_server, make_user, _no_tiles):
    u, p = make_user(username="mp2_main", role="superadmin")
    with sync_playwright() as pw_:
        browser = pw_.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            _login(page, live_server, u, p)
            _open(page, live_server)
            st = _state(page)
            print("MP2 實測：%r" % st)
            assert len(st["coarse"]) == 1, "區級那一點要是空心圖釘：%r" % st
            assert float(st["coarse"][0]["op"]) < 1 and st["coarse"][0]["bg"] == "rgb(255, 255, 255)", st
            assert st["solid"] and all(float(o) == 1 for o in st["solid"]), "對照組：細精度照舊實心不透明：%r" % st
            assert st["clusters"] == ["5"], "擠在一起的五個點要合成一個「5」：%r" % st

            # 焦點在群聚裡的那一點 ⇒ 群聚展開、彈窗打開（MP1 的 ?focus= 不因群聚失效）。
            _open(page, live_server, "?focus=customers%3A4")
            pop = page.locator(".leaflet-popup-content")
            pop.first.wait_for(state="visible", timeout=8000)
            assert "點4" in pop.first.inner_text(), pop.first.inner_text()
        finally:
            browser.close()


@pytest.mark.e2e
def test_mp2_without_the_cluster_plugin_every_point_is_still_drawn(live_server, make_user, _no_tiles):
    """群聚外掛載不到（被擋／檔案不在）⇒ 退回一般圖層，七個點全部畫出來，不可以整張圖空白。"""
    u, p = make_user(username="mp2_noclu", role="superadmin")
    with sync_playwright() as pw_:
        browser = pw_.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            _login(page, live_server, u, p)
            _open(page, live_server, block_cluster=True)
            st = _state(page)
            err = page.evaluate("() => " + _D + ".loadError")
            print("MP2 無群聚外掛實測：%r／loadError %r" % (st, err))
            assert st["pins"] == 7 and st["clusters"] == [], st
            assert not err, err
        finally:
            browser.close()
