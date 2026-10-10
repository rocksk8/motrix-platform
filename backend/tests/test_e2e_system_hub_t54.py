# -*- coding: utf-8 -*-
"""第 54 班 e2e：系統中心（左：分組、右：細項列）。

- 載入只打一次 /api/system-hub；左欄 8 個分組、點分組 ⇒ 網址 hash 變、右欄換成該組項目；方向鍵切換分組；搜尋跨分組
- 畫面是白話：整頁文字不出現網址、檔名、底線代碼；導覽列的『系統』是單一連結（不再是 21 項下拉）
- 沒有任何系統權限的人：看到說明、導覽列沒有『系統』；舊網址（使用者管理）照常可開且頂端有『← 系統』
- 手機寬度：左欄變水平分組列、頁面不出現橫向捲動
"""
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

CODEISH = re.compile(r"\.html|/api/|https?://|\b[a-z]+_[a-z_]+\b")


def _open_hub(page, live_server, user):
    inject_login(page, live_server, user[0], user[1])
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if r.url.split("?")[0].endswith("/api/system-hub") else None)
    page.goto(live_server + "/pages/system-hub.html")
    return reqs


@pytest.mark.e2e
def test_superadmin_hub_groups_hash_keyboard_search_and_plain_language(live_server, make_user, new_context):
    sa = make_user(username="hub_e2e_sa", role="superadmin")
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    reqs = _open_hub(page, live_server, sa)
    page.wait_for_selector("[data-testid=hub-groups] .grp", state="visible", timeout=25000)
    assert page.locator("[data-testid=hub-groups] .grp").count() == 8
    assert len(reqs) == 1, "載入只打一次系統中心端點：%s" % reqs
    # 點分組 ⇒ hash 變、右欄換內容
    page.click("[data-testid=hub-group-data]")
    page.wait_for_selector("[data-testid=hub-item-storage-settings]", state="visible", timeout=10000)
    assert page.evaluate("() => location.hash") == "#data"
    # 方向鍵：下一個分組
    page.focus("[data-testid=hub-group-data]")
    page.keyboard.press("ArrowDown")
    page.wait_for_function("() => location.hash === '#audit'", timeout=5000)
    page.wait_for_selector("[data-testid=hub-item-audit-log]", state="visible", timeout=5000)
    # 上一頁 ⇒ 回 #data
    page.go_back()
    page.wait_for_selector("[data-testid=hub-item-storage-settings]", state="visible", timeout=5000)
    # 搜尋跨分組
    page.fill("[data-testid=hub-search]", "備份")
    page.wait_for_selector("[data-testid=hub-item-backup-retention]", state="visible", timeout=5000)
    page.fill("[data-testid=hub-search]", "")
    # 白話：整頁可見文字不出現網址／檔名／底線代碼
    text = page.locator("main").inner_text()
    assert CODEISH.search(text) is None, CODEISH.search(text)
    # 第一次使用提示：關掉後重新整理不再出現
    page.wait_for_selector("[data-testid=hub-first-hint]", state="visible", timeout=5000)
    page.click("[data-testid=hub-first-hint] button")
    page.reload()
    page.wait_for_selector("[data-testid=hub-groups] .grp", state="visible", timeout=25000)
    assert page.locator("[data-testid=hub-first-hint]").is_visible() is False
    # 導覽列：『系統』是單一連結，沒有展開 21 項
    nav = page.locator("#app-mainnav a.mnav__top", has_text="系統")
    assert nav.count() == 1 and "system-hub.html" in (nav.first.get_attribute("href") or "")
    assert page.locator("#app-mainnav .mnav__item", has_text="使用者管理").count() == 0


@pytest.mark.e2e
def test_user_without_system_permissions_sees_the_plain_empty_state_and_no_nav_entry(live_server, make_user, new_context):
    u = make_user(username="hub_e2e_plain", role="viewer", modules=[])
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    _open_hub(page, live_server, u)
    page.wait_for_selector("[data-testid=hub-empty]", state="visible", timeout=25000)
    assert "沒有可用的系統功能" in page.locator("[data-testid=hub-empty]").inner_text()
    assert page.locator("#app-mainnav a.mnav__top", has_text="系統").count() == 0


@pytest.mark.e2e
def test_old_urls_still_work_and_get_the_back_to_system_link(live_server, make_user, new_context):
    sa = make_user(username="hub_e2e_sa2", role="superadmin")
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto(live_server + "/pages/users.html")
    page.wait_for_selector("[data-testid=sys-crumb]", state="attached", timeout=25000)
    assert "system-hub.html" in (page.get_attribute("[data-testid=sys-crumb]", "href") or "")
    assert page.locator("[data-testid=sys-crumb]").inner_text().strip() == "← 系統"


@pytest.mark.e2e
def test_phone_width_groups_become_a_horizontal_bar_without_page_scroll(live_server, make_user, new_context):
    sa = make_user(username="hub_e2e_sa3", role="superadmin")
    page = new_context(viewport={"width": 390, "height": 800}).new_page()
    _open_hub(page, live_server, sa)
    page.wait_for_selector("[data-testid=hub-groups] .grp", state="visible", timeout=25000)
    assert page.evaluate("() => getComputedStyle(document.querySelector('[data-testid=hub-groups]')).flexDirection") == "row"
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
