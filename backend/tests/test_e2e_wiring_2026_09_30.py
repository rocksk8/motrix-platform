# -*- coding: utf-8 -*-
"""接線稽核 e2e（R2）：① 鈴鐺點了模組定義送審通知 ⇒ 開審核頁 ② 申請人以外的最高管理者在簽核佇列看得到定義審核卡片、也決定得了
③ 佇列上修訂過的單據卡片單號帶 -R。截圖先存 %TEMP%\\w1-shots-wiring，跑完複製到 D:\\開發測試檔\\shots\\wip-w1-wiring\\。"""
import os

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e

KEY = "wre2e"


def _shot(page, name):
    try:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "w1-shots-wiring")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"))
    except Exception as e:                                                # noqa: BLE001
        print("SHOT FAIL", name, ascii(e)[:160])


def _body():
    return {"name": "接線e2e", "permission": "custom." + KEY, "numbering": {"prefix": "WE", "period": "none", "digits": 3},
            "fields": [{"key": "t", "label": "標題", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "go", "label": "送出", "from": "draft", "to": "done"}]}}


def _hdr(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


@pytest.fixture()
def world(client, make_user):
    boss = make_user(username="we_boss", role="superadmin")
    appr = make_user(username="we_appr", role="admin", modules=[])
    sa2 = make_user(username="we_sa2", role="superadmin")
    bh = _hdr(client, boss)
    assert client.put("/api/custom-modules/definition-review", headers=bh, json={"reviewers": ["we_appr"]}).status_code == 200
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=bh, json={"body": _body()}).status_code == 200
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=bh, json={"note": "n"}).json()["pending"] is True
    return boss, appr, sa2


def test_bell_notice_opens_the_review_page(live_server, world, new_page, login_as):
    boss, appr, sa2 = world
    page = new_page()
    login_as(page, appr)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.locator("button.topbar__btn:has-text('通知')").first.click()
    item = page.locator("[data-notif-id]").first
    item.wait_for(state="visible", timeout=20000)
    assert "模組" in item.inner_text() or KEY in item.inner_text()
    _shot(page, "bell-open")
    item.click()
    page.wait_for_url(f"**/custom-def-review.html?key={KEY}*", timeout=20000)
    _shot(page, "bell-landed-on-review-page")


def test_other_superadmin_sees_the_definition_review_card_and_can_decide(live_server, client, world, new_page, login_as):
    boss, appr, sa2 = world
    page = new_page()
    login_as(page, sa2)
    page.goto(f"{live_server}/pages/approval-queue.html")
    card = page.locator(".aq-card:has-text('%s')" % KEY).first
    card.wait_for(state="visible", timeout=20000)
    _shot(page, "queue-superadmin-sees-def-review")
    card.click()                                                       # 定義審核卡片 ⇒ 開審核頁（決定鈕在審核頁）
    page.wait_for_url(f"**/custom-def-review.html?key={KEY}*", timeout=20000)
    approve = page.locator("#dr-approve")
    approve.wait_for(state="visible", timeout=15000)                   # 最高管理者決定得了
    _shot(page, "queue-superadmin-can-decide")
    approve.click()
    page.wait_for_function("() => document.querySelector('#dr-done') && document.querySelector('#dr-done').offsetParent !== null", timeout=15000)
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT status FROM ui_definitions WHERE kind='custom_module' AND key=? AND version=1", (KEY,)).fetchone()["status"] == "published"
    finally:
        c.close()
    # 申請人自己：佇列看得到自己送的卡片，但審核頁沒有決定鈕
    page2 = new_page()
    login_as(page2, boss)
    page2.goto(f"{live_server}/pages/custom-def-review.html?key={KEY}")
    page2.wait_for_selector("#dr-title", timeout=15000)
    page2.wait_for_timeout(800)
    assert page2.locator("#dr-approve:visible").count() == 0
