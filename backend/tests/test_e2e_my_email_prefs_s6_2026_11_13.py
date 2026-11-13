# -*- coding: utf-8 -*-
"""瀏覽器端對端：我的帳號 → 通知分頁 →「我要收的 Email 通知」（S6，2026-11-13；共用元件 settings-matrix.js 的草稿模式）。

驗：點選只算草稿、按儲存才寫入、重整後仍在；簽核／系統技術類取消勾選要跳確認視窗（取消＝不寫入）；
業務類可批次、非業務類被批次略過；手機寬度不橫向捲動；沒有 Email 的提示。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _exec(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _muted(username):
    return json.loads(_q("SELECT notification_muted FROM users WHERE username=?", (username,))[0]["notification_muted"] or "[]")


def _setup(client, make_user, name):
    """一位主角超管＋一位同樣收得到信的超管（免得撞「最後一位最高管理者不能退訂」）；回 (user, items)。"""
    me = make_user(username=name, role="superadmin")
    peer = make_user(username=name + "_peer", role="superadmin")
    for u in (name, name + "_peer"):
        _exec("UPDATE users SET email=?, active=1, notification_muted='[]' WHERE username=?", (u + "@example.test", u))
    assert peer
    r = client.post("/api/auth/login", json={"username": me[0], "password": me[1]})
    items = client.get("/api/mail-types/mine", headers={"Authorization": "Bearer " + r.json()["token"]}).json()["items"]
    return me, items


def _open(live_server, new_page, login_as, user, width=1280):
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, user)
    page.goto(f"{live_server}/pages/my-account.html?tab=notify")
    page.locator("[data-testid=ep-matrix] .mx-row, [data-testid=ep-matrix] .mx-card-row").first.wait_for(state="attached", timeout=20000)
    return page


def _sw(page, key):
    return page.locator("[data-testid='mx-row-%s'] .mx-sw" % key)


def _dlg_btn(page, text):
    return page.locator(".mx-dlg button").filter(has_text=text).first


def _first(items, low_risk):
    return [i["key"] for i in items if i["lowRisk"] is low_risk][0]


@pytest.mark.e2e
def test_click_is_a_draft_until_saved_and_survives_a_reload(live_server, client, make_user, new_page, login_as):
    me, items = _setup(client, make_user, "e2e_ep1")
    key = _first(items, True)
    page = _open(live_server, new_page, login_as, me)
    expect(_sw(page, key)).to_have_attribute("aria-checked", "true")           # 預設全收
    _sw(page, key).click()
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項未儲存的修改")
    assert _muted("e2e_ep1") == [], "草稿階段不寫入"
    page.locator("[data-testid=mx-draft-save]").click()                          # 只動業務類 ⇒ 沒有確認視窗，直接存
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已儲存")
    assert _muted("e2e_ep1") == [key]
    page.reload()
    page.locator("[data-testid='mx-row-%s']" % key).wait_for(state="attached", timeout=20000)
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")


@pytest.mark.e2e
def test_turning_off_a_risky_type_asks_first_and_cancel_writes_nothing(live_server, client, make_user, new_page, login_as):
    me, items = _setup(client, make_user, "e2e_ep2")
    key = _first(items, False)
    page = _open(live_server, new_page, login_as, me)
    _sw(page, key).click()
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "仍要不收").wait_for(state="visible", timeout=10000)
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert _muted("e2e_ep2") == [], "取消確認 ⇒ 不寫入"
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項未儲存的修改")      # 草稿還在，可以再按
    page.locator("[data-testid=mx-draft-save]").click()
    _dlg_btn(page, "仍要不收").wait_for(state="visible", timeout=10000)
    _dlg_btn(page, "仍要不收").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert _muted("e2e_ep2") == [key]


@pytest.mark.e2e
def test_batch_covers_business_rows_and_skips_the_rest(live_server, client, make_user, new_page, login_as):
    me, items = _setup(client, make_user, "e2e_ep3")
    low = [i["key"] for i in items if i["lowRisk"]]
    high = [i["key"] for i in items if not i["lowRisk"]]
    assert low and high
    page = _open(live_server, new_page, login_as, me)
    expect(page.locator("[data-testid='mx-row-%s'] input[type=checkbox]" % high[0])).to_be_disabled()
    page.locator("[data-testid='mx-row-%s'] input[type=checkbox]" % low[0]).check()
    page.locator("[data-testid=mx-batch-off]").click()
    expect(page.locator("[data-testid=mx-draft-count]")).to_contain_text("1 項未儲存的修改")
    page.locator("[data-testid=mx-draft-save]").click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0)
    assert _muted("e2e_ep3") == [low[0]]


@pytest.mark.e2e
def test_no_email_notice_and_phone_width_has_no_horizontal_scroll(live_server, client, make_user, new_page, login_as):
    me, _items = _setup(client, make_user, "e2e_ep4")
    _exec("UPDATE users SET email='' WHERE username=?", ("e2e_ep4",))
    page = _open(live_server, new_page, login_as, me, width=375)
    expect(page.locator("[data-testid=ep-no-email]")).to_be_visible()
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
