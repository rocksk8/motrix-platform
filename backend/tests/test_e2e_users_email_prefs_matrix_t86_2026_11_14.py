# -*- coding: utf-8 -*-
"""瀏覽器端對端：使用者管理 → 編輯 →「Email 通知偏好」矩陣（T86，2026-11-14）。
矩陣只改表單狀態；按視窗的「儲存變更」才寫入 users.notification_muted。觀測點打在資料庫落地值與元件狀態。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

_MAKE_USER_DEFAULT_ROLE = "superadmin"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _muted(username):
    return json.loads(_q("SELECT notification_muted FROM users WHERE username=?", (username,))[0]["notification_muted"] or "[]")


def _items(client, sa, username):
    r = client.post("/api/auth/login", json={"username": sa[0], "password": sa[1]})
    uid = _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]
    d = client.get("/api/mail-types/receivable?user_id=%d" % uid, headers={"Authorization": "Bearer " + r.json()["token"]}).json()
    return uid, d["items"]


def _open(live_server, new_page, login_as, sa, uid, width=1400):
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, sa)
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_function(f"() => {DATA}.users && {DATA}.users.length > 0", timeout=20000)
    page.evaluate(f"() => {DATA}.openEdit({DATA}.users.find(u => u.id === {uid}))")
    page.locator("[data-testid=up-email-matrix] .mx-row, [data-testid=up-email-matrix] .mx-card-row").first.wait_for(state="attached", timeout=20000)
    return page


def _sw(page, key):
    return page.locator("[data-testid='mx-row-%s'] .mx-sw" % key)


def _muted_in_form(page):
    return page.evaluate(f"() => [...{DATA}.form.notificationMuted]")


def _save(page):
    page.get_by_role("button", name="儲存變更").first.click()
    page.wait_for_function(f"() => !{DATA}.showModal", timeout=15000)


@pytest.mark.e2e
def test_not_receivable_rows_are_listed_but_disabled(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa1", role="superadmin")
    make_user(username="t86e_adm", role="admin")
    uid, items = _items(client, sa, "t86e_adm")
    out = [i["key"] for i in items if not i["receivable"]]
    assert out, "前提：管理員收不到某些系統技術類信件"
    page = _open(live_server, new_page, login_as, sa, uid)
    expect(_sw(page, out[0])).to_be_disabled()
    expect(_sw(page, out[0])).to_have_attribute("aria-checked", "false")
    expect(page.locator("[data-testid=up-email-summary]")).to_contain_text("不在收件範圍")


@pytest.mark.e2e
def test_click_changes_the_form_only_and_the_save_button_persists_it(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa2", role="superadmin")
    make_user(username="t86e_u2", role="admin")
    uid, items = _items(client, sa, "t86e_u2")
    key = [i["key"] for i in items if i["receivable"] and i["lowRisk"]][0]
    page = _open(live_server, new_page, login_as, sa, uid)
    expect(_sw(page, key)).to_have_attribute("aria-checked", "true")
    _sw(page, key).click()
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")
    assert _muted_in_form(page) == [key]
    assert _muted("t86e_u2") == [], "矩陣不直接寫入帳號"
    _save(page)
    assert _muted("t86e_u2") == [key]


@pytest.mark.e2e
def test_batch_off_then_undo_this_batch(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa3", role="superadmin")
    make_user(username="t86e_u3", role="admin")
    uid, items = _items(client, sa, "t86e_u3")
    low = [i["key"] for i in items if i["receivable"] and i["lowRisk"]][:2]
    assert len(low) == 2
    page = _open(live_server, new_page, login_as, sa, uid)
    for k in low:
        page.locator("input[data-mx=sel][data-key='%s']" % k).locator("visible=true").check()
    page.locator("[data-testid=mx-batch-off]").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("2 項")
    assert sorted(_muted_in_form(page)) == sorted(low)
    page.locator("[data-testid=mx-undo]").click()
    page.wait_for_function(f"() => {DATA}.form.notificationMuted.length === 0", timeout=10000)
    assert _muted("t86e_u3") == []


@pytest.mark.e2e
def test_undo_is_refused_when_the_batch_was_touched_afterwards(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa4", role="superadmin")
    make_user(username="t86e_u4", role="admin")
    uid, items = _items(client, sa, "t86e_u4")
    low = [i["key"] for i in items if i["receivable"] and i["lowRisk"]][:2]
    page = _open(live_server, new_page, login_as, sa, uid)
    for k in low:
        page.locator("input[data-mx=sel][data-key='%s']" % k).locator("visible=true").check()
    page.locator("[data-testid=mx-batch-off]").click()
    undo = page.locator("[data-testid=mx-undo]")
    undo.wait_for(state="visible", timeout=10000)
    page.evaluate(f"(k) => {{ const m = {DATA}.form.notificationMuted; m.splice(m.indexOf(k), 1) }}", low[0])      # 批次之後這一項被別處改回「收」
    undo.click()
    expect(page.locator("[data-testid=mx-toast-text]").last).to_contain_text("不能整批復原")
    assert _muted_in_form(page) == [low[1]], "整批不復原：沒有動到其他項目"


@pytest.mark.e2e
def test_turning_off_a_risky_type_asks_first(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa5", role="superadmin")
    make_user(username="t86e_u5", role="superadmin")
    uid, items = _items(client, sa, "t86e_u5")
    key = [i["key"] for i in items if i["receivable"] and not i["lowRisk"]][0]
    page = _open(live_server, new_page, login_as, sa, uid)
    expect(page.locator("[data-testid='mx-row-%s'] input[type=checkbox]" % key)).to_be_disabled()      # 非業務類不能批次
    _sw(page, key).click()
    page.locator(".mx-dlg button").filter(has_text="取消").first.click()
    assert _muted_in_form(page) == [], "取消確認 ⇒ 表單不變"
    _sw(page, key).click()
    page.locator(".mx-dlg button").filter(has_text="仍要不收").first.click()
    page.wait_for_function(f"() => {DATA}.form.notificationMuted.length === 1", timeout=10000)
    assert _muted_in_form(page) == [key]


@pytest.mark.e2e
def test_phone_width_has_no_horizontal_scroll(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa6", role="superadmin")
    make_user(username="t86e_u6", role="admin")
    uid, _items_ = _items(client, sa, "t86e_u6")
    page = _open(live_server, new_page, login_as, sa, uid, width=375)
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def _footer_save_is_reachable(page):
    return page.evaluate("""() => {
        const b = [...document.querySelectorAll('.modal-foot .btn-primary')].find(x => x.offsetParent);
        const r = b.getBoundingClientRect();
        const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return b === el || b.contains(el);
    }""")


@pytest.mark.e2e
@pytest.mark.parametrize("width", [390, 1440])
def test_batch_bar_does_not_cover_the_modal_save_button(live_server, client, make_user, new_page, login_as, width):
    sa = make_user(username="t86e_sa7_%d" % width, role="superadmin")
    make_user(username="t86e_u7_%d" % width, role="admin")
    uid, items = _items(client, sa, "t86e_u7_%d" % width)
    low = [i["key"] for i in items if i["receivable"] and i["lowRisk"]][:2]
    page = _open(live_server, new_page, login_as, sa, uid, width=width)
    for k in low:
        page.locator("input[data-mx=sel][data-key='%s']" % k).locator("visible=true").check()
    page.locator("[data-testid=mx-batch-off]").wait_for(state="visible", timeout=10000)
    page.evaluate("() => document.querySelector('.modal-foot .btn-primary').scrollIntoView({block: 'end'})")
    assert _footer_save_is_reachable(page), "選了列之後，批次動作列蓋住「儲存變更」"


@pytest.mark.e2e
def test_toolbar_does_not_float_over_rows_in_the_modal(live_server, client, make_user, new_page, login_as):
    sa = make_user(username="t86e_sa8", role="superadmin")
    make_user(username="t86e_u8", role="admin")
    uid, _items_ = _items(client, sa, "t86e_u8")
    page = _open(live_server, new_page, login_as, sa, uid, width=1440)
    assert page.evaluate("() => getComputedStyle(document.querySelector('#up-email-box .mx-sticky')).position") == "static"
