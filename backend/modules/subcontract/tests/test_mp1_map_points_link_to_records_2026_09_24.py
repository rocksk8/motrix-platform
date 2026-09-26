# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_mp1_map_points_link_to_records_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
`MP1` · 地圖點位連到單據（雙向）。

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


# ══════════════════════════════════════════════════════════════════════
# 頁面（e2e）
# ══════════════════════════════════════════════════════════════════════

# 稽核 Y-4（2026-09-25）：importorskip 原本在**模組層** ⇒ 沒有 playwright 時，上面的 API 題（以及 import 本檔
# `_geo` 的 test_mp6 的地圖可見性題）整檔一起 skip。改成 e2e 題內呼叫 `_page_deps()`，只跳過 e2e 題。
def _page_deps():
    pytest.importorskip("playwright.sync_api")
    from tests._map_tiles import block_tiles
    from tests._e2e_login import inject_login as _login
    return block_tiles, _login

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
def test_mp1_record_links_follow_each_page_gate(live_server, make_user, _geo, e2e_browser):
    block_tiles, _login = _page_deps()
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
    block_tiles, _login = _page_deps()
    # `_geo`：標案雷達頁會畫自己的小地圖，後端會探測圖磚——換掉，不對外連線（NETGUARD）。
    ids = _seed()
    u, p = make_user(username="mp1_pages", role="superadmin")
    cases = [
        ("customers.html?id=%d" % ids["customers"], "MP1客戶", "customers%%3A%d" % ids["customers"]),
        ("suppliers.html?id=%d" % ids["suppliers"], "MP1供應商", "suppliers%%3A%d" % ids["suppliers"]),
        ("contractors.html?id=%d" % ids["contractors"], "MP1外包", "contractors%%3A%d" % ids["contractors"]),
        ("vendor-contractors.html?id=%d" % ids["vendor_contractors"], "MP1承攬商",
         "vendor_contractors%%3A%d" % ids["vendor_contractors"]),
    ]
    from core import source_tree
    if not source_tree.module_installed("modules/supply/"):     # 供應商頁屬 M03：不在時是提示頁（PLAYBOOK §B-11）
        cases = [c for c in cases if not c[0].startswith("suppliers.html")]
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
    # 標案雷達那一段（`?case=` ⇒ 那一列被標示並有回地圖的連結）屬 M11：
    # modules/tender_radar/tests/test_tender_mp1_case_link_2026_09_24.py（2026-09-25 拆出）
