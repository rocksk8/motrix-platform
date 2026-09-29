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
    assert page.locator('.h-band__c .h-band__n').first.inner_text().strip() == "2"
    assert "2" in page.locator('[data-testid="home-mine-count"]').inner_text()
    h = {"Authorization": "Bearer " + sess["token"]}
    assert client.get("/api/approval-queue/count", headers=h).json()["count"] == 2
    r = client.post("/api/quotations/MQ-W2H-001/approve", headers=h, json={})
    assert r.status_code == 200, r.text[:300]
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    page.wait_for_function("() => document.querySelectorAll('[data-testid=home-mine-row]').length === 1", timeout=10000)
    assert page.locator('.h-band__c .h-band__n').first.inner_text().strip() == "1"
    assert client.get("/api/approval-queue/count", headers=h).json()["count"] == 1
