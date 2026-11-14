# -*- coding: utf-8 -*-
"""瀏覽器層級：一條龍 P0a（旗標 onepipe.links）——案件頁直接落在材料申請、從案件開請購單／採購單帶好案件。

旗標關：案件頁沒有新入口、?sub=materials 不生效（與今天相同）；旗標開：兩者出現，點「開請購單」到申請頁時案件與類型已選好。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁與費用單據申請頁")

NO = "MQ-OPE2E-001"


def _flag(on):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        SR.publish("onepipe", {"links": 1 if on else 0, **({} if on else {"timeline": 0})}, reason="e2e", user="ope2e", conn=c)      # 關＝入口與時間軸兩個旗標都關（?sub=materials 兩者任一開都會生效）
        c.commit()
    finally:
        c.close()


def _case():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "入口客戶", "入口工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


@pytest.mark.e2e
def test_flag_off_no_entries_and_sub_param_is_ignored(live_server, make_user, e2e_browser):
    u, p = make_user(username="ope2e_off", role="superadmin")
    _case()
    _flag(False)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&sub=materials")
    page.wait_for_selector(f'text={NO}', timeout=15000)
    page.wait_for_timeout(1500)
    assert page.locator('[data-testid="op-open-bar"]').count() == 1 and not page.locator('[data-testid="op-open-bar"]').is_visible()
    assert not page.get_by_text("材料申請清單").is_visible(), "旗標關：?sub=materials 不可把畫面帶到材料申請"


@pytest.mark.e2e
def test_flag_on_sub_param_lands_on_materials_and_open_buttons_prefill_the_case(live_server, make_user, e2e_browser):
    u, p = make_user(username="ope2e_on", role="superadmin")
    _case()
    _flag(True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&sub=materials")
    page.wait_for_selector('[data-testid="op-open-bar"]', state="visible", timeout=15000)
    assert page.get_by_text("材料申請清單").is_visible(), "?sub=materials 要直接落在材料申請"
    href = page.get_attribute('[data-testid="op-open-pr"]', 'href')
    assert href == f"payment-request.html?case={NO}&type=purchase_req", href
    assert page.get_attribute('[data-testid="op-open-po"]', 'href') == f"payment-request.html?case={NO}&type=purchase_order"
    page.click('[data-testid="op-open-pr"]')
    page.wait_for_selector('#pr-typed-form', state="visible", timeout=15000)
    assert page.input_value('#pr-type') == 'purchase_req'
    assert page.locator(f'.pr-case.is-on[data-case-pick="{NO}"]').count() == 1, "案件要已選好，不必重新搜尋"


@pytest.mark.e2e
def test_flag_on_unknown_case_param_stays_on_the_plain_picker(live_server, make_user, e2e_browser):
    u, p = make_user(username="ope2e_unk", role="superadmin")
    _flag(True)
    page = e2e_browser.new_page()
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/payment-request.html?case=MQ-NO-SUCH&type=purchase_order")
    page.wait_for_selector('#pr-cases[data-loaded="1"]', timeout=15000)
    page.wait_for_timeout(1500)
    assert not page.is_visible('#pr-typed-form')
    assert page.locator('.pr-case.is-on').count() == 0
