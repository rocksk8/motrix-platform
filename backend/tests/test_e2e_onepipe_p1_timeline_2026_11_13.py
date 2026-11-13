# -*- coding: utf-8 -*-
"""瀏覽器層級：一條龍 P1'（旗標 onepipe.timeline）——案件頁的「物料流程」入口與唯讀時間軸頁。

旗標關：案件頁沒有入口、直接開頁只看到「尚未開放」；旗標開：入口出現，頁面顯示七格與下一步，沒有任何金額。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁與物料流程頁")

NO = "MQ-P1E2E-001"


def _flag(on):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        SR.publish("onepipe", {"timeline": 1 if on else 0}, reason="e2e", user="p1e2e", conn=c)
        c.commit()
    finally:
        c.close()


def _case():
    import db
    data = {"dealTag": "已成案", "caseRecord": {"devices": [{"id": 1, "sn": "SN-E2E", "warrantyStart": "2099-01-01", "warrantyMonths": 12}],
                                                "materialOrders": [{"itemId": "i1", "itemName": "交換器", "unitPrice": 98765, "totalPrice": 98765}]}}
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "流程客戶", "流程工程", 424242, 400000, json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.execute("INSERT OR REPLACE INTO case_material_approvals (quote_no, item_id, doc_code, status, received_on) VALUES (?,?,?,?,?)", (NO, "i1", "MO-E2E-1", "已核准", ""))
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_flag_off_no_entry_and_page_says_not_open(live_server, make_user, e2e_browser):
    u, p = make_user(username="p1e2e_off", role="superadmin")
    _case()
    _flag(False)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="case-link-material-flow"]').count() == 0
    page.goto(f"{live_server}/pages/material-flow.html?q={NO}")
    page.wait_for_selector('[data-testid="mf-err"]', state="visible", timeout=10000)
    assert page.locator('[data-testid^="mf-cell-"]').count() == 0


@pytest.mark.e2e
def test_flag_on_entry_opens_timeline_with_cells_and_next_step_and_no_money(live_server, make_user, e2e_browser):
    u, p = make_user(username="p1e2e_on", role="superadmin")
    _case()
    _flag(True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector('[data-testid="case-link-material-flow"]', state="visible", timeout=15000)
    page.click('[data-testid="case-link-material-flow"]')
    page.wait_for_selector('[data-testid="mf-cell-call"]', timeout=15000)
    keys = page.evaluate("() => [...document.querySelectorAll('[data-testid^=mf-cell-]')].map(e => e.dataset.testid)")
    assert keys == ["mf-cell-call", "mf-cell-purchase", "mf-cell-arrive", "mf-cell-stock", "mf-cell-ship", "mf-cell-device", "mf-cell-warranty"]
    assert page.get_attribute('[data-testid="mf-cell-call"]', 'data-state') == 'done'
    assert page.get_attribute('[data-testid="mf-cell-arrive"]', 'data-state') == 'inprogress'
    assert "MO-E2E-1" in page.inner_text('[data-testid="mf-cell-arrive"]') and "還沒到" in page.inner_text('[data-testid="mf-cell-arrive"]')
    assert page.is_visible('[data-testid="mf-next"]')
    text = page.inner_text('[data-testid="mf-page"]')
    for n in ("98765", "424242", "400000"):
        assert n not in text, "畫面不得出現金額：" + n
    href = page.get_attribute('[data-testid="mf-next-go"]', 'href')
    assert NO in href
    page.click('[data-testid="mf-back"]')
    page.wait_for_url(lambda url: "case-management.html" in url and NO in url, timeout=10000)
