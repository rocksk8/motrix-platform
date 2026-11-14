"""首頁「等我簽核」數字／清單與簽核佇列連動（使用者 2026-09-30）。
觀測點：首頁 band 的數字、下方清單筆數、側欄角標端點，三者同一個值；簽核之後回到首頁（focus）三者一起變。"""
from tests._requires import requires_module  # noqa: E402
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_queue_and_feed_scoping_2026_09_15 import _insert_pending_quotation  # noqa: E402

pytestmark = requires_module("case", "打 M01（案件）的資料")


@pytest.mark.e2e
def test_home_count_list_and_badge_agree_and_follow_approval(live_server, make_user, e2e_browser, client):
    u, p = make_user(username="w2h_appr", role="admin")[:2]
    make_user(username="w2h_sales", role="sales")
    _insert_pending_quotation("MQ-W2H-001", "w2h_sales", [["w2h_appr"]])
    _insert_pending_quotation("MQ-W2H-002", "w2h_sales", [["w2h_appr"]])
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    sess = inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/index.html")
    page.wait_for_function("() => document.querySelectorAll('[data-testid=home-mine-row]').length === 2", timeout=20000)
    assert page.locator('[data-testid=band-approvals] .h-band__n').inner_text().strip() == "2"
    assert page.locator('[data-testid="home-mine-count"]').count() == 0     # 2026-11-11 D1：清單標題不再重複數字（統計卡＋清單列數負責）
    h = {"Authorization": "Bearer " + sess["token"]}
    assert client.get("/api/approval-queue/count", headers=h).json()["count"] == 2
    r = client.post("/api/quotations/MQ-W2H-001/approve", headers=h, json={})
    assert r.status_code == 200, r.text[:300]
    # 首頁的 focus 監聽在 init() 讀完統計之後才掛（清單列出現時可能還沒掛）⇒ 只丟一次 focus 偶爾落空（單獨重跑約 1/4 紅）。
    # 改成每 500 ms 丟一次再檢查（首頁自己 300 ms 內去重、同時只飛一趟）；要驗的是「簽核之後回到首頁會跟著變」，不是監聽掛上的先後。
    page.wait_for_function("() => { window.dispatchEvent(new Event('focus')); return document.querySelectorAll('[data-testid=home-mine-row]').length === 1 }", polling=500, timeout=15000)
    assert page.locator('[data-testid=band-approvals] .h-band__n').inner_text().strip() == "1"
    assert client.get("/api/approval-queue/count", headers=h).json()["count"] == 1


@pytest.mark.e2e
def test_focus_before_stats_returns_still_refreshes_the_approval_count(live_server, make_user, e2e_browser, client):
    """2026-11-13（PM）：init() 原本先 await 完 stats 才掛 focus 監聽，stats 慢的時候回到分頁的 focus 事件被丟掉、
    「等我簽核」不更新。監聽要先掛、再 await：stats 還沒回來就觸發 focus，數字也要跟上。"""
    u, p = make_user(username="w2h_early", role="admin")[:2]
    make_user(username="w2h_early_s", role="sales")
    _insert_pending_quotation("MQ-W2H-E01", "w2h_early_s", [["w2h_early"]])
    _insert_pending_quotation("MQ-W2H-E02", "w2h_early_s", [["w2h_early"]])
    ctx = e2e_browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    held = []
    page.route("**/api/dashboard/bundle*", lambda route: route.abort())          # T86 U7：儀表板六段開頁走 bundle；這題要卡的是單打 stats ⇒ bundle 失敗、各段退回原端點
    page.route("**/api/dashboard/stats*", lambda route: held.append(route))      # stats 一直不回
    sess = inject_login(page, live_server, u, p)
    h = {"Authorization": "Bearer " + sess["token"]}
    page.goto(f"{live_server}/index.html")
    page.wait_for_function("() => window.__mineAt > 0", timeout=20000)             # 簽核數字那一趟已回來
    page.wait_for_timeout(600)                                                      # 過了「事件 300 ms 內不重送」的窗
    assert held, "stats 請求應該卡住了（測試前提）"
    r = client.post("/api/quotations/MQ-W2H-E01/approve", headers=h, json={})
    assert r.status_code == 200, r.text[:300]
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")               # stats 還沒回來就回到分頁
    page.wait_for_function("() => window.__mineAt > 0 && !window.__mineInflight", timeout=10000)
    for route in held:
        route.continue_()                                                           # 這時才放行 stats
    page.wait_for_function("() => document.querySelectorAll('[data-testid=home-mine-row]').length === 1", timeout=15000)
    assert page.locator('[data-testid=band-approvals] .h-band__n').inner_text().strip() == "1"
