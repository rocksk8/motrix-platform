# -*- coding: utf-8 -*-
"""瀏覽器層級：簽核佇列詳情的「修改人」列（fix/unlock-edit-keep-requester，N2）。

最高管理者解鎖編輯存檔後，送審人維持原送審人、另記 editedBy。簽核人在佇列點開那一張時要看得到「誰改了內容」；
沒被解鎖改過的單（佇列項目沒有 editedBy 鍵）完全不出現這一列（畫面與以前相同）。

做法同 test_e2e_approval_queue_mine_count：攔截 GET /api/approval-queue 回兩張固定的單（一張有 editedBy、一張沒有），
其餘請求照常。後端欄位本身（只在解鎖改過的單才有 editedBy／editedByDisplay）由
test_unlock_edit_keep_requester_2026_11_13 的 test_queue_item_carries_edited_by_only_for_unlock_edited_quotes 驗。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

_MAKE_USER_DEFAULT_ROLE = "superadmin"

ROW = '[data-testid="aq-edited-by"]'


def _item(no, **kw):
    base = {"type": "quotation", "quoteNo": no, "requestedBy": "orig_req", "requestedByDisplay": "原送審人",
            "requestedAt": "2026-11-12 09:00:00", "customerName": "測試客戶", "projectName": "測試專案", "total": 1000,
            "tiers": [], "currentApprovers": [], "currentTier": 0}
    base.update(kw)
    return base


def _open(page, live_server, items):
    page.route("**/api/approval-queue", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"queue": [{"requestedBy": "orig_req", "items": items}], "total": len(items),
                         "myDelegatedFor": [], "reassignTypes": []}))
        if r.request.method == "GET" else r.continue_())
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.locator(".vm-andon").wait_for(state="visible", timeout=20000)


def _select(page, no):
    page.locator(f'[data-testid="aq-item-{no}"]').first.click()
    # 點完不要馬上讀 UI：先等 Alpine 把 selected 換成這一張
    page.wait_for_function("(no) => { const d = Alpine.$data(document.body); return d.selected && d.selected.quoteNo === no }",
                           arg=no, timeout=10000)


@pytest.mark.e2e
def test_the_detail_shows_the_editor_only_for_a_quote_that_was_unlock_edited(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_aq_editedby")
    page = new_page()
    login_as(page, tuple(user)[:2])
    _open(page, live_server, [
        _item("MQ-EDITED-1", editedBy="sa_editor", editedByDisplay="最高管理者甲"),
        _item("MQ-PLAIN-1"),
    ])

    _select(page, "MQ-EDITED-1")
    row = page.locator(ROW)
    row.wait_for(state="visible", timeout=5000)
    text = row.inner_text()
    assert "修改人" in text and "最高管理者甲" in text, text
    assert "sa_editor" not in text, "有顯示名稱時用顯示名稱：" + text
    # 申請人那一列仍是原送審人（送審人維持）
    # 詳情頁有好幾個 .aq-info-grid（基本資訊／承攬商匯款／案件／欄位，各是一節）：只看含「修改人」列的那一格（基本資訊），不靠全頁唯一
    assert "原送審人" in page.locator(".aq-info-grid", has=page.locator(ROW)).inner_text()

    _select(page, "MQ-PLAIN-1")
    page.wait_for_function("() => !document.querySelector('[data-testid=\"aq-edited-by\"]') || "
                           "document.querySelector('[data-testid=\"aq-edited-by\"]').offsetParent === null", timeout=5000)
    assert not page.is_visible(ROW), "沒被解鎖改過的單不該有「修改人」列"

    _select(page, "MQ-EDITED-1")                                                # 切回去又出現（不殘留上一張的狀態）
    page.locator(ROW).wait_for(state="visible", timeout=5000)


@pytest.mark.e2e
def test_the_editor_row_falls_back_to_the_username_when_there_is_no_display_name(live_server, make_user, new_page, login_as):
    user = make_user(username="e2e_aq_editedby2")
    page = new_page()
    login_as(page, tuple(user)[:2])
    _open(page, live_server, [_item("MQ-EDITED-2", editedBy="sa_editor")])
    _select(page, "MQ-EDITED-2")
    page.locator(ROW).wait_for(state="visible", timeout=5000)
    assert "sa_editor" in page.locator(ROW).inner_text()
