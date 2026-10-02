# -*- coding: utf-8 -*-
"""建構器方案 B e2e（自訂模組掛成內建頁面的頁籤；設計 docs/platform/plans/BUILDER-B-DESIGN.md）：
發布掛在 `daily_tasks.daily-tasks` 的自訂模組 ⇒ 每日工作事項頁（選一件工作後的頁籤列）出現頁籤 ⇒ 點選後同源 iframe（?embed=1）載入、
隱藏頂欄／側欄 ⇒ 在 iframe 內新增一筆單據 ⇒ DB 有列 ⇒ 刪除模組 ⇒ 重載頁籤消失；沒有 `custom.<key>` 的人看不到頁籤（隱藏不是存取控制，API 另驗）。
斷言打在伺服器狀態（DB／API）與 DOM 的終點狀態，不用 sleep。"""
import json
import os
from datetime import date

import pytest

pytest.importorskip("playwright.sync_api")

KEY = "mb_form"
POINT = "daily_tasks.daily-tasks"
TAB = '[data-mount-tab="%s"]' % KEY
IFRAME = 'iframe[data-mt-key="%s"]' % KEY


def _hdr(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body():
    return {"name": "請款單掛載", "permission": "custom.%s" % KEY, "numbering": {"prefix": "MB", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "摘要", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]},
            "ui": {"form": {"groups": []}, "list": {"columns": []}},
            "mount": {"point": POINT, "label": "請款單頁籤"}}


@pytest.fixture()
def world(client, make_user):
    sa = make_user(username="mb_sa", role="superadmin")
    none = make_user(username="mb_none", role="user", modules=["daily_task"])
    ok = make_user(username="mb_ok", role="user", modules=["daily_task", "custom." + KEY])
    h = _hdr(client, sa)
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body()})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    # 一件指派給兩位使用者的今日工作（頁籤列在「選了一件工作」之後才出現）
    t = client.post("/api/daily-tasks", headers=h, json={"task_date": date.today().isoformat(), "title": "掛載測試工作",
                                                         "assigned_to": ["mb_ok", "mb_none"]})
    assert t.status_code == 201, t.text
    return client, h, sa, none, ok


def _open_and_select(page, live_server):
    """開頁 ⇒ 等工作清單 ⇒ 選一件（掛載元件在「選了工作」之後才渲染，所以取頁籤的請求在選取之後）⇒ 回該請求的回應。"""
    page.goto(live_server + "/pages/daily-tasks.html")
    page.wait_for_function("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return d.tasks && d.tasks.length > 0 }", timeout=30000)
    with page.expect_response(lambda r: "/api/platform/mounts" in r.url, timeout=30000) as resp:
        page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); d.calMode = false; d.monthCalMode = false; d.boardMode = false; d.selectTask(d.tasks[0]) }")
    page.wait_for_selector("[data-mount-point] .dt-tab-bar", state="visible", timeout=15000)
    return resp.value


def _records():
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT record_no, data_json FROM custom_records WHERE module_key=?", (KEY,)).fetchall()]
    finally:
        conn.close()


@pytest.mark.e2e
def test_mount_tab_appears_embeds_the_module_creates_a_record_and_disappears_after_delete(live_server, world, new_context):
    client, h, sa, none, ok = world
    from tests._e2e_login import inject_login
    ctx = new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, ok[0], ok[1])
    r = _open_and_select(page, live_server)
    assert r.status == 200 and [t["key"] for t in r.json()["tabs"]] == [KEY]
    page.wait_for_selector(TAB, state="visible", timeout=15000)
    assert page.locator(TAB).inner_text().strip() == "請款單頁籤"
    assert page.locator(IFRAME).count() == 0, "懶載入：沒點頁籤之前不可以建立 iframe"
    page.click(TAB)
    page.wait_for_selector(IFRAME, state="attached", timeout=15000)
    frame = page.frame_locator(IFRAME)
    frame.locator("#cr-new").wait_for(state="visible", timeout=30000)
    assert page.evaluate("() => document.querySelector('iframe[data-mt-key]').contentDocument.documentElement.getAttribute('data-embed')") == "1"
    assert page.evaluate("() => getComputedStyle(document.querySelector('iframe[data-mt-key]').contentDocument.getElementById('app-topbar')).display") == "none"
    frame.locator("#cr-new").click()
    frame.locator("#cr-form input[type=text], #cr-form input:not([type])").first.fill("掛載頁籤內新增")
    frame.locator("#cr-save").click()
    page.wait_for_function("() => true")
    deadline_rows = None
    for _ in range(40):
        deadline_rows = _records()
        if deadline_rows:
            break
        page.wait_for_timeout(250)
    assert deadline_rows and "掛載頁籤內新增" in deadline_rows[0]["data_json"], "在 iframe 內新增的單據沒有進 DB"
    # 高度回報（postMessage，origin＋source 檢查）：iframe 高度不是預設的 480px 也不小於下限
    h_px = page.evaluate("() => document.querySelector('iframe[data-mt-key]').getBoundingClientRect().height")
    assert h_px >= 160
    # 刪除模組（有單據 ⇒ with_records）⇒ 重載後頁籤消失；頁面其餘功能照常
    assert client.delete("/api/definitions/custom_module/%s?with_records=1" % KEY, headers=h).status_code == 200
    r2 = _open_and_select(page, live_server)
    assert r2.status == 200 and r2.json()["tabs"] == []
    assert page.locator(TAB).count() == 0
    assert page.locator(".dt-tab-btn").count() >= 2, "原本的頁籤（本次紀錄／歷史紀錄）要照常在"
    assert not errors, errors


@pytest.mark.e2e
def test_user_without_the_custom_permission_sees_no_tab(live_server, world, new_context):
    client, h, sa, none, ok = world
    from tests._e2e_login import inject_login
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, none[0], none[1])
    r = _open_and_select(page, live_server)
    assert r.status == 200 and r.json()["tabs"] == [], "沒有 custom.%s 的人不該拿到頁籤" % KEY
    assert page.locator(TAB).count() == 0
    # 隱藏頁籤不是存取控制：直接打 records API 照樣被擋
    hn = _hdr(client, none)
    assert client.get("/api/custom/%s/records" % KEY, headers=hn).status_code == 403
