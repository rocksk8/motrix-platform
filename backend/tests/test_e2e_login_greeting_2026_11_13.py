# -*- coding: utf-8 -*-
"""瀏覽器端對端：首頁登入問候語（UX P1.5，2026-11-13）。伺服器判斷、前端只顯示。"""
import pytest

pytest.importorskip("playwright.sync_api")


def _open(live_server, page, login_as, user):
    sess = login_as(page, user)
    page.goto(f"{live_server}/index.html")
    return sess


@pytest.mark.e2e
def test_first_login_shows_welcome_and_start_button(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_greet_first", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(live_server, page, login_as, user)
    line = page.locator("[data-testid=login-greeting]")
    line.wait_for(state="visible", timeout=20000)
    assert line.inner_text().startswith("歡迎加入，")
    btn = page.locator("[data-testid=login-greeting-action]")
    assert btn.is_visible() and btn.inner_text() == "開始使用" and "my-account.html" in btn.get_attribute("href")
    # 標題仍是「早安／午安／晚安，名字。」＋原本的待辦句（問候語不取代標題）
    page.wait_for_function("/件事等您處理|尚無待您簽核/.test(document.querySelector('h1.h-hero__t').innerText)", timeout=20000)
    h1 = page.locator("h1.h-hero__t").inner_text()
    assert h1[:2] in ("早安", "午安", "晚安") and ("件事等您處理" in h1 or "尚無待您簽核" in h1)


@pytest.mark.e2e
def test_second_login_is_not_a_welcome_and_off_hides_everything(live_server, make_user, new_page, login_as, client, monkeypatch):
    user = make_user(username="e2e_greet_off", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)                                              # 第 1 次登入（吃掉「第一次」）
    sess = login_as(page, user)                                       # 第 2 次
    page.goto(f"{live_server}/index.html")
    line = page.locator("[data-testid=login-greeting]")
    line.wait_for(state="visible", timeout=20000)
    assert not line.inner_text().startswith("歡迎加入")
    assert not page.locator("[data-testid=login-greeting-action]").is_visible()
    # 個人選關閉 ⇒ 整塊不出現，標題退回原本的算法
    from helpers import login_greeting as LG
    monkeypatch.setattr(LG, "personal_pref", lambda uid: "off")        # 個人偏好存在 user_prefs（我的帳號偏好頁）；這裡直接模擬「個人選了關閉」
    page.reload()
    page.wait_for_selector("h1.h-hero__t", timeout=20000)
    page.wait_for_timeout(1500)
    assert not page.locator("[data-testid=login-greeting]").is_visible()
    assert page.locator("h1.h-hero__t").inner_text()[:2] in ("早安", "午安", "晚安")
