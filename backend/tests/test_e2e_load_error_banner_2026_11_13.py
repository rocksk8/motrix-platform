# -*- coding: utf-8 -*-
"""載入失敗不可以是一片空白／「暫無紀錄」（2026-11-13，SYSTEM-MENU-UX 提案 §T5）。

五個頁面（歷史紀錄、在線時數、Schema 狀態、版本紀錄、出貨單歷史）以前在讀取失敗時 `catch(e){}` 靜默：
畫面停在空清單／「暫無紀錄」，使用者以為真的沒資料。現在：白話原因＋「重試」按鈕，重試成功後錯誤條消失。
"""
import json
import time

import pytest

pytest.importorskip("playwright.sync_api")

_MAKE_USER_DEFAULT_ROLE = "superadmin"

# (頁面, 會被打的 API 路徑片段, 失敗時「不可以出現」的空狀態文字)
PAGES = [
    ("audit-log.html", "**/api/audit-log**", "暫無紀錄"),
    ("online-stats.html", "**/api/user-activity**", "還沒有任何活躍紀錄"),
    ("schema-status.html", "**/api/system/schema-status", None),
    ("module-versions.html", "**/api/module-versions", None),
    ("shipping-export-history.html", "**/api/shipping-notes/export-history", "尚無符合條件的匯出紀錄"),
]


def _boom(route):
    route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))


@pytest.mark.e2e
@pytest.mark.parametrize("page_name,pattern,empty_text", PAGES, ids=[p[0] for p in PAGES])
def test_load_failure_shows_a_plain_reason_and_retry_recovers(live_server, make_user, new_page, login_as, page_name, pattern, empty_text):
    user = make_user(username="e2e_loaderr_" + page_name.split(".")[0].replace("-", "_"))
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.route(pattern, _boom)
    page.goto(f"{live_server}/pages/{page_name}")
    banner = page.locator('[data-testid="load-error"]')
    banner.wait_for(state="visible", timeout=20000)
    text = banner.inner_text()
    assert "載入失敗" in text and "重試" in text, text
    assert "[object" not in text and "undefined" not in text and "boom" not in text, "錯誤條不可以出現程式碼樣式的字：" + text
    assert "HTTP" not in text and "500" not in text, "錯誤條不可以出現狀態碼（UX 規範：只給白話原因＋重試）：" + text
    if empty_text:
        assert not page.get_by_text(empty_text).first.is_visible(), "讀取失敗時不可以顯示空狀態「%s」（會被當成真的沒資料）" % empty_text
    # 後端恢復 ⇒ 按重試 ⇒ 錯誤條消失
    page.unroute(pattern, _boom)
    page.locator('[data-testid="load-retry"]').click()
    banner.wait_for(state="hidden", timeout=20000)


@pytest.mark.e2e
def test_network_failure_says_the_system_is_unreachable(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_loaderr_net")
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.route("**/api/system/schema-status", lambda r: r.abort("connectionrefused"))
    page.goto(f"{live_server}/pages/schema-status.html")
    banner = page.locator('[data-testid="load-error"]')
    banner.wait_for(state="visible", timeout=20000)
    assert "連不上系統" in banner.inner_text()


@pytest.mark.e2e
@pytest.mark.parametrize("page_name,pattern,empty_text", PAGES, ids=[p[0] for p in PAGES])
def test_401_logs_out_and_returns_to_the_login_page(live_server, make_user, new_page, login_as, page_name, pattern, empty_text):
    """登入過期（401）：五頁一致——清掉本機 session、導回登入頁，不是停在錯誤條上叫人重試（重試永遠不會成功）。"""
    user = make_user(username="e2e_loaderr401_" + page_name.split(".")[0].replace("-", "_"))
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.route(pattern, lambda route: route.fulfill(status=401, content_type="application/json", body=json.dumps({"detail": "未登入"})))
    # login_as 的 init script 每次載入都會重新寫入 session，所以不能事後查 localStorage；改看「通知伺服器登出」那支請求有送出
    logouts = []
    page.on("request", lambda rq: logouts.append(rq.url) if rq.url.endswith("/api/auth/logout") and rq.method == "POST" else None)
    # ⚠️ 不用 wait_for_url（它等 load 事件）：login_as 的 init script 每次載入都重寫 session，登入頁看到有效 session 會再轉走，
    # 負載高時 load 事件前就被轉走 ⇒ 抓不到登入頁那一瞬間（2026-11-13 作者閘門 online-stats 逾時 20 s、單獨重跑 3 秒過）。
    # 改成記下「主框架到過的網址」，只要到過 login.html 就算導回登入頁。
    navs = []
    page.on("framenavigated", lambda fr: navs.append(fr.url) if fr == page.main_frame else None)
    page.goto(f"{live_server}/pages/{page_name}")
    deadline = time.time() + 20
    while time.time() < deadline and not (any("/login.html" in u for u in navs) and logouts):
        page.wait_for_timeout(100)
    assert any("/login.html" in u for u in navs), "401 要導回登入頁；主框架到過的網址：%s" % navs
    assert logouts, "401 要走登出（通知伺服器）而不是停在錯誤條上"
    assert not page.locator('[data-testid="load-error"]').count(), "401 不該顯示載入失敗錯誤條"


@pytest.mark.e2e
def test_403_says_you_have_no_permission_for_this_page(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_loaderr_403")
    page = new_page()
    login_as(page, tuple(user)[:2])
    page.route("**/api/system/schema-status", lambda r: r.fulfill(status=403, content_type="application/json", body=json.dumps({"detail": "forbidden"})))
    page.goto(f"{live_server}/pages/schema-status.html")
    banner = page.locator('[data-testid="load-error"]')
    banner.wait_for(state="visible", timeout=20000)
    text = banner.inner_text()
    assert "您沒有權限查看這一頁" in text and "403" not in text and "HTTP" not in text, text
