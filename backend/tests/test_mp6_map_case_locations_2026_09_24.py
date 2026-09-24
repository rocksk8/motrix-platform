# -*- coding: utf-8 -*-
"""`MP6` · 地圖案件地點圖層。

權威原文：`HANDOFF-PENDING-2026-09-23.md`「🟢 MP 地圖優化」MP6：
「報價／案件的交貨地點（`deliveryAddress`／`deliveryLocation`）成新 dataset；權限比照 shipping
（case_manage 或 quotation）；走既有地址定位階梯與背景預熱」。

# 🔴 權限有兩層
1. 資料集門檻：模組 `case_manage` 或 `quotation`（比照出貨單）。
2. **逐筆**：非 admin／superadmin 只看得到自己名下或被分配的案件——與案件管理頁同一條規則
   （`_check_quotation_owner`）。只做第一層的話，業務會在地圖上看到別的業務的客戶與工地地址。
3. ⇒ 回應快取的鍵要含「是誰」（非管理員要到案件時），否則 A 的案件會從快取回給 B。

⚙️ 對照組：admin 看得到全部；沒有模組的人收到 `no_permission`（說出來，不是少一層點）；
   分配變了（assigned_user_ids）快取要失效。
"""
import json

import pytest

from routers import map_points
from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: F401

CASE_A = "MQ-MP6-001"      # 業務甲名下
CASE_B = "MQ-MP6-002"      # 業務乙名下
CASE_ASSIGNED = "MQ-MP6-003"   # 業務乙名下，但分配給甲
CASE_QUOTE_ONLY = "MQ-MP6-004"  # 只有報價單的交貨地點（沒有案件合約地址），甲名下



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。"""
    page.evaluate("() => new Promise(r => Alpine.nextTick(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def test_mp6_case_address_prefers_the_contract_address():
    both = json.dumps({"deliveryLocation": "台中市南屯區",
                       "caseRecord": {"contract": {"deliveryAddress": "台中市西屯區"}}})
    assert map_points._case_address(both) == "台中市西屯區"
    assert map_points._case_address(json.dumps({"deliveryLocation": "台中市南屯區"})) == "台中市南屯區"
    assert map_points._case_address(json.dumps({"caseRecord": {"contract": {"deliveryAddress": " "}},
                                                "deliveryLocation": "高雄市前鎮區"})) == "高雄市前鎮區"
    for broken in ("{壞掉", None, "[]", json.dumps({"caseRecord": "x"})):
        assert map_points._case_address(broken) == "", broken


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _seed(a_id, b_id):
    import db
    conn = db.get_db()
    try:
        rows = [
            (CASE_A, a_id, [], {"caseRecord": {"contract": {"deliveryAddress": "台中市西屯區"}}}),
            (CASE_B, b_id, [], {"caseRecord": {"contract": {"deliveryAddress": "台中市南屯區"}}}),
            (CASE_ASSIGNED, b_id, [a_id], {"deliveryLocation": "台中市梧棲區"}),
            (CASE_QUOTE_ONLY, a_id, [], {"deliveryLocation": "高雄市前鎮區"}),
            ("MQ-MP6-005", a_id, [], {}),            # 沒填地點：不畫、不算定位不到
        ]
        for qn, sp, assigned, data in rows:
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json,"
                " sales_person_id, assigned_user_ids, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (qn, "草稿", "客戶" + qn[-3:], "專案" + qn[-3:], json.dumps(data, ensure_ascii=False),
                 sp, json.dumps(assigned), "2026-09-24", "2026-09-24"))
        conn.commit()
    finally:
        conn.close()


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _cases(client, hdr):
    r = client.get("/api/map/points?sources=cases", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    return (sorted(p["quoteNo"] for p in body["points"] if p.get("sourceKey") == "cases"),
            body, r.headers.get("X-Map-Cache"))


@pytest.fixture()
def people(client, make_user, _geo):
    a = make_user(username="mp6_sales_a", role="user", modules=["case_manage"])
    b = make_user(username="mp6_sales_b", role="user", modules=["case_manage"])
    adm = make_user(username="mp6_admin", role="admin")
    none = make_user(username="mp6_nomod", role="user", modules=["customer"])
    a_id, b_id = _uid(a[0]), _uid(b[0])
    _seed(a_id, b_id)
    return {"a": _login(client, *a), "b": _login(client, *b), "admin": _login(client, *adm),
            "none": _login(client, *none), "a_id": a_id}


def test_mp6_each_salesperson_sees_only_their_own_and_assigned_cases(client, people):
    got_a, body_a, _ = _cases(client, people["a"])
    got_b, _, _ = _cases(client, people["b"])
    got_admin, _, _ = _cases(client, people["admin"])
    print("MP6 實測：甲 %r／乙 %r／admin %r" % (got_a, got_b, got_admin))
    assert got_a == sorted([CASE_A, CASE_ASSIGNED, CASE_QUOTE_ONLY]), got_a
    assert got_b == sorted([CASE_B, CASE_ASSIGNED]), got_b
    assert got_admin == sorted([CASE_A, CASE_B, CASE_ASSIGNED, CASE_QUOTE_ONLY]), got_admin
    pa = {p["quoteNo"]: p for p in body_a["points"]}
    assert pa[CASE_A]["address"] == "台中市西屯區" and pa[CASE_QUOTE_ONLY]["address"] == "高雄市前鎮區"
    assert pa[CASE_A]["recordId"] == CASE_A and pa[CASE_A]["dataset"] == "cases"
    info = [s for s in body_a["sources"] if s["source"] == "cases"][0]
    assert info["skipped"] is None and info["count"] == 3 and info["withoutLocation"] == 0, info


def test_mp6_the_response_cache_never_hands_one_salespersons_cases_to_another(client, people):
    """🔴 同樣模組的兩個業務：甲先開（寫進快取），乙接著開——乙不可以拿到甲的快取。"""
    got_a, _, cache_a = _cases(client, people["a"])
    got_a2, _, cache_a2 = _cases(client, people["a"])
    got_b, _, cache_b = _cases(client, people["b"])
    print("MP6 快取：甲 %s→%s／乙 %s（%r）" % (cache_a, cache_a2, cache_b, got_b))
    assert cache_a2 == "hit", "量尺：同一個人第二次要命中快取，否則這題驗不到快取"
    assert cache_b == "miss" and CASE_A not in got_b and CASE_QUOTE_ONLY not in got_b, got_b


def test_mp6_a_new_assignment_shows_up_without_waiting_for_the_cache(client, people):
    _cases(client, people["a"])
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?",
                     (json.dumps([people["a_id"]]), CASE_B))
        conn.commit()
    finally:
        conn.close()
    got_a, _, cache = _cases(client, people["a"])
    assert CASE_B in got_a and cache == "miss", (got_a, cache)


def test_mp6_without_the_module_it_says_so(client, people):
    got, body, _ = _cases(client, people["none"])
    info = [s for s in body["sources"] if s["source"] == "cases"][0]
    assert got == [] and info["skipped"] == "no_permission", info


def test_mp6_case_addresses_join_the_background_geocode_backlog(client, people):
    backlog = map_points._map_geocode_backlog()
    for addr in ("台中市西屯區", "台中市南屯區", "台中市梧棲區", "高雄市前鎮區"):
        assert addr in backlog, addr


# ══════════════════════════════════════════════════════════════════════
# 頁面（e2e）：圖層預設開著、圖例有「案」、清單連回案件頁
# ══════════════════════════════════════════════════════════════════════

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login as _page_login)

_D = """Alpine.$data(document.querySelector('[x-data="mapPage()"]'))"""


@pytest.mark.e2e
def test_mp6_the_case_layer_is_on_by_default_and_links_to_the_case(live_server, make_user, _geo):
    u, p = make_user(username="mp6_page", role="superadmin")
    body = {"points": [{"dataset": "cases", "sourceKey": "cases", "recordId": "MQ-202609-007",
                        "quoteNo": "MQ-202609-007", "name": "某工地專案", "org": "某客戶",
                        "address": "台中市西屯區", "lat": 24.18, "lon": 120.64, "precision": "street",
                        "distanceFromOfficeKm": 3.2, "distanceFromUserKm": None}],
            "locations": [], "sources": []}
    with sync_playwright() as pw_:
        browser = pw_.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            seen = []
            page.route("**/api/map/points*", lambda route: (seen.append(route.request.url), route.fulfill(
                status=200, content_type="application/json", body=json.dumps(body)))[1])
            page.route("**/tile.openstreetmap.org/**", lambda route: route.abort())
            _page_login(page, live_server, u, p)
            page.goto(live_server + "/pages/map.html")
            page.wait_for_function("() => { const d = " + _D + "; return d.info && d.info.points"
                                   " && d.info.points.length === 1 }", timeout=15000)
            _rendered(page)   # PERF #6：原本固定等 300ms
            got = page.evaluate("""() => { const tr = document.querySelector('tr.mp-row');
                return tr ? {src: tr.querySelectorAll('td')[0].innerText.trim(),
                             href: tr.querySelector('a.mp-rec') && tr.querySelector('a.mp-rec').getAttribute('href')} : null }""")
            print("MP6 頁面實測：%r／請求 %r" % (got, seen[:1]))
            assert any("cases" in u_ for u_ in seen), "要跟後端要案件地點：%r" % seen
            # 前端一次抓全部來源（MP8）⇒ 「預設開著」看的是清單裡真的有這一列（勾選篩選沒把它篩掉）。
            assert got and got["src"].endswith("案件地點"), got
            assert got["href"] == "case-management.html?q=MQ-202609-007", got
        finally:
            browser.close()
