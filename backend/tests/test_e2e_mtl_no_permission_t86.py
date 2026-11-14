# -*- coding: utf-8 -*-
"""T86（h3 最終複測）：非本案成員的財務／出納只靠 cashier 模組唯讀進案件時，物料時間軸五關都保留，
入庫／出貨顯示「無檢視權限」；不送注定回 404 的 material-flow／item-shipped；匯入、同步、確認到貨被擋時明說原因。
權限規則本身不動（後端 require_case 照舊）。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_material_timeline_t86 import NO, _case  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁")


def _open_materials(page, live_server):
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    page.get_by_role("button", name="材料申請").first.click()
    page.locator('[data-testid="mtl-row-mb"]').wait_for(state="visible", timeout=15000)


@pytest.mark.e2e
def test_non_member_finance_keeps_five_stages_and_sends_no_doomed_requests(live_server, make_user, e2e_browser):
    u, p = make_user(username="mtl_np_fin", role="finance", modules=["case_manage", "cashier", "finance"])[:2]
    _case()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 1000})
    urls = []
    page.on("request", lambda r: urls.append(r.url))
    inject_login(page, live_server, u, p)
    _open_materials(page, live_server)
    page.locator('[data-testid="mtl-readonly-note"]').wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(1500)                                   # 給時間軸補讀的機會；之後不該出現注定失敗的請求
    for mid in ("ma", "mb"):
        for k in ("req", "po", "arrive", "stock", "ship"):
            assert page.locator(f'[data-testid="mtl-st-{mid}-{k}"]').count() == 1, f"{mid}/{k} 五關要保留"
        for k in ("stock", "ship"):
            assert "無檢視權限" in page.locator(f'[data-testid="mtl-st-{mid}-{k}"]').inner_text()
    assert not [x for x in urls if "/material-flow" in x or "/item-shipped" in x], "不該送注定失敗的請求：%s" % [x for x in urls if "/material-flow" in x or "/item-shipped" in x]
    # 無檢視權限的關卡不是「目前這一關」：交換器前三關完成，目前關不落在入庫
    assert page.locator('[data-testid="mtl-st-mb-stock"]').get_attribute("data-state") == "todo"
    # 匯入／同步被擋時說明原因（不是無聲無息）
    note = page.locator('[data-testid="mtl-readonly-note"]').inner_text()
    assert "您不是本案成員" in note and "匯入品項" in note and "確認到貨" in note
    assert "您不是本案成員" in (page.locator('[data-testid="mtl-import-quote"]').get_attribute("title") or "")
    assert page.locator('[data-testid="mtl-import-quote"]').is_disabled()
    # 時間軸上沒有會寫入的按鈕（確認到貨等）
    assert page.locator('[data-testid="mtl-act-mb-arrive"]').count() == 0


@pytest.mark.e2e
def test_flow_endpoint_404_shows_placeholder_instead_of_dropping_the_columns(live_server, make_user, e2e_browser):
    u, p = make_user(username="mtl_np_boss", role="superadmin")[:2]
    _case()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 1000})
    page.route("**/api/quotations/*/material-flow", lambda route: route.fulfill(status=404, content_type="application/json", body='{"detail":"x"}'))
    inject_login(page, live_server, u, p)
    _open_materials(page, live_server)
    page.locator('[data-testid="mtl-st-mb-stock"]').wait_for(state="visible", timeout=15000)
    assert "無檢視權限" in page.locator('[data-testid="mtl-st-mb-stock"]').inner_text()
    assert "無檢視權限" in page.locator('[data-testid="mtl-st-mb-ship"]').inner_text()
    assert page.locator('[data-testid="mtl-readonly-note"]').is_hidden()          # 成員身分：沒有「您不是本案成員」說明


@pytest.mark.e2e
def test_settlement_shipped_column_says_no_permission_for_non_member_finance(live_server, make_user, e2e_browser):
    """精算頁「出貨數量」：item-shipped 回 404（非本案成員）時欄位標明「無檢視權限」，不是無聲的「—」。"""
    u, p = make_user(username="mtl_np_stl", role="finance", modules=["case_manage", "cashier", "finance"])[:2]
    _case()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 1000})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/settlement.html?no={NO}")
    page.wait_for_function("() => { const el = document.querySelector('body'); const d = el && el._x_dataStack && el._x_dataStack[0]; return d && d.itemShippedNoPerm === true }", timeout=20000)
    cell = page.get_by_text("無檢視權限").first
    cell.wait_for(state="visible", timeout=10000)
