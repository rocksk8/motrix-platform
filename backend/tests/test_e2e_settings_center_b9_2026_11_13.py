"""瀏覽器端對端：設定中心彙整＋「?」說明（選單去工程師化 批次 9，2026-11-13）。

- 左欄依共用分類資料檔分類（分類標題、區段標題、群組按鈕）；搜尋涵蓋欄位問句
- 欄位旁的「?」：滑過／聚焦顯示四段、Enter 開、Esc 關、點外面收起；說明文字來自資料檔（頁面沒寫死）
- 手機寬度：點一下開底部面板，有「關閉」鈕，頁面不橫向捲動
- 標籤本身已夠清楚（白名單）的欄位沒有「?」
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _open(page, live_server, group):
    page.goto(f"{live_server}/pages/settings-center.html")
    page.locator(f'[data-testid="sc-group-{group}"]').wait_for(timeout=20000)
    page.locator(f'[data-testid="sc-group-{group}"]').click()


@pytest.mark.e2e
def test_sidebar_is_grouped_by_category_and_search_covers_field_questions(live_server, make_user, e2e_browser):
    sa = make_user(username="b9_e2e_a", role="superadmin")
    page = e2e_browser.new_page()
    inject_login(page, live_server, *sa)
    _open(page, live_server, "uploads")
    for c in ("company", "people", "flow", "numbering", "notify", "data", "custom"):
        page.locator(f'[data-testid="sc-cat-{c}"]').wait_for(timeout=10000)
    assert page.locator('[data-testid="sc-cat-data"] [data-testid="sc-group-uploads"]').count() == 1
    assert page.locator('[data-testid="sc-cat-custom"] [data-testid="sc-group-builder_layout"]').count() == 1
    assert "開放哪些客製功能" in page.locator('[data-testid="sc-cat-custom"]').inner_text()
    # 搜尋欄位問句（群組名稱裡沒有的字）
    page.fill('[data-testid="sc-search"]', "最大可以多大")
    page.wait_for_function("() => document.querySelectorAll('[data-testid^=\"sc-group-\"]').length === 1", timeout=10000)
    assert page.locator('[data-testid="sc-group-uploads"]').count() == 1
    page.fill('[data-testid="sc-search"]', "完全不存在的字串zzz")
    page.locator('[data-testid="sc-search-empty"]').wait_for(timeout=10000)
    page.fill('[data-testid="sc-search"]', "")
    page.locator('[data-testid="sc-group-uploads"]').wait_for(timeout=10000)
    assert page.locator('[data-testid="sc-when"]').inner_text().startswith("什麼時候需要：")


@pytest.mark.e2e
def test_question_mark_popover_opens_with_four_sections_and_closes_with_escape(live_server, make_user, e2e_browser):
    sa = make_user(username="b9_e2e_b", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 1280, "height": 900})
    inject_login(page, live_server, *sa)
    _open(page, live_server, "retention")
    hint = page.locator('[data-testid="sc-hint-audit_log_keep_days"]')
    hint.wait_for(timeout=15000)
    btn = hint.locator(".hint__btn")
    btn.wait_for(timeout=10000)
    assert btn.get_attribute("aria-expanded") == "false" and btn.get_attribute("aria-label").startswith("說明：")
    pop = hint.locator(".hint__pop")
    assert not pop.is_visible()
    btn.hover()
    pop.wait_for(state="visible", timeout=5000)
    txt = pop.inner_text()
    for sec in ("這是什麼", "什麼時候要改", "改了會影響什麼", "預設值與建議"):
        assert sec in txt, sec
    assert "五年" in txt and "系統預設" in txt
    page.mouse.move(5, 5)
    pop.wait_for(state="hidden", timeout=5000)
    btn.focus()                                              # 鍵盤：Tab 聚焦即顯示；Enter 切換；Esc 關
    pop.wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    pop.wait_for(state="hidden", timeout=5000)
    btn.click()                                              # 點一下開、點外面收
    pop.wait_for(state="visible", timeout=5000)
    page.locator("h1.pg__t").click()
    pop.wait_for(state="hidden", timeout=5000)
    # 標籤已夠清楚（白名單）的欄位沒有 ?
    assert page.locator('[data-testid="sc-hint-nonexistent"]').count() == 0
    _open(page, live_server, "uploads")
    page.locator('[data-testid="sc-field-max_file_mb"]').wait_for(timeout=10000)
    assert page.locator('[data-testid="sc-hint-max_file_mb"]').count() == 0


@pytest.mark.e2e
def test_mobile_tap_opens_bottom_sheet_with_close_button_and_no_horizontal_scroll(live_server, make_user, e2e_browser):
    sa = make_user(username="b9_e2e_c", role="superadmin")
    page = e2e_browser.new_page(viewport={"width": 390, "height": 800}, has_touch=True)
    inject_login(page, live_server, *sa)
    _open(page, live_server, "retention")
    hint = page.locator('[data-testid="sc-hint-audit_log_keep_days"]')
    hint.wait_for(timeout=15000)
    hint.locator(".hint__btn").click()
    pop = hint.locator(".hint__pop")
    pop.wait_for(state="visible", timeout=5000)
    box = pop.bounding_box()
    assert box["y"] + box["height"] >= 790 and box["width"] >= 380, "手機是貼底的底部面板"
    pop.locator(".hint__close").click()
    pop.wait_for(state="hidden", timeout=5000)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "手機寬度不橫向捲動"
