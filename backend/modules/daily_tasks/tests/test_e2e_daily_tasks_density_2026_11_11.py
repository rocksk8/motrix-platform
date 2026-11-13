"""瀏覽器端對端：每日工作事項 UX 密度（C6，2026-11-11）。

預設：日曆視圖只展開當月（前一個月收成一條標題列，按一下展開）；工具列只留「今日」「日曆視圖」（以及已解鎖時的
「新增工作事項」），回報彙整／月曆總覽／看板／解鎖管理視角收進「更多」選單。每個原有動作仍然點得到、行為不變。
"""
import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _open(live_server, make_user, e2e_browser, name, viewport=None):
    username, password = make_user(username=name, role="superadmin")
    page = e2e_browser.new_page(viewport=viewport or {"width": 1440, "height": 900})
    sess = inject_login(page, live_server, username, password)
    r = page.context.request.post(
        live_server + "/api/daily-tasks",
        headers={"Authorization": "Bearer " + sess["token"]},
        data={"task_date": datetime.date.today().isoformat(), "title": "密度測試事項", "assigned_to": [username]})
    assert r.ok, r.text()[:200]
    page.goto(f"{live_server}/pages/daily-tasks.html")
    page.wait_for_selector("[data-testid=dt-more]", timeout=20000)
    return page


def _data(page, expr):
    return page.evaluate("() => { const d = Alpine.$data(document.body); return %s }" % expr)


@pytest.mark.e2e
def test_calendar_defaults_to_current_month_only(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_dt1")
    page.wait_for_selector("[data-testid=cal-prev-card]", state="visible", timeout=20000)
    prev = page.locator("[data-testid=cal-prev-card]")
    assert prev.locator(".dt-cal-grid").is_hidden()
    cur_cells = page.locator(".dt-cal-card:not([data-testid=cal-prev-card]) .dt-cal-grid .dt-cal-cell")
    assert cur_cells.count() >= 28 and cur_cells.first.is_visible()
    # 前一個月的標題列還在，按一下才展開
    assert "展開" in prev.locator("[data-testid=cal-prev-toggle]").inner_text()
    prev.locator("[data-testid=cal-prev-toggle]").click()
    prev.locator(".dt-cal-grid").wait_for(state="visible")
    assert prev.locator(".dt-cal-grid .dt-cal-cell").count() >= 28
    prev.locator("[data-testid=cal-prev-toggle]").click()
    prev.locator(".dt-cal-grid").wait_for(state="hidden")


@pytest.mark.e2e
def test_toolbar_primary_vs_more_menu(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_dt2")
    bar = page.locator(".dt-bar")
    # init() 在 `await loadTasks()` 之後才把 calMode 設成 true，按鈕字樣才從「日曆視圖」變成「← 關閉日曆」：先等到這個狀態再斷言
    # （只等 dt-more 會在負載下搶在字樣翻轉之前判斷 ⇒ 平行跑偶發紅；is_visible() 不重試，改用會等待的 expect）
    page.wait_for_selector(".dt-bar-act-cal.on", timeout=20000)
    assert bar.locator("[data-testid=dt-today]").is_visible()
    bar.get_by_role("button", name="← 關閉日曆").wait_for(state="visible", timeout=10000)
    for name in ("回報彙整", "月曆總覽", "看板", "解鎖管理視角"):
        assert not bar.get_by_role("button", name=name, exact=True).is_visible(), name + " 應該收在「更多」"
    menu = page.locator("[data-testid=dt-more-menu]")
    assert not menu.is_visible()
    # 選單：四個動作都在
    page.click("[data-testid=dt-more]")
    menu.wait_for(state="visible")
    items = [t.strip() for t in menu.locator("[role=menuitem]").all_inner_texts()]
    assert items == ["回報彙整", "月曆總覽", "看板", "解鎖管理視角"], items
    # Escape 關閉、點外面關閉
    page.keyboard.press("Escape")
    menu.wait_for(state="hidden")
    page.click("[data-testid=dt-more]")
    menu.wait_for(state="visible")
    page.click(".dt-bar-title")
    menu.wait_for(state="hidden")


@pytest.mark.e2e
def test_every_more_action_still_works(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_dt3")
    menu = page.locator("[data-testid=dt-more-menu]")

    def pick(label):
        page.click("[data-testid=dt-more]")
        menu.wait_for(state="visible")
        menu.get_by_role("menuitem", name=label, exact=True).click()
        menu.wait_for(state="hidden")

    # 回報彙整：進入後，列上多一顆「← 返回列表」可一步退出
    pick("回報彙整")
    page.wait_for_function("() => Alpine.$data(document.body).reportMode === true")
    page.locator("[data-testid=dt-exit-report]").click()
    page.wait_for_function("() => Alpine.$data(document.body).reportMode === false")
    # 月曆總覽
    pick("月曆總覽")
    page.wait_for_function("() => Alpine.$data(document.body).monthCalMode === true")
    page.locator("[data-testid=dt-exit-month]").click()
    page.wait_for_function("() => Alpine.$data(document.body).monthCalMode === false")
    # 看板
    pick("看板")
    page.wait_for_function("() => Alpine.$data(document.body).boardMode === true")
    page.locator("[data-testid=dt-exit-board]").click()
    page.wait_for_function("() => Alpine.$data(document.body).boardMode === false")
    # 解鎖管理視角：開出輸入框（原本就是這個動作）
    pick("解鎖管理視角")
    page.wait_for_function("() => Alpine.$data(document.body).showUnlock === true")


@pytest.mark.e2e
def test_today_button_returns_to_current_month(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "e2e_dt4")
    today = datetime.date.today()
    cur = "%d年%d月" % (today.year, today.month)
    assert page.locator(".dt-month-label").inner_text().strip() == cur
    page.locator(".dt-month-nav button").first.click()
    page.wait_for_function("(c) => document.querySelector('.dt-month-label').innerText.trim() !== c", arg=cur)
    page.locator("[data-testid=dt-today]").click()
    page.wait_for_function("(c) => document.querySelector('.dt-month-label').innerText.trim() === c", arg=cur)


@pytest.mark.e2e
def test_narrow_screen_toolbar_stays_inside_the_viewport(live_server, make_user, e2e_browser):
    """手機寬度：工具列（今日／日曆視圖／更多）不再被擠出畫面（頁面最上方的全站頂欄另有自己的寬度，不在這題範圍）。"""
    page = _open(live_server, make_user, e2e_browser, "e2e_dt5", viewport={"width": 390, "height": 844})
    for sel in (".dt-bar", "[data-testid=dt-today]", "[data-testid=dt-more]"):
        box = page.locator(sel).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391, "%s 超出畫面寬度：%s" % (sel, box)
    page.click("[data-testid=dt-more]")
    page.locator("[data-testid=dt-more-menu]").wait_for(state="visible", timeout=5000)
    box = page.locator("[data-testid=dt-more-menu]").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391, "更多選單超出畫面：%s" % box
