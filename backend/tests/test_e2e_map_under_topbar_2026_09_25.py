"""地圖往下捲時不可以蓋住頂欄（使用者 2026-09-25：「標案地圖開啟後，向下拖曳，地圖會把上橫欄蓋住穿模」）。

Leaflet 的 pane／控制項自帶 z-index（400～1000），比頂欄（100）高；地圖容器沒有自己的堆疊層 ⇒
這些 z-index 跟頂欄在同一層比較，捲到頂欄底下時地圖浮在頂欄上面。
觀測點：頂欄／導覽列範圍內的 document.elementFromPoint 要落在頂欄或導覽列裡。
反向控制：「全螢幕」仍要蓋住整頁（包含頂欄）。
外網：地理編碼用替身、圖磚攔截成 1×1 PNG。
"""
import base64
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_mark_all_read_2026_09_24 import live_server  # noqa: F401  (live_server 是 fixture)

MD = "Alpine.$data(document.querySelector('.mp-wrap'))"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
ADDR = {"台中市北區三民路三段1號": (24.1570, 120.6840), "台中市北區三民路三段5號": (24.1574, 120.6844)}

# 頂欄與導覽列範圍內、地圖水平範圍內的取樣點：各點最上層的元素是否在 .topbar／.mnav 裡
# ⚠ Leaflet 的圖磚是 pointer-events:none ⇒ elementFromPoint 看不到它，只驗得到控制項（假綠）。
#   取樣前讓地圖內所有元素都可被 hit-test：只改點擊判定，不改堆疊順序。
HITS = """() => {
  if (!document.getElementById('probe-pe')) {
    const st = document.createElement('style'); st.id = 'probe-pe'
    st.textContent = '#mp-canvas, #mp-canvas * { pointer-events: auto !important }'
    document.head.appendChild(st)
  }
  const m =document.getElementById('mp-canvas').getBoundingClientRect()
  const hdr = document.querySelector('.mnav').getBoundingClientRect().bottom
  const out = []
  const top = Math.max(2, Math.ceil(m.top) + 2)          // 只取地圖與頂欄重疊的那一段
  for (const y of [top, Math.round((top + hdr) / 2), hdr - 4]) {
    for (const x of [m.left + 20, m.left + 60, (m.left + m.right) / 2, m.right - 20]) {
      const e = document.elementFromPoint(x, y)
      out.push({ x: Math.round(x), y, ok: !!(e && e.closest('.topbar, .mnav')), el: e ? (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) : null })
    }
  }
  return { mapTop: m.top, hdr, out } }"""


@pytest.fixture()
def _geo(monkeypatch):
    from helpers import geo
    from tests._map_cache_warm import serve_from_fake
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        hit = ADDR.get(key)
        if not hit:
            return geo.GeoResult(error="查表沒有：%r" % key, address=key)
        return geo.GeoResult(coord=hit, precision=geo.PRECISION_STREET, source=geo.SOURCE_NOMINATIM, address=key)

    monkeypatch.setattr(geo, "locate_cached", _fake)
    serve_from_fake(monkeypatch, _fake)


def _seed():
    import db
    conn = db.get_db()
    try:
        for i, a in enumerate(ADDR):
            conn.execute("INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
                         (f"穿模客戶{i}", json.dumps({"deliveryAddress": a}, ensure_ascii=False), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _open(browser, base, u):
    ctx = browser.new_context(viewport={"width": 1440, "height": 520})
    ctx.route("**/tile.openstreetmap.org/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    page = ctx.new_page()
    page.goto(f"{base}/pages/login.html")
    page.fill('input[x-model="username"]', u[0])
    page.fill('input[x-model="password"]', u[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    page.goto(f"{base}/pages/map.html")
    page.wait_for_function(f"() => {{ try {{ return {MD}._map }} catch (e) {{ return false }} }}", timeout=20000)
    page.wait_for_timeout(1200)
    return page


@pytest.mark.e2e
def test_scrolling_the_map_under_the_topbar_does_not_cover_it(live_server, make_user, _geo):
    u = make_user(username="mut_e1", role="superadmin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            # 捲到地圖頂端跑到頂欄正中間（使用者「向下拖曳」之後的樣子）
            page.evaluate("() => { const t = document.getElementById('mp-canvas').getBoundingClientRect().top; window.scrollBy(0, t - 30) }")
            page.wait_for_timeout(400)
            r = page.evaluate(HITS)
            assert r["mapTop"] < r["hdr"] - 20, ("前提：地圖要捲到頂欄底下", r["mapTop"], r["hdr"])
            bad = [h for h in r["out"] if not h["ok"]]
            assert not bad, ("頂欄範圍內被地圖蓋住（穿模）", bad)
        finally:
            browser.close()


@pytest.mark.e2e
def test_fullscreen_map_still_covers_the_whole_page(live_server, make_user, _geo):
    """反向控制：全螢幕是刻意蓋住頂欄的，修穿模不可以連它一起壓下去。"""
    u = make_user(username="mut_e2", role="superadmin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            page.locator("button.mp-full-btn").click()
            page.wait_for_timeout(500)
            hit = page.evaluate("() => { const e = document.elementFromPoint(720, 20); return !!(e && e.closest('.mp-map-panel')) }")
            assert hit, "全螢幕時頂欄位置應是地圖面板"
        finally:
            browser.close()
