"""CORE-SPEC §9c 模組管理頁與選單（e2e）。

① superadmin 在「模組管理」頁看到標案雷達「啟用」；按停用 ⇒ 該列標「待重啟」、訊息說「重新啟動服務後生效」，
   目前狀態仍是「啟用」（重啟後生效）；再按一次回復。頁面沒有重啟按鈕。
② 選單：這次啟動沒載入的模組（狀態表改成 disabled 模擬重啟後的結果）⇒ 側欄的「標案雷達」入口不見；
   正對照：狀態是 loaded 時入口看得到。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402


def _open(e2e_browser, live_server, make_user, name, path):
    u = make_user(username=name, role="superadmin")
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/{path}")
    return page


@pytest.mark.e2e
def test_module_settings_page_toggle_is_pending_until_restart(live_server, make_user, e2e_browser):
    page = _open(e2e_browser, live_server, make_user, "mse_sa1", "module-settings.html")
    state = page.locator("[data-testid='ms-state-tender_radar']")
    state.wait_for(timeout=15000)
    assert state.inner_text().strip() == "啟用"
    assert not page.locator("[data-testid='ms-pending-tender_radar']").is_visible()
    assert "重新啟動服務後才生效" in page.locator("[data-testid='ms-restart-note']").inner_text()

    toggle = page.locator("[data-testid='ms-toggle-tender_radar']")
    assert toggle.inner_text().strip() == "停用"
    toggle.click()
    page.locator("[data-testid='ms-pending-tender_radar']").wait_for(state="visible", timeout=10000)
    assert "重新啟動服務後生效" in page.locator("[data-testid='ms-msg']").inner_text()
    assert state.inner_text().strip() == "啟用", "目前狀態要到重啟後才變"
    assert toggle.inner_text().strip() == "啟用"

    toggle.click()                                                  # 回復
    page.locator("[data-testid='ms-pending-tender_radar']").wait_for(state="hidden", timeout=10000)
    assert toggle.inner_text().strip() == "停用"
    assert page.locator("button:has-text('重啟'), button:has-text('重新啟動')").count() == 0


@pytest.mark.e2e
def test_sidebar_hides_entries_of_unloaded_modules(live_server, make_user, e2e_browser, monkeypatch):
    from core import registry
    link = "a[href$='tender-radar.html']"

    page = _open(e2e_browser, live_server, make_user, "mse_sa2", "module-settings.html")
    page.locator("[data-testid='ms-table']").wait_for(timeout=15000)
    # 觀測點＝入口元素自己的 style.display（側欄是收合的下拉分組，is_visible() 會因為父層收合而是 False，
    # 那不是這裡要驗的事）。正反兩邊用同一個觀測點。
    hidden = f"() => {{ const a = document.querySelector(\"{link}\"); return a ? a.style.display === 'none' : null }}"
    page.wait_for_function(f"() => document.querySelector(\"{link}\")", timeout=10000)
    page.wait_for_load_state("networkidle")
    assert page.evaluate(hidden) is False, "正對照：模組已載入時入口不可被藏"

    st = dict(registry._STATES["tender_radar"])
    monkeypatch.setitem(registry._STATES, "tender_radar", {**st, "state": "disabled", "reason": "管理者已停用"})
    page.reload()
    page.locator("[data-testid='ms-table']").wait_for(timeout=15000)
    page.wait_for_function(hidden, timeout=10000)
    assert page.evaluate(hidden) is True
