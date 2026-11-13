# -*- coding: utf-8 -*-
"""案件管理頁 `?quick=` 深連結（UX P1.5，2026-11-13）：首頁「我的工作」連過來要帶著篩選；四個常用篩選逐一點過。"""
import pytest

pytest.importorskip("playwright.sync_api")

KEYS = ["mine", "stage_overdue", "recv_overdue", "missing_docs"]


def _pressed(page):
    return {k: page.locator(f"[data-testid=case-quick-filters] [data-quick={k}]").get_attribute("aria-pressed") for k in KEYS}


def _open(live_server, page, login_as, user, query=""):
    login_as(page, user)
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/api/quotations?" in r.url else None)
    page.goto(f"{live_server}/pages/case-management.html{query}")
    page.locator("[data-testid=case-quick-filters]").wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(800)
    return reqs


@pytest.mark.e2e
def test_quick_param_preselects_and_first_request_is_already_filtered(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_cq_a", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    reqs = _open(live_server, page, login_as, user, "?quick=mine,stage_overdue,不認得的")
    assert _pressed(page) == {"mine": "true", "stage_overdue": "true", "recv_overdue": "false", "missing_docs": "false"}
    first = next(u for u in reqs if "deal_tag" in u)
    assert "mine=1" in first and "stage_overdue=1" in first and "recv_overdue" not in first      # 第一次載入就帶篩選，不先閃未篩選的清單


@pytest.mark.e2e
def test_no_quick_param_means_nothing_selected(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_cq_b", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    _open(live_server, page, login_as, user)
    assert set(_pressed(page).values()) == {"false"}


@pytest.mark.e2e
@pytest.mark.parametrize("key", KEYS)
def test_every_quick_filter_toggles_and_reaches_the_server(live_server, make_user, new_page, login_as, key):
    user = make_user(username="e2e_cq_" + key, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    reqs = _open(live_server, page, login_as, user)
    n0 = len(reqs)
    btn = page.locator(f"[data-testid=case-quick-filters] [data-quick={key}]")
    btn.click()
    page.wait_for_function("(k) => document.querySelector(`[data-quick=${k}]`).getAttribute('aria-pressed') === 'true'", arg=key, timeout=10000)
    page.wait_for_timeout(500)
    assert any(f"{key}=1" in u for u in reqs[n0:]), reqs[n0:]
    btn.click()
    page.wait_for_function("(k) => document.querySelector(`[data-quick=${k}]`).getAttribute('aria-pressed') === 'false'", arg=key, timeout=10000)


@pytest.mark.e2e
def test_dashboard_case_links_use_supported_quick_keys(live_server, make_user, client):
    """首頁連到案件頁的每個 `?quick=` 值都必須是頁面認得的篩選（連到不存在的參數＝靜默失效）。"""
    from routers import dashboard_mine as DM
    sa = make_user(username="e2e_cq_links", role="superadmin")
    DM.reset_cache()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]}).json()["token"]}
    d = client.get("/api/dashboard/mine", headers=h).json()
    seen = set()
    for g in d["groups"]:
        for href in [g.get("href", "")] + [i.get("href", "") for i in g["items"]]:
            if "quick=" in href:
                seen.update(href.split("quick=")[1].split("&")[0].split(","))
    assert seen and seen <= set(KEYS), seen
