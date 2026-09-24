# -*- coding: utf-8 -*-
"""`MP1` · 地圖點位連到單據（雙向）。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP1：
「回傳帶記錄 id；彈窗與表格可點開客戶／供應商／標案／出貨單；單據頁加『在地圖上看』
（`map.html?focus=kind:key`）」。

# 做法
- 後端：自有資料的點帶 `recordId`（出貨單另帶 `quoteNo`——它沒有自己的頁，落在案件的出貨分頁）；
  標案沿用 `caseNo`。客戶的送貨／發票兩個點帶**同一個** id。
- 前端共用 `static/record-link.js`：點 → 單據網址（**照各單據頁自己的入口檢查**，看不到那一頁的人
  不給連結）；`focusKey` ＝ `<sourceKey>:<recordId|caseNo>`，地圖 `?focus=` 與單據頁共用同一種寫法。
- 地圖 `?focus=` ⇒ 視野移到那一點並打開彈窗；單據頁 `?id=`／`?case=` ⇒ 直接打開那一筆。
  **兩邊找不到都要說出來**（`.motrix-deeplink-miss`），不可以靜靜停在清單上。

⚙️ 對照組：焦點沒指定時地圖照常（不開彈窗）；看得到那一頁的人**有**連結（不是全部都拿掉）。
"""
import json

import pytest

from helpers import geo
from tests._map_cache_warm import serve_from_fake

_ADDR = {
    "台中市西屯區": (24.1815, 120.6400),
    "台中市南屯區": (24.1380, 120.6430),
    "台中市梧棲區": (24.2550, 120.5310),
    "高雄市前鎮區": (22.5743, 120.3352),
}



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。"""
    page.evaluate("() => new Promise(r => Alpine.nextTick(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

@pytest.fixture()
def _geo(monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    monkeypatch.setattr(geo, "GEO_ENABLED", True)
    monkeypatch.setattr(geo, "_CACHE", {})

    def _fake(address, manual_coord=None):
        key = (address or "").strip()
        hit = _ADDR.get(key)
        if not hit:
            return geo.GeoResult(error="查表沒有：%r" % key, address=key)
        return geo.GeoResult(coord=hit, precision=geo.PRECISION_STREET,
                             source=geo.SOURCE_NOMINATIM, address=key)

    monkeypatch.setattr(geo, "locate_cached", _fake)
    serve_from_fake(monkeypatch, _fake)


def _auth(client, make_user):
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed():
    """回 `{來源: 那一筆的 id}`。"""
    import db
    conn = db.get_db()
    try:
        ids = {}
        # 先塞一筆沒有地址的，讓「id 剛好等於 1」這種巧合不成立。
        conn.execute("INSERT INTO vendor_contractors (name, address, active, created_at)"
                     " VALUES ('墊號', '', 1, '2026-09-24')")
        ids["vendor_contractors"] = conn.execute(
            "INSERT INTO vendor_contractors (name, address, active, created_at)"
            " VALUES ('MP1承攬商', '台中市西屯區', 1, '2026-09-24')").lastrowid
        ids["contractors"] = conn.execute(
            "INSERT INTO contractors (name, address, active, created_at)"
            " VALUES ('MP1外包', '台中市梧棲區', 1, '2026-09-24')").lastrowid
        ids["shipping_notes"] = conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, customer_name,"
            " delivery_address, items_json, created_at) VALUES (?,?,?,?,?,?,?)",
            ("MP1-SN-1", "MQ-MP1-001", "草稿", "MP1出貨客戶", "台中市南屯區", "[]",
             "2026-09-24")).lastrowid
        ids["customers"] = conn.execute(
            "INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
            ("MP1客戶", json.dumps({"deliveryAddress": "台中市西屯區",
                                   "invoiceAddress": "高雄市前鎮區"}, ensure_ascii=False),
             "2026-09-24")).lastrowid
        ids["suppliers"] = conn.execute(
            "INSERT INTO suppliers (name, data_json, created_at) VALUES (?,?,?)",
            ("MP1供應商", json.dumps({"address": "台中市南屯區"}, ensure_ascii=False),
             "2026-09-24")).lastrowid
        conn.commit()
        return ids
    finally:
        conn.close()


def test_mp1_every_own_point_carries_the_id_of_its_record(client, make_user, _geo):
    ids = _seed()
    hdr = _auth(client, make_user)
    r = client.get("/api/map/points?sources=contractors,vendor_contractors,shipping_notes,"
                   "customers,suppliers", headers=hdr)
    assert r.status_code == 200, r.text
    pts = r.json()["points"]
    got = {}
    for p in pts:
        got.setdefault(p.get("sourceKey"), set()).add(p.get("recordId"))
    print("MP1 實測：各來源點位的 recordId %r；應為 %r" % (got, ids))
    for src, rid in ids.items():
        assert got.get(src) == {rid}, "%s 的點位沒有帶回自己那一筆的 id：%r（應為 %r）" % (
            src, got.get(src), rid)
    cust = [p for p in pts if p.get("sourceKey") == "customers"]
    assert len(cust) == 2, "客戶送貨＋發票兩個點（量尺）：%r" % cust
    ship = [p for p in pts if p.get("sourceKey") == "shipping_notes"]
    assert ship and ship[0].get("quoteNo") == "MQ-MP1-001", (
        "出貨單要帶所屬案件的 quote_no（它沒有自己的頁）：%r" % ship)


# ══════════════════════════════════════════════════════════════════════
# 頁面（e2e）
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests._map_tiles import block_tiles  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402,F401

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


def _body(points):
    return json.dumps({"points": points, "locations": [], "sources": []})


_POINT = {"dataset": "customers_delivery", "sourceKey": "customers", "recordId": 7,
          "name": "焦點客戶", "address": "台中市西屯區", "lat": 24.18, "lon": 120.64,
          "precision": "street", "distanceFromUserKm": None, "distanceFromOfficeKm": None}
_OTHER = dict(_POINT, recordId=8, name="別的客戶", lat=22.57, lon=120.33)


def _open_map(page, live_server, query):
    page.route("**/api/map/points*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=_body([_OTHER, _POINT])))
    page.goto(live_server + "/pages/map.html" + query)
    page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                           " && d.info.points.length === 2 }", timeout=15000)
    # 自動開圖有斷路器（上次圖磚載不到就不自動開）⇒ 測試環境明著開，量的是焦點不是自動開。
    page.evaluate("() => { const d = " + _D + "; if (!d.mapOpen) d.openMap() }")
    # ⚠️ 等「兩個點都畫進圖層」，不是等 DOM 裡有兩個圖釘：MP2 之後資料點在群聚圖層裡，
    #    群聚只把**視野內**的標記放進 DOM ⇒ 定位到其中一點後，另一點不在 DOM 是正常的。
    page.wait_for_function("() => { const d = " + _D + ";"
                           " return d._markerByKey && Object.keys(d._markerByKey).length === 2 }",
                           timeout=15000)
    page.wait_for_timeout(500)


@pytest.mark.e2e
def test_mp1_map_focus_opens_that_point_with_a_link_to_its_record(live_server, make_user, _geo, e2e_browser):
    u, p = make_user(username="mp1_focus", role="superadmin")
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    block_tiles(page)   # 地圖圖磚不連外（conftest._browser_netguard）
    _login(page, live_server, u, p)
    _open_map(page, live_server, "?focus=customers%3A7")
    pops = page.locator(".leaflet-popup-content")
    pops.first.wait_for(state="visible", timeout=5000)
    text = pops.first.inner_text()
    href = pops.first.locator("a.mp-rec").get_attribute("href")
    rows = page.locator("a.mp-rec:visible").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    print("MP1 地圖實測：彈窗 %r／連結 %r／表格連結 %r" % (text[:40], href, rows))
    assert "焦點客戶" in text, "?focus= 要打開**那一點**的彈窗，不是別的：%r" % text
    assert href == "customers.html?id=7", href
    assert "customers.html?id=8" in rows and "customers.html?id=7" in rows, rows
    # 對照組：沒有 focus ⇒ 不自己開彈窗。
    _open_map(page, live_server, "")
    assert page.locator(".leaflet-popup-content").count() == 0
    # 找不到 ⇒ 說出來。
    _open_map(page, live_server, "?focus=customers%3A999")
    miss = page.locator(".motrix-deeplink-miss")
    miss.wait_for(state="visible", timeout=5000)
    assert page.locator(".leaflet-popup-content").count() == 0


@pytest.mark.e2e
def test_mp1_record_links_follow_each_page_gate(live_server, make_user, _geo, e2e_browser):
    """看不到那一頁的人不給連結（協力廠商頁限管理員；外包名冊頁要模組；標案雷達要 dev_crm）。"""
    u, p = make_user(username="mp1_gate", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    block_tiles(page)   # 地圖圖磚不連外（conftest._browser_netguard）
    _login(page, live_server, u, p)
    page.goto(live_server + "/pages/map.html")
    page.wait_for_function("() => window.MotrixRecordLink", timeout=15000)
    got = page.evaluate("""() => {
        const L = window.MotrixRecordLink
        const v = {sourceKey: 'vendor_contractors', recordId: 3}
        const c = {sourceKey: 'contractors', recordId: 4}
        const t = {sourceKey: 'tenders', caseNo: 'A/1'}
        const s = {sourceKey: 'shipping_notes', recordId: 5, quoteNo: 'MQ-1'}
        const user = {role: 'user', modules: ['procurement']}
        const admin = {role: 'admin', modules: []}
        return {
          vUser: L.recordUrl(v, user), vAdmin: L.recordUrl(v, admin),
          cUser: L.recordUrl(c, user), cMod: L.recordUrl(c, {role: 'user', modules: ['contractor_list']}),
          tUser: L.recordUrl(t, user), tDev: L.recordUrl(t, {role: 'user', modules: ['dev_crm']}),
          sUser: L.recordUrl(s, user), fk: L.focusKey(t),
        }
    }""")
    print("MP1 權限對照：%r" % got)
    assert got["vUser"] is None and got["vAdmin"] == "vendor-contractors.html?id=3", got
    assert got["cUser"] is None and got["cMod"] == "contractors.html?id=4", got
    assert got["tUser"] is None and got["tDev"] == "tender-radar.html?case=A%2F1", got
    assert got["sUser"] == "case-management.html?q=MQ-1&tab=shipping", got
    assert got["fk"] == "tenders:A/1", got


@pytest.mark.e2e
def test_mp1_source_pages_open_the_record_from_the_link_and_link_back(live_server, make_user, _geo, e2e_browser):
    # `_geo`：標案雷達頁會畫自己的小地圖，後端會探測圖磚——換掉，不對外連線（NETGUARD）。
    ids = _seed()
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at)"
                     " VALUES ('MP1-T-9', 'MP1標案', 'MP1機關', '台中市', '2026-09-24')")
        # 第二筆：「只有那一列被標示」要有別列可以比（只有一列時「全部標示」也會過——突變 M5 抓到）。
        conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at)"
                     " VALUES ('MP1-T-8', 'MP1別的標案', 'MP1機關', '台中市', '2026-09-24')")
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(username="mp1_pages", role="superadmin")
    cases = [
        ("customers.html?id=%d" % ids["customers"], "MP1客戶", "customers%%3A%d" % ids["customers"]),
        ("suppliers.html?id=%d" % ids["suppliers"], "MP1供應商", "suppliers%%3A%d" % ids["suppliers"]),
        ("contractors.html?id=%d" % ids["contractors"], "MP1外包", "contractors%%3A%d" % ids["contractors"]),
        ("vendor-contractors.html?id=%d" % ids["vendor_contractors"], "MP1承攬商",
         "vendor_contractors%%3A%d" % ids["vendor_contractors"]),
    ]
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    block_tiles(page)   # 地圖圖磚不連外（conftest._browser_netguard）
    _login(page, live_server, u, p)
    for url, name, focus in cases:
        page.goto(live_server + "/pages/" + url)
        pane = page.locator(".detail-pane.open")
        pane.wait_for(state="visible", timeout=15000)
        _rendered(page)   # PERF #6：原本固定等 300ms
        text = pane.inner_text()
        href = pane.locator("a.mp1-onmap").get_attribute("href")
        print("MP1 %s：明細 %r／在地圖上看 %r" % (url, text[:30], href))
        assert name in text, "%s 要直接打開那一筆：%r" % (url, text[:80])
        assert href == "map.html?focus=" + focus, (url, href)
    # 找不到 ⇒ 說出來。
    page.goto(live_server + "/pages/customers.html?id=99999")
    page.locator(".motrix-deeplink-miss").wait_for(state="visible", timeout=15000)
    assert page.locator(".detail-pane.open").count() == 0
    # 標案雷達：`?case=` ⇒ 那一列被標示並有回地圖的連結。
    page.goto(live_server + "/pages/tender-radar.html?case=MP1-T-9")
    page.wait_for_function(
        "() => { const r = document.querySelector('tr[data-case-no=\"MP1-T-9\"]');"
        " return r && r.style.outline.indexOf('2px') >= 0 }", timeout=15000)
    href = page.locator('tr[data-case-no="MP1-T-9"] a.mp1-onmap').get_attribute("href")
    assert href == "map.html?focus=tenders%3AMP1-T-9", href
    other = page.locator("tr[data-case-no]").evaluate_all(
        "els => els.filter(e => e.style.outline).map(e => e.dataset.caseNo)")
    rows_n = page.locator("tr[data-case-no]").count()
    assert rows_n >= 2 and other == ["MP1-T-9"], "只有那一列被標示（共 %d 列）：%r" % (rows_n, other)


def test_mp1_the_shipping_note_links_to_its_point_on_the_map():
    """出貨單列在案件頁的出貨分頁（沒有自己的頁）⇒「在地圖上看」寫在那裡，焦點鍵與地圖一致。"""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "pages"
            / "case-management.html").read_text(encoding="utf-8")
    assert "encodeURIComponent('shipping_notes:' + n.id)" in html
