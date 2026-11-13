# -*- coding: utf-8 -*-
"""簽核頁「據點」列（UX 提案 D2，2026-11-13）：這一頁原本向 `/settings/company-profile`（少了 /api）取據點 ⇒ 404，
而且佇列項目本身也沒帶 `locationId` ⇒ 「據點」那一列從來不會出現。兩個都補上。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")


def _seed(quote_no, approver, location_id):
    import db
    at = "2026-11-10T09:00:00"
    data = {"quoteNo": quote_no, "approval": {"requestedBy": "someone", "requestedAt": at, "currentTier": 0,
            "tiers": [{"approvers": [{"username": approver, "displayName": approver, "status": "pending"}]}]}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, "
                     "deal_tag, sales_person, assigned_user_ids, location_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "待審核", "據點客戶", "據點專案", 1000, 952, json.dumps(data, ensure_ascii=False), at, at, "", "someone", "[]", location_id))
        conn.commit()
    finally:
        conn.close()


def test_queue_items_carry_location_id(client, make_user):
    u = make_user("e2e_loc_api", role="superadmin")
    _seed("MQ-LOC-API", "e2e_loc_api", "L2")
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    q = client.get("/api/approval-queue", headers={"Authorization": "Bearer " + tok}).json()
    items = [it for g in q["queue"] for it in g["items"] if it["quoteNo"] == "MQ-LOC-API"]
    assert items and items[0]["locationId"] == "L2"


@pytest.mark.e2e
def test_drawer_shows_location_when_company_has_several(live_server, make_user, new_page, login_as):
    from helpers.settings import _set_setting
    user = make_user(username="e2e_loc_ui", role="superadmin")
    _set_setting("company_profile", {"locations": [{"id": "L1", "name": "台北總公司", "address": "台北市"},
                                                   {"id": "L2", "name": "五股分公司", "address": "新北市五股區"}]})
    _seed("MQ-LOC-UI", "e2e_loc_ui", "L2")
    page = new_page(viewport={"width": 1440, "height": 900})
    bad = []
    page.on("response", lambda r: bad.append(r.url) if "company-profile" in r.url and r.status >= 400 else None)
    login_as(page, user)
    page.goto(f"{live_server}/pages/approval-queue.html")
    card = page.locator("[data-testid='aq-item-MQ-LOC-UI']").first
    card.wait_for(state="visible", timeout=20000)
    card.click()
    row = page.locator(".aq-info-row", has_text="據點").first
    row.wait_for(state="visible", timeout=20000)
    assert "五股分公司" in row.inner_text()
    assert not bad, "company-profile 請求不可失敗：%s" % bad


@pytest.mark.e2e
def test_single_location_company_hides_the_row(live_server, make_user, new_page, login_as):
    from helpers.settings import _set_setting
    user = make_user(username="e2e_loc_one", role="superadmin")
    _set_setting("company_profile", {"locations": [{"id": "L1", "name": "唯一據點", "address": "台北市"}]})
    _seed("MQ-LOC-ONE", "e2e_loc_one", "L1")
    page = new_page(viewport={"width": 1440, "height": 900})
    login_as(page, user)
    page.goto(f"{live_server}/pages/approval-queue.html")
    card = page.locator("[data-testid='aq-item-MQ-LOC-ONE']").first
    card.wait_for(state="visible", timeout=20000)
    card.click()
    page.locator(".aq-info-row", has_text="客戶").first.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(500)
    assert not page.locator(".aq-info-row", has_text="據點").first.is_visible()      # 只有一個據點時不顯示（QL15）
