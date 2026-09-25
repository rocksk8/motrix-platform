"""採購・庫存・出貨模組（M03）不在時，案件頁要說清楚少了什麼（IP-16、IP-17，M03 搬遷前置 2026-09-26）。

- 出貨單分頁：顯示「採購・庫存・出貨模組未安裝：沒有出貨單資料」，不顯示「尚未建立任何出貨單」，也不顯示「新增出貨單」
- 設備序號存檔：存檔照常，狀態列顯示「已儲存；設備序號未同步庫存…」

模擬「模組不在」：伺服器端拿掉兩個提供者；瀏覽器端把 /api/shipping-notes 一律回 404（模組不在時路由本來就沒有掛）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.platform.test_case_stage_connectors import _without  # noqa: E402

NO = "MQ-NOSUPPLY-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": []}, "stages": [], "devices": []}},
                        ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _open(e2e_browser, live_server, user):
    ctx = e2e_browser.new_context()
    ctx.route("**/api/shipping-notes**",
              lambda r: r.fulfill(status=404, content_type="application/json", body='{"detail":"Not Found"}'))
    page = ctx.new_page()
    inject_login(page, live_server, user[0], user[1])
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


@pytest.mark.e2e
def test_shipping_tab_says_the_module_is_missing(live_server, make_user, e2e_browser, monkeypatch):
    from routers import quotations as q
    _without(monkeypatch, "shipping.list_for_case", "supply")
    u = make_user(username="nosup_e1", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, u)
    # 先等開案件的整包套用完（說明來自整包那一段）；否則點分頁的重新載入會早於整包，測不到「沿用」
    page.wait_for_function(f"() => !!{DATA_JS}.shippingNotesNotice", timeout=10000)
    with page.expect_request("**/api/shipping-notes**"):              # 分頁上重新載入（404 沒有說明）也要沿用那一句
        page.locator("button.cm-tab", has_text="出貨單").click()
    page.wait_for_function(f"() => !{DATA_JS}.shippingNotesLoading", timeout=8000)   # 等這一次載入的終點
    box = page.locator("[data-testid=shipping-unavailable]")
    box.wait_for(state="visible", timeout=8000)
    assert box.inner_text().strip() == q.SHIPPING_UNAVAILABLE
    assert not page.get_by_text("尚未建立任何出貨單").is_visible()
    assert not page.locator("button.btn-add", has_text="新增出貨單").is_visible()


@pytest.mark.e2e
def test_saving_device_serials_says_stock_was_not_synced(live_server, make_user, e2e_browser, monkeypatch):
    from routers import quotations as q
    _without(monkeypatch, "stock.serial", "supply")
    u = make_user(username="nosup_e2", role="superadmin")
    _seed()
    page = _open(e2e_browser, live_server, u)
    page.evaluate(f"async () => {{ const c = {DATA_JS}; c.cr.caseRecord.devices = [{{id: 1, name: 'AP', sn: 'SN-E2E-1'}}];"
                  f" await c.saveCaseRecord() }}")
    label = page.locator(".save-label")
    label.wait_for(state="visible", timeout=8000)
    page.wait_for_function("t => document.querySelector('.save-label').textContent.includes(t)",
                           arg=q.STOCK_UNAVAILABLE, timeout=8000)
    assert label.inner_text().startswith("已儲存；")
