"""瀏覽器端對端（M01-PLAN §5 ④，稽核 D M4-M2）：別組頁面呼叫 M01（案件）端點，M01 不在時要說出原因。

M01 不在 ⇒ 那些路由不存在 ⇒ 404＋FastAPI 預設 detail "Not Found"。本檔以攔截回應模擬（驗的是別組頁面在 M01 不在時的行為，
不可以因為 M01 不在就略過）。
正對照：同樣是 404、但 detail 是「報價單 X 不存在」（c-case404 之後「看不到」也是這一句）⇒ **不可以**說成模組未安裝。
觀測點一律是使用者看得到的東西（DOM 可見、控制項停用、alert 的字），不看 Alpine 模型（稽核 D M4-M1 的教訓）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from core import source_tree  # noqa: E402

DATA = "Alpine.$data(document.querySelector('body[x-data]'))"
NO = "MQ-E2E-NOCASE"


def _route_404(page, pattern, detail):
    page.route(pattern, lambda route: route.fulfill(status=404, content_type="application/json",
                                                     body=json.dumps({"detail": detail}, ensure_ascii=False)))


def _page(live_server, make_user, new_page, login_as, name, path, pattern, detail):
    user = make_user(username=name, role="superadmin")
    page = new_page()
    _route_404(page, pattern, detail)
    login_as(page, tuple(user)[:2])
    page.goto(f"{live_server}/pages/{path}")
    page.wait_for_function(f"() => window.Alpine && {DATA}", timeout=20000)
    return page


def _wait_until(page, cond, timeout_ms=10000):
    """等 Python 端的條件成立（dialog 在 Python 事件裡收集）；每 50ms 讓瀏覽器事件迴圈跑一次。"""
    for _ in range(timeout_ms // 50):
        if cond():
            return
        page.wait_for_timeout(50)
    raise AssertionError("等不到終點狀態")


def _dialogs(page):
    seen = []

    def on(d):
        seen.append(d.message)
        d.accept()
    page.on("dialog", on)
    return seen


# ── M10 網路規劃：綁定案件 ──────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("detail,absent", [("Not Found", True), ("報價單 %s 不存在" % NO, False)])
def test_network_plan_case_picker(live_server, make_user, new_page, login_as, detail, absent):
    if not source_tree.module_installed("modules/netplan/"):
        pytest.skip("網路規劃模組（M10）不在 ⇒ 頁面本來就不在（PLAYBOOK §B-11）")
    page = _page(live_server, make_user, new_page, login_as, "e2e_np_nocase_%d" % absent, "network-plans.html",
                 "**/api/quotations?*", detail)
    with page.expect_response(lambda r: "/api/quotations?" in r.url, timeout=15000):
        page.evaluate(f"() => {DATA}.openCreateModal()")
    note = page.locator("[data-testid=case-options-unavailable]")
    search = page.locator("input[x-model='caseSearch']")
    if absent:
        note.wait_for(state="visible", timeout=10000)
        assert note.inner_text().strip() == "案件模組未安裝：無法綁定案件（規劃書本身照常可建立）"
        assert search.is_disabled()
    else:
        page.wait_for_function(f"() => {DATA}.caseOptionsLoading === false", timeout=10000)   # 終點：載入結束
        assert not note.is_visible() and search.is_enabled()


# ── M05 請款單：帶入案件資料 ─────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("detail,absent", [("Not Found", True), ("報價單 %s 不存在" % NO, False)])
def test_payment_request_form_quote_info(live_server, make_user, new_page, login_as, detail, absent):
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("應收應付模組（M05）不在 ⇒ 頁面本來就不在（PLAYBOOK §B-11）")
    user = make_user(username="e2e_pr_nocase_%d" % absent, role="superadmin")
    page = new_page()
    _route_404(page, "**/api/quotations/%s" % NO, detail)
    login_as(page, tuple(user)[:2])
    with page.expect_response(lambda r: ("/api/quotations/%s" % NO) in r.url, timeout=20000):
        page.goto(f"{live_server}/pages/payment-request-form.html?quote_no={NO}")
    note = page.locator("[data-testid=quote-info-unavailable]")
    if absent:
        note.wait_for(state="visible", timeout=10000)
        assert note.inner_text().strip() == "案件模組未安裝：無法帶入案件資料（客戶、專案名稱、請款條件）"
    else:
        page.wait_for_function("() => document.readyState === 'complete'", timeout=10000)
        page.wait_for_function(f"() => {DATA} && {DATA}.quoteNo === {NO!r}", timeout=10000)   # 終點：init 已跑完這支載入
        assert not note.is_visible()


# ── M05 出納：收款／發票登錄 ─────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("detail,absent", [("Not Found", True), ("報價單 %s 不存在" % NO, False)])
def test_cashier_receipt_action(live_server, make_user, new_page, login_as, detail, absent):
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("應收應付模組（M05）不在 ⇒ 頁面本來就不在（PLAYBOOK §B-11）")
    page = _page(live_server, make_user, new_page, login_as, "e2e_cash_nocase_%d" % absent, "cashier.html",
                 "**/api/quotations/%s/payment/**" % NO, detail)
    seen = _dialogs(page)
    with page.expect_response(lambda r: "/payment/" in r.url, timeout=15000):
        page.evaluate(f"() => {DATA}.toggleReceived({{quoteNo: '{NO}', idx: 0}}, true)")
    _wait_until(page, lambda: len(seen) >= 2)                     # 終點：confirm 之後的 alert 已出現
    alerts = [m for m in seen if "標記此款項" not in m]           # 第一個是 confirm
    want = "案件模組未安裝：收款與發票紀錄存在案件裡，無法登錄" if absent else detail
    assert alerts == [want], seen


# ── M08 營運報表：精算明細 ───────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("detail,absent", [("Not Found", True), ("報價單 %s 不存在" % NO, False)])
def test_reports_settlement_drilldown(live_server, make_user, new_page, login_as, detail, absent):
    if not source_tree.module_installed("modules/analytics/"):
        pytest.skip("營運分析模組（M08）不在 ⇒ 頁面本來就不在（PLAYBOOK §B-11）")
    page = _page(live_server, make_user, new_page, login_as, "e2e_rep_nocase_%d" % absent, "reports.html",
                 "**/api/quotations/%s/settlement" % NO, detail)
    seen = _dialogs(page)
    with page.expect_response(lambda r: "/settlement" in r.url, timeout=15000):
        page.evaluate(f"() => {DATA}.openSettlement('{NO}')")
    _wait_until(page, lambda: len(seen) >= 1)                     # 終點：alert 已出現
    want = "載入精算資料失敗：" + ("案件模組未安裝：精算資料在案件裡" if absent else "載入精算失敗")
    assert seen == [want], seen
