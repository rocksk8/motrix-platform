"""瀏覽器端對端：簽核流程設定頁 UX 密度（C4，2026-11-11）。

預設狀態：頁首三句話、統一／獨立對照圖、每個單據類型收成一列（名稱｜現況摘要｜[調整]）、各簽核流程區塊收合、
說明收合；頁面約兩屏。展開後原有控制項（套用範圍開關、兩邊預覽、新增簽核層、儲存）都還在、行為不變。
只動呈現，不動權限與儲存內容。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _open(live_server, make_user, e2e_browser, name, viewport=None):
    username, password = make_user(username=name, role="superadmin")
    page = e2e_browser.new_page(viewport=viewport or {"width": 1440, "height": 900})
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/approval-settings.html")
    page.wait_for_function(
        "() => { const e = document.querySelector('.scope-row__digest'); return e && e.textContent.trim() && !e.textContent.includes('載入中'); }",
        timeout=20000)
    return page


@pytest.mark.e2e
def test_default_is_collapsed_and_short(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_as1")
    assert page.locator("[data-testid=as-intro] li").count() == 3
    assert page.locator("[data-testid=as-compare]").is_visible()
    assert page.locator("[data-testid=as-compare] svg").count() == 2
    # 每個單據類型一列，且一開始都沒有展開
    rows = page.locator(".scope-row")
    assert rows.count() >= 5
    quote = page.locator("[data-doc-type=quotation]")
    assert "報價單" in quote.inner_text()
    assert "統一流程：" in quote.locator(".scope-row__digest").inner_text()
    assert quote.locator("[data-testid=as-scope-adjust]").inner_text().strip() == "調整"
    assert not quote.locator("input[data-saved-field]").is_visible()
    assert not quote.locator(".scope-side").first.is_visible()
    # 簽核流程區塊收合：看不到「新增簽核層」，但標題列、摘要與「儲存設定」還在
    card = page.locator("#as-flow-unified")
    assert card.is_visible()
    assert not card.get_by_role("button", name="新增簽核層").is_visible()
    assert card.get_by_role("button", name="儲存設定").is_visible()
    # 說明預設收合
    assert page.locator("#as-help").evaluate("e => e.open") is False
    # 約兩屏（1440x900）
    h = page.evaluate("document.documentElement.scrollHeight")
    assert h <= 2400, "收合後頁面仍有 %s px，超過約兩屏" % h


@pytest.mark.e2e
def test_expanding_reveals_the_old_controls(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_as2")
    quote = page.locator("[data-doc-type=quotation]")
    quote.locator("[data-testid=as-scope-adjust]").click()
    box = quote.locator("input[data-saved-field]")
    assert box.is_visible() and box.is_checked()
    assert quote.locator(".scope-side").count() == 2
    assert quote.locator(".scope-side.live").is_visible()
    # 撥動開關：預覽照舊（儲存後變這個），摘要註明尚未儲存；沒有任何請求被送出（只是畫面狀態）
    box.evaluate("e => e.click()")
    assert quote.locator(".scope-side.next").is_visible()
    assert "尚未儲存" in quote.locator(".scope-row__digest").inner_text()
    box.evaluate("e => e.click()")
    assert quote.locator(".scope-side.next").count() == 0
    # 「編輯簽核層」展開並帶到統一流程的編輯區塊
    quote.get_by_role("button", name="編輯簽核層").click()
    card = page.locator("#as-flow-unified")
    card.get_by_role("button", name="新增簽核層").wait_for(state="visible", timeout=5000)
    assert card.get_by_role("button", name="儲存設定").is_visible()
    assert card.locator(".as-add-row").is_visible()
    # 收合回去
    card.locator("[data-testid=as-flow-toggle]").click()
    card.get_by_role("button", name="新增簽核層").wait_for(state="hidden", timeout=5000)
    assert card.locator("[data-testid=as-flow-toggle]").inner_text().strip() == "調整"


@pytest.mark.e2e
def test_toc_jumps_and_opens_the_section(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_as3")
    toc = page.locator("[data-testid=as-toc]")
    assert toc.is_visible()
    toc.locator("a[href='#as-flow-unified']").click()
    card = page.locator("#as-flow-unified")
    card.get_by_role("button", name="新增簽核層").wait_for(state="visible", timeout=5000)
    toc.locator("a[href='#as-help']").click()
    page.wait_for_function("() => document.getElementById('as-help').open === true", timeout=5000)


@pytest.mark.e2e
def test_narrow_screen_hides_toc_and_keeps_rows(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_as4", viewport={"width": 390, "height": 844})
    assert not page.locator("[data-testid=as-toc]").is_visible()
    assert page.locator("[data-doc-type=quotation] [data-testid=as-scope-adjust]").is_visible()
    over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度出現橫向捲動 %s px" % over
