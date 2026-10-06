# -*- coding: utf-8 -*-
"""輪到我簽核時，主選單「我的工作」群組標題要有紅點（使用者 2026-10-01）。

來源＝`/api/approval-queue/count`（與簽核佇列項目的數字徽章同一份；canApprove 的項目數）——不是未讀通知列（登入彈窗的舊 bug）。
驗：有待簽 ⇒ 群組標題的紅點可見（下拉收起也看得到）、面板內徽章同數字；簽完（簽核佇列頁重抓清單）⇒ 紅點消失；沒有待簽的人 ⇒ 沒有紅點；
顏色是語意 token（`--danger`；淺色／深色各自解析成不同值，不是寫死色碼）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

DOT = "#sb-dot-mywork"
BADGE = "#sb-approval-badge"
QNO = "MQ-DOT-001"


def _hdr(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _pending_for(username):
    import db
    appr = {"requestedBy": "dot_requester", "requestedByDisplay": "申請人", "requestedAt": "2026-10-01T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": username, "displayName": username, "status": "pending"}]}]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?)", (QNO, "待審核", "客戶", "專案", 1000, json.dumps({"approval": appr}, ensure_ascii=False),
                                                  "2026-10-01", "2026-10-01"))
        conn.commit()
    finally:
        conn.close()


def _open(page, live_server, path="quotations.html"):
    with page.expect_response(lambda r: "/api/approval-queue/count" in r.url, timeout=30000) as resp:
        page.goto("%s/pages/%s" % (live_server, path))
    page.wait_for_selector(".mnav__grp", state="attached", timeout=30000)
    return resp.value


@pytest.fixture()
def world(client, make_user):
    make_user(username="dot_requester", role="admin")
    waiting = make_user(username="dot_waiting", role="admin")
    idle = make_user(username="dot_idle", role="admin")
    _pending_for("dot_waiting")
    return client, waiting, idle


@pytest.mark.e2e
def test_dot_shows_for_a_user_with_a_pending_approval_and_goes_away_after_approving(live_server, world, new_context):
    client, waiting, _idle = world
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, waiting[0], waiting[1])
    r = _open(page, live_server)
    assert r.json()["count"] == 1
    page.wait_for_selector(DOT, state="visible", timeout=15000)               # 下拉收起（沒有 hover）也看得到
    assert page.inner_text(BADGE) == "1" or page.evaluate("() => document.getElementById('sb-approval-badge').textContent") == "1"
    # 簽掉（API），再由簽核佇列頁重抓清單——頁面自己每次處理完都會這樣做——紅點要消失
    page2 = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page2, live_server, waiting[0], waiting[1])
    _open(page2, live_server, "approval-queue.html")
    page2.wait_for_selector(DOT, state="visible", timeout=15000)
    ok = client.post("/api/quotations/%s/approve" % QNO, headers=_hdr(client, waiting), json={})
    assert ok.status_code == 200, ok.text
    with page2.expect_response(lambda x: "/api/approval-queue/count" in x.url, timeout=15000):
        page2.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).loadQueue()")
    page2.wait_for_function("() => { const d = document.getElementById('sb-dot-mywork'); return !!d && getComputedStyle(d).display === 'none' }", timeout=15000)
    assert not page2.locator(DOT).is_visible()


@pytest.mark.e2e
def test_no_dot_for_a_user_with_nothing_waiting(live_server, world, new_context):
    _client, _waiting, idle = world
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, idle[0], idle[1])
    r = _open(page, live_server)
    assert r.json()["count"] == 0
    page.wait_for_timeout(800)                                                  # 不會出現的東西只能等一下再確認
    assert not page.locator(DOT).is_visible()


@pytest.mark.e2e
def test_dot_color_is_the_semantic_danger_token_in_light_and_dark(live_server, world, new_context):
    _client, waiting, _idle = world
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, waiting[0], waiting[1])
    _open(page, live_server)
    page.wait_for_selector(DOT, state="visible", timeout=15000)
    RESOLVE = """() => { const p = document.createElement('i'); p.style.background = 'var(--danger)'; document.body.appendChild(p);
        const tok = getComputedStyle(p).backgroundColor; p.remove(); return [getComputedStyle(document.getElementById('sb-dot-mywork')).backgroundColor, tok] }"""
    light_dot, light_tok = page.evaluate(RESOLVE)
    assert light_dot == light_tok, "紅點不是 --danger 的值（寫死色碼？）"
    page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
    dark_dot, dark_tok = page.evaluate(RESOLVE)
    assert dark_dot == dark_tok and dark_dot != light_dot, "深色模式紅點應跟著 token 換色"


@pytest.mark.e2e
@pytest.mark.parametrize("path", ["index.html", "daily-tasks.html", "quotations.html"])
def test_plain_role_user_approver_gets_the_dot_on_every_page(live_server, client, make_user, new_context, path):
    """一般使用者（role=user，不是管理員）是最常見的簽核人：通知資料元件原本只掛在「管理員才有的通知鈴鐺」裡（第44班起所有角色都有鈴鐺，同一個實例），
    ⇒ 這類使用者在任何頁面都不會抓待簽數、沒有紅點／徽章／登入橫幅。現在掛一個看不見的實例（不畫鈴鐺）。"""
    make_user(username="dot_requester", role="admin")
    u = make_user(username="dot_waiting", role="user", modules=["quotation", "daily_task"])
    _pending_for("dot_waiting")
    page = new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    url = live_server + ("/index.html" if path == "index.html" else "/pages/" + path)
    with page.expect_response(lambda r: "/api/approval-queue/count" in r.url, timeout=30000):
        page.goto(url)
    page.wait_for_selector(DOT, state="visible", timeout=15000)
    assert page.locator(BADGE).count() == 1 and page.evaluate("() => document.getElementById('sb-approval-badge').textContent") == "1"
    # 第44班（使用者裁示）：所有角色都有通知鈴鐺——同一個 notifStore 實例既是鈴鐺也是紅點／徽章的資料來源（不再有隱形元件）
    assert page.locator('[data-testid="notif-headless"]').count() == 0
    assert page.locator(".topbar__btn:has-text('通知')").count() == 1, "一般使用者也要有通知鈴鐺"
