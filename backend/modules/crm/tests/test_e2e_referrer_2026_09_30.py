# -*- coding: utf-8 -*-
"""業務開發頁「介紹人」（R2：開頁、點每個新增／變更的控制項、斷言 DOM＋DB、截圖）：
新增案件填介紹人 ⇒ 列表卡片顯示、搜尋框用介紹人找得到、詳情顯示；編輯改介紹人並存 ⇒ DB 與畫面同步、稽核 old→new；
太長（>60）⇒ 輸入框 maxlength 擋住，且伺服器端 400 的訊息會顯示在視窗（字串 detail）。
截圖先存 repo 內 logs/e2e-shots/（BK19 不准寫到 repo／tmp 之外），再由人搬到 D:/開發測試檔/shots/wip-w2-referrer/。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))      # …/backend
SHOTS = os.path.join(BACKEND, "logs", "e2e-shots", "wip-w2-referrer")


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, name), "wb") as f:
        f.write(page.screenshot())


def _rows(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


@pytest.mark.e2e
def test_referrer_add_list_search_detail_edit(live_server, new_context, make_user):
    user = make_user(username="rfe_user", role="superadmin", modules=["dev_crm"])
    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/dev-crm.html")
    page.get_by_role("button", name="新增案件").first.click()
    modal = page.locator(".dc-modal", has=page.locator('[data-testid="case-referrer"]'))
    modal.wait_for(state="visible", timeout=15000)
    ref = modal.locator('[data-testid="case-referrer"]')
    assert ref.get_attribute("placeholder") == "例：客戶或同業介紹" and ref.get_attribute("maxlength") == "60"
    assert "介紹人" in modal.inner_text()
    modal.locator('input[placeholder="例：XX公司辦公室弱電整合"]').fill("弱電整合案")
    ref.fill("  王大哥（同業介紹）  ")
    _shot(page, "referrer-new-modal.png")
    page.get_by_role("button", name="建立案件").click()
    modal.wait_for(state="hidden", timeout=15000)
    row = _rows("SELECT id, referrer FROM dev_cases WHERE case_name='弱電整合案'")[0]
    assert row["referrer"] == "王大哥（同業介紹）"                                                # 去頭尾空白、存進 DB
    # 詳情（建立後自動選取）顯示介紹人
    detail = page.locator('[data-testid="detail-referrer"]')
    detail.wait_for(state="visible", timeout=10000)
    assert "王大哥（同業介紹）" in detail.inner_text()
    # 列表卡片顯示
    card = page.locator('[data-testid="card-referrer"]', has_text="王大哥")
    card.first.wait_for(state="visible", timeout=10000)
    assert card.first.inner_text() == "介紹人：王大哥（同業介紹）"
    _shot(page, "referrer-list-and-detail.png")
    # 搜尋框用介紹人找得到；找別人的名字找不到
    box = page.locator("input.dc-search")
    assert "介紹人" in (box.get_attribute("placeholder") or "")
    box.fill("同業介紹")
    page.wait_for_function("() => document.querySelectorAll('.dc-case-card').length === 1", timeout=10000)
    assert "弱電整合案" in page.locator(".dc-case-card").first.inner_text()
    box.fill("查無此人")
    page.wait_for_function("() => document.querySelectorAll('.dc-case-card').length === 0", timeout=10000)
    box.fill("")
    page.wait_for_function("() => document.querySelectorAll('.dc-case-card').length >= 1", timeout=10000)
    # 編輯：改介紹人並存
    page.locator(".dc-case-card", has_text="弱電整合案").first.click()
    page.get_by_role("button", name="編輯").first.click()
    modal.wait_for(state="visible", timeout=10000)
    assert ref.input_value() == "王大哥（同業介紹）"                                              # 編輯視窗帶入原值
    ref.fill("李經理")
    page.get_by_role("button", name="儲存變更").click()
    modal.wait_for(state="hidden", timeout=15000)
    assert _rows("SELECT referrer FROM dev_cases WHERE id=?", (row["id"],))[0]["referrer"] == "李經理"
    page.wait_for_function("() => document.querySelector('[data-testid=detail-referrer]') && document.querySelector('[data-testid=detail-referrer]').innerText.includes('李經理')", timeout=10000)
    aud = [json.loads(r["detail"]) for r in _rows("SELECT detail FROM audit_log WHERE action='dev_case.update' AND target_id=?", (str(row["id"]),))]
    assert aud and aud[-1] == {"referrer": {"from": "王大哥（同業介紹）", "to": "李經理"}}
    _shot(page, "referrer-after-edit.png")
    # 清空：卡片不再顯示介紹人那一行
    page.get_by_role("button", name="編輯").first.click()
    modal.wait_for(state="visible", timeout=10000)
    ref.fill("")
    page.get_by_role("button", name="儲存變更").click()
    modal.wait_for(state="hidden", timeout=15000)
    assert _rows("SELECT referrer FROM dev_cases WHERE id=?", (row["id"],))[0]["referrer"] == ""
    page.wait_for_function("() => document.querySelectorAll('[data-testid=card-referrer]').length === 0 || [...document.querySelectorAll('[data-testid=card-referrer]')].every(e => e.offsetParent === null)", timeout=10000)
    assert not errors, errors


@pytest.mark.e2e
def test_referrer_server_rejection_is_shown_in_the_modal(live_server, new_context, make_user):
    """輸入框有 maxlength，但繞過（例如貼上程式改掉屬性）時伺服器 400 的訊息要顯示在視窗，而且沒有建立案件。"""
    user = make_user(username="rfe_user2", role="superadmin", modules=["dev_crm"])
    page = new_context().new_page()
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/dev-crm.html")
    page.get_by_role("button", name="新增案件").first.click()
    modal = page.locator(".dc-modal", has=page.locator('[data-testid="case-referrer"]'))
    modal.wait_for(state="visible", timeout=15000)
    modal.locator('input[placeholder="例：XX公司辦公室弱電整合"]').fill("過長介紹人案")
    ref = modal.locator('[data-testid="case-referrer"]')
    ref.evaluate("e => e.removeAttribute('maxlength')")
    ref.fill("字" * 61)
    page.get_by_role("button", name="建立案件").click()
    page.wait_for_selector("text=介紹人最多 60 個字", timeout=10000)
    assert modal.is_visible()
    assert _rows("SELECT COUNT(*) AS n FROM dev_cases WHERE case_name='過長介紹人案'")[0]["n"] == 0
    _shot(page, "referrer-too-long-rejected.png")
