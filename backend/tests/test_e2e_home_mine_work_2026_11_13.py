# -*- coding: utf-8 -*-
"""瀏覽器端對端：首頁「我的工作」（UX P1.5，2026-11-13）。分組由伺服器依權限決定，前端只顯示。"""
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.mark.e2e
def test_mine_work_shows_approvals_group_and_empty_state(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_mw_sales", role="sales", modules=["quotation", "case_manage"])
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/index.html")
    sec = page.locator("[data-testid=home-mine-work]")
    sec.wait_for(state="visible", timeout=20000)
    assert sec.locator("h2").inner_text() == "我的工作"
    assert page.locator("[data-testid=home-mine-receivable_overdue]").count() == 0     # 業務沒有「錢」那一組
    # 什麼事都沒有 ⇒ 一句話＋去處，不是一排 0
    empty = page.locator("[data-testid=home-mine-empty]")
    assert empty.is_visible() and "目前沒有需要您處理的事" in empty.inner_text()
    assert empty.locator("a", has_text="看今日工作事項").is_visible()


@pytest.mark.e2e
def test_mine_work_hidden_when_endpoint_fails(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_mw_fail", role="sales", modules=["quotation"])
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.route("**/api/dashboard/mine*", lambda route: route.fulfill(status=500, body="{}"))
    page.goto(f"{live_server}/index.html")
    page.wait_for_selector("h1.h-hero__t", timeout=20000)
    page.wait_for_timeout(1500)
    assert not page.locator("[data-testid=home-mine-work]").is_visible()          # 讀不到 ⇒ 整區不出現（不顯示成 0）


@pytest.mark.e2e
def test_mine_work_lists_pending_item_with_blocker_and_days(live_server, make_user, new_page, login_as):
    import json
    import db
    user = make_user(username="e2e_mw_appr", role="sales", modules=["quotation", "case_manage"])
    data = {"quoteNo": "MQ-MW-001", "approval": {"requestedBy": "someone", "requestedAt": "2026-11-01T09:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": "e2e_mw_appr", "displayName": "我", "status": "pending"}]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("MQ-MW-001", "待審核", "測試客戶", "測試專案", 1000, 952, json.dumps(data, ensure_ascii=False),
                                                       "2026-11-01T09:00:00", "2026-11-01T09:00:00", "", "someone", "[]"))
        conn.commit()
    finally:
        conn.close()
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/index.html")
    card = page.locator("[data-testid=home-mine-approvals]")
    card.wait_for(state="visible", timeout=20000)
    txt = card.inner_text()
    assert "待我簽核" in txt and "測試客戶 測試專案" in txt and "已 " in txt and "天" in txt
    assert not page.locator("[data-testid=home-mine-empty]").is_visible()
    assert card.locator("a.h-mine__go").get_attribute("href") == "pages/approval-queue.html"
