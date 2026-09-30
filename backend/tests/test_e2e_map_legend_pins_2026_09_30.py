# -*- coding: utf-8 -*-
"""地圖頁：圖例與圖釘要看得清楚（使用者 2026-09-30，第 27 班）。

使用者截圖：Google 底圖上我們的「標」圖釘（34px 紅圓）被滿地 POI 水滴淹掉；圖例太小太淡；放大後圖釘也看不出來。
改法：圓角方塊圖釘（跟 Google 的水滴／圓形分開）、尺寸隨縮放（≤12 → 44px、13–15 → 50px、≥16 → 56px）、
名稱標籤（名稱最多 16 字＋…，第二行 機關 · 截止日；重疊只留截止最近的一個，其餘滑過才顯示）、圖例用同一形狀 28px。

驗（畫面終點，量 getBoundingClientRect／computed style）：
① 圖例：圖釘 ≥26px、標記字 ≥14px 粗體、名稱 13px、標題 13px 粗體、標籤範例存在；窄螢幕不橫向溢出；
② 圖釘尺寸在縮放 10／14／17 各達門檻（Leaflet 與 Google 兩條路）；
③ 名稱標籤文字＝標案名稱（≤16 字全文、>16 字前 16 字＋…、HTML 已跳脫）；
④ Leaflet：兩個標籤重疊 ⇒ 只顯示截止最近的一個，另一個滑過圖釘才顯示；
⑤ Google：標記 zIndex 高於據點（500）、容器標了 data-mp-bm=google；
⑥ 反向控制：把 --mp-pin 拿掉（舊的 20px 規格）⇒ 尺寸斷言必須變紅。
底圖圖磚與 Google JS 都用假的（不連外）——只證明我們的畫面邏輯，不證明真 Google；真 Google 的 POI 密度見 docs／回報。
截圖：D:\\開發測試檔\\shots\\wip-w3-map-legend\\。
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_map_google_basemap_2026_09_28 import (  # noqa: E402
    BROWSER_KEY, FAKE_CLUSTER, FAKE_GMAPS, MAP_ID, MD, PNG, SERVER_KEY, _keys)

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR", r"D:\開發測試檔\shots")) / "wip-w3-map-legend"

#: 假 Google 補上 addListener／setZoom 觸發事件（原假貨沒有；真 Google 的 zoom_changed／idle）
FAKE_GMAPS_EXTRA = r"""
(function () {
  var M = window.google.maps.Map, oz = M.prototype.setZoom;
  M.prototype.addListener = function (ev, fn) { this.__l = this.__l || {}; (this.__l[ev] = this.__l[ev] || []).push(fn) };
  M.prototype.setZoom = function (z) { oz.call(this, z); var l = this.__l || {};
    (l.zoom_changed || []).forEach(function (f) { f() }); (l.idle || []).forEach(function (f) { f() }) };
})();
"""

LONG = "第一標案ABCDEFGHIJKLMNOPQRST"          # 24 字 ⇒ 前 16 字＋…
SHORT = "短標案"
XSS = "<b>x</b>&\"'"
TENDERS = [  # (案號, 名稱, 機關, 座標, 截止幾天後)
    ("T-1", LONG, "臺中市政府", (24.1570, 120.6840), 30),          # 三點都在 1 公里內：z14 相距 70–110px＞群聚半徑 40px，但標籤（約 140px 寬）會互相重疊
    ("T-2", SHORT, "臺中榮總", (24.1570, 120.6901), 3),          # 與 T-1 東西相隔 70px ⇒ 標籤重疊；截止更近 ⇒ 它留下
    ("T-3", XSS, "彰化縣政府", (24.1610, 120.6780), 10),
    ("T-4", "遠處標案", "苗栗縣政府", (24.4000, 120.7000), 20),        # 25 公里外：z10 是單獨的圖釘（其他三個群聚在一起）
]


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.locator("#mp-canvas").scroll_into_view_if_needed()
        page.locator("#mp-canvas").screenshot(path=str(SHOTS / (name + ".png")))
    except Exception:                                            # noqa: BLE001 — 截圖失敗不影響判定
        pass


def _seed(monkeypatch, source, precision):
    from helpers import geo
    from tests._map_cache_warm import clear_map_response_cache
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)
    monkeypatch.setattr(geo, "_CACHE", {})
    clear_map_response_cache()
    import db
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        for no, name, org, (lat, lon), days in TENDERS:
            conn.execute("INSERT OR REPLACE INTO geocode_cache (address, lat, lon, source, precision, created_at) VALUES (?,?,?,?,?,?)",
                         (org, lat, lon, getattr(geo, source), getattr(geo, precision), now))
            conn.execute("INSERT INTO tenders (case_no, name, org, location, deadline, fetched_at) VALUES (?,?,?,?,?,?)",
                         (no, name, org, "", (date.today() + timedelta(days=days)).isoformat(), now))
        conn.commit()
    finally:
        conn.close()


def _open(e2e_browser, base, user, google, viewport=None):
    ctx = e2e_browser.new_context(viewport=viewport or {"width": 1280, "height": 900})
    ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    if google:
        ctx.route(re.compile(r"https://maps\.googleapis\.com/maps/api/js.*"),
                  lambda r: r.fulfill(status=200, content_type="application/javascript", body=FAKE_GMAPS + FAKE_GMAPS_EXTRA))
        ctx.route("**/markerclusterer-2.6.2/markerclusterer.min.js",
                  lambda r: r.fulfill(status=200, content_type="application/javascript", body=FAKE_CLUSTER))
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/map.html")
    btn = page.get_by_role("button", name=re.compile("開啟地圖"))
    try:
        btn.wait_for(state="visible", timeout=4000)
        btn.click()
    except Exception:                                            # noqa: BLE001 — 已自動開啟就沒有這顆按鈕
        pass
    page.wait_for_function(f"() => {{ try {{ const d = {MD}; return d._map && !d.loading && !d.mapLoading }} catch (e) {{ return false }} }}", timeout=20000)
    try:
        page.wait_for_function("() => document.querySelectorAll('#mp-canvas .mp-mk').length >= 1", timeout=20000)
    except Exception:                                            # noqa: BLE001
        print("DBG", page.evaluate(f"() => {{ const d = {MD}; return JSON.stringify({{pts: d.view.points.length, mk: document.querySelectorAll('.mp-mk').length, src: d.info && d.info.sources, wl: d.info && d.info.withoutLocation, err: d.error}}) }}"))
        raise
    return page


def _set_zoom(page, z, google=False):
    # Leaflet：固定看 T-1..T-3 中心（z10 時 T-4 在視野內、z14/17 時只有前三個）；假 Google 只有 setZoom
    page.evaluate(f"() => {{ const m = {MD}._map; " + (f"m.setZoom({z})" if google else f"m.setView([24.159, 120.683], {z}, {{animate: false}})") + " }")
    page.wait_for_function("(z) => { const v = getComputedStyle(document.getElementById('mp-canvas')).getPropertyValue('--mp-pin').trim();"
                           " return v === (z >= 16 ? '56px' : (z >= 13 ? '50px' : '44px')) }", arg=z, timeout=10000)
    page.wait_for_timeout(300)


def _pin_size(page):
    return page.evaluate("() => { const w = [...document.querySelectorAll('#mp-canvas .mp-mk > .mp-pin')].map(e => e.getBoundingClientRect().width);"
                         " return w.length ? Math.min(...w) : 0 }")          # 0 個圖釘 ⇒ 0（不讓「沒有圖釘」通過門檻）


THRESH = {10: 44, 14: 50, 17: 56}


def _check_legend(page):
    lg = page.evaluate("""() => {
      const q = s => [...document.querySelectorAll(s)];
      const pins = q('[data-testid=mp-legend-pin]'), cs = e => getComputedStyle(e);
      const h = document.querySelector('[data-testid=mp-legend-h]'), chip = document.querySelector('[data-testid=mp-legend-chip]');
      const box = document.querySelector('[data-testid=mp-legend]');
      return { n: pins.length, minW: Math.min(...pins.map(e => e.getBoundingClientRect().width)),
               minH: Math.min(...pins.map(e => e.getBoundingClientRect().height)),
               font: Math.min(...pins.map(e => parseFloat(cs(e).fontSize))), weight: Math.min(...pins.map(e => parseInt(cs(e).fontWeight))),
               label: parseFloat(cs(pins[0].nextElementSibling).fontSize), hFont: parseFloat(cs(h).fontSize), hWeight: parseInt(cs(h).fontWeight),
               chip: !!chip && chip.getBoundingClientRect().width > 0, chipFont: chip ? parseFloat(cs(chip).fontSize) : 0,
               overflow: box.scrollWidth > box.clientWidth + 1, radius: cs(pins[0]).borderRadius } }""")
    assert lg["n"] >= 9 and lg["minW"] >= 26 and lg["minH"] >= 26, lg
    assert lg["font"] >= 14 and lg["weight"] >= 700 and lg["label"] >= 13 and lg["hFont"] >= 13 and lg["hWeight"] >= 700, lg
    assert lg["chip"] and lg["chipFont"] >= 13 and not lg["overflow"], lg
    assert lg["radius"] != "50%", "圖釘要是圓角方塊（跟 Google 圓形／水滴分開）"


def _chips(page):
    return page.evaluate("""() => [...document.querySelectorAll('#mp-canvas .mp-mk[data-chip="1"]')].map(m => ({
        title: m.querySelector('.mp-chip-t').textContent, sub: (m.querySelector('small') || {}).textContent || '',
        off: m.querySelector('.mp-chip').classList.contains('mp-chip--off'), full: m.querySelector('.mp-chip').getAttribute('title') }))""")


def _expect_titles():
    return {LONG[:16] + "…", SHORT, XSS}          # 用「包含」比：z10／Google 假底圖還會有 T-4


@pytest.mark.e2e
def test_leaflet_legend_pins_zoom_steps_chips_and_overlap(live_server, make_user, e2e_browser, monkeypatch):
    _keys("")
    _seed(monkeypatch, "SOURCE_NOMINATIM", "PRECISION_STREET")
    u = make_user(username="mlp_l1", role="superadmin")
    page = _open(e2e_browser, live_server, u, google=False)
    assert page.evaluate("() => document.getElementById('mp-canvas').getAttribute('data-mp-bm')") == "leaflet"
    _check_legend(page)
    page.locator("[data-testid=mp-legend]").screenshot(path=str(_mk(SHOTS) / "legend_closeup.png"))
    for z in (10, 14, 17):
        _set_zoom(page, z)
        assert _pin_size(page) >= THRESH[z], (z, _pin_size(page))
        me = page.evaluate("() => (document.querySelector('.mp-ov-pin') || {}).offsetWidth || 99")
        assert me >= 26
        _shot(page, "leaflet_zoom%d" % z)
    chips = _chips(page)
    assert _expect_titles() <= {c["title"] for c in chips}, chips
    assert all(len(c["title"]) <= 17 for c in chips)
    by = {c["title"]: c for c in chips}
    assert by[SHORT]["sub"].startswith("臺中榮總 · ") and by[XSS]["full"] == XSS, by
    # XSS 名稱是字面文字，DOM 裡沒有 <b>
    assert page.evaluate("() => document.querySelectorAll('#mp-canvas .mp-chip b').length") == 0
    # ④ 同一點兩個標籤：只顯示截止最近的（SHORT，3 天）；LONG（30 天）被藏，滑過圖釘才顯示
    _set_zoom(page, 14)
    chips = {c["title"]: c for c in _chips(page)}
    assert chips[SHORT]["off"] is False and chips[LONG[:16] + "…"]["off"] is True, chips
    # 顯示中的標籤不可被任何別人的圖釘或標籤蓋住（真的量矩形，不是只信 class）
    assert page.evaluate("""() => { const hit = (a, b) => !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
        const mks = [...document.querySelectorAll('#mp-canvas .mp-mk[data-chip="1"]')];
        const vis = mks.filter(m => !m.querySelector('.mp-chip').classList.contains('mp-chip--off'));
        return vis.every(m => { const r = m.querySelector('.mp-chip').getBoundingClientRect();
          return mks.every(o => o === m || !hit(r, o.querySelector('.mp-pin').getBoundingClientRect()))
            && vis.every(o => o === m || !hit(r, o.querySelector('.mp-chip').getBoundingClientRect())) }) }""")
    hidden = page.locator("#mp-canvas .mp-mk", has_text=LONG[:16])
    hidden.locator(".mp-pin").hover()
    assert hidden.locator(".mp-chip").is_visible()
    # 彈窗有全文與連結所在（名稱全文）
    page.locator("#mp-canvas .mp-mk", has_text=SHORT).locator(".mp-pin").click()
    page.wait_for_selector(".leaflet-popup", state="visible")
    assert SHORT in page.inner_text(".leaflet-popup")
    _shot(page, "leaflet_popup")


@pytest.mark.e2e
def test_google_path_pins_zoom_steps_chips_and_z_order(live_server, make_user, e2e_browser, monkeypatch):
    _keys(BROWSER_KEY)
    _seed(monkeypatch, "SOURCE_GOOGLE", "PRECISION_ROOFTOP")
    u = make_user(username="mlp_g1", role="superadmin")
    page = _open(e2e_browser, live_server, u, google=True)
    assert page.evaluate("() => document.getElementById('mp-canvas').getAttribute('data-mp-bm')") == "google"
    assert page.evaluate("() => window.__gm.maps[0].opts.clickableIcons") is False
    _check_legend(page)
    for z in (10, 14, 17):
        _set_zoom(page, z, google=True)
        assert _pin_size(page) >= THRESH[z], (z, _pin_size(page))
        _shot(page, "google_zoom%d" % z)
    z = page.evaluate("() => window.__gm.markers.filter(m => m.content.classList && m.content.classList.contains('mp-mk')).map(m => m.zIndex)")
    assert z and min(z) >= 900, "資料點的 zIndex 要高於據點（500）與 Google 自己的標記：%s" % z
    assert _expect_titles() <= {c["title"] for c in _chips(page)}
    assert page.evaluate("() => getComputedStyle(document.querySelector('#mp-canvas .mp-mk')).transform") != "none"


@pytest.mark.e2e
def test_legend_wraps_cleanly_on_a_narrow_screen(live_server, make_user, e2e_browser, monkeypatch):
    _keys("")
    _seed(monkeypatch, "SOURCE_NOMINATIM", "PRECISION_STREET")
    u = make_user(username="mlp_n1", role="superadmin")
    page = _open(e2e_browser, live_server, u, google=False, viewport={"width": 390, "height": 800})
    _check_legend(page)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "窄螢幕不可橫向捲動"
    page.locator("[data-testid=mp-legend]").screenshot(path=str(_mk(SHOTS) / "legend_narrow.png"))


@pytest.mark.e2e
def test_reverse_control_old_20px_spec_would_fail_the_size_assertions(live_server, make_user, e2e_browser, monkeypatch):
    """反向控制：把尺寸變數拿掉、換回舊規格（20px 圓形）⇒ 門檻斷言必須變紅（證明上面的題不是恆真）。"""
    _keys("")
    _seed(monkeypatch, "SOURCE_NOMINATIM", "PRECISION_STREET")
    u = make_user(username="mlp_r1", role="superadmin")
    page = _open(e2e_browser, live_server, u, google=False)
    page.add_style_tag(content="#mp-canvas .mp-mk > .mp-pin { width:20px !important; height:20px !important; border-radius:50% !important }")
    _set_zoom(page, 17)
    assert 0 < _pin_size(page) < THRESH[17]


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    return p
