"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_e2e_case_open_requests_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
瀏覽器端對端：開案件的請求數（CM8，2026-09-24）。

原本 selectCase 一次發 15 支 /api 請求。改成：開案件只打 case-bundle（＋既有的 presence／已讀／
清單排序偏好等小請求），財務、匯款憑據、今日工作改成點到分頁才載入、同一件只載一次。
觀測點：瀏覽器實際送出的請求（page.on("request")），不是程式裡的計數。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, _login,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

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
def test_create_voucher_button_waits_for_voucher_list(live_server, make_user, e2e_browser):
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
    browser = e2e_browser
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
