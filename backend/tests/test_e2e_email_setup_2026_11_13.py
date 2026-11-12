# -*- coding: utf-8 -*-
"""瀏覽器端對端：寄信帳號卡（批次 3，static/email-setup.js）。

驗：①抽出後的卡片照樣出現在通知設定頁、能載入與儲存設定、與 LINE 卡、月報卡並存。
（精靈流程的 e2e 在本檔後段。）
"""
import pytest

pytest.importorskip("playwright.sync_api")


def _open(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    return page


@pytest.mark.e2e
def test_extracted_email_card_renders_loads_and_saves(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "e2e_es1")
    page.locator("[data-testid=ns-base-url]").wait_for(state="visible", timeout=20000)
    assert page.locator("#chk-enabled").count() == 1
    assert page.locator("#line-panel").count() == 1                      # 與 LINE 卡並存
    page.locator("[data-testid=ns-base-url]").fill("https://erp.example.com")
    page.get_by_role("button", name="儲存設定").first.click()
    page.get_by_text("設定已儲存").first.wait_for(state="visible", timeout=10000)
    page.reload()
    page.locator("[data-testid=ns-base-url]").wait_for(state="visible", timeout=20000)
    page.wait_for_function("document.querySelector('[data-testid=ns-base-url]').value === 'https://erp.example.com'", timeout=10000)
