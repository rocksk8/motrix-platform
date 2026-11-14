# -*- coding: utf-8 -*-
"""瀏覽器層級：一條龍 P4a（旗標 onepipe.entry_unify）——現場人員在每日工作事項頁新增「掛案件、指派給自己」的事項。

旗標關：工具列沒有「新增我的案件事項」；旗標開：有，建立後事項出現在自己的清單。最高管理者的畫面不受影響（不出現這顆鈕）。
"""
import datetime
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的新增事項要掛案件（案件清單來自 M01）")

NO = "MQ-P4AE2E-001"
BTN = '[data-testid="dt-self-add"]'


def _flag(on):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        SR.publish("onepipe", {"entry_unify": 1 if on else 0}, reason="e2e", user="p4ae2e", conn=c)
        c.commit()
    finally:
        c.close()


def _case(username):
    import db
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "自建客戶", "自建工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", json.dumps([uid])))
        c.commit()
    finally:
        c.close()


def _open(page, live_server):
    page.goto(f"{live_server}/pages/daily-tasks.html")
    page.wait_for_selector("[data-testid=dt-more]", timeout=20000)


@pytest.mark.e2e
def test_flag_off_staff_has_no_self_add_button(live_server, make_user, e2e_browser):
    u, p = make_user(username="p4ae_off", role="engineer", modules=["daily_task"])
    _case(u)
    _flag(False)
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    _open(page, live_server)
    page.wait_for_timeout(1500)                                  # 旗標是非同步讀的；關著＝一直不會出現（負向，給它時間）
    assert page.locator(BTN).count() == 0


@pytest.mark.e2e
def test_flag_on_staff_creates_a_case_task_and_sees_it(live_server, make_user, e2e_browser):
    u, p = make_user(username="p4ae_on", role="engineer", modules=["daily_task"])
    _case(u)
    _flag(True)
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    _open(page, live_server)
    page.locator(BTN).wait_for(state="visible", timeout=10000)
    page.click(BTN)
    page.locator('[data-testid="dt-self-modal"]').wait_for(state="visible", timeout=5000)
    page.wait_for_function("(no) => [...document.querySelectorAll('[data-testid=dt-self-case] option')].some(o => o.value === no)", arg=NO, timeout=10000)
    page.select_option('[data-testid="dt-self-case"]', NO)
    page.fill('[data-testid="dt-self-title"]', "到場確認設備位置E2E")
    page.fill('[data-testid="dt-self-date"]', datetime.date.today().isoformat())
    page.click('[data-testid="dt-self-save"]')
    page.locator('[data-testid="dt-self-modal"]').wait_for(state="hidden", timeout=10000)
    # 事項進了本人的清單（頁面的 tasks 狀態；畫面有多種檢視、同名標題也出現在隱藏的完成明細，不靠找文字）
    page.wait_for_function("(t) => { const d = Alpine.$data(document.querySelector('[x-data]')); return d.tasks.some(x => x.title === t) }",
                           arg="到場確認設備位置E2E", timeout=10000)


@pytest.mark.e2e
def test_superadmin_never_sees_the_self_add_button(live_server, make_user, e2e_browser):
    u, p = make_user(username="p4ae_sa", role="superadmin")
    _flag(True)
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    _open(page, live_server)
    page.wait_for_timeout(1500)
    assert page.locator(BTN).count() == 0


@pytest.mark.e2e
def test_flag_on_staff_without_any_case_is_told_why_the_list_is_empty(live_server, make_user, e2e_browser):
    """沒有可掛的案件時，下拉不是靜默空白：說出原因、下拉停用（h9 審查：不留沒有說明的空清單）。"""
    u, p = make_user(username="p4ae_nocase", role="engineer", modules=["daily_task"])
    _flag(True)
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    _open(page, live_server)
    page.locator(BTN).wait_for(state="visible", timeout=10000)
    page.click(BTN)
    note = page.locator('[data-testid="dt-self-cases-notice"]')
    note.wait_for(state="visible", timeout=5000)
    page.wait_for_function("() => document.querySelector('[data-testid=dt-self-cases-notice]').innerText.includes('尚無可關聯')", timeout=10000)
    assert page.locator('[data-testid="dt-self-case"]').is_disabled()
