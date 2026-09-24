"""瀏覽器端對端：開案件的請求數（CM8，2026-09-24）。

原本 selectCase 一次發 15 支 /api 請求。改成：開案件只打 case-bundle（＋既有的 presence／已讀／
清單排序偏好等小請求），財務、匯款憑據、今日工作改成點到分頁才載入、同一件只載一次。
觀測點：瀏覽器實際送出的請求（page.on("request")），不是程式裡的計數。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, _login, live_server,
)

NO = "MQ-OPENREQ-001"
LAZY = ("/finance-summary", "/invoice-vouchers", "/payment-requests", "/material-orders",
        "/contractor-vouchers", "/api/daily-tasks")
MERGED = ("/close-gates", "/vouchers/by-case/", "/contractor-dispatches", "/shipping-notes",
          "/completion-notes", "/updates", "/extra-expenses")


def _seed():
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100, "received": False}]},
          "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "請求客", "請求案", 100, 95, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


def _case_calls(reqs):
    return [u for u in reqs if NO in u or "quote_no=" + NO in u or "case_no=" + NO in u]


@pytest.mark.e2e
def test_opening_a_case_uses_the_bundle_and_defers_tab_data(live_server, make_user):
    u = make_user(username="or_admin", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            reqs = []
            page.on("request", lambda r: reqs.append(r.url) if "/api/" in r.url else None)
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/case-management.html?q={NO}")
            page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
            page.wait_for_function(f"() => {DATA_JS}.caseHealth.quoteNo === '{NO}'", timeout=10000)
            page.wait_for_timeout(800)
            calls = _case_calls(reqs)
            assert sum("/case-bundle" in c for c in calls) == 1, calls
            assert not any(re.search(r"/api/quotations/%s(\?|$)" % NO, c) for c in calls), "本體改由 bundle 帶回"
            for frag in MERGED + LAZY:
                assert not any(frag in c for c in calls), (frag, calls)

            # 點財務 ⇒ 財務那幾支才發，而且只發一次
            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'fin' }}")
            page.wait_for_function(f"() => !{DATA_JS}.financeSummaryLoading", timeout=10000)
            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'biz' }}")
            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'fin' }}")
            page.wait_for_timeout(500)
            calls = _case_calls(reqs)
            for frag in ("/finance-summary", "/invoice-vouchers", "/payment-requests", "/material-orders"):
                assert sum(frag in c for c in calls) == 1, (frag, calls)

            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'dispatch' }}")
            page.wait_for_function(f"() => !{DATA_JS}.contractorVouchersLoading", timeout=10000)
            assert sum("/contractor-vouchers" in c for c in _case_calls(reqs)) == 1
        finally:
            browser.close()


@pytest.mark.e2e
def test_deep_link_tab_loads_its_data_immediately(live_server, make_user):
    u = make_user(username="or_admin2", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=fin")
            page.wait_for_function(f"() => {DATA_JS}.activeTab === 'fin' && {DATA_JS}.financeSummary", timeout=20000)
        finally:
            browser.close()


@pytest.mark.e2e
def test_create_voucher_button_waits_for_voucher_list(live_server, make_user):
    """匯款憑據改成點進承攬商分頁才載入：載入完成前不可以顯示「產生匯款申請」（按了會重複建立）。"""
    import db
    u = make_user(username="or_admin3", role="admin")
    _seed()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (NO, "2026-01-01", "amount", "[]", 1000, "completed", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            held = []
            # 把憑據清單的請求扣住（handler 不回應 ⇒ 請求懸著），量「回應抵達之前」畫面長什麼樣子；
            # 之後由主流程放行。handler 裡不可以 sleep——sync API 下會卡住事件迴圈。
            page.route("**/api/contractor-vouchers**", lambda route: held.append(route))
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/case-management.html?q={NO}")
            page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
            page.wait_for_function(f"() => {DATA_JS}.dispatches.length === 1", timeout=10000)
            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'dispatch' }}")
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(50)
            assert held, "量尺：點進承攬商分頁應該要發出憑據清單的請求"
            btn = page.locator("button:has-text('產生匯款申請')")
            assert page.evaluate(f"() => {DATA_JS}.contractorVouchersLoading") is True
            assert btn.count() == 0 or not btn.first.is_visible(), "憑據還在載入就出現「產生匯款申請」"
            for route in held:
                route.fulfill(status=200, content_type="application/json", body="[]")
            page.wait_for_function(f"() => !{DATA_JS}.contractorVouchersLoading", timeout=10000)
            assert btn.first.is_visible(), "載入完成、沒有憑據時才出現"
        finally:
            browser.close()


@pytest.mark.e2e
def test_opening_fin_while_the_case_is_still_loading_loads_once_and_keeps_data(live_server, make_user):
    """〈先渲染再非同步載入＝競態〉：selected 一設定分頁列就可以點，而 selectCase 後段還在建立預設階段
    （POST /stages ×5）。這段期間點開財務：只載一次、載好的資料不可以被後段的重設清掉。
    階段的 POST 由這裡扣住，確定「點財務」發生在後段之前。"""
    u = make_user(username="or_admin4", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            reqs, held = [], []
            page.on("request", lambda r: reqs.append(r.url) if "/api/" in r.url else None)
            page.route(f"**/api/quotations/{NO}/stages", lambda route: held.append(route)
                       if route.request.method == "POST" else route.continue_())
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/case-management.html?q={NO}")
            page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(50)
            assert held, "量尺：selectCase 應該正在建立預設階段"
            page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'fin' }}")
            page.wait_for_function(f"() => {DATA_JS}.financeSummary !== null", timeout=10000)
            # 放行：預設階段是一支接一支建立的，放行一支、下一支才會出現
            for _ in range(200):
                if held:
                    held.pop(0).continue_()
                if page.evaluate(f"() => ({DATA_JS}.cr.caseRecord?.stages || []).length >= 5"):
                    break
                page.wait_for_timeout(50)
            page.wait_for_timeout(800)
            assert page.evaluate(f"() => {DATA_JS}.financeSummary !== null"), "後段把已載好的應收應付清掉了"
            assert sum("/finance-summary" in c for c in reqs) == 1, [c for c in reqs if "finance" in c]
        finally:
            browser.close()
