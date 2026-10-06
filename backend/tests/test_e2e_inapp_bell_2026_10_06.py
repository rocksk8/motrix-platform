# -*- coding: utf-8 -*-
"""站內通知鈴鐺（第44班）：所有角色可見；點通知＝標已讀並開對應單據；管理員既有鈴鐺行為不變（有「查看全部操作紀錄」連結）；一般人沒有。"""
import pytest

from tests._e2e_login import inject_login
from helpers.audit import _notify

BELL = ".topbar__btn:has-text('通知')"


def _open(page, live_server, path="index.html"):
    page.goto(live_server + ("/index.html" if path == "index.html" else "/pages/" + path))
    page.wait_for_selector(".topbar__btn", state="attached", timeout=30000)


@pytest.mark.e2e
@pytest.mark.parametrize("role,mods", [("viewer", ["dashboard"]), ("sales", ["quotation"]), ("engineer", ["case_manage"]), ("finance", None), ("admin", None)])
def test_every_role_has_the_bell_with_an_unread_badge_and_a_working_click(live_server, make_user, new_context, role, mods):
    u = make_user(username="eb_" + role, role=role, modules=mods)
    _notify("eb_" + role, "bellcheck_approved", "S-1", "S-1", "出貨單 S-1 已核准", "customers.html")
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    page.wait_for_selector(BELL, state="visible", timeout=15000)
    page.wait_for_function("() => { const b = [...document.querySelectorAll('.topbar__btn')].find(x => x.textContent.includes('通知')); return b && b.querySelector('span') && b.querySelector('span').offsetParent !== null }", timeout=15000)
    page.locator(BELL).click()
    row = page.locator('[data-notif-id]').first
    row.wait_for(state="visible", timeout=10000)
    assert row.get_attribute("data-unread") == "1"
    audit_link = page.locator('[x-data="notifStore()"] a[href$="audit-log.html"]')
    assert (audit_link.count() >= 1) == (role == "admin"), "『查看全部操作紀錄』只給管理員（鈴鐺本身所有角色都有）"
    with page.expect_navigation(timeout=15000):
        row.click()
    assert page.url.endswith("customers.html"), page.url                        # link 是 customers.html ⇒ 點了開那一頁（相對 pages/）
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT is_read FROM notifications WHERE username=?", ("eb_" + role,)).fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.e2e
def test_a_notification_without_a_link_only_marks_read_and_a_bad_link_is_not_followed(live_server, make_user, new_context):
    u = make_user(username="eb_nolink", role="viewer", modules=["dashboard"])
    _notify("eb_nolink", "info", "x", "無連結", "純文字")
    import db
    conn = db.get_db()
    conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at, link) VALUES (?,?,?,?,?,?,?,?)",
                 ("eb_nolink", "info", "y", "壞連結", "資料庫裡被塞了外部網址", 0, "2026-10-06T10:00:00", "http://evil.example/x.html"))
    conn.commit()
    conn.close()
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    page.locator(BELL).click()
    page.wait_for_selector('[data-notif-id]', state="visible", timeout=10000)
    url0 = page.url
    for i in range(page.locator('[data-notif-id]').count()):
        page.locator('[data-notif-id]').nth(i).click()
    page.wait_for_timeout(600)
    assert page.url == url0 and "evil" not in page.url, "沒有連結／連結不合格 ⇒ 只標已讀，不導頁"
    page.wait_for_function("() => document.querySelectorAll('[data-notif-id][data-unread=\"1\"]').length === 0", timeout=10000)
